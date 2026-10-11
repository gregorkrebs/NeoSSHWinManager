"""
ipc_security.py – The named pipe between the GUI instance and its helpers
(SSH_ASKPASS helper, NeoSSHWinManager-cli.exe).

Server side: the pipe gets a protected DACL that admits only the account the
app runs as, rejects remote clients, and the first instance must be created
by the app itself (a pipe of that name somebody else created first is never
joined).

Client side: before anything is sent (a CLI access key, an askpass token),
the process serving the pipe must run as the same account. On a shared
machine (terminal server) another user could otherwise create the pipe name
first and collect what the clients send.

Pure ctypes on private WinDLL instances, so the argtypes set here never
change the signatures other modules see through ctypes.windll.
"""

from __future__ import annotations

import ctypes
import json
import sys
from ctypes import wintypes
from typing import Optional

PIPE_NAME = r"\\.\pipe\SSHWinManager_IPC_v1"

PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008

SERVER_OPEN_MODE = PIPE_ACCESS_DUPLEX
SERVER_PIPE_MODE = PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SDDL_REVISION_1 = 1
_ERROR_MORE_DATA = 234
_MAX_REPLY_BYTES = 2 * 1024 * 1024


class IpcError(Exception):
    """The request could not be delivered."""


class IpcNotRunning(IpcError):
    """No pipe of that name: the app is not running (or not signed in)."""


class IpcUntrustedServer(IpcError):
    """The pipe is served by a process of another account."""


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


_LIBS = None


def _libs():
    global _LIBS
    if _LIBS is not None:
        return _LIBS
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    HANDLE, DWORD, BOOL = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL

    k.GetCurrentProcess.argtypes = []
    k.GetCurrentProcess.restype = HANDLE
    k.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
    k.OpenProcess.restype = HANDLE
    k.CloseHandle.argtypes = [HANDLE]
    k.CloseHandle.restype = BOOL
    k.LocalFree.argtypes = [ctypes.c_void_p]
    k.LocalFree.restype = ctypes.c_void_p
    k.GetNamedPipeServerProcessId.argtypes = [HANDLE, ctypes.POINTER(wintypes.ULONG)]
    k.GetNamedPipeServerProcessId.restype = BOOL
    k.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, DWORD]
    k.WaitNamedPipeW.restype = BOOL
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, DWORD, DWORD, ctypes.c_void_p, DWORD, DWORD, HANDLE]
    k.CreateFileW.restype = HANDLE
    k.SetNamedPipeHandleState.argtypes = [HANDLE, ctypes.POINTER(DWORD), ctypes.c_void_p, ctypes.c_void_p]
    k.SetNamedPipeHandleState.restype = BOOL
    k.WriteFile.argtypes = [HANDLE, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD), ctypes.c_void_p]
    k.WriteFile.restype = BOOL
    k.ReadFile.argtypes = [HANDLE, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD), ctypes.c_void_p]
    k.ReadFile.restype = BOOL

    a.OpenProcessToken.argtypes = [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
    a.OpenProcessToken.restype = BOOL
    a.GetTokenInformation.argtypes = [HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD)]
    a.GetTokenInformation.restype = BOOL
    a.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    a.EqualSid.restype = BOOL
    a.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    a.ConvertSidToStringSidW.restype = BOOL
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.ULONG)]
    a.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = BOOL
    _LIBS = (k, a)
    return _LIBS


def _invalid(handle) -> bool:
    return handle is None or handle == ctypes.c_void_p(-1).value


