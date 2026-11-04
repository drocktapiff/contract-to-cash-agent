"""Current-user Windows generic credentials. No plaintext files or shell arguments."""

import ctypes
from ctypes import wintypes
import os
from .operator_auth import valid_operator_password


class CredentialError(RuntimeError):
    pass


class Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def api():
    if os.name != "nt":
        raise CredentialError("Windows Credential Manager is only available on Windows")
    dll = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    dll.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    dll.CredFree.restype = None
    return dll


def read(target):
    dll = api()
    pointer = ctypes.POINTER(Credential)()
    if not dll.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
            return None
        raise CredentialError("Credential Manager could not read the operator credential")
    try:
        size = pointer.contents.CredentialBlobSize
        if size > 2048 or size % 2:
            raise CredentialError("Stored operator credential has an unsupported format")
        return ctypes.string_at(pointer.contents.CredentialBlob, size).decode("utf-16-le")
    except UnicodeError:
        raise CredentialError("Stored operator credential has an unsupported format") from None
    finally:
        dll.CredFree(pointer)


def write(target, password):
    if not valid_operator_password(password):
        raise CredentialError("Local operator password must contain 5–512 characters and no NUL")
    dll = api()
    blob = ctypes.create_string_buffer(password.encode("utf-16-le"))
    try:
        credential = Credential()
        credential.Type, credential.Persist = 1, 2  # Generic; current user on this machine.
        credential.TargetName = target
        credential.UserName = "Ledgerline local operator"
        credential.CredentialBlobSize = len(password.encode("utf-16-le"))
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        if not dll.CredWriteW(ctypes.byref(credential), 0):
            raise CredentialError("Credential Manager could not save the operator credential")
    finally:
        ctypes.memset(ctypes.addressof(blob), 0, ctypes.sizeof(blob))


def delete(target):
    dll = api()
    if not dll.CredDeleteW(target, 1, 0) and ctypes.get_last_error() != 1168:
        raise CredentialError("Credential Manager could not remove the operator credential")
