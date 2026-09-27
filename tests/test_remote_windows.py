import pytest

from src.remote_os import os_from_banner
from src.remote_path import looks_like_windows_path, normalize_remote_input
from src.ui.system_info_panel import SSHSystemInfoThread, _fmt_kb


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"W:\foo\bar", "/W:/foo/bar"),
        ("C:/Users", "/C:/Users"),
        ("/C:/Users", "/C:/Users"),
        ("W:\\", "/W:"),
        ("/C:/a//b/", "/C:/a/b"),
        ("", "/"),
    ],
)
def test_normalize_windows_input(raw, expected):
    assert normalize_remote_input(raw, True) == expected


def test_normalize_posix_input_only_adds_leading_slash():
    assert normalize_remote_input("home/alice", False) == "/home/alice"
    assert normalize_remote_input("/var", False) == "/var"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/C:/Users/Administrator", True),
        (r"C:\Users", True),
        ("/home/alice", False),
        ("/", False),
    ],
)
def test_looks_like_windows_path(path, expected):
    assert looks_like_windows_path(path) is expected


@pytest.mark.parametrize(
    ("banner", "expected"),
    [
        ("SSH-2.0-OpenSSH_for_Windows_9.5", "windows"),
        ("SSH-2.0-9.35 FlowSsh: Bitvise SSH Server (WinSSHD) 9.35", "windows"),
        ("SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.10", None),
        (None, None),
    ],
)
def test_os_from_banner(banner, expected):
    assert os_from_banner(banner) == expected


def test_has_ok_needs_bare_sentinel_line():
    assert SSHSystemInfoThread._has_ok("motd\n##SSH_OK##\n##_os_##\n")
    # cmd.exe echoes the Linux probe including its quotes.
    assert not SSHSystemInfoThread._has_ok("'##SSH_OK##'; echo '##_os_##'\n")


def test_linux_disk_parsed_from_raw_kib_figures():
    raw = (
        "##SSH_OK##\n"
        "##_mem_kb_##\n16757160 3069708\n"
        "##_disk_kb_##\n102687672 20123456 77334216\n"
    )
    info = SSHSystemInfoThread._parse_sentinels(raw)
    SSHSystemInfoThread._postprocess(info)

    assert info["memory_total"] == "16.0G"
    assert info["memory_used"] == "13.1G"
    assert info["memory_percent"] == "81.7"
    assert info["disk_total"] == "97.9G"
    assert info["disk_used"] == "19.2G"
    # df's Use% basis: used / (used + available)
    assert info["disk_use_percent"] == "20.6"


def test_drives_section_keeps_one_record_per_line():
    raw = "##SSH_OK##\n##_drives_##\n0|NTFS|10|5|5|C:|\n1|exFAT|20|5|15|E:|Stick\n##_ip_##\n10.0.0.1\n"
    info = SSHSystemInfoThread._parse_sentinels(raw)
    assert info["drives"].splitlines() == ["0|NTFS|10|5|5|C:|", "1|exFAT|20|5|15|E:|Stick"]
    assert info["ip"] == "10.0.0.1"


def test_windows_drives_titled_by_letter_and_label():
    info = {
        "_detected_os": "windows",
        "drives": "1|exFAT|61049856|12345678|48704178|E:|USB Stick\n"
                  "0|NTFS|229691388|222965936|6725452|C:|\n"
                  "garbage line\n",
    }
    SSHSystemInfoThread._postprocess(info)
    drives = info["drives_list"]

    assert [d["title"] for d in drives] == ["C:", "E: USB Stick"]
    assert drives[0]["external"] is False and drives[0]["detail"] == "NTFS"
    assert drives[1]["external"] is True
    assert drives[1]["used"] == "11.8G" and drives[1]["total"] == "58.2G"


def test_linux_drives_root_first_and_mountpoint_kept_whole():
    info = {
        "_detected_os": "linux",
        "drives": "0|xfs|2000000000|1800000000|200000000|/dev/mapper/vg-data|/data\n"
                  "1|exfat|61049856|12345678|48704178|/dev/sdb1|/media/greg/My | Stick\n"
                  "0|ext4|102687672|20123456|77334216|/dev/nvme0n1p2|/\n",
    }
    SSHSystemInfoThread._postprocess(info)
    drives = info["drives_list"]

    assert [d["title"] for d in drives] == ["/", "/data", "/media/greg/My | Stick"]
    assert drives[0]["detail"] == "/dev/nvme0n1p2 · ext4"
    assert drives[2]["external"] is True
    assert round(drives[1]["percent"]) == 90


def test_postprocess_ignores_malformed_figures():
    info = {"mem_kb": "n/a", "disk_kb": "1 2"}
    SSHSystemInfoThread._postprocess(info)
    assert "memory_total" not in info
    assert "disk_total" not in info


@pytest.mark.parametrize(
    ("kb", "expected"),
    [(512, "512K"), (2048, "2.0M"), (16318464, "15.6G"), (3 * 1024**3, "3.0T")],
)
def test_fmt_kb(kb, expected):
    assert _fmt_kb(kb) == expected
