import pytest

from src.filebrowser import commands
from src.filebrowser.model import (
    ACT_DELETE_REMOTE, ACT_DOWNLOAD, ACT_UPLOAD, KEEP_BOTH, OVERWRITE, SKIP,
    SYNC_BOTH, SYNC_DOWNLOAD, SYNC_UPLOAD,
    ConflictInfo, FileEntry, SyncSide, auto_decision, compare_trees, file_extension,
    keep_both_name, lparent, lparts, parse_octal_mode, path_within, rebase_path, rjoin,
    rparent, rparts, same_path, sort_entries, split_name, windows_remote_to_native,
)
from src.filebrowser.settings import BrowserSettings


def _f(name, size=10, mtime=1000.0, is_dir=False):
    return FileEntry(name=name, path="/" + name, is_dir=is_dir, size=size, mtime=mtime)


# ── naming ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("name", "expected"), [
    ("report.pdf", ("report", ".pdf")),
    ("backup.tar.gz", ("backup", ".tar.gz")),
    (".bashrc", (".bashrc", "")),
    ("README", ("README", "")),
])
def test_split_name(name, expected):
    assert split_name(name) == expected


def test_keep_both_counts_up_to_first_free_name():
    taken = {"report_1.pdf", "report_2.pdf"}
    assert keep_both_name("report.pdf", taken.__contains__) == "report_3.pdf"
    assert keep_both_name("backup.tar.gz", set().__contains__) == "backup_1.tar.gz"
    assert keep_both_name("README", set().__contains__) == "README_1"


def test_file_extension_is_lowercase_without_dot():
    assert file_extension("Photo.JPG") == "jpg"
    assert file_extension("x.tar.gz") == "tar.gz"
    assert file_extension("Makefile") == ""


def test_sort_is_folders_first_and_natural():
    entries = [_f("file10"), _f("file2"), _f("zdir", is_dir=True), _f("Adir", is_dir=True)]
    assert [e.name for e in sort_entries(entries)] == ["Adir", "zdir", "file2", "file10"]


# ── paths ────────────────────────────────────────────────────────────────────

def test_remote_paths():
    assert rjoin("/", "a") == "/a"
    assert rjoin("/a/", "b") == "/a/b"
    assert rparent("/a/b") == "/a"
    assert rparent("/a") == "/"
    assert rparent("/C:/Users") == "/C:"
    assert rparent("/C:") == "/"
    assert rparts("/var/www") == [("/", "/"), ("var", "/var"), ("www", "/var/www")]


def test_local_paths():
    assert lparent("C:\\Users\\greg") == "C:\\Users"
    assert lparent("C:\\") == ""
    assert lparts("C:\\Users") == [("⌂", ""), ("C:\\", "C:\\"), ("Users", "C:\\Users")]


def test_windows_remote_to_native():
    assert windows_remote_to_native("/C:/Users/x") == "C:\\Users\\x"
    assert windows_remote_to_native("/C:") == "C:\\"


def test_same_path_and_path_within():
    assert same_path("/a/b/", "/a/b", local=False)
    assert not same_path("/a/B", "/a/b", local=False)
    assert same_path("C:\\Users\\X\\", "c:\\users\\x", local=True)
    assert path_within("/a/b/c", "/a/b", local=False)
    assert path_within("/a/b", "/a/b", local=False)
    assert not path_within("/a/bc", "/a/b", local=False)       # sibling with same prefix
    assert path_within("/anything", "/", local=False)
    assert path_within("C:\\Users\\x", "c:\\users", local=True)
    assert path_within("D:\\x", "", local=True)                # "" = drive list, holds everything
    assert not path_within("C:\\Users2", "C:\\Users", local=True)


def test_rebase_path_follows_a_moved_folder():
    assert rebase_path("/a/b/c", "/a/b", "/x/b", local=False) == "/x/b/c"
    assert rebase_path("/a/b", "/a/b", "/x/b", local=False) == "/x/b"
    assert rebase_path("/a/bc", "/a/b", "/x/b", local=False) is None
    assert rebase_path("/a", "/", "/x", local=False) is None          # roots never move
    assert rebase_path("C:\\a\\b\\c", "C:\\a\\b", "D:\\z\\b", local=True) == "D:\\z\\b\\c"
    assert rebase_path("C:\\a", "", "D:\\", local=True) is None


def test_parse_octal_mode():
    assert parse_octal_mode("755") == 0o755
    assert parse_octal_mode("0644") == 0o644
    assert parse_octal_mode("999") is None
    assert parse_octal_mode("rwx") is None


# ── conflicts ────────────────────────────────────────────────────────────────

def test_auto_decisions():
    newer = ConflictInfo(source=_f("a", mtime=2000), target=_f("a", mtime=1000), direction="up")
    older = ConflictInfo(source=_f("a", mtime=1000), target=_f("a", mtime=2000), direction="up")
    assert auto_decision("ask", newer) is None
    assert auto_decision("overwrite", older) == OVERWRITE
    assert auto_decision("skip", newer) == SKIP
    assert auto_decision("keep_both", newer) == KEEP_BOTH
    assert auto_decision("newer", newer) == OVERWRITE
    assert auto_decision("newer", older) == SKIP


