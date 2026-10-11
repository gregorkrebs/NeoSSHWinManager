"""
WebSocket ↔ Paramiko SSH bridge server for the integrated xterm.js terminal.

Security properties:
- SSH passwords are used only inside paramiko.SSHClient.connect() and wiped afterward.
- The WebSocket carries only raw terminal I/O (stdin/stdout/stderr); no credentials ever.
- Session tokens are UUID4, single-use: consumed on first WebSocket connection.
- Server binds exclusively to 127.0.0.1 on an OS-assigned ephemeral port.
- Host keys are checked inside the handshake (HostKeyVerifier): unknown keys are
  shown to the user with the fingerprint of the key actually presented.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import paramiko

# Maximum WebSocket message size: 256 KB
_MAX_WS_MSG_BYTES = 256 * 1024

# Pending tokens expire after 60 seconds if never consumed by a WebSocket connection
_TOKEN_EXPIRY_SEC = 60.0


@dataclass
class TerminalSession:
    conn_id: str
    client: "paramiko.SSHClient"
    channel: "paramiko.Channel"
    websocket: object | None = None
    forwarder_task: asyncio.Task | None = None


@dataclass
class _PendingToken:
    conn_id: str
    created_at: float = field(default_factory=time.monotonic)


class TerminalBridgeServer:
    """
    Runs an asyncio websockets server in a daemon thread.

    Call start() once after creation, stop() on application exit.
    All public methods that create/close sessions are called from the Qt main thread
    and schedule coroutines into self._loop.
    """

    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}
        self._pending_tokens: dict[str, _PendingToken] = {}  # token → _PendingToken
        self._port: int = 0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server = None

        # Qt signal-compatible callback for TOFU host-key dialog.
        # Set by MainWindow: callable(host, port, fingerprint) → bool (accepted)
        self.host_key_verify_callback: object | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        self._loop = asyncio.new_event_loop()
        ready = threading.Event()

        def _run():
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._serve(ready))
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True, name="TerminalBridge")
        self._thread.start()
        ready.wait(timeout=10)

    def stop(self):
        if self._loop is None:
            return
        # Close SSH channels synchronously first so _recv_channel executor
        # threads unblock (select timeout is 0.2 s) before the loop stops.
        for session in list(self._sessions.values()):
            try:
                session.channel.close()
            except Exception:
                pass
            try:
                session.client.close()
            except Exception:
                pass
        self._sessions.clear()
        self._loop.call_soon_threadsafe(self._loop.stop)

    @property
    def port(self) -> int:
        return self._port

    # ------------------------------------------------------------------
    # Session management (called from Qt main thread)
    # ------------------------------------------------------------------

    def create_session_token(self, conn_id: str, conn) -> str | None:
        """
        Opens an SSH connection using conn's credentials and returns a single-use
        WebSocket token. Returns None on connection failure.

        conn is a Connection dataclass with fields:
          host, port, user (ssh_user), auth_method, password, key_path, putty_key_path
        """
        import paramiko

        host = conn.host or ""
        port = int(conn.port or 22)
        user = getattr(conn, "user", "") or getattr(conn, "ssh_user", "") or ""
        auth_method = getattr(conn, "auth_method", "password")
        password = getattr(conn, "password", "") or ""
        key_path = getattr(conn, "key_path", "") or ""

        from src.sftp_client import HostKeyChanged, HostKeyRejected, HostKeyVerifier
        from src.ui.host_key_utils import default_known_hosts

        # The key is checked inside the handshake: the fingerprint the user is
        # asked about is the key this very connection presented, and that is
        # the key that gets saved.
        verifier = HostKeyVerifier(host, port, default_known_hosts(),
                                   self.host_key_verify_callback)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(verifier)
        common = dict(port=port, username=user, timeout=15,
                      transport_factory=verifier.transport_factory)

        try:
            if auth_method == "key" and key_path:
                client.connect(host, key_filename=key_path, **common)
            elif auth_method == "key" and getattr(conn, "putty_key_path", ""):
                # PPK keys: paramiko can load them if they are OpenSSH-compatible
                # (PPK v2/v3 format). Try key_path first, fallback to putty_key_path.
                client.connect(host, key_filename=conn.putty_key_path, **common)
            elif auth_method in ("password", "ask") and password:
                client.connect(host, password=password, **common)
            else:
                logger.error("Terminal: unsupported auth_method=%s or missing credentials", auth_method)
                client.close()
                return None
        except (HostKeyRejected, HostKeyChanged) as e:
            logger.warning("Terminal: host key not trusted for %s:%d – %s", host, port, e)
            client.close()
            return None
        except paramiko.AuthenticationException as e:
            logger.error("Terminal: authentication failed for %s@%s:%d – %s", user, host, port, e)
            client.close()
            return None
        except Exception as e:
            logger.error("Terminal: SSH connect error for %s:%d – %s", host, port, e)
            client.close()
            return None
        finally:
            password = ""

        try:
            channel = client.invoke_shell(term="xterm-256color", width=80, height=24)
            channel.setblocking(False)
        except Exception as e:
            logger.error("Terminal: could not open a shell on %s:%d – %s", host, port, e)
            client.close()
            return None

        # Keepalive every 30 s — prevents server-side idle disconnect regardless of data flow
        transport = client.get_transport()
        if transport:
            transport.set_keepalive(30)

        session = TerminalSession(conn_id=conn_id, client=client, channel=channel)
        self._sessions[conn_id] = session

        token = str(uuid.uuid4())
        self._pending_tokens[token] = _PendingToken(conn_id=conn_id)
        logger.debug("Terminal: session created for %s, token %s", conn_id, token[:8] + "…")
        return token

    def close_session(self, conn_id: str):
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(self._close_session_async(conn_id), loop=self._loop)
            )

    def resize_session(self, conn_id: str, cols: int, rows: int):
        session = self._sessions.get(conn_id)
        if session and session.channel and not session.channel.closed:
            try:
                session.channel.resize_pty(width=cols, height=rows)
            except Exception as e:
                logger.debug("Terminal: resize error for %s: %s", conn_id, e)

    def is_session_alive(self, conn_id: str) -> bool:
        session = self._sessions.get(conn_id)
        if session is None:
            return False
        return not session.channel.closed


    # ------------------------------------------------------------------
    # Internal asyncio coroutines
    # ------------------------------------------------------------------

    async def _serve(self, ready_event: threading.Event):
        import websockets

        server = await websockets.serve(
            self._ws_handler,
            "127.0.0.1",
            0,
            max_size=_MAX_WS_MSG_BYTES,
            ping_interval=30,
            ping_timeout=10,
        )
        self._server = server
        self._port = server.sockets[0].getsockname()[1]
        logger.info("Terminal bridge listening on 127.0.0.1:%d", self._port)
        ready_event.set()
        # Start periodic cleanup of expired pending tokens
        asyncio.ensure_future(self._cleanup_expired_tokens())

    async def _cleanup_expired_tokens(self):
        """Periodically remove pending tokens that were never consumed, closing
        the associated SSH connection to avoid resource leaks."""
        while True:
            await asyncio.sleep(30)
            now = time.monotonic()
            expired = [
                token for token, pt in list(self._pending_tokens.items())
                if now - pt.created_at > _TOKEN_EXPIRY_SEC
            ]
            for token in expired:
                pt = self._pending_tokens.pop(token, None)
                if pt:
                    logger.info("Terminal: expiring unused token for conn_id=%s", pt.conn_id)
                    session = self._sessions.pop(pt.conn_id, None)
                    if session:
                        try:
                            session.channel.close()
                        except Exception:
                            pass
                        try:
                            session.client.close()
                        except Exception:
                            pass

    async def _ws_handler(self, websocket, path: str):
        import websockets

        # Extract token from path: /ws/{token}
        parts = path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "ws":
            await websocket.close(1008, "Invalid path")
            return

        token = parts[1]
        pending = self._pending_tokens.pop(token, None)
        if pending is None:
            logger.warning("Terminal: unknown or already-used token %s", token[:8] + "…")
            await websocket.close(1008, "Invalid token")
            return
        # Check token has not expired (belt-and-suspenders alongside cleanup task)
        if time.monotonic() - pending.created_at > _TOKEN_EXPIRY_SEC:
            logger.warning("Terminal: expired token rejected for conn_id=%s", pending.conn_id)
            await websocket.close(1008, "Token expired")
            return
        conn_id = pending.conn_id

        session = self._sessions.get(conn_id)
        if session is None:
            await websocket.close(1011, "Session not found")
            return

        session.websocket = websocket
        logger.debug("Terminal: WebSocket connected for %s", conn_id)

        # Start SSH→WS forwarder
        forwarder = asyncio.ensure_future(self._ssh_to_ws(session))
        session.forwarder_task = forwarder

        try:
            # WS→SSH
            async for message in websocket:
                if session.channel.closed:
                    break
                try:
                    if isinstance(message, str):
                        # JSON control message (e.g. resize from xterm.js)
                        if message.startswith('{'):
                            import json as _json
                            handled = False
                            try:
                                ctrl = _json.loads(message)
                                msg_type = ctrl.get("type")
                                if msg_type == "resize":
                                    cols = int(ctrl.get("cols", 80))
                                    rows = int(ctrl.get("rows", 24))
                                    if cols > 0 and rows > 0:
                                        self.resize_session(conn_id, cols, rows)
                                    handled = True
                                elif msg_type is not None:
                                    handled = True  # unknown ctrl msg, ignore
                            except (ValueError, KeyError, TypeError, AttributeError):
                                pass  # not valid JSON – send to SSH as-is
                            if handled:
                                continue
                        session.channel.sendall(message.encode("utf-8"))
                    else:
                        session.channel.sendall(message)
                except Exception as e:
                    logger.debug("Terminal: WS→SSH send error: %s", e)
                    break
        except Exception as e:
            logger.debug("Terminal: WebSocket receive error: %s", e)
        finally:
            forwarder.cancel()
            logger.debug("Terminal: WebSocket disconnected for %s", conn_id)

    async def _ssh_to_ws(self, session: TerminalSession):
        loop = asyncio.get_event_loop()
        while True:
            try:
                data = await loop.run_in_executor(None, self._recv_channel, session.channel)
            except Exception:
                break
            if data is None:
                break
            if session.websocket:
                try:
                    await session.websocket.send(data)
                except Exception:
                    break

    @staticmethod
    def _recv_channel(channel) -> bytes | None:
        import select
        while True:
            if channel.closed:
                return None
            r, _, _ = select.select([channel], [], [], 0.2)
            if r:
                try:
                    data = channel.recv(4096)
                    return data if data else None
                except Exception:
                    return None

    async def _close_session_async(self, conn_id: str):
        session = self._sessions.pop(conn_id, None)
        if session is None:
            return
        if session.forwarder_task:
            session.forwarder_task.cancel()
        try:
            session.channel.close()
        except Exception:
            pass
        try:
            session.client.close()
        except Exception:
            pass
        logger.debug("Terminal: session %s closed", conn_id)