def _token_user(process_handle):
    """TOKEN_USER of a process as a buffer (its SID points into it), or None."""
    k, a = _libs()
    token = wintypes.HANDLE()
    if not a.OpenProcessToken(process_handle, _TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD()
        a.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        if not size.value:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if not a.GetTokenInformation(token, _TOKEN_USER, buf, size, ctypes.byref(size)):
            return None
        return buf
    finally:
        k.CloseHandle(token)


def _sid_of(token_user_buf) -> int:
    # TOKEN_USER starts with SID_AND_ATTRIBUTES, whose first member is the PSID.
    return ctypes.cast(token_user_buf, ctypes.POINTER(ctypes.c_void_p))[0]


def process_runs_as_current_user(pid: int) -> bool:
    """True if the process `pid` runs under the same account as this one."""
    k, a = _libs()
    mine = _token_user(k.GetCurrentProcess())
    if mine is None:
        return False
    proc = k.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not proc:
        return False
    try:
        theirs = _token_user(proc)
    finally:
        k.CloseHandle(proc)
    if theirs is None:
        return False
    return bool(a.EqualSid(_sid_of(mine), _sid_of(theirs)))


def owner_only_security_attributes() -> Optional[SECURITY_ATTRIBUTES]:
    """
    SECURITY_ATTRIBUTES whose protected DACL grants read/write to this
    process's account only, or None if it cannot be built. The descriptor is
    allocated by Windows and stays valid for the life of the process: create
    the attributes once and reuse them.
    """
    k, a = _libs()
    mine = _token_user(k.GetCurrentProcess())
    if mine is None:
        return None
    sid_str = wintypes.LPWSTR()
    if not a.ConvertSidToStringSidW(_sid_of(mine), ctypes.byref(sid_str)):
        return None
    try:
        sddl = f"D:P(A;;GRGW;;;{sid_str.value})"
    finally:
        k.LocalFree(ctypes.cast(sid_str, ctypes.c_void_p))
    sd = ctypes.c_void_p()
    if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, _SDDL_REVISION_1, ctypes.byref(sd), None):
        return None
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = sd.value
    sa.bInheritHandle = False
    return sa


def _connect(timeout_ms: int):
    k, _a = _libs()
    if not k.WaitNamedPipeW(PIPE_NAME, timeout_ms):
        raise IpcNotRunning(PIPE_NAME)
    handle = k.CreateFileW(PIPE_NAME, _GENERIC_READ | _GENERIC_WRITE, 0, None,
                           _OPEN_EXISTING, 0, None)
    if _invalid(handle):
        raise IpcError(f"CreateFile failed ({ctypes.get_last_error()})")
    pid = wintypes.ULONG()
    if not (k.GetNamedPipeServerProcessId(handle, ctypes.byref(pid))
            and process_runs_as_current_user(pid.value)):
        k.CloseHandle(handle)
        raise IpcUntrustedServer(PIPE_NAME)
    mode = wintypes.DWORD(PIPE_READMODE_MESSAGE)
    k.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None)
    return handle


def request(payload: dict, timeout_ms: int = 10000) -> dict:
    """
    Send one JSON request to the running app and return its JSON reply.
    Raises IpcNotRunning, IpcUntrustedServer or IpcError.
    """
    if sys.platform != "win32":
        raise IpcNotRunning("named pipes need Windows")
    k, _a = _libs()
    handle = _connect(timeout_ms)
    try:
        data = json.dumps(payload).encode("utf-8")
        written = wintypes.DWORD()
        if not k.WriteFile(handle, data, len(data), ctypes.byref(written), None):
            raise IpcError(f"WriteFile failed ({ctypes.get_last_error()})")
        chunk = ctypes.create_string_buffer(65536)
        read = wintypes.DWORD()
        reply = bytearray()
        while True:
            ok = k.ReadFile(handle, chunk, len(chunk), ctypes.byref(read), None)
            reply.extend(chunk.raw[:read.value])
            if ok:
                break
            if ctypes.get_last_error() != _ERROR_MORE_DATA or len(reply) > _MAX_REPLY_BYTES:
                raise IpcError("no complete reply")
    finally:
        k.CloseHandle(handle)
    try:
        return json.loads(reply.decode("utf-8"))
    except ValueError as e:
        raise IpcError("invalid reply") from e
