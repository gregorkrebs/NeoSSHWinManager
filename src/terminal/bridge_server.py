"""
WebSocket ↔ Paramiko SSH bridge server for the integrated xterm.js terminal.

Security properties:
- SSH passwords are used only inside paramiko.SSHClient.connect() and wiped afterward.
- The WebSocket carries only raw terminal I/O (stdin/stdout/stderr); no credentials ever.
- Session tokens are UUID4, single-use: consumed on first WebSocket connection.
- Server binds exclusively to 127.0.0.1 on an OS-assigned ephemeral port.
- Host key verification uses RejectPolicy + TOFU dialog (no AutoAddPolicy).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import paramiko

# Maximum WebSocket message size: 256 KB
_MAX_WS_MSG_BYTES = 256 * 1024


@dataclass
class TerminalSession:
    conn_id: str
    client: "paramiko.SSHClient"
    channel: "paramiko.Channel"
    websocket: object | None = None
    forwarder_task: asyncio.Task | None = None


class TerminalBridgeServer:
    """
    Runs an asyncio websockets server in a daemon thread.

    Call start() once after creation, stop() on application exit.
    All public methods that create/close sessions are called from the Qt main thread
    and schedule coroutines into self._loop.
    """

    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}
        self._pending_tokens: dict[str, str] = {}  # token → conn_id
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

        known_hosts_path = os.path.expanduser(r"~\.ssh\known_hosts")

        client = paramiko.SSHClient()

        # Check if host is already known
        if _is_host_known(host, port, known_hosts_path):
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.load_host_keys(known_hosts_path)
        else:
            # Unknown host: ask user via TOFU callback
            fingerprint = _get_server_fingerprint(host, port)
            accepted = False
            if self.host_key_verify_callback and fingerprint:
                accepted = self.host_key_verify_callback(host, port, fingerprint)
            if not accepted:
                logger.warning("Terminal: TOFU rejected for %s:%d", host, port)
                return None
            # Accept and save to known_hosts
            policy = _TOFUAcceptPolicy(known_hosts_path)
            client.set_missing_host_key_policy(policy)

        try:
            if auth_method == "key" and key_path:
                client.connect(host, port=port, username=user, key_filename=key_path, timeout=15)
            elif auth_method == "key" and getattr(conn, "putty_key_path", ""):
                # PPK keys: paramiko can load them if they are OpenSSH-compatible
                # (PPK v2/v3 format). Try key_path first, fallback to putty_key_path.
                ppk_path = conn.putty_key_path
                client.connect(host, port=port, username=user, key_filename=ppk_path, timeout=15)
            elif auth_method in ("password", "ask") and password:
                client.connect(host, port=port, username=user, password=password, timeout=15)
            else:
                logger.error("Terminal: unsupported auth_method=%s or missing credentials", auth_method)
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
            # Wipe password from local scope regardless of success/failure
            password = ""

        channel = client.invoke_shell(term="xterm-256color", width=80, height=24)
        channel.setblocking(False)

        # Keepalive every 30 s — prevents server-side idle disconnect regardless of data flow
        transport = client.get_transport()
        if transport:
            transport.set_keepalive(30)

        session = TerminalSession(conn_id=conn_id, client=client, channel=channel)
        self._sessions[conn_id] = session

        token = str(uuid.uuid4())
        self._pending_tokens[token] = conn_id
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

    async def _ws_handler(self, websocket, path: str):
        import websockets

        # Extract token from path: /ws/{token}
        parts = path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "ws":
            await websocket.close(1008, "Invalid path")
            return

        token = parts[1]
        conn_id = self._pending_tokens.pop(token, None)
        if conn_id is None:
            logger.warning("Terminal: unknown or already-used token %s", token[:8] + "…")
            await websocket.close(1008, "Invalid token")
            return

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


# ---------------------------------------------------------------------------
# Host-key helpers (shared with sftp_client via host_key_utils)
# ---------------------------------------------------------------------------

from src.ui.host_key_utils import (
    is_host_known as _is_host_known,
    get_server_fingerprint as _get_server_fingerprint,
    TOFUAcceptPolicy as _TOFUAcceptPolicy,
)
