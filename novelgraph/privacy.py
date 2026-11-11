"""OS-native fail-closed private file permissions for NovelGraph data.

POSIX requires owner-only mode. Windows uses the *effective DACL entries*,
not os.stat().st_mode, which does not represent NTFS permissions.
"""
from __future__ import annotations

import os
from pathlib import Path


def private_path(path: Path) -> bool:
    """Only current owner, local Administrators and SYSTEM may have Allow ACEs.

Windows DACL unreadable, NULL DACL, or unsupported Allow ACE => deny.
    """
    if os.name != "nt":
        return not bool(path.stat().st_mode & 0o077)
    return _windows_private_path(path)


def _windows_private_path(path: Path) -> bool:
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p

    class ACL(ctypes.Structure):
        _fields_ = [("revision", ctypes.c_ubyte), ("sbz1", ctypes.c_ubyte),
                    ("size", ctypes.c_ushort), ("count", ctypes.c_ushort),
                    ("sbz2", ctypes.c_ushort)]

    get_security = advapi.GetNamedSecurityInfoW
    get_security.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.POINTER(pointer), ctypes.POINTER(pointer),
                             ctypes.POINTER(pointer), ctypes.POINTER(pointer),
                             ctypes.POINTER(pointer)]
    get_security.restype = wintypes.DWORD
    get_ace = advapi.GetAce
    get_ace.argtypes = [pointer, wintypes.DWORD, ctypes.POINTER(pointer)]
    get_ace.restype = wintypes.BOOL
    convert_sid = advapi.ConvertSidToStringSidW
    convert_sid.argtypes = [pointer, ctypes.POINTER(pointer)]
    convert_sid.restype = wintypes.BOOL
    local_free = kernel.LocalFree
    local_free.argtypes = [pointer]
    local_free.restype = pointer

    def sid_text(sid: pointer) -> str:
        result = pointer()
        if not convert_sid(sid, ctypes.byref(result)):
            raise OSError("Cannot resolve Windows file ACL identity")
        try:
            return ctypes.wstring_at(result).upper()
        finally:
            local_free(result)

    def token_identity() -> str:
        kernel.GetCurrentProcess.restype = pointer
        advapi.OpenProcessToken.argtypes = [pointer, wintypes.DWORD, ctypes.POINTER(pointer)]
        advapi.OpenProcessToken.restype = wintypes.BOOL
        advapi.GetTokenInformation.argtypes = [pointer, wintypes.DWORD, pointer,
                                               wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        advapi.GetTokenInformation.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [pointer]
        kernel.CloseHandle.restype = wintypes.BOOL
        token = pointer()
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise OSError("Cannot read Windows process token")
        try:
            size = wintypes.DWORD()
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not 8 <= size.value <= 65536:
                raise OSError("Invalid Windows process token")
            buffer = ctypes.create_string_buffer(size.value)
            if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
                raise OSError("Cannot resolve Windows process identity")
            return sid_text(ctypes.cast(buffer, ctypes.POINTER(pointer)).contents)
        finally:
            kernel.CloseHandle(token)

    owner = pointer()
    dacl = pointer()
    descriptor = pointer()
    try:
        if get_security(str(path), 1, 0x00000005, ctypes.byref(owner), None,
                        ctypes.byref(dacl), None, ctypes.byref(descriptor)) != 0:
            return False
        if not owner.value or not dacl.value:
            return False
        user = token_identity()
        owner_sid = sid_text(owner)
        # OWNER RIGHTS (S-1-3-4) applies only to the file owner; not a public group.
        allowed = {user, "S-1-5-18", "S-1-5-32-544", "S-1-3-4"}
        if owner_sid not in allowed:
            return False
        entries = ctypes.cast(dacl, ctypes.POINTER(ACL)).contents
        if not 0 <= entries.count <= 4096:
            return False
        for i in range(entries.count):
            ace = pointer()
            if not get_ace(dacl, i, ctypes.byref(ace)) or not ace.value:
                return False
            code = ctypes.c_ubyte.from_address(ace.value).value
            flags = ctypes.c_ubyte.from_address(ace.value + 1).value
            mask = ctypes.c_uint32.from_address(ace.value + 4).value
            # ACE_FLAG INHERIT_ONLY (0x08) does not grant current path access.
            if flags & 0x08 or mask == 0:
                continue
            if code == 0:  # ACCESS_ALLOWED_ACE_TYPE; SID immediately after Mask.
                if sid_text(pointer(ace.value + 8)) not in allowed:
                    return False
            elif code in (5, 9, 11):
                # Object or callback ALLOW ACEs have different layouts: fail closed.
                return False
        return True
    except (OSError, ValueError):
        return False
    finally:
        if descriptor.value:
            local_free(descriptor)
