"""Windows-Integration: Autostart, nur eine laufende Instanz, Verknüpfungen, Taskleiste."""
import ctypes
import logging
import os
import subprocess
import sys

from engine import config

APP_ID = "FiratOeztuerk.BackupManager"
APP_NAME = "Backup Manager"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "BackupManager"
START_SCRIPT = os.path.join(config.APP_DIR, "engine", "start.py")
APP_ICO = os.path.join(config.APP_DIR, "engine", "ui", "assets", "app.ico")
IS_WINDOWS = os.name == "nt"
LNK_NAME = APP_NAME + ".lnk"


def pythonw_path():
    venv = os.path.join(config.APP_DIR, ".venv", "Scripts", "pythonw.exe")
    if os.path.exists(venv):
        return venv
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def _no_window():
    return subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0


# --------------------------------------------------------------------------- Autostart

def autostart_command():
    return f'"{pythonw_path()}" "{START_SCRIPT}" --minimized'


def _autostart_value():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_NAME)[0]
    except OSError:
        return None


def autostart_enabled():
    return IS_WINDOWS and _autostart_value() is not None


def set_autostart(enabled):
    """Trägt den Backup Manager in den Windows-Autostart ein (nur aktueller Benutzer, keine Adminrechte)."""
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as e:
        logging.error(f"Autostart konnte nicht geändert werden: {e}")
        return False


def repair_autostart():
    """Passt den Autostart-Eintrag an, falls das Programm verschoben wurde."""
    value = _autostart_value() if IS_WINDOWS else None
    if value and value != autostart_command():
        set_autostart(True)


# --------------------------------------------------------------------------- Einzelinstanz

class SingleInstance:
    """Benannter Mutex + Ereignis: ein zweiter Start holt das laufende Fenster nach vorn."""

    MUTEX = "Local\\FiratOeztuerk.BackupManager.Instance"
    EVENT = "Local\\FiratOeztuerk.BackupManager.Show"

    def __init__(self):
        self.mutex = None
        self.event = None
        self._k32 = None
        if IS_WINDOWS:
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateMutexW.restype = wintypes.HANDLE
            k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            k32.CreateEventW.restype = wintypes.HANDLE
            k32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
            k32.OpenEventW.restype = wintypes.HANDLE
            k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
            k32.SetEvent.argtypes = [wintypes.HANDLE]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k32.WaitForSingleObject.restype = wintypes.DWORD
            self._k32 = k32

    def acquire(self):
        """True, wenn dies die erste Instanz ist."""
        if not self._k32:
            return True
        self.mutex = self._k32.CreateMutexW(None, False, self.MUTEX)
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            return False
        self.event = self._k32.CreateEventW(None, False, False, self.EVENT)
        return True

    def signal_running_instance(self):
        if not self._k32:
            return False
        handle = self._k32.OpenEventW(0x0002, False, self.EVENT)  # EVENT_MODIFY_STATE
        if not handle:
            return False
        self._k32.SetEvent(handle)
        self._k32.CloseHandle(handle)
        return True

    def show_requested(self):
        return bool(self.event) and self._k32.WaitForSingleObject(self.event, 0) == 0


# --------------------------------------------------------------------------- Verknüpfungen

def _folder(csidl):
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


def desktop_dir(all_users=False):
    return _folder(0x0019 if all_users else 0x0010)  # CSIDL_(COMMON_)DESKTOPDIRECTORY


def has_desktop_shortcut():
    return any(os.path.exists(os.path.join(desktop_dir(all_users), LNK_NAME)) for all_users in (False, True))


def programs_dir(all_users=False):
    return _folder(0x0017 if all_users else 0x0002)  # CSIDL_(COMMON_)PROGRAMS (Startmenü\Programme)


def taskbar_pin_dir():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Internet Explorer", "Quick Launch",
                        "User Pinned", "TaskBar")


def _create_link_pywin32(path, target, args, workdir, icon, description):
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell
    pythoncom.CoInitialize()
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    link.SetPath(target)
    link.SetArguments(args)
    link.SetWorkingDirectory(workdir)
    link.SetIconLocation(icon, 0)
    link.SetDescription(description)
    store = link.QueryInterface(propsys.IID_IPropertyStore)
    # gleiche App-ID wie das laufende Fenster → angeheftetes Symbol und Fenster gehören zusammen
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(path, 0)


def _create_link_powershell(path, target, args, workdir, icon, description):
    def ps(value):
        return "'" + value.replace("'", "''") + "'"
    cmd = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({ps(path)}); "
           f"$s.TargetPath = {ps(target)}; $s.Arguments = {ps(args)}; $s.WorkingDirectory = {ps(workdir)}; "
           f"$s.IconLocation = {ps(icon)}; $s.Description = {ps(description)}; $s.Save()")
    res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                         capture_output=True, text=True, creationflags=_no_window())
    if res.returncode != 0:
        raise OSError(res.stderr.strip() or "PowerShell-Fehler")


def create_shortcut(folder):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, LNK_NAME)
    args = (pythonw_path(), f'"{START_SCRIPT}"', config.APP_DIR, APP_ICO,
            "Backup Manager – entwickelt von Firat Öztürk")
    try:
        _create_link_pywin32(path, *args)
    except Exception as e:
        logging.info(f"pywin32 nicht verfügbar ({e}) – Verknüpfung per PowerShell")
        _create_link_powershell(path, *args)
    return path


def create_shortcuts(desktop=True, start_menu=True, all_users=False):
    remove_shortcuts()  # keine doppelten Verknüpfungen (Benutzer + alle Benutzer)
    created = []
    if desktop:
        created.append(create_shortcut(desktop_dir(all_users)))
    if start_menu:
        created.append(create_shortcut(programs_dir(all_users)))
    return created


def remove_shortcuts(include_taskbar=False):
    folders = [desktop_dir(), programs_dir(), desktop_dir(True), programs_dir(True)]
    if include_taskbar:
        folders.append(taskbar_pin_dir())
    for folder in folders:
        path = os.path.join(folder, LNK_NAME)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def is_pinned_to_taskbar():
    return os.path.exists(os.path.join(taskbar_pin_dir(), LNK_NAME))


def try_pin_to_taskbar(shortcut_path):
    """Versucht, die Verknüpfung an die Taskleiste anzuheften. Windows 11 (und neuere Windows-10-Versionen)
    erlauben das Programmen nicht – dann False, und der Nutzer heftet per Rechtsklick selbst an."""
    if is_pinned_to_taskbar():
        return True
    folder, name = os.path.split(shortcut_path)

    def ps(value):
        return "'" + value.replace("'", "''") + "'"
    cmd = (f"$i = (New-Object -ComObject Shell.Application).Namespace({ps(folder)}).ParseName({ps(name)}); "
           "$v = $i.Verbs() | Where-Object { $_.Name.Replace('&','') -match 'An Taskleiste anheften|Pin to taskbar' }; "
           "if ($v) { $v.DoIt() }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                       capture_output=True, text=True, timeout=20, creationflags=_no_window())
    except Exception:
        pass
    return is_pinned_to_taskbar()
