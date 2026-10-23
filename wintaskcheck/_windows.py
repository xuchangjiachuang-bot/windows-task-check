"""Small typed Win32 layer. No shell, task registration or elevation.

Job-list attributes attach the process to its job during creation, avoiding an
orphan window between CreateProcess and AssignProcessToJobObject (Windows 10+).
"""
import ctypes as C
from ctypes import wintypes as W
import os
import subprocess
import time

if os.name != "nt":
    raise OSError("windows-task-check requires Windows 10 or later")

K = C.WinDLL("kernel32", use_last_error=True)
SIZE = C.c_size_t


class BASIC_LIMIT(C.Structure):
    _fields_ = [("PerProcessUserTimeLimit", C.c_int64), ("PerJobUserTimeLimit", C.c_int64),
                ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", SIZE),
                ("MaximumWorkingSetSize", SIZE), ("ActiveProcessLimit", W.DWORD),
                ("Affinity", SIZE), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class IO_COUNTERS(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount",
                "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class EXTENDED_LIMIT(C.Structure):
    _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", SIZE), ("JobMemoryLimit", SIZE),
                ("PeakProcessMemoryUsed", SIZE), ("PeakJobMemoryUsed", SIZE)]


class ACCOUNTING(C.Structure):
    _fields_ = [(name, C.c_int64) for name in ("TotalUserTime", "TotalKernelTime",
                "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")] + [
                (name, W.DWORD) for name in ("TotalPageFaultCount", "TotalProcesses",
                "ActiveProcesses", "TotalTerminatedProcesses")]


class STARTUPINFO(C.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR),
                ("lpTitle", W.LPWSTR)] + [(name, W.DWORD) for name in (
                "dwX", "dwY", "dwXSize", "dwYSize", "dwXCountChars", "dwYCountChars",
                "dwFillAttribute", "dwFlags")] + [("wShowWindow", W.WORD),
                ("cbReserved2", W.WORD), ("lpReserved2", C.POINTER(W.BYTE)),
                ("hStdInput", W.HANDLE), ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]


class STARTUPINFOEX(C.Structure):
    _fields_ = [("StartupInfo", STARTUPINFO), ("lpAttributeList", W.LPVOID)]


class PROCESS_INFORMATION(C.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE),
                ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


def _bind(name, args, result=W.BOOL):
    function = getattr(K, name)
    function.argtypes = args
    function.restype = result
    return function


close = _bind("CloseHandle", [W.HANDLE])
_create_job = _bind("CreateJobObjectW", [W.LPVOID, W.LPCWSTR], W.HANDLE)
_set_job = _bind("SetInformationJobObject", [W.HANDLE, C.c_int, W.LPVOID, W.DWORD])
_query_job = _bind("QueryInformationJobObject", [W.HANDLE, C.c_int, W.LPVOID, W.DWORD, W.LPVOID])
_terminate_job = _bind("TerminateJobObject", [W.HANDLE, W.UINT])
_init_attributes = _bind("InitializeProcThreadAttributeList", [W.LPVOID, W.DWORD, W.DWORD, C.POINTER(SIZE)])
_update_attribute = _bind("UpdateProcThreadAttribute", [W.LPVOID, W.DWORD, SIZE, W.LPVOID, SIZE, W.LPVOID, W.LPVOID])
_delete_attributes = _bind("DeleteProcThreadAttributeList", [W.LPVOID], None)
_create_process = _bind("CreateProcessW", [W.LPCWSTR, W.LPWSTR, W.LPVOID, W.LPVOID,
    W.BOOL, W.DWORD, W.LPVOID, W.LPCWSTR, C.POINTER(STARTUPINFOEX), C.POINTER(PROCESS_INFORMATION)])
_wait = _bind("WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD)
_exit_code = _bind("GetExitCodeProcess", [W.HANDLE, C.POINTER(W.DWORD)])
_duplicate = _bind("DuplicateHandle", [W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD])
_current = _bind("GetCurrentProcess", [], W.HANDLE)
_open_process = _bind("OpenProcess", [W.DWORD, W.BOOL, W.DWORD], W.HANDLE)
_in_job = _bind("IsProcessInJob", [W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)])
_console = _bind("GetConsoleWindow", [], W.HWND)


def checked(value):
    if not value:
        raise C.WinError(C.get_last_error())
    return value


def console_handle():
    return _console() or 0


def process_alive(pid):
    """Return False only for proven death; inaccessible processes raise."""
    handle = _open_process(0x100000, False, pid)
    if not handle:
        if C.get_last_error() == 87:
            return False
        raise C.WinError(C.get_last_error())
    try:
        result = _wait(handle, 0)
        if result == 0xFFFFFFFF:
            raise C.WinError(C.get_last_error())
        return result != 0
    finally:
        close(handle)


