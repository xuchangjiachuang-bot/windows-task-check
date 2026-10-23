"""Explicit recovery of small JSON {pid: integer} locks; never automatic."""
import ctypes as C
from ctypes import wintypes as W
import json
import os


def recover(path):
    """Delete only after exclusive access and proven owner death.

    PID reuse is handled conservatively: an unrelated live PID blocks cleanup.
    This is not a lock acquisition protocol or a substitute for OS file locking.
    """
    if os.name != "nt":
        raise OSError("Lock recovery requires Windows")
    from ._windows import _bind, close, process_alive

    create_file = _bind("CreateFileW", [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE], W.HANDLE)
    read_file = _bind("ReadFile", [W.HANDLE, W.LPVOID, W.DWORD, C.POINTER(W.DWORD), W.LPVOID])
    get_info = _bind("GetFileInformationByHandleEx", [W.HANDLE, C.c_int, W.LPVOID, W.DWORD])
    set_info = _bind("SetFileInformationByHandle", [W.HANDLE, C.c_int, W.LPVOID, W.DWORD])
    # Do not resolve(): opening a symlink itself lets us refuse reparse points.
    name = os.path.abspath(os.fspath(path))
    handle = create_file(name, 0x80000000 | 0x10000, 0, None, 3, 0x00200000, None)
    if handle == W.HANDLE(-1).value:
        return "absent" if C.get_last_error() in (2, 3) else "busy_or_unavailable"
    try:
        attributes = (W.DWORD * 2)()
        if not get_info(handle, 9, attributes, C.sizeof(attributes)):
            return "busy_or_unavailable"
        if attributes[0] & (0x400 | 0x10):  # Reparse point or directory
            return "invalid_lock"
        buffer = C.create_string_buffer(4097)
        size = W.DWORD()
        if not read_file(handle, buffer, 4097, C.byref(size), None) or size.value > 4096:
            return "invalid_lock"
        try:
            value = json.loads(buffer.raw[:size.value])
            pid = value["pid"]
            if type(pid) is not int or not 1 <= pid <= 0xFFFFFFFF:
                return "invalid_lock"
        except (ValueError, KeyError, TypeError, UnicodeError):
            return "invalid_lock"
        try:
            if process_alive(pid):
                return "owner_alive"
        except OSError:
            return "owner_unknown"
        delete = W.BOOL(True)
        if not set_info(handle, 4, C.byref(delete), C.sizeof(delete)):
            return "cleanup_failed"
        return "dead_owner_removed"
    finally:
        close(handle)
