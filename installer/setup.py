"""Backup Manager – Installer / Deinstaller.

Wird mit PyInstaller zu "BackupManager-Setup.exe" gebaut (siehe build_installer.py). Ablauf:
  1. Programmdateien (payload.zip) nach C:\\Program Files\\BackupManager kopieren
  2. install.bat ausführen → Python + Pakete automatisch installieren
  3. Verknüpfungen (Desktop, Startmenü, Taskleiste versuchen), Eintrag unter „Apps“ mit Deinstallation

Parameter:
  /S              ohne Oberfläche (Protokoll: %TEMP%\\BackupManager-Setup.log)
  /D=<Ordner>     Installationsordner
  /nodesktop /nopin /nostart
  /uninstall [/purge]   entfernen (/purge löscht auch Einstellungen, Logs und Snapshots)
"""
import ctypes
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import zipfile

FROZEN = getattr(sys, "frozen", False)
HERE = os.path.dirname(os.path.abspath(__file__))
if not FROZEN:
    sys.path.insert(0, os.path.dirname(HERE))  # Projektordner → engine.* importierbar
BUNDLE = getattr(sys, "_MEIPASS", HERE)
PAYLOAD = os.path.join(BUNDLE, "payload.zip") if FROZEN else os.path.join(HERE, "build", "payload.zip")
ICON_FILE = os.path.join(BUNDLE, "app.ico") if FROZEN else os.path.join(os.path.dirname(HERE), "engine", "ui", "assets", "app.ico")

from engine.version import APP_NAME, DEVELOPER, VERSION, WEBSITE, WEBSITE_LABEL  # noqa: E402

UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\BackupManager"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
LNK_NAME = APP_NAME + ".lnk"
PROGRAM_FILES = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
DEFAULT_DIR = os.path.join(PROGRAM_FILES, "BackupManager")
USER_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Programs", "BackupManager")
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "BackupManager")
LOG_FILE = os.path.join(tempfile.gettempdir(), "BackupManager-Setup.log")
NO_WINDOW = 0x08000000


# =========================================================================== Hilfsfunktionen

def parse_args(argv):
    o = {"silent": False, "dir": None, "desktop": True, "pin": True, "start": True,
         "uninstall": False, "purge": False, "go": False, "elevated": False}
    for a in argv:
        al = a.lower()
        if al in ("/s", "/silent"):
            o["silent"] = True
        elif al.startswith("/d="):
            o["dir"] = a[3:].strip().strip('"')
        elif al == "/nodesktop":
            o["desktop"] = False
        elif al == "/nopin":
            o["pin"] = False
        elif al == "/nostart":
            o["start"] = False
        elif al == "/uninstall":
            o["uninstall"] = True
        elif al == "/purge":
            o["purge"] = True
        elif al == "/go":
            o["go"] = True
        elif al == "/elevated":
            o["elevated"] = True
    return o


def build_args(o, target, extra=()):
    args = [f"/D={target}"]
    for key, flag in (("desktop", "/nodesktop"), ("pin", "/nopin"), ("start", "/nostart")):
        if not o[key]:
            args.append(flag)
    if o["uninstall"]:
        args.append("/uninstall")
    if o["purge"]:
        args.append("/purge")
    if o["silent"]:
        args.append("/S")
    return args + list(extra)


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def can_write(path):
    """Prüft Schreibrechte im Ordner bzw. im nächsten vorhandenen Elternordner, ohne etwas anzulegen."""
    p = os.path.abspath(path)
    while not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            return False
        p = parent
    try:
        fd, tmp = tempfile.mkstemp(prefix=".bm_test_", dir=p)
        os.close(fd)
        os.remove(tmp)
        return True
    except OSError:
        return False


