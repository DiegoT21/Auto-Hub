"""Una sola instancia de Auto-Hub. El segundo exe restaura la ventana."""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

MUTEX_NAME = "Local\\Posper.AutoHub.1"
EVENT_NAME = "Local\\Posper.AutoHub.1.Show"

ERROR_ALREADY_EXISTS = 183
INFINITE = 0xFFFFFFFF
EVENT_MODIFY_STATE = 0x0002

_kernel32 = ctypes.windll.kernel32
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.SetEvent.restype = wintypes.BOOL
_kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
_kernel32.ResetEvent.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.GetLastError.restype = wintypes.DWORD


class InstanceLock:
    def __init__(self) -> None:
        self.mutex = None
        self.event = None

    def acquire(self) -> bool:
        """True si esta es la primera instancia. Si no, avisa a la que ya corre."""
        self.mutex = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if _kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            ev = _kernel32.OpenEventW(EVENT_MODIFY_STATE, False, EVENT_NAME)
            if ev:
                _kernel32.SetEvent(ev)
                _kernel32.CloseHandle(ev)
            if self.mutex:
                _kernel32.CloseHandle(self.mutex)
                self.mutex = None
            return False
        self.event = _kernel32.CreateEventW(None, True, False, EVENT_NAME)
        return True

    def watch_show(self, callback: Callable[[], None]) -> None:
        if not self.event:
            return

        def loop() -> None:
            while True:
                _kernel32.WaitForSingleObject(self.event, INFINITE)
                _kernel32.ResetEvent(self.event)
                try:
                    callback()
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True).start()
