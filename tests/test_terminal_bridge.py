"""
WebSocket side of the terminal bridge (src/terminal/bridge_server.py).

Terminal input travels as binary frames and reaches the shell unchanged;
text frames are control messages only. Up to 1.7.2 input was sent as text
and anything that parsed as JSON with a "type" key was swallowed, so pasting
such JSON into the terminal never reached the server.
"""

import os
import socket
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from websockets.sync.client import connect  # noqa: E402

from src.terminal.bridge_server import TerminalBridgeServer, TerminalSession, _PendingToken  # noqa: E402


class _FakeChannel:
    """Enough of a paramiko channel: select()-able, records what it gets."""

    def __init__(self):
        self._ours, self._theirs = socket.socketpair()
        self.sent = bytearray()
        self.resized = []
        self.closed = False

    def fileno(self):
        return self._ours.fileno()

    def recv(self, n):
        return self._ours.recv(n)

    def sendall(self, data):
        self.sent.extend(data)

    def resize_pty(self, width, height):
        self.resized.append((width, height))

    def close(self):
        self.closed = True
        self._ours.close()
        self._theirs.close()


class _FakeClient:
    def close(self):
        pass


@pytest.fixture
def bridge():
    server = TerminalBridgeServer()
    server.start()
    channel = _FakeChannel()
    server._sessions["c#1"] = TerminalSession(conn_id="c#1", client=_FakeClient(), channel=channel)
    server._pending_tokens["tok"] = _PendingToken(conn_id="c#1")
    yield server, channel
    server.stop()


def _until(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_pasted_json_reaches_the_shell(bridge):
    server, channel = bridge
    paste = b'{"type": "service", "name": "web"}\r'
    with connect(f"ws://127.0.0.1:{server.port}/ws/tok") as ws:
        ws.send(paste)
        assert _until(lambda: bytes(channel.sent) == paste)


def test_text_frames_are_control_messages_only(bridge):
    server, channel = bridge
    with connect(f"ws://127.0.0.1:{server.port}/ws/tok") as ws:
        ws.send('{"type": "resize", "cols": 120, "rows": 40}')
        ws.send("ls -la\r")                      # not input: never typed
        ws.send('{"type": "resize", "cols": 99999, "rows": 40}')
        ws.send(b"x")
        assert _until(lambda: bytes(channel.sent) == b"x")
    assert channel.resized == [(120, 40)]
    assert bytes(channel.sent) == b"x"


def test_shell_output_reaches_the_page(bridge):
    server, channel = bridge
    with connect(f"ws://127.0.0.1:{server.port}/ws/tok") as ws:
        channel._theirs.sendall(b"hello")
        assert ws.recv(timeout=5) == b"hello"


def test_token_is_single_use(bridge):
    server, _channel = bridge
    with connect(f"ws://127.0.0.1:{server.port}/ws/tok"):
        pass
    with connect(f"ws://127.0.0.1:{server.port}/ws/tok") as ws:
        with pytest.raises(Exception):
            ws.recv(timeout=5)


def test_page_sends_input_as_binary_frames():
    path = os.path.join(os.path.dirname(__file__), "..", "assets", "terminal", "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    assert "encoder.encode(data)" in html
    assert "ws.send(data)" not in html