def relaunch_elevated(args):
    """Startet den Installer mit Administratorrechten neu (UAC). True, wenn gestartet."""
    if FROZEN:
        exe, params = sys.executable, subprocess.list2cmdline(args)
    else:
        exe, params = sys.executable, subprocess.list2cmdline([os.path.abspath(__file__)] + args)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def safe_install_dir(path):
    """Schutz vor dem Löschen falscher Ordner: nur echte Backup-Manager-Ordner."""
    p = os.path.normcase(os.path.abspath(path))
    forbidden = {os.path.normcase(os.path.abspath(x)) for x in
                 (PROGRAM_FILES, os.environ.get("ProgramFiles(x86)", PROGRAM_FILES), os.environ.get("SystemRoot", "C:\\Windows"),
                  os.path.expanduser("~"), os.environ.get("LOCALAPPDATA", "~"))}
    return (p not in forbidden and len(p) > 3
            and os.path.exists(os.path.join(path, "engine", "start.py"))
            and os.path.exists(os.path.join(path, "install.bat")))


def stop_running_app(target):
    """Beendet laufende Instanzen aus diesem Ordner (sonst sind Dateien gesperrt)."""
    pattern = os.path.join(target, "engine", "start.py").replace("'", "''").replace("[", "`[").replace("]", "`]")
    cmd = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + pattern + "*' } | "
           "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                   capture_output=True, creationflags=NO_WINDOW)


def shell_folder(csidl):
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return buf.value


def dir_size_kb(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total // 1024


def read_registered_location():
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, UNINSTALL_KEY) as k:
                return winreg.QueryValueEx(k, "InstallLocation")[0]
        except OSError:
            continue
    return None


# =========================================================================== Installation

class InstallError(Exception):
    pass


STEPS = [("copy", "Programmdateien kopieren"), ("python", "Python prüfen bzw. installieren"),
         ("packages", "Komponenten installieren"), ("check", "Selbsttest"),
         ("shortcuts", "Verknüpfungen anlegen"), ("register", "In Windows registrieren")]


