"""Anmeldung an Netzwerkfreigaben (NAS) über die Windows-Netzwerk-API.

Das Passwort wird nie vom Backup Manager gespeichert: Mit „Anmeldedaten speichern“ landet es – wie beim gleichnamigen
Haken im Explorer – in der Windows-Anmeldeinformationsverwaltung, die Windows bei späteren Zugriffen auf diesen
Server automatisch verwendet (auch bei der Synchronisierung im Hintergrund).
"""
import ctypes
import os
from ctypes import wintypes

from engine import utils

_RESOURCETYPE_DISK = 1
_CRED_TYPE_DOMAIN_PASSWORD = 2
_CRED_PERSIST_ENTERPRISE = 3  # wie „Anmeldedaten speichern“ im Explorer


class _NETRESOURCEW(ctypes.Structure):
    _fields_ = [('dwScope', wintypes.DWORD), ('dwType', wintypes.DWORD), ('dwDisplayType', wintypes.DWORD),
                ('dwUsage', wintypes.DWORD), ('lpLocalName', wintypes.LPWSTR), ('lpRemoteName', wintypes.LPWSTR),
                ('lpComment', wintypes.LPWSTR), ('lpProvider', wintypes.LPWSTR)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD), ('TargetName', wintypes.LPWSTR),
                ('Comment', wintypes.LPWSTR), ('LastWritten', wintypes.FILETIME),
                ('CredentialBlobSize', wintypes.DWORD), ('CredentialBlob', ctypes.c_void_p),
                ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD), ('Attributes', ctypes.c_void_p),
                ('TargetAlias', wintypes.LPWSTR), ('UserName', wintypes.LPWSTR)]


def _add_connection(share, user, password):
    nr = _NETRESOURCEW()
    nr.dwType = _RESOURCETYPE_DISK
    nr.lpRemoteName = share
    mpr = ctypes.WinDLL('mpr')
    mpr.WNetAddConnection2W.argtypes = [ctypes.POINTER(_NETRESOURCEW), wintypes.LPCWSTR, wintypes.LPCWSTR,
                                        wintypes.DWORD]
    return mpr.WNetAddConnection2W(ctypes.byref(nr), password, user or None, 0)


def save_credentials(server, user, password):
    """Legt die Anmeldedaten für `server` in der Windows-Anmeldeinformationsverwaltung ab. Rückgabe: True/False."""
    blob = password.encode('utf-16-le')
    buf = ctypes.create_string_buffer(blob, len(blob))
    cred = _CREDENTIALW()
    cred.Type = _CRED_TYPE_DOMAIN_PASSWORD
    cred.TargetName = server
    cred.UserName = user
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.c_void_p)
    cred.Persist = _CRED_PERSIST_ENTERPRISE
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    advapi.CredWriteW.restype = wintypes.BOOL
    ok = bool(advapi.CredWriteW(ctypes.byref(cred), 0))
    ctypes.memset(buf, 0, len(blob))
    return ok


def delete_credentials(server):
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredDeleteW.restype = wintypes.BOOL
    return bool(advapi.CredDeleteW(server, _CRED_TYPE_DOMAIN_PASSWORD, 0))


def connect(path, user, password, remember=True):
    """Meldet sich an der Freigabe von `path` an. Rückgabe: None bei Erfolg, sonst eine Fehlermeldung."""
    if os.name != 'nt':
        return "Die Anmeldung an Netzwerkfreigaben ist nur unter Windows möglich."
    share, server = utils.unc_root(path), utils.server_of(path)
    if not share:
        return "Das ist kein Netzwerkpfad."
    rc = _add_connection(share, user, password)
    if rc not in (0, 1202):  # 1202 = ERROR_DEVICE_ALREADY_REMEMBERED
        err = OSError(None, ctypes.FormatError(rc).strip(), None, rc)
        return utils.network_error_text(err, utils.location_name(path), server)
    if remember and user and not save_credentials(server, user, password):
        utils.forget_network_status(path)
        return ("Verbunden, aber die Anmeldedaten konnten nicht gespeichert werden – nach einem Neustart ist eine "
                "erneute Anmeldung nötig.")
    utils.forget_network_status(path)
    return None
