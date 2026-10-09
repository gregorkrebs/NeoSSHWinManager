"""Import of FileZilla's Site Manager (src/filezilla_import.py and its dialog)."""
import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.config import Connection, PROTOCOL_FTP, PROTOCOL_FTPS, PROTOCOL_SFTP  # noqa: E402
from src.filezilla_import import (  # noqa: E402
    NotFileZillaError, is_duplicate, parse_remote_dir, parse_site_manager,
    to_connection, unique_name,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


SITE_MANAGER = f"""<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3 version="3.69.3" platform="windows">
  <Servers>
    <Server>
      <Host>web-01.example.com</Host>
      <Port>2222</Port>
      <Protocol>1</Protocol>
      <Type>0</Type>
      <User>deploy</User>
      <Pass encoding="base64">{b64("s3cret ü")}</Pass>
      <Logontype>1</Logontype>
      <Name>Web 01</Name>
      <RemoteDir>1 0 3 var 3 www 8 my files</RemoteDir>
    </Server>
    <Folder expanded="1">Customers
      <Folder expanded="1">Muster, GmbH
        <Server>
          <Host>ftp.example.com</Host>
          <Port>21</Port>
          <Protocol>0</Protocol>
          <User>muster</User>
          <Pass encoding="crypt" pubkey="abc">ZZZ</Pass>
          <Logontype>1</Logontype>
          <PasvMode>MODE_ACTIVE</PasvMode>
          <Name>Muster FTP</Name>
        </Server>
      </Folder>
      <Server>
        <Host>secure.example.com</Host>
        <Protocol>3</Protocol>
        <User>alice</User>
        <Logontype>2</Logontype>
        <Name>Implicit</Name>
      </Server>
    </Folder>
    <Server>
      <Host>files.example.com</Host>
      <Protocol>4</Protocol>
      <User>bob</User>
      <Pass encoding="base64">{b64("pw")}</Pass>
      <Logontype>1</Logontype>
      <Name>Explicit</Name>
    </Server>
    <Server>
      <Host>old.example.com</Host>
      <Protocol>6</Protocol>
      <Logontype>0</Logontype>
      <Name>Anonymous</Name>
    </Server>
    <Server>
      <Host>key.example.com</Host>
      <Protocol>1</Protocol>
      <User>root</User>
      <Logontype>5</Logontype>
      <Keyfile>C:\\Keys\\server.ppk</Keyfile>
      <Name>PuTTY key</Name>
    </Server>
    <Server>
      <Host>key2.example.com</Host>
      <Protocol>1</Protocol>
      <User>root</User>
      <Logontype>5</Logontype>
      <Keyfile>C:\\Keys\\id_ed25519</Keyfile>
      <RemoteDir>3 0 2 C: 5 Users 2 me</RemoteDir>
      <Name>OpenSSH key</Name>
    </Server>
    <Server>
      <Host>bucket.example.com</Host>
      <Protocol>7</Protocol>
      <Name>S3</Name>
    </Server>
    <Server>
      <Host>legacy.example.com</Host>
      <Protocol>1</Protocol>
      <User>x</User>
      <Pass>plain</Pass>
      <Logontype>1</Logontype>Legacy name
    </Server>
  </Servers>
</FileZilla3>
"""


@pytest.fixture
def sites():
    return {s.name: s for s in parse_site_manager(SITE_MANAGER)}


def test_reads_every_site_in_order_with_folders_as_groups():
    names = [s.name for s in parse_site_manager(SITE_MANAGER)]
    assert names == ["Web 01", "Muster FTP", "Implicit", "Explicit", "Anonymous",
                     "PuTTY key", "OpenSSH key", "S3", "Legacy name"]
    by = {s.name: s for s in parse_site_manager(SITE_MANAGER)}
    assert by["Muster FTP"].group == "Customers / Muster, GmbH"
    assert by["Implicit"].group == "Customers"
    assert by["Web 01"].group == ""


def test_sftp_site_with_stored_password_and_remote_dir(sites):
    s = sites["Web 01"]
    assert (s.protocol, s.host, s.port, s.user) == (PROTOCOL_SFTP, "web-01.example.com", 2222, "deploy")
    assert (s.auth_method, s.password) == ("password", "s3cret ü")
    assert s.remote_path == "/var/www/my files"
    assert s.supported and not s.notes


def test_ftp_protocols_map_to_ftp_and_ftps(sites):
    tls_if = sites["Muster FTP"]
    assert (tls_if.protocol, tls_if.ftp_implicit_tls, tls_if.port) == (PROTOCOL_FTPS, False, 21)
    assert tls_if.ftp_passive is False
    assert ("import.fz.note.tls_if_available", {}) in tls_if.notes
    assert (sites["Implicit"].protocol, sites["Implicit"].ftp_implicit_tls, sites["Implicit"].port) == (PROTOCOL_FTPS, True, 990)
    assert (sites["Explicit"].protocol, sites["Explicit"].ftp_implicit_tls) == (PROTOCOL_FTPS, False)
    assert sites["Anonymous"].protocol == PROTOCOL_FTP
    assert sites["Explicit"].ftp_passive is True


def test_passwords_that_cannot_be_read_are_asked_for(sites):
    locked = sites["Muster FTP"]
    assert (locked.auth_method, locked.password) == ("ask", "")
    assert ("import.fz.note.master_password", {}) in locked.notes
    ask = sites["Implicit"]
    assert ask.auth_method == "ask"
    assert ("import.fz.note.ask", {}) in ask.notes


def test_anonymous_plain_password_and_name_after_children(sites):
    assert (sites["Anonymous"].user, sites["Anonymous"].auth_method) == ("anonymous", "password")
    legacy = sites["Legacy name"]
    assert (legacy.password, legacy.auth_method) == ("plain", "password")


def test_key_files(sites):
    ppk = sites["PuTTY key"]
    assert (ppk.auth_method, ppk.putty_key_path, ppk.key_path) == ("key", "C:\\Keys\\server.ppk", "")
    assert ("import.fz.note.ppk", {}) in ppk.notes
    openssh = sites["OpenSSH key"]
    assert (openssh.key_path, openssh.putty_key_path) == ("C:\\Keys\\id_ed25519", "")
    assert openssh.remote_path == "C:\\Users\\me"


def test_other_protocols_are_listed_but_not_supported(sites):
    s3 = sites["S3"]
    assert not s3.supported
    assert s3.protocol_label == "S3"
    assert ("import.fz.note.unsupported", {"proto": "S3"}) in s3.notes


@pytest.mark.parametrize("value, path", [
    ("1 0 4 home 4 user", "/home/user"),
    ("1 0", "/"),
    ("", ""),
    ("3 0 2 C:", "C:\\"),
    ("1 0 99 broken", ""),
    ("garbage", ""),
])
def test_parse_remote_dir(value, path):
    assert parse_remote_dir(value) == path


@pytest.mark.parametrize("data", [b"<html/>", b"not xml", b"<FileZilla3"])
def test_rejects_other_files(data):
    with pytest.raises(NotFileZillaError):
        parse_site_manager(data)


def test_duplicates_unique_names_and_connection(sites):
    existing = [Connection(name="Web 01", host="WEB-01.example.com", user="deploy", port=2222)]
    assert is_duplicate(sites["Web 01"], existing)
    assert not is_duplicate(sites["PuTTY key"], existing)
    assert unique_name("Web 01", {"web 01", "Web 01 (2)"}) == "Web 01 (3)"
    assert unique_name("New", {"Web 01"}) == "New"

    c = to_connection(sites["Muster FTP"], "Muster FTP", "Z:")
    assert (c.protocol, c.host, c.user, c.auth_method, c.ftp_passive) == (
        PROTOCOL_FTPS, "ftp.example.com", "muster", "ask", False)
    assert c.groups == "Customers / Muster GmbH"       # commas separate groups in the app
    w = to_connection(sites["Web 01"], "Web 01 (2)", "W:")
    assert (w.name, w.drive_letter, w.password, w.remote_path) == ("Web 01 (2)", "W:", "s3cret ü", "/var/www/my files")


def test_dialog_lists_sites_and_returns_the_checked_ones(qapp, tmp_path):
    from src.ui.dialogs.filezilla_import_dialog import FileZillaImportDialog
    path = tmp_path / "sitemanager.xml"
    path.write_text(SITE_MANAGER, encoding="utf-8")
    existing = [Connection(name="x", host="web-01.example.com", user="deploy", port=2222)]
    dlg = FileZillaImportDialog(existing, path=str(path))
    boxes = {site.name: box for box, site in dlg._boxes}
    assert len(boxes) == 9
    assert not boxes["Web 01"].isChecked()            # already in the list
    assert not boxes["S3"].isEnabled()
    selected = {s.name for s in dlg.selected()}
    assert selected == {"Muster FTP", "Implicit", "Explicit", "Anonymous", "PuTTY key", "OpenSSH key", "Legacy name"}
    dlg._set_all(False)
    assert dlg.selected() == []
    assert not dlg._import_btn.isEnabled()
    dlg._set_all(True)
    assert len(dlg.selected()) == 8


def test_dialog_without_site_manager(qapp, tmp_path):
    from src.ui.dialogs.filezilla_import_dialog import FileZillaImportDialog
    dlg = FileZillaImportDialog([], path=str(tmp_path / "missing.xml"))
    assert dlg.selected() == []
    assert not dlg._import_btn.isEnabled()
    bad = tmp_path / "bad.xml"
    bad.write_text("<settings/>", encoding="utf-8")
    dlg._load(str(bad))
    assert dlg._sites == []