class InstallJob:
    def __init__(self, target, opts, emit):
        self.target = os.path.abspath(target)
        self.opts = opts
        self.emit = emit  # emit(event, *daten) – thread-sicher
        self.result = {"taskbar_manual": False, "shortcut": None}

    def log(self, text):
        self.emit("log", text)

    def step(self, key):
        self.emit("step", key)

    def run(self):
        try:
            self.step("copy")
            self.copy_files()
            self.step("python")
            self.run_install_bat()
            self.step("shortcuts")
            self.create_shortcuts()
            self.step("register")
            self.register()
            self.emit("done", self.result)
        except Exception as e:
            self.log(f"FEHLER: {e}")
            self.emit("error", str(e))

    def copy_files(self):
        if not os.path.exists(PAYLOAD):
            raise InstallError(f"Programmpaket fehlt: {PAYLOAD}")
        if os.path.isdir(self.target):
            self.log("Vorhandene Installation gefunden – wird aktualisiert (Einstellungen bleiben erhalten).")
            stop_running_app(self.target)
        os.makedirs(self.target, exist_ok=True)
        with zipfile.ZipFile(PAYLOAD) as z:
            names = z.namelist()
            for i, name in enumerate(names, 1):
                dest = os.path.join(self.target, *name.split("/"))
                if name.endswith("/"):
                    os.makedirs(dest, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with z.open(name) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
            self.log(f"{len(names)} Dateien nach {self.target} kopiert.")
        if FROZEN:
            shutil.copy2(sys.executable, os.path.join(self.target, "Uninstall.exe"))

    def run_install_bat(self):
        bat = os.path.join(self.target, "install.bat")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        proc = subprocess.Popen(["cmd.exe", "/c", bat, "/auto"], cwd=self.target, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env, creationflags=NO_WINDOW)
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line.strip():
                continue
            if "[3/5]" in line:
                self.step("packages")
            elif "[4/5]" in line:
                self.step("check")
            self.log(line)
        rc = proc.wait()
        if rc != 0:
            raise InstallError("Die Komponenten konnten nicht installiert werden (Internetverbindung?). "
                               "Details unter „Protokoll anzeigen“.")

    def create_shortcuts(self):
        py = os.path.join(self.target, ".venv", "Scripts", "python.exe")
        args = [py, os.path.join(self.target, "engine", "start.py"), "--create-shortcuts"]
        if not self.opts["desktop"]:
            args.append("--no-desktop")
        if self.opts["pin"]:
            args.append("--pin")
        if is_admin() and os.path.normcase(self.target).startswith(os.path.normcase(PROGRAM_FILES)):
            args.append("--all-users")
        res = subprocess.run(args, capture_output=True, creationflags=NO_WINDOW,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        out = res.stdout.decode("utf-8", errors="replace")
        for line in out.splitlines():
            if line.startswith("Verknuepfung erstellt: "):
                self.result["shortcut"] = line.split(": ", 1)[1].strip()
            self.log(line)
        if "HINWEIS_TASKLEISTE" in out:
            self.result["taskbar_manual"] = True
        if res.returncode != 0:
            self.log("Hinweis: Verknüpfungen konnten nicht vollständig angelegt werden.")

    def register(self):
        import winreg
        hive = winreg.HKEY_LOCAL_MACHINE if is_admin() else winreg.HKEY_CURRENT_USER
        uninstaller = os.path.join(self.target, "Uninstall.exe")
        values = {
            "DisplayName": APP_NAME, "DisplayVersion": VERSION, "Publisher": DEVELOPER,
            "URLInfoAbout": WEBSITE, "HelpLink": WEBSITE,
            "DisplayIcon": os.path.join(self.target, "engine", "ui", "assets", "app.ico"),
            "InstallLocation": self.target,
            "UninstallString": f'"{uninstaller}" /uninstall',
            "QuietUninstallString": f'"{uninstaller}" /uninstall /S',
        }
        with winreg.CreateKey(hive, UNINSTALL_KEY) as k:
            for name, val in values.items():
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, dir_size_kb(self.target))
        self.log("Unter „Apps“ registriert (Deinstallation über Windows-Einstellungen möglich).")


def start_app(target, shortcut=None):
    """Startet den Backup Manager ohne Adminrechte (über den Explorer)."""
    launch = shortcut if shortcut and os.path.exists(shortcut) else os.path.join(target, "gui", "backup_manager.vbs")
    subprocess.Popen(["explorer.exe", launch], creationflags=NO_WINDOW)


# =========================================================================== Deinstallation

class UninstallJob(InstallJob):
    def run(self):
        try:
            import winreg
            self.log("Laufende Instanzen werden beendet …")
            stop_running_app(self.target)
            for folder in (shell_folder(0x10), shell_folder(0x02), shell_folder(0x19), shell_folder(0x17),
                           os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Internet Explorer",
                                        "Quick Launch", "User Pinned", "TaskBar")):
                lnk = os.path.join(folder, LNK_NAME)
                if os.path.exists(lnk):
                    try:
                        os.remove(lnk)
                        self.log(f"Entfernt: {lnk}")
                    except OSError as e:
                        self.log(f"Konnte {lnk} nicht entfernen: {e}")
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, "BackupManager")
                    self.log("Autostart entfernt.")
            except OSError:
                pass
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    winreg.DeleteKey(hive, UNINSTALL_KEY)
                except OSError:
                    pass
            if self.opts["purge"] and os.path.isdir(DATA_DIR):
                shutil.rmtree(DATA_DIR, ignore_errors=True)
                self.log(f"Einstellungen, Logs und Snapshots gelöscht: {DATA_DIR}")
            self.emit("done", self.result)
        except Exception as e:
            self.emit("error", str(e))


def schedule_folder_removal(target):
    """Löscht den Programmordner kurz nach dem Beenden (die laufende Uninstall.exe liegt darin)."""
    if not safe_install_dir(target):
        return False
    cmd = f'ping 127.0.0.1 -n 5 >nul & rmdir /s /q "{target}"'
    # Der PyInstaller-Starter steckt alle Kindprozesse in ein Job-Objekt, das beim Beenden alles abräumt –
    # der Löschprozess muss deshalb aus dem Job ausbrechen (oder per WMI außerhalb gestartet werden).
    try:
        subprocess.Popen(["cmd.exe", "/c", cmd], cwd=tempfile.gettempdir(),
                         creationflags=NO_WINDOW | 0x01000000)  # CREATE_BREAKAWAY_FROM_JOB
        return True
    except OSError:
        pass
    full = f'cmd.exe /c {cmd}'.replace("'", "''")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                    f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
                    f"@{{CommandLine='{full}'; CurrentDirectory='{tempfile.gettempdir()}'}} | Out-Null"],
                   capture_output=True, creationflags=NO_WINDOW)
    return True