def test_resume_only_offered_for_smaller_targets():
    assert ConflictInfo(_f("a", size=100), _f("a", size=40), "up").can_resume
    assert not ConflictInfo(_f("a", size=100), _f("a", size=100), "up").can_resume
    assert not ConflictInfo(_f("a", size=100), _f("a", size=0), "up").can_resume


# ── sync ─────────────────────────────────────────────────────────────────────

def _side(**files):
    return SyncSide(files={k: _f(k, *v) for k, v in files.items()})


def test_sync_upload_copies_missing_changed_and_newer_and_mirrors():
    local = _side(same=(10, 1000), changed=(20, 1000), newer=(10, 5000), only_l=(1, 1))
    remote = _side(same=(10, 1001), changed=(10, 1000), newer=(10, 1000), only_r=(1, 1))
    items = compare_trees(local, remote, SYNC_UPLOAD, delete_extra=True)
    got = {(i.rel, i.action) for i in items}
    assert got == {
        ("changed", ACT_UPLOAD), ("newer", ACT_UPLOAD), ("only_l", ACT_UPLOAD),
        ("only_r", ACT_DELETE_REMOTE),
    }


def test_sync_download_never_deletes_without_mirror():
    local = _side(only_l=(1, 1))
    remote = _side(only_r=(1, 1))
    items = compare_trees(local, remote, SYNC_DOWNLOAD)
    assert [(i.rel, i.action) for i in items] == [("only_r", ACT_DOWNLOAD)]


def test_sync_both_lets_newer_side_win():
    local = _side(a=(10, 5000), b=(10, 1000), c=(1, 1))
    remote = _side(a=(10, 1000), b=(10, 5000), d=(1, 1))
    got = {(i.rel, i.action) for i in compare_trees(local, remote, SYNC_BOTH)}
    assert got == {("a", ACT_UPLOAD), ("b", ACT_DOWNLOAD), ("c", ACT_UPLOAD), ("d", ACT_DOWNLOAD)}


# ── commands ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "file:///C:/Windows/win.ini", "ftp://x/y", "javascript:alert(1)", "http://", "https://a b/c", "",
])
def test_validate_url_rejects(url):
    with pytest.raises(commands.UrlError):
        commands.validate_url(url)


def test_validate_url_accepts_http():
    assert commands.validate_url(" https://example.com/a.zip ") == "https://example.com/a.zip"


def test_filename_from_url():
    assert commands.filename_from_url("https://x.org/dl/My%20File.zip?x=1") == "My File.zip"
    assert commands.filename_from_url("https://x.org/") == "download"
    assert commands.filename_from_url(
        "https://x.org/get", 'attachment; filename="report 2026.pdf"') == "report 2026.pdf"
    evil = commands.filename_from_url("https://x.org/a/..%2F..%2Fevil")
    assert "/" not in evil and "\\" not in evil and not evil.startswith(".")


def test_linux_commands_are_quoted():
    cmd = commands.pack_command(False, "/srv/my dir", ["a b", "-rf"], "out.tar.gz", "tar.gz")
    assert cmd == "cd '/srv/my dir' && tar -czf ./out.tar.gz './a b' ./-rf"
    fetch = commands.fetch_url_command(False, "https://x.org/a;rm$(id)", "/tmp/f")
    assert fetch.count("'https://x.org/a;rm$(id)'") == 2     # curl and wget, both quoted


def test_windows_commands_are_encoded_powershell():
    import base64
    cmd = commands.checksum_command(True, "/C:/Users/it's.txt")
    assert cmd.startswith("powershell -NoProfile -NonInteractive -EncodedCommand ")
    script = base64.b64decode(cmd.rsplit(" ", 1)[1]).decode("utf-16-le")
    assert "-LiteralPath 'C:\\Users\\it''s.txt'" in script


def test_parse_checksum():
    digest = "a" * 64
    assert commands.parse_checksum(f"{digest}  /tmp/x\n") == digest
    assert commands.parse_checksum("A" * 64) == digest
    assert commands.parse_checksum("no hash here") is None


def test_terminal_cd_input():
    assert commands.terminal_cd_input(False, "/var/www") == "cd /var/www && clear\r"
    assert commands.terminal_cd_input(True, "/E:/data") == 'E:\rcd "E:\\data"\rcls\r'


# ── settings ─────────────────────────────────────────────────────────────────

def test_settings_are_clamped_and_tolerant():
    s = BrowserSettings.from_dict({
        "max_uploads": 99, "max_downloads": 0, "conflict_policy": "bogus",
        "limit_up_kib": "250", "open_with": {".TXT": "notepad.exe"}, "unknown": 1,
    })
    assert s.max_uploads == 8 and s.max_downloads == 1
    assert s.conflict_policy == "ask"
    assert s.limit_up_kib == 250
    assert s.program_for("txt") == "notepad.exe"
    assert BrowserSettings.from_dict(None) == BrowserSettings()