class ProcessTree:
    """Own all ordinary descendants; close kills anything still in this job."""

    def __init__(self, argv, cwd, stdin, stdout, stderr):
        import msvcrt

        self.job = None
        self.process = None
        self.pid = None
        self.job = checked(_create_job(None, None))
        attributes = None
        attributes_ready = False
        inherited = []
        info = PROCESS_INFORMATION()
        try:
            limits = EXTENDED_LIMIT()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            checked(_set_job(self.job, 9, C.byref(limits), C.sizeof(limits)))
            size = SIZE()
            _init_attributes(None, 2, 0, C.byref(size))
            attributes = C.create_string_buffer(size.value)
            checked(_init_attributes(attributes, 2, 0, C.byref(size)))
            attributes_ready = True
            for stream in (stdin, stdout, stderr):
                target = W.HANDLE()
                checked(_duplicate(_current(), msvcrt.get_osfhandle(stream.fileno()),
                                   _current(), C.byref(target), 0, True, 2))
                inherited.append(target.value)
            handles = (W.HANDLE * 3)(*inherited)
            jobs = (W.HANDLE * 1)(self.job)
            checked(_update_attribute(attributes, 0, 0x20002, handles, C.sizeof(handles), None, None))
            checked(_update_attribute(attributes, 0, 0x2000D, jobs, C.sizeof(jobs), None, None))
            startup = STARTUPINFOEX()
            startup.StartupInfo.cb = C.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x100 | 1  # USESTDHANDLES | USESHOWWINDOW
            startup.StartupInfo.wShowWindow = 0
            startup.StartupInfo.hStdInput, startup.StartupInfo.hStdOutput, startup.StartupInfo.hStdError = inherited
            startup.lpAttributeList = C.cast(attributes, W.LPVOID)
            command = C.create_unicode_buffer(subprocess.list2cmdline(argv))
            checked(_create_process(argv[0], command, None, None, True,
                0x08000000 | 0x00080000, None, cwd, C.byref(startup), C.byref(info)))
            self.process, self.pid = info.hProcess, info.dwProcessId
        except BaseException:
            self.close()
            raise
        finally:
            if info.hThread:
                close(info.hThread)
            for handle in inherited:
                close(handle)
            if attributes_ready:
                _delete_attributes(attributes)

    def wait(self, timeout):
        # Short waits allow Ctrl+C to be handled promptly by Python.
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            milliseconds = 100 if deadline is None else max(0, min(100, int((deadline - time.monotonic()) * 1000)))
            result = _wait(self.process, milliseconds)
            if result == 0:
                code = W.DWORD()
                checked(_exit_code(self.process, C.byref(code)))
                return code.value
            if result == 0xFFFFFFFF:
                raise C.WinError(C.get_last_error())
            if deadline is not None and time.monotonic() >= deadline:
                return None

    def _member_handles(self):
        # Hold real handles before termination: job accounting can reach zero
        # before a terminating process becomes signaled. PID-only polling also
        # risks observing a reused PID belonging to an unrelated process.
        capacity = 32
        while capacity <= 1048576:
            class PROCESS_IDS(C.Structure):
                _fields_ = [("assigned", W.DWORD), ("count", W.DWORD),
                            ("ids", SIZE * capacity)]
            members = PROCESS_IDS()
            if _query_job(self.job, 3, C.byref(members), C.sizeof(members), None):
                break
            error = C.get_last_error()
            if error != 234:  # ERROR_MORE_DATA: membership grew during query
                raise C.WinError(error)
            capacity = max(capacity * 2, members.assigned)
        else:
            raise OSError("Process-tree membership exceeds cleanup capacity")
        handles = []
        try:
            for pid in members.ids[:members.count]:
                if pid == self.pid:
                    continue
                handle = _open_process(0x100000 | 0x1000, False, pid)
                if not handle:
                    if C.get_last_error() == 87:  # already exited
                        continue
                    raise C.WinError(C.get_last_error())
                try:
                    member = W.BOOL()
                    checked(_in_job(handle, self.job, C.byref(member)))
                    if member.value:
                        handles.append(handle)
                        handle = None
                finally:
                    if handle:
                        close(handle)
            return handles
        except BaseException:
            for handle in handles:
                close(handle)
            raise

    def terminate(self, code=124):
        handles = self._member_handles()
        try:
            checked(_terminate_job(self.job, code))
            deadline = time.monotonic() + 10
            for handle in [self.process, *handles]:
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                result = _wait(handle, remaining)
                if result == 0xFFFFFFFF:
                    raise C.WinError(C.get_last_error())
                if result != 0:
                    raise OSError("Process-tree cleanup did not complete within 10 seconds")
            while True:
                accounting = ACCOUNTING()
                checked(_query_job(self.job, 1, C.byref(accounting), C.sizeof(accounting), None))
                if accounting.ActiveProcesses == 0:
                    return
                if time.monotonic() >= deadline:
                    raise OSError("Process-tree cleanup did not complete within 10 seconds")
                time.sleep(0.01)
        finally:
            for handle in handles:
                close(handle)

    def close(self):
        if self.job:
            close(self.job)
            self.job = None
        if self.process:
            close(self.process)
            self.process = None