# =========================================================================== Ohne Oberfläche (/S)

def run_silent(opts, target):
    lines = []

    def emit(event, *data):
        if event == "log":
            lines.append(data[0])
        elif event == "step":
            lines.append(f"== {dict(STEPS).get(data[0], data[0])}")
        elif event in ("done", "error"):
            lines.append(f"== {event.upper()} {data[0] if data else ''}")

    job = (UninstallJob if opts["uninstall"] else InstallJob)(target, opts, emit)
    job.run()
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(str(x) for x in lines))
    ok = not any(x.startswith("== ERROR") for x in lines)
    if ok and opts["uninstall"]:
        schedule_folder_removal(target)
    return 0 if ok else 1


# =========================================================================== Oberfläche

def run_gui(opts, target, notice=None):
    import customtkinter as ctk
    from PIL import Image, ImageDraw, ImageFont

    from engine.ui import theme as T
    from engine.ui import widgets as W
    from engine.ui.icons import app_icon_image, icon

    W.APP_ICON = ICON_FILE if os.path.exists(ICON_FILE) else None
    ctk.set_appearance_mode("system")

    def brand_image(w=270, h=600, scale=2):
        W_, H_ = w * scale, h * scale
        img = Image.new("RGBA", (W_, H_))
        d = ImageDraw.Draw(img)
        top, bottom = (79, 70, 229), (49, 46, 129)
        for y in range(H_):
            k = y / (H_ - 1)
            d.line([(0, y), (W_, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)) + (255,))
        fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")

        def font(name, size):
            for candidate in (name, "segoeui.ttf", "arial.ttf"):
                try:
                    return ImageFont.truetype(os.path.join(fonts, candidate), size * scale)
                except OSError:
                    continue
            return ImageFont.load_default()
        logo = app_icon_image(64 * scale)
        ring = Image.new("RGBA", logo.size, (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle([0, 0, logo.size[0] - 1, logo.size[1] - 1], radius=int(logo.size[0] * 0.23),
                                               outline=(255, 255, 255, 90), width=2 * scale)
        img.alpha_composite(logo, (28 * scale, 40 * scale))
        img.alpha_composite(ring, (28 * scale, 40 * scale))
        white, soft = (255, 255, 255, 255), (224, 228, 255, 220)
        d.text((28 * scale, 124 * scale), APP_NAME, font=font("segoeuib.ttf", 24), fill=white)
        d.text((28 * scale, 158 * scale), f"Version {VERSION}", font=font("segoeui.ttf", 13), fill=soft)
        y = 214
        for line in ("Inkrementelle Backups", "Snapshots & Rollback", "Automatische Synchronisierung",
                     "Läuft dezent im Infobereich"):
            d.ellipse([28 * scale, (y + 6) * scale, 35 * scale, (y + 13) * scale], fill=(165, 180, 252, 255))
            d.text((46 * scale, y * scale), line, font=font("segoeui.ttf", 13), fill=soft)
            y += 30
        d.line([(28 * scale, (h - 92) * scale), ((w - 28) * scale, (h - 92) * scale)], fill=(255, 255, 255, 50), width=scale)
        d.text((28 * scale, (h - 78) * scale), "Entwickelt von", font=font("segoeui.ttf", 11), fill=soft)
        d.text((28 * scale, (h - 60) * scale), DEVELOPER, font=font("segoeuib.ttf", 14), fill=white)
        d.text((28 * scale, (h - 36) * scale), WEBSITE_LABEL + "  →", font=font("seguisb.ttf", 13), fill=(199, 210, 254, 255))
        return ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))

    class SetupWindow(ctk.CTk):
        def __init__(self):
            super().__init__(fg_color=T.BG)
            T.init_fonts(self)
            self.uninstall = opts["uninstall"]
            self.title(f"{APP_NAME} {VERSION} – " + ("Deinstallation" if self.uninstall else "Installation"))
            self.geometry("860x600")
            self.resizable(False, False)
            if W.APP_ICON:
                try:
                    self.iconbitmap(W.APP_ICON)
                except Exception:
                    pass
            self.target = target
            self.q = queue.Queue()
            self.result = None
            self.log_lines = []
            self.grid_columnconfigure(1, weight=1)
            self.grid_rowconfigure(0, weight=1)
            brand = ctk.CTkLabel(self, text="", image=brand_image(), cursor="hand2")
            brand.grid(row=0, column=0, rowspan=2, sticky="nsew")
            brand.bind("<Button-1>", lambda e: webbrowser.open(WEBSITE)
                       if e.y > brand.winfo_height() - 100 else None)
            self.body = ctk.CTkFrame(self, fg_color="transparent")
            self.body.grid(row=0, column=1, sticky="nsew", padx=36, pady=(34, 0))
            self.footer = ctk.CTkFrame(self, fg_color="transparent")
            self.footer.grid(row=1, column=1, sticky="ew", padx=36, pady=(10, 26))
            self.protocol("WM_DELETE_WINDOW", self.on_close)
            self.busy = False
            self.after(60, self._drain)
            if self.uninstall:
                self.page_uninstall()
            elif opts["go"]:
                self.start_install()
            else:
                self.page_welcome()
            # Fenster mittig
            self.update_idletasks()
            x = (self.winfo_screenwidth() - self.winfo_width()) // 2
            y = (self.winfo_screenheight() - self.winfo_height()) // 3
            self.wm_geometry(f"+{max(0, x)}+{max(0, y)}")

        # ---------------------------------------------------------- Grundgerüst
        def clear(self):
            for frame in (self.body, self.footer):
                for w in frame.winfo_children():
                    w.destroy()

        def title_block(self, title, text=None, icon_name=None, tone="primary"):
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.pack(fill="x")
            if icon_name:
                W.IconBubble(row, icon_name, tone, size=46, icon_size=22).pack(side="left", padx=(0, 14))
            W.label(row, title, 24, "bold").pack(side="left", anchor="w")
            if text:
                lbl = W.label(self.body, text, 13, color=T.MUTED, wraplength=500)
                lbl.pack(fill="x", pady=(10, 0))

        def footer_buttons(self, *buttons):
            for text, kind, cmd, icon_name in reversed(buttons):
                W.button(self.footer, text, kind, icon_name, height=40, command=cmd).pack(side="right", padx=(10, 0))

        def on_close(self):
            if self.busy:
                return
            self.destroy()

        def _drain(self):
            try:
                while True:
                    event, data = self.q.get_nowait()
                    self.handle(event, *data)
            except queue.Empty:
                pass
            self.after(60, self._drain)

        def emit(self, event, *data):
            self.q.put((event, data))

        # ---------------------------------------------------------- Willkommen
        def page_welcome(self):
            self.clear()
            self.title_block("Willkommen", "Dieser Assistent installiert den Backup Manager auf deinem PC. Fehlende "
                                           "Komponenten (Python und benötigte Pakete) werden automatisch "
                                           "heruntergeladen – dafür ist eine Internetverbindung nötig.")
            if notice:
                box = ctk.CTkFrame(self.body, fg_color=T.WARNING_SOFT, corner_radius=12)
                box.pack(fill="x", pady=(14, 0))
                W.label(box, notice, 12, color=T.WARNING, wraplength=480).pack(anchor="w", padx=14, pady=10)
            W.label(self.body, "Installationsordner", 13, "bold").pack(anchor="w", pady=(22, 6))
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.pack(fill="x")
            self.path = ctk.CTkEntry(row, height=38, corner_radius=10, font=T.font(13), fg_color=T.CARD,
                                     border_color=T.BORDER_STRONG, text_color=T.TEXT)
            self.path.insert(0, self.target)
            self.path.pack(side="left", fill="x", expand=True)
            W.button(row, "Ändern …", "secondary", "folder_open", height=38, command=self.choose_dir).pack(side="left", padx=(8, 0))
            self.data_hint = W.label(self.body, "", 11, color=T.SUBTLE, wraplength=500)
            self.data_hint.pack(anchor="w", pady=(6, 0))
            self.path.bind("<KeyRelease>", lambda e: self.update_hint())
            self.update_hint()

            opts_frame = ctk.CTkFrame(self.body, fg_color=T.CARD, corner_radius=12, border_width=1, border_color=T.BORDER)
            opts_frame.pack(fill="x", pady=(18, 0))
            self.vars = {}
            for key, text in (("desktop", "Verknüpfung auf dem Desktop anlegen"),
                              ("pin", "An die Taskleiste anheften (falls Windows es erlaubt)"),
                              ("start", "Backup Manager nach der Installation starten")):
                var = ctk.BooleanVar(value=opts[key])
                ctk.CTkCheckBox(opts_frame, text=text, variable=var, font=T.font(13), text_color=T.TEXT,
                                fg_color=T.PRIMARY, hover_color=T.PRIMARY_HOVER, border_color=T.BORDER_STRONG,
                                corner_radius=6).pack(anchor="w", padx=16, pady=(12 if key == "desktop" else 6, 12 if key == "start" else 0))
                self.vars[key] = var
            W.label(self.body, "Ein Eintrag im Startmenü wird immer angelegt.", 11, color=T.SUBTLE).pack(anchor="w", pady=(6, 0))
            self.footer_buttons(("Abbrechen", "secondary", self.destroy, None),
                                ("Installieren", "primary", self.on_install, "download"))

        def update_hint(self):
            p = self.path.get().strip()
            protected = os.path.normcase(os.path.abspath(p or ".")).startswith(os.path.normcase(PROGRAM_FILES))
            self.data_hint.configure(text=(f"Einstellungen, Logs und Snapshots werden in {DATA_DIR} gespeichert "
                                           f"(der Snapshot-Ordner ist später in den Einstellungen änderbar)."
                                           if protected else "Einstellungen, Logs und Snapshots werden im "
                                                             "Programmordner gespeichert."))

        def choose_dir(self):
            from tkinter import filedialog
            path = filedialog.askdirectory(parent=self, title="Installationsordner wählen")
            if path:
                path = os.path.normpath(path)
                if os.path.basename(path).lower() != "backupmanager":
                    path = os.path.join(path, "BackupManager")
                self.path.delete(0, "end")
                self.path.insert(0, path)
                self.update_hint()

        def on_install(self):
            for key, var in self.vars.items():
                opts[key] = bool(var.get())
            self.target = os.path.abspath(self.path.get().strip() or DEFAULT_DIR)
            if not can_write(self.target) and not is_admin():
                if relaunch_elevated(build_args(opts, self.target, ["/go", "/elevated"])):
                    self.destroy()
                    return
                if W.confirm(self, "Keine Administratorrechte",
                             f"Für „{self.target}“ werden Administratorrechte benötigt. Stattdessen nur für deinen "
                             f"Benutzer installieren?", "Für mich installieren", facts=[("Ordner", USER_DIR, None)]):
                    self.target = USER_DIR
                else:
                    return
            self.start_install()

        # ---------------------------------------------------------- Fortschritt
        def page_progress(self, title):
            self.clear()
            self.title_block(title)
            self.step_label = W.label(self.body, "", 13, color=T.MUTED)
            self.step_label.pack(anchor="w", pady=(8, 14))
            self.bar = ctk.CTkProgressBar(self.body, height=8, corner_radius=4, progress_color=T.PRIMARY, fg_color=T.CARD_ALT)
            self.bar.pack(fill="x")
            self.bar.set(0)
            steps = ctk.CTkFrame(self.body, fg_color=T.CARD, corner_radius=12, border_width=1, border_color=T.BORDER)
            steps.pack(fill="x", pady=(16, 0))
            self.step_rows = {}
            step_list = STEPS if not self.uninstall else [("remove", "Verknüpfungen, Autostart und Eintrag entfernen")]
            for i, (key, text) in enumerate(step_list):
                row = ctk.CTkFrame(steps, fg_color="transparent")
                row.pack(fill="x", padx=14, pady=(10 if i == 0 else 4, 10 if i == len(step_list) - 1 else 0))
                bubble = W.IconBubble(row, "clock", "muted", size=26, icon_size=13)
                bubble.pack(side="left")
                lbl = W.label(row, text, 13, color=T.MUTED)
                lbl.pack(side="left", padx=10)
                self.step_rows[key] = (bubble, lbl)
            self.log_box = ctk.CTkTextbox(self.body, height=110, font=T.mono(11), fg_color=T.INPUT, border_width=1,
                                          border_color=T.BORDER, corner_radius=10, text_color=T.MUTED, wrap="none")
            self.log_toggle = W.button(self.body, "Protokoll anzeigen", "ghost", "list", height=30, command=self.toggle_log)
            self.log_toggle.pack(anchor="w", pady=(8, 0))
            self.current_step = None

        def toggle_log(self):
            if self.log_box.winfo_ismapped():
                self.log_box.pack_forget()
                self.log_toggle.configure(text="Protokoll anzeigen")
            else:
                self.log_box.pack(fill="both", expand=True, pady=(6, 0))
                self.log_toggle.configure(text="Protokoll ausblenden")
                self.log_box.see("end")

        def set_step(self, key):
            keys = list(self.step_rows)
            if self.current_step in self.step_rows:
                b, l = self.step_rows[self.current_step]
                b.set("check", "success", icon_size=13)
                l.configure(text_color=T.TEXT)
            for k in keys[: keys.index(key)] if key in keys else []:
                b, l = self.step_rows[k]
                b.set("check", "success", icon_size=13)
                l.configure(text_color=T.TEXT)
            if key in self.step_rows:
                b, l = self.step_rows[key]
                b.set("sync", "primary", icon_size=13)
                l.configure(text_color=T.TEXT)
                self.step_label.configure(text=dict(STEPS).get(key, "Wird ausgeführt") + " …")
                self.bar.set(keys.index(key) / len(keys))
            self.current_step = key

        def start_install(self):
            self.busy = True
            self.page_progress("Wird installiert …")
            job = InstallJob(self.target, opts, self.emit)
            threading.Thread(target=job.run, daemon=True).start()

        def handle(self, event, *data):
            if event == "log":
                self.log_lines.append(data[0])
                if hasattr(self, "log_box"):
                    self.log_box.insert("end", data[0] + "\n")
                    self.log_box.see("end")
            elif event == "step":
                self.set_step(data[0])
            elif event == "done":
                self.busy = False
                self.set_step("__ende__")
                self.bar.set(1)
                self.page_done(data[0]) if not self.uninstall else self.page_uninstalled()
            elif event == "error":
                self.busy = False
                self.page_error(data[0])

        # ---------------------------------------------------------- Ergebnis
        def page_done(self, result):
            self.result = result
            self.clear()
            self.title_block("Installation abgeschlossen", f"Der Backup Manager ist jetzt unter „{self.target}“ "
                                                           f"installiert und im Startmenü zu finden.", "completed", "success")
            if opts["pin"] and result.get("taskbar_manual"):
                box = ctk.CTkFrame(self.body, fg_color=T.INFO_SOFT, corner_radius=12)
                box.pack(fill="x", pady=(20, 0))
                W.label(box, "An die Taskleiste anheften", 13, "bold", color=T.INFO).pack(anchor="w", padx=16, pady=(12, 2))
                W.label(box, "Windows erlaubt Programmen nicht, sich selbst an die Taskleiste anzuheften. So geht es "
                             "in zwei Klicks:\n1. Backup Manager starten\n2. Rechtsklick auf sein Symbol in der "
                             "Taskleiste → „An Taskleiste anheften“", 12, color=T.TEXT, wraplength=470
                        ).pack(anchor="w", padx=16, pady=(0, 12))
            elif opts["pin"]:
                W.label(self.body, "✓ An die Taskleiste angeheftet.", 13, color=T.SUCCESS).pack(anchor="w", pady=(16, 0))
            self.start_var = ctk.BooleanVar(value=opts["start"])
            ctk.CTkCheckBox(self.body, text="Backup Manager jetzt starten", variable=self.start_var, font=T.font(13),
                            text_color=T.TEXT, fg_color=T.PRIMARY, hover_color=T.PRIMARY_HOVER,
                            border_color=T.BORDER_STRONG, corner_radius=6).pack(anchor="w", pady=(20, 0))
            self.footer_buttons(("Fertig", "primary", self.finish, "check"))

        def finish(self):
            if self.start_var.get():
                start_app(self.target, (self.result or {}).get("shortcut"))
            self.destroy()

        def page_error(self, message):
            self.clear()
            self.title_block("Installation fehlgeschlagen", message, "error", "danger")
            box = ctk.CTkTextbox(self.body, height=230, font=T.mono(11), fg_color=T.INPUT, border_width=1,
                                 border_color=T.BORDER, corner_radius=10, text_color=T.MUTED, wrap="none")
            box.insert("1.0", "\n".join(self.log_lines[-400:]))
            box.configure(state="disabled")
            box.pack(fill="both", expand=True, pady=(16, 0))
            self.footer_buttons(("Schließen", "secondary", self.destroy, None),
                                ("Erneut versuchen", "primary", self.start_install, "refresh"))

        # ---------------------------------------------------------- Deinstallation
        def page_uninstall(self):
            self.clear()
            self.title_block("Backup Manager entfernen", f"Entfernt das Programm aus „{self.target}“ sowie "
                                                         f"Verknüpfungen, Autostart und den Eintrag unter „Apps“.",
                             "delete", "danger")
            self.purge = ctk.BooleanVar(value=opts["purge"])
            ctk.CTkCheckBox(self.body, text="Auch Einstellungen, Logs und Snapshots löschen", variable=self.purge,
                            font=T.font(13), text_color=T.TEXT, fg_color=T.DANGER, hover_color=T.DANGER_HOVER,
                            border_color=T.BORDER_STRONG, corner_radius=6).pack(anchor="w", pady=(22, 0))
            W.label(self.body, f"Ordner: {DATA_DIR}\nDeine gesicherten Dateien im Backup-Ziel bleiben in jedem Fall "
                               f"erhalten.", 12, color=T.MUTED, wraplength=480).pack(anchor="w", padx=(30, 0), pady=(6, 0))
            self.footer_buttons(("Abbrechen", "secondary", self.destroy, None),
                                ("Entfernen", "danger", self.on_uninstall, "delete"))

        def on_uninstall(self):
            opts["purge"] = bool(self.purge.get())
            if not can_write(self.target) and not is_admin():
                if relaunch_elevated(build_args(opts, self.target, ["/go", "/elevated"])):
                    self.destroy()
                return
            self.busy = True
            self.page_progress("Wird entfernt …")
            self.set_step("remove")
            threading.Thread(target=UninstallJob(self.target, opts, self.emit).run, daemon=True).start()

        def page_uninstalled(self):
            self.clear()
            self.title_block("Entfernt", "Der Backup Manager wurde deinstalliert. Der Programmordner wird nach dem "
                                         "Schließen dieses Fensters gelöscht.", "completed", "success")
            self.footer_buttons(("Fertig", "primary", self.close_uninstalled, "check"))

        def close_uninstalled(self):
            schedule_folder_removal(self.target)
            self.destroy()

    win = SetupWindow()
    if opts["uninstall"] and opts["go"]:
        win.after(200, win.on_uninstall)
    win.mainloop()
    return 0


# =========================================================================== Start

def main():
    opts = parse_args(sys.argv[1:])
    if opts["uninstall"]:
        target = opts["dir"] or (os.path.dirname(sys.executable) if FROZEN else None) or read_registered_location()
    else:
        target = opts["dir"] or read_registered_location() or DEFAULT_DIR
    if not target:
        return 1
    target = os.path.abspath(target)
    notice = None
    if opts["silent"]:
        if not can_write(target) and not is_admin():
            if not opts["elevated"] and relaunch_elevated(build_args(opts, target, ["/elevated"])):
                return 0
            return 1
        return run_silent(opts, target)
    if opts["go"] and not opts["uninstall"] and not can_write(target) and not is_admin():
        opts["go"] = False
        notice = "Die Administratorrechte wurden nicht erteilt. Wähle einen anderen Ordner oder starte erneut."
    return run_gui(opts, target, notice)


if __name__ == "__main__":
    sys.exit(main())
