# single_instance.py
# Ensures only one instance of application runs at a time.
#
# How it works:
#   1. On startup, try to create a named Windows Mutex.
#   2. If mutex already exists → another instance is running.
#   3. Find that instance's window via EnumWindows and bring it to front.
#   4. Then exit immediately.
#
# The mutex is automatically released by Windows when the process exits,
# even on crash – no cleanup needed.

import ctypes
import ctypes.wintypes
import sys
import os

# Must match the app's main window title (or a unique prefix of it)
APP_WINDOW_TITLE = "NEO SSH-Win Manager"

try:
    with open(os.path.join(os.path.dirname(__file__), "version.txt"), "r", encoding="utf-8") as f:
        APP_VERSION = f.read().strip()
except Exception:
    APP_VERSION = "?"

# Unique mutex name – use your app name + a GUID to avoid collisions
MUTEX_NAME = f"SSHFSWinManager_SingleInstance_Mutex_v{APP_VERSION}{{A3F2B1C4-9E7D-4A8F-B3C2-1D5E6F7A8B9C}}"


def _find_and_focus_existing_window() -> bool:
    """
    Enumerate all top-level windows, find the one belonging to the
    already-running instance, restore it if minimized, and bring it
    to the foreground.
    Returns True if the window was found and focused.
    """
    user32 = ctypes.windll.user32

    found_hwnd = ctypes.wintypes.HWND(0)
    hidden_hwnd = ctypes.wintypes.HWND(0)

    # EnumWindows callback signature: BOOL CALLBACK(HWND hwnd, LPARAM lParam)
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def _enum_callback(hwnd, lparam):
        # Get window title
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True  # continue enumeration

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        if APP_WINDOW_TITLE.lower() in title.lower():
            if user32.IsWindowVisible(hwnd):
                found_hwnd.value = hwnd
                return False  # stop enumeration
            if not hidden_hwnd.value:
                hidden_hwnd.value = hwnd
        return True  # continue

    callback = WNDENUMPROC(_enum_callback)
    user32.EnumWindows(callback, 0)

    hwnd = found_hwnd.value or hidden_hwnd.value

    if hwnd:
        SW_RESTORE = 9
        SW_SHOW = 5
        # Restore if minimized
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.ShowWindow(hwnd, SW_SHOW)
        # Bring to foreground (works even if window is behind others)
        user32.SetForegroundWindow(hwnd)
        # Flash taskbar button to draw attention
        user32.FlashWindow(hwnd, True)
        return True

    return False


def ensure_single_instance() -> None:
    """
    Call this at the very start of main(), before creating QApplication.

    If another instance is already running:
      - Focuses that instance's window
      - Exits this process immediately with code 0

    If this is the first instance:
      - Creates the mutex and returns normally
      - The mutex lives for the entire process lifetime
    """
    kernel32 = ctypes.windll.kernel32

    # Try to create the mutex
    # If it already exists, GetLastError() returns ERROR_ALREADY_EXISTS (183)
    mutex = kernel32.CreateMutexW(
        None,       # default security
        True,       # request initial ownership
        MUTEX_NAME,
    )

    last_error = kernel32.GetLastError()
    ERROR_ALREADY_EXISTS = 183

    if last_error == ERROR_ALREADY_EXISTS:
        _find_and_focus_existing_window()
        sys.exit(0)

    # Store mutex handle in a module-level variable so it is NOT garbage-collected.
    global _mutex_handle
    _mutex_handle = mutex

# Module-level handle – must stay alive for the entire process lifetime
_mutex_handle = None


def release_instance_lock() -> None:
    """Release the mutex so a new instance can start (e.g. for restart)."""
    global _mutex_handle
    if _mutex_handle:
        ctypes.windll.kernel32.ReleaseMutex(_mutex_handle)
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None
