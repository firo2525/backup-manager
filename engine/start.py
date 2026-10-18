"""Startpunkt des Backup Managers.

    pythonw engine/start.py                       → Oberfläche starten
    pythonw engine/start.py --minimized           → unsichtbar im Infobereich starten (Autostart)
    python  engine/start.py --selftest            → Abhängigkeiten prüfen (install.bat)
    python  engine/start.py --create-shortcuts    → Verknüpfungen Desktop + Startmenü (install.bat / Installer)
            [--no-desktop | --keep-desktop] [--pin]
    python  engine/start.py --remove-integration  → Verknüpfungen und Autostart entfernen (Deinstallation)
"""
import os
import sys
import traceback

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

MIN_PYTHON = (3, 9)
_instance = None  # hält den Einzelinstanz-Mutex für die Lebensdauer des Prozesses


def _missing_dependencies():
    missing = []
    modules = [("tkinter", "tkinter (Teil von Python)"), ("customtkinter", "customtkinter"), ("PIL", "pillow"),
               ("darkdetect", "darkdetect"), ("pystray", "pystray")]
    if os.name == "nt":
        modules.append(("win32com", "pywin32"))
    for module, package in modules:
        try:
            __import__(module)
        except Exception:
            missing.append(package)
    return missing


def selftest():
    print(f"Python {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < MIN_PYTHON:
        print(f"FEHLER: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} oder neuer wird benoetigt.")
        return 1
    missing = _missing_dependencies()
    if missing:
        print("FEHLER: Fehlende Pakete: " + ", ".join(missing))
        return 1
    import customtkinter
    import PIL
    print(f"customtkinter {customtkinter.__version__}, pillow {PIL.__version__}")
    from engine import backup, config, system, versions  # noqa: F401
    from engine.ui import app  # noqa: F401
    from engine.ui.icons import ensure_app_icon, FONT_PATH
    ico = ensure_app_icon(system.APP_ICO)
    print(f"Datenordner: {config.DATA_DIR}")
    print(f"Symbolschrift: {FONT_PATH or 'nicht gefunden (Icons werden ausgeblendet)'}")
    print(f"App-Symbol: {ico or 'konnte nicht erzeugt werden'}")
    print("OK")
    return 0


def create_shortcuts(desktop=True, pin=False, all_users=False):
    from engine import system
    try:
        created = system.create_shortcuts(desktop=desktop, start_menu=True, all_users=all_users)
    except Exception as e:
        print(f"Verknuepfungen konnten nicht erstellt werden: {e}")
        return 1
    for path in created:
        print("Verknuepfung erstellt: " + path)
    if pin and created:
        if system.try_pin_to_taskbar(created[-1]):
            print("An die Taskleiste angeheftet.")
        else:
            print("HINWEIS_TASKLEISTE: Windows erlaubt Programmen nicht, sich selbst anzuheften. "
                  "Starte den Backup Manager, Rechtsklick auf sein Symbol in der Taskleiste -> 'An Taskleiste anheften'.")
    return 0


def remove_integration():
    from engine import system
    system.remove_shortcuts(include_taskbar=True)
    system.set_autostart(False)
    print("Verknuepfungen und Autostart entfernt.")
    return 0


def _show_startup_error(title, message, offer_install=False):
    """Fehlermeldung ohne CustomTkinter (nur Tk bzw. Windows-MessageBox)."""
    install = os.path.join(BASE_DIR, "install.bat")
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        if offer_install and os.path.exists(install):
            if messagebox.askyesno(title, message + "\n\nJetzt install.bat ausführen?"):
                os.startfile(install)  # type: ignore[attr-defined]
        else:
            messagebox.showerror(title, message)
        root.destroy()
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message + ("\n\nBitte install.bat ausführen." if offer_install else ""),
                                         title, 0x10)
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)


def _write_crash_log(text):
    try:
        from engine import config
        log_dir = config.LOG_DIR
    except Exception:
        log_dir = os.path.join(BASE_DIR, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "crash.log")
        with open(path, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}\n")
        return path
    except Exception:
        return None


def main():
    global _instance
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    if "--create-shortcuts" in args:
        desktop = "--no-desktop" not in args
        if "--keep-desktop" in args:  # Update: nur ersetzen, was schon da ist
            from engine import system
            desktop = system.has_desktop_shortcut()
        return create_shortcuts(desktop=desktop, pin="--pin" in args, all_users="--all-users" in args)
    if "--remove-integration" in args:
        return remove_integration()

    minimized = "--minimized" in args
    if sys.version_info < MIN_PYTHON:
        _show_startup_error("Backup Manager", f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} oder neuer wird benötigt "
                                              f"(gefunden: {sys.version.split()[0]}).", offer_install=True)
        return 1
    missing = _missing_dependencies()
    if missing:
        _show_startup_error("Backup Manager – fehlende Komponenten",
                            "Folgende Komponenten fehlen:\n  • " + "\n  • ".join(missing), offer_install=True)
        return 1

    from engine import system
    _instance = system.SingleInstance()
    if not _instance.acquire():
        # läuft schon: beim normalen Start das vorhandene Fenster nach vorn holen
        if not minimized:
            _instance.signal_running_instance()
        return 0

    if os.name == "nt":
        try:
            import ctypes
            # eigenes Taskleisten-Symbol (passend zur App-ID der Verknüpfungen)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(system.APP_ID)
        except Exception:
            pass

    try:
        from engine.ui.app import BackupApp
        app = BackupApp(start_minimized=minimized, instance=_instance)
        app.mainloop()
        return 0
    except Exception:
        text = traceback.format_exc()
        path = _write_crash_log(text)
        _show_startup_error("Backup Manager – Fehler beim Start",
                            f"Das Programm konnte nicht gestartet werden.\n\n{text.strip().splitlines()[-1]}"
                            + (f"\n\nDetails: {path}" if path else ""))
        return 1


if __name__ == "__main__":
    sys.exit(main())
