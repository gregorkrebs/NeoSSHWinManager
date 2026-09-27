"""
Host-key verification of the SFTP client (file browser) against the local
paramiko test server: first contact, known key, changed key, other key type.
"""

import socket

import paramiko
import pytest

from src import sftp_client
from src.config import Connection
from src.sftp_client import HostKeyChanged, HostKeyRejected, HostKeyVerifier, SftpClient
from src.ui.host_key_utils import key_fingerprint, known_hosts_line
from tests.sftp_test_server import SftpTestServer


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sftp_client, "_session_keys", {})
    return tmp_path


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with SftpTestServer(str(root)) as srv:
        yield srv


def _conn(server):
    return Connection(name="t", host="127.0.0.1", user="user", password="pass", port=server.port)


def _known_hosts(home):
    return home / ".ssh" / "known_hosts"


def test_first_contact_asks_with_the_real_fingerprint_and_saves_it(home, server):
    asked = []
    client = SftpClient()
    client.connect(_conn(server), tofu_callback=lambda h, p, fp: asked.append(fp) or True)
    client.disconnect()
    assert asked == [key_fingerprint(server._key)]
    assert asked[0].startswith("2048 SHA256:") and asked[0].endswith("(RSA)")
    data = _known_hosts(home).read_bytes()
    assert data == (known_hosts_line(f"[127.0.0.1]:{server.port}", server._key) + "\n").encode()

    # Known now: no question, even without a callback.
    sftp_client._session_keys.clear()
    again = SftpClient()
    again.connect(_conn(server))
    again.disconnect()


def test_declined_key_is_rejected_and_not_saved(home, server):
    with pytest.raises(HostKeyRejected):
        SftpClient().connect(_conn(server), tofu_callback=lambda *_a: False)
    assert not _known_hosts(home).exists()


def test_changed_key_is_refused_without_asking(home, server):
    other = paramiko.RSAKey.generate(2048)
    _known_hosts(home).parent.mkdir()
    _known_hosts(home).write_text(known_hosts_line(f"[127.0.0.1]:{server.port}", other) + "\n")
    asked = []
    with pytest.raises(HostKeyChanged) as info:
        SftpClient().connect(_conn(server), tofu_callback=lambda *a: asked.append(a) or True)
    assert not asked
    assert info.value.fingerprint == key_fingerprint(server._key)


def test_other_known_key_type_asks_for_the_new_type(home, server):
    ecdsa = paramiko.ECDSAKey.generate()
    _known_hosts(home).parent.mkdir()
    # CRLF and no trailing newline, as older app versions wrote it.
    _known_hosts(home).write_bytes(
        (known_hosts_line(f"[127.0.0.1]:{server.port}", ecdsa)).encode() + b"\r")
    asked = []
    client = SftpClient()
    client.connect(_conn(server), tofu_callback=lambda *a: asked.append(a) or True)
    client.disconnect()
    assert len(asked) == 1
    lines = _known_hosts(home).read_text().splitlines()
    assert len(lines) == 2 and lines[1].split()[1] == "ssh-rsa"


def test_known_rsa_key_prefers_all_rsa_signature_algorithms(home):
    rsa = paramiko.RSAKey.generate(2048)
    _known_hosts(home).parent.mkdir()
    _known_hosts(home).write_text(known_hosts_line("example.org", rsa) + "\n")
    verifier = HostKeyVerifier("Example.org", 22, str(_known_hosts(home)), None)
    assert set(verifier.known) == {"ssh-rsa"}           # host names match case-insensitively
    a, b = socket.socketpair()
    try:
        transport = verifier.transport_factory(a)
        order = transport.get_security_options().key_types
        assert set(order[:3]) == {"rsa-sha2-512", "rsa-sha2-256", "ssh-rsa"}
        transport.close()
    finally:
        a.close()
        b.close()


def test_session_cache_allows_reconnect_when_known_hosts_is_not_writable(home, server, monkeypatch):
    def fail(*_a, **_k):
        raise OSError("read-only")
    monkeypatch.setattr(sftp_client, "append_known_hosts", fail)
    client = SftpClient()
    client.connect(_conn(server), tofu_callback=lambda *_a: True)
    client.disconnect()
    again = SftpClient()
    again.connect(_conn(server))                        # no callback: must not ask again
    again.disconnect()
