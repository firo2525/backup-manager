"""Hauptfenster des Backup Managers.

Grundregel: Tkinter darf nur im Haupt-Thread benutzt werden. Hintergrund-Threads (Backup, Rollback,
Snapshot-Analyse) melden sich ausschließlich über `post()`; die Warteschlange wird im Haupt-Thread
abgearbeitet. Das behebt die früheren Abstürze („invalid command name …“).
"""
import ctypes
import logging
import os
import queue
import threading
import time
import traceback
from collections import deque
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk

from engine import backup, config, system, utils, version, versions
from engine.ui import theme as T
from engine.ui import widgets as W
from engine.ui.icons import app_icon_image, ensure_app_icon, icon
from engine.ui.pages.about import DEVELOPER, AboutPage
from engine.ui.pages.dashboard import DashboardPage
from engine.ui.pages.log import LogPage
from engine.ui.pages.settings import SettingsPage
from engine.ui.pages.snapshots import KIND_LABELS, SnapshotsPage
from engine.ui.pages.sources import SourcesPage
from engine.ui.tray import TrayIcon

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
APP_ICO = os.path.join(ASSETS_DIR, "app.ico")


class GuiLogHandler(logging.Handler):
    """Sammelt Log-Einträge thread-sicher in einer Warteschlange für die Protokoll-Seite."""

    def __init__(self, target_queue):
        super().__init__(logging.INFO)
        self.target_queue = target_queue

    def emit(self, record):
        try:
            msg = record.getMessage()
            if record.exc_info and record.levelno >= logging.ERROR:
                msg += "\n" + "".join(traceback.format_exception(*record.exc_info)).rstrip()
        except Exception:
            msg = str(record.msg)
        self.target_queue.put((record.created, record.levelno, msg))


class SnapshotStore:
    """Lädt die Snapshot-Übersicht im Hintergrund und prüft anschließend Größe/Vollständigkeit."""

    def __init__(self, app):
        self.app = app
        self.summaries = []
        self.info = {}
        self.loaded = False
        self._by_id = {}
        self._gen = 0

    def refresh(self, clear=False):
        self._gen += 1
        if clear:
            versions.clear_caches()
            self.info = {}
        threading.Thread(target=self._work, args=(self._gen, self.app.profile_name), daemon=True,
                         name="snapshot-scan").start()

    def _work(self, gen, profile):
        try:
            summaries = versions.list_run_summaries()
        except Exception:
            logging.exception("Snapshots konnten nicht geladen werden")
            summaries = []
        self.app.post(self._loaded, gen, summaries)
        for s in sorted(summaries, key=lambda s: not self.matches_profile(s, profile)):
            if gen != self._gen or self.app.closed:
                return
            if s["run_id"] in self.info:
                continue
            try:
                info = versions.inspect_run(s["run_id"])
            except Exception:
                continue
            self.app.post(self._inspected, gen, s["run_id"], info)

    def _loaded(self, gen, summaries):
        if gen != self._gen:
            return
        self.summaries = summaries
        self._by_id = {s["run_id"]: s for s in summaries}
        self.loaded = True
        self.app.broadcast("on_snapshots_changed")

    def _inspected(self, gen, run_id, info):
        if gen != self._gen:
            return
        self.info[run_id] = info
        self.app.broadcast("on_snapshot_info", run_id)

    @staticmethod
    def matches_profile(summary, name):
        return bool(name) and config.same_profile(summary.get("profile"), name)

    def for_profile(self, name):
        return [s for s in self.summaries if self.matches_profile(s, name)]

    def get(self, run_id):
        return self._by_id.get(run_id)

    def status(self, r):
        if r["status"] == "nometa":
            return "Ohne Metadaten", "muted"
        if r["total"] == 0:
            return "Leer", "muted"
        info = self.info.get(r["run_id"])
        if info is None:
            text, tone = "Wird geprüft …", "muted"
        elif info["missing"] == 0:
            text, tone = "OK", "success"
        elif info["missing"] < info["with_snapshot"]:
            text, tone = f"Teilweise ({utils.format_count(info['missing'])} fehlen)", "warning"
        else:
            text, tone = "Fehlend", "danger"
        extras = []
        if r["status"] == "running":
            extras.append("unvollständig")
        if r["rolled_back"]:
            extras.append("zurückgesetzt")
        return " · ".join([text] + extras), tone


class Sidebar(ctk.CTkFrame):
    NAV = [
        ("dashboard", "Übersicht", "home"),
        ("sources", "Quellen & Ziel", "folder"),
        ("snapshots", "Snapshots", "history"),
        ("log", "Protokoll", "list"),
        ("settings", "Einstellungen", "settings"),
        ("about", "Über", "info"),
    ]

    def __init__(self, app):
        super().__init__(app, fg_color=T.SIDEBAR, corner_radius=0, width=236)
        self.app = app
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(11, weight=1)

        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(24, 0))
        logo = ctk.CTkImage(light_image=app_icon_image(96), dark_image=app_icon_image(96), size=(40, 40))
        ctk.CTkLabel(brand, text="", image=logo).pack(side="left")
        txt = ctk.CTkFrame(brand, fg_color="transparent")
        txt.pack(side="left", padx=12)
        W.label(txt, app.APP_NAME, 16, "bold").pack(anchor="w")
        credit = W.label(txt, f"Entwickelt von {DEVELOPER}", 11, color=T.MUTED, cursor="hand2")
        credit.pack(anchor="w")
        credit.bind("<Button-1>", lambda e: app.show_page("about"))
        credit.bind("<Enter>", lambda e: credit.configure(text_color=T.PRIMARY_TEXT))
        credit.bind("<Leave>", lambda e: credit.configure(text_color=T.MUTED))

        W.label(self, "PROFIL", 10, "bold", color=T.SUBTLE).grid(row=1, column=0, sticky="w", padx=24, pady=(28, 6))
        self.profile_menu = ctk.CTkOptionMenu(
            self, values=["–"], command=self._on_profile, height=40, corner_radius=10,
            font=T.font(14, "bold"), dropdown_font=T.font(13), fg_color=T.CARD_ALT, button_color=T.CARD_ALT,
            button_hover_color=T.HOVER, text_color=T.TEXT, dropdown_fg_color=T.CARD, dropdown_hover_color=T.HOVER,
            dropdown_text_color=T.TEXT, dynamic_resizing=False, anchor="w")
        self.profile_menu.grid(row=2, column=0, sticky="ew", padx=16)
        prow = ctk.CTkFrame(self, fg_color="transparent")
        prow.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 0))
        prow.grid_columnconfigure(0, weight=1)
        self.btn_new = W.button(prow, "Neues Profil", "secondary", "add", height=34, icon_size=14, command=app.new_profile)
        self.btn_new.grid(row=0, column=0, sticky="ew")
        self.btn_del = W.button(prow, "", "secondary", "delete", height=34, icon_size=14, command=app.delete_profile)
        self.btn_del.configure(hover_color=T.DANGER_SOFT)
        self.btn_del.grid(row=0, column=1, padx=(8, 0))

        W.label(self, "MENÜ", 10, "bold", color=T.SUBTLE).grid(row=4, column=0, sticky="w", padx=24, pady=(26, 6))
        self.nav = {}
        for i, (key, title, icon_name) in enumerate(self.NAV):
            b = ctk.CTkButton(self, text="  " + title, anchor="w", height=40, corner_radius=10, fg_color="transparent",
                              hover_color=T.HOVER, text_color=T.MUTED, font=T.font(14),
                              image=icon(icon_name, 18, T.MUTED), compound="left",
                              command=lambda k=key: app.show_page(k))
            b.grid(row=5 + i, column=0, sticky="ew", padx=12, pady=1)
            self.nav[key] = (b, icon_name)

        self.activity = ctk.CTkFrame(self, fg_color=T.PRIMARY_SOFT, corner_radius=12)
        self.act_label = W.label(self.activity, "", 12, "bold", color=T.PRIMARY_TEXT)
        self.act_label.pack(fill="x", padx=14, pady=(12, 6))
        self.act_bar = ctk.CTkProgressBar(self.activity, height=6, corner_radius=3, progress_color=T.PRIMARY, fg_color=T.CARD)
        self.act_bar.pack(fill="x", padx=14, pady=(0, 14))
        for w in (self.activity, self.act_label):
            w.bind("<Button-1>", lambda e: app.show_page("dashboard"))

        self.theme_btn = ctk.CTkButton(self, text="", anchor="w", height=38, corner_radius=10, fg_color="transparent",
                                       hover_color=T.HOVER, text_color=T.MUTED, font=T.font(13),
                                       compound="left", command=self._toggle_theme)
        self.theme_btn.grid(row=13, column=0, sticky="ew", padx=12, pady=(6, 18))
        self.update_theme_button()

    def _on_profile(self, value):
        if value in self.app.profiles:
            self.app.set_profile(value)

    def refresh_profiles(self):
        names = sorted(self.app.profiles, key=str.lower)
        self.profile_menu.configure(values=names or ["Kein Profil"])
        self.profile_menu.set(self.app.profile_name or ("Kein Profil" if not names else "Profil wählen …"))
        self.btn_del.configure(state="normal" if self.app.profile_name and not self.app.busy else "disabled")

    def select(self, key):
        for k, (b, icon_name) in self.nav.items():
            if k == key:
                b.configure(fg_color=T.PRIMARY_SOFT, text_color=T.PRIMARY_TEXT, font=T.font(14, "bold"),
                            image=icon(icon_name, 18, T.PRIMARY_TEXT), hover_color=T.PRIMARY_SOFT)
            else:
                b.configure(fg_color="transparent", text_color=T.MUTED, font=T.font(14),
                            image=icon(icon_name, 18, T.MUTED), hover_color=T.HOVER)

    def on_busy_changed(self, busy, kind=None):
        state = "disabled" if busy else "normal"
        self.profile_menu.configure(state=state)
        self.btn_new.configure(state=state)
        self.btn_del.configure(state="disabled" if busy or not self.app.profile_name else "normal")
        if busy:
            self.act_label.configure(text=f"{self.app.operation_label or 'Vorgang'} läuft …")
            self.act_bar.configure(mode="indeterminate")
            self.act_bar.start()
            self.activity.grid(row=12, column=0, sticky="ew", padx=16, pady=(0, 6))
        else:
            self.act_bar.stop()
            self.activity.grid_forget()

    def update_activity(self, p):
        op = self.app.operation_label or "Vorgang"
        if p.phase == "scan":
            self.act_label.configure(text=f"{op}: Analyse …")
            return
        if str(self.act_bar.cget("mode")) != "determinate":
            self.act_bar.stop()
            self.act_bar.configure(mode="determinate")
        frac = (p.bytes_done / p.bytes_total) if p.bytes_total else (p.files_done / p.files_total if p.files_total else 0)
        self.act_bar.set(min(1.0, frac))
        self.act_label.configure(text=f"{op} · {int(frac * 100)} %")

    def update_theme_button(self):
        dark = T.is_dark()
        self.theme_btn.configure(text="  Helles Design" if dark else "  Dunkles Design",
                                 image=icon("sun" if dark else "moon", 18, T.MUTED))

    def _toggle_theme(self):
        mode = "light" if T.is_dark() else "dark"
        self.app.settings["appearance"] = mode
        config.save_settings(self.app.settings)
        self.app.set_appearance(mode)
        settings_page = self.app.pages.get("settings")
        if settings_page:
            settings_page.appearance.set("Dunkel" if mode == "dark" else "Hell")


class BackupApp(ctk.CTk):
    APP_NAME = version.APP_NAME
    APP_VERSION = version.VERSION

    def __init__(self, start_minimized=False, instance=None):
        self.settings = config.load_settings()
        ctk.set_appearance_mode(self.settings["appearance"])
        super().__init__(fg_color=T.BG)
        T.init_fonts(self)
        self._start_minimized = start_minimized
        self.instance = instance
        self._want_zoom = False
        self.operation_profile = None
        self.operation_label = None
        self._sync_queue = []
        self._syncing = False
        self._sync_auto = False
        self._sync_summary = []
        self._next_sync = time.time() + 120
        self.closed = False
        self._closing = False
        self._error_dialog_open = False
        self.title(self.APP_NAME)
        self._place_window(1320, 860)
        self.minsize(980, 620)
        ico = ensure_app_icon(APP_ICO)
        W.APP_ICON = ico
        if ico:
            try:
                self.iconbitmap(ico)
            except Exception:
                pass
        self.report_callback_exception = self._on_tk_error

        self._queue = queue.Queue()
        self._log_queue = queue.Queue()
        self.log_records = deque(maxlen=20000)
        self.log_handler = GuiLogHandler(self._log_queue)
        backup.setup_logging(extra_handler=self.log_handler, console=False, keep_files=self.settings["log_keep"])

        self.profiles = config.load_profiles()
        self.profile_name = None
        self.busy = False
        self.operation = None
        self.worker = None
        self.current_page = None
        self.snapshots = SnapshotStore(self)
        self.tray = TrayIcon(self)

        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.sidebar = Sidebar(self)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        ctk.CTkFrame(self, width=1, fg_color=T.BORDER, corner_radius=0).grid(row=0, column=1, sticky="ns")
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=2, sticky="nsew", padx=28, pady=(24, 20))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages = {
            "dashboard": DashboardPage(self.content, self),
            "sources": SourcesPage(self.content, self),
            "snapshots": SnapshotsPage(self.content, self),
            "log": LogPage(self.content, self),
            "settings": SettingsPage(self.content, self),
            "about": AboutPage(self.content, self),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")
            page.grid_remove()
        self.toast = W.Toast(self)

        initial = config.find_profile(self.profiles, self.settings.get("last_profile"))
        if not initial and self.profiles:
            initial = sorted(self.profiles, key=str.lower)[0]
        self.set_profile(initial, initial_load=True)
        self.show_page("dashboard")
        self.snapshots.refresh()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Control-b>", lambda e: self.start_backup())
        self.bind("<F5>", lambda e: self.snapshots.refresh(clear=True))
        for i, (key, _t, _i) in enumerate(Sidebar.NAV, start=1):
            self.bind(f"<Control-Key-{i}>", lambda e, k=key: self.show_page(k))
        try:
            from customtkinter.windows.widgets.appearance_mode import AppearanceModeTracker
            AppearanceModeTracker.add(self._on_appearance_mode, self)
        except Exception:
            pass
        self.after(40, self._drain)
        logging.info(f"{self.APP_NAME} {self.APP_VERSION} gestartet. Daten: {config.DATA_DIR} · "
                     f"Snapshots: {versions.VERSIONS_DIR}")

        if os.name == "nt":
            self.tray.start()
        try:
            system.repair_autostart()
        except Exception:
            logging.debug("Autostart-Prüfung fehlgeschlagen", exc_info=True)
        self._init_scheduler()
        if self.instance:
            self.after(500, self._poll_instance)
        if self._start_minimized:
            if self.tray.running:
                self.withdraw()
            else:
                self.iconify()
            logging.info("Im Hintergrund gestartet (Infobereich der Taskleiste).")
        elif not self.settings.get("autostart_asked"):
            self.after(900, self._ask_autostart)

    # ------------------------------------------------------------------ Fenster & Infrastruktur
    def _place_window(self, width, height):
        self.update_idletasks()
        scale = ctk.ScalingTracker.get_window_scaling(self)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(width, int(sw / scale * 0.94))
        height = min(height, int(sh / scale * 0.9))
        x = max(0, int((sw - width * scale) / 2))
        y = max(0, int((sh - height * scale) / 2.4))
        self.geometry(f"{width}x{height}+{x}+{y}")
        # kleine Bildschirme (z. B. Laptop mit 150 % Skalierung): maximiert anzeigen
        self._want_zoom = sh / scale < 900 and os.name == "nt"
        if self._want_zoom and not self._start_minimized:
            self._want_zoom = False
            self.after(0, lambda: self.state("zoomed"))

    def post(self, fn, *args, **kwargs):
        """Führt fn im Haupt-Thread aus (aus beliebigen Threads aufrufbar)."""
        self._queue.put((fn, args, kwargs))

    def _drain(self):
        if self.closed:
            return
        for _ in range(500):
            try:
                fn, args, kwargs = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args, **kwargs)
            except Exception:
                logging.exception("Fehler bei der Aktualisierung der Oberfläche")
        records = []
        while len(records) < 2000:
            try:
                records.append(self._log_queue.get_nowait())
            except queue.Empty:
                break
        if records:
            self.log_records.extend(records)
            self.pages["log"].append(records)
        self.after(40, self._drain)

    def broadcast(self, method, *args):
        for page in self.pages.values():
            fn = getattr(page, method, None)
            if fn:
                try:
                    fn(*args)
                except Exception:
                    logging.exception(f"Fehler in {type(page).__name__}.{method}")

    def show_page(self, key, **kwargs):
        W.HelpBadge.hide_all()
        page = self.pages[key]
        if self.current_page != key:
            for k, p in self.pages.items():
                if k != key:
                    p.grid_remove()
            page.grid()
            self.current_page = key
            self.sidebar.select(key)
        if hasattr(page, "on_show"):
            page.on_show(**kwargs)

    def set_appearance(self, mode):
        ctk.set_appearance_mode(mode)
        self.after(30, self._restyle)

    def _on_appearance_mode(self, _mode):
        self.after(30, self._restyle)

    def _restyle(self):
        self.sidebar.update_theme_button()
        self.broadcast("restyle")

    def _on_tk_error(self, exc, val, tb):
        logging.error("Unerwarteter Fehler in der Oberfläche", exc_info=(exc, val, tb))
        if self._error_dialog_open or self.closed:
            return
        self._error_dialog_open = True
        try:
            W.info(self, "Unerwarteter Fehler", f"{exc.__name__}: {val}", "error",
                   details=traceback.format_exception(exc, val, tb)[-6:])
        except Exception:
            pass
        finally:
            self._error_dialog_open = False

    def _flash(self):
        """Lässt das Taskleisten-Symbol aufblinken, wenn das Fenster nicht im Vordergrund ist."""
        try:
            if self.focus_displayof() is None and os.name == "nt":
                ctypes.windll.user32.FlashWindow(int(self.wm_frame(), 16), True)
        except Exception:
            pass

    def on_close(self):
        """X-Knopf: in den Infobereich minimieren (falls eingestellt) oder beenden."""
        if self._closing:
            return
        if self.settings.get("close_to_tray") and self.tray.running:
            self.hide_to_tray()
            return
        self.quit_app(confirm=self.settings["confirm_close"])

    def quit_app(self, confirm=False):
        if self._closing:
            return
        if self.busy:
            self.show_window()
            if not W.confirm(self, "Vorgang läuft noch", "Soll der laufende Vorgang abgebrochen und das Programm beendet "
                                                         "werden? Bereits kopierte Dateien bleiben im Snapshot erfasst.",
                             "Abbrechen & beenden", kind="warning"):
                return
            self._closing = True
            backup.set_cancel_flag(True)
            self.toast.show("Wird beendet, sobald der aktuelle Schritt abgeschlossen ist …", "info", 60000)
            self.after(20000, self.destroy)
            return
        if confirm and not W.confirm(self, "Backup Manager beenden?",
                                     "Danach findet keine automatische Synchronisierung mehr statt, bis du das Programm "
                                     "wieder startest. Die Abfrage lässt sich in den Einstellungen abschalten.", "Beenden"):
            return
        self.destroy()

    def show_window(self):
        self.deiconify()
        if self._want_zoom:
            self._want_zoom = False
            self.state("zoomed")
        elif self.state() == "iconic":
            self.state("normal")
        self.lift()
        try:
            self.attributes("-topmost", True)
            self.after(250, lambda: self.attributes("-topmost", False))
        except Exception:
            pass
        self.focus_force()

    def hide_to_tray(self):
        W.HelpBadge.hide_all()
        self.withdraw()
        if not self.settings.get("tray_hint_shown"):
            self.settings["tray_hint_shown"] = True
            self._save_settings()
            self.tray.notify("Der Backup Manager läuft im Infobereich weiter und synchronisiert automatisch. "
                             "Klick auf das Symbol öffnet ihn, Rechtsklick → Beenden schließt ihn.")

    def _poll_instance(self):
        if self.closed:
            return
        try:
            if self.instance.show_requested():
                self.show_window()
        except Exception:
            pass
        self.after(500, self._poll_instance)

    def destroy(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.tray.stop()
        except Exception:
            pass
        logging.getLogger().removeHandler(self.log_handler)
        try:
            from customtkinter.windows.widgets.appearance_mode import AppearanceModeTracker
            AppearanceModeTracker.remove(self._on_appearance_mode)
        except Exception:
            pass
        super().destroy()

    def run_background(self, fn, on_done):
        def work():
            try:
                result = fn()
            except Exception as e:
                logging.exception("Hintergrundaufgabe fehlgeschlagen")
                result = e
            self.post(on_done, result)
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ Profile
    def current_profile(self):
        return self.profiles.get(self.profile_name) if self.profile_name else None

    def set_profile(self, name, initial_load=False):
        if self.busy and not initial_load:
            self.toast.show("Während eines Vorgangs kann das Profil nicht gewechselt werden.", "warning")
            self.sidebar.refresh_profiles()
            return
        self.profile_name = name if name in self.profiles else None
        if self.settings.get("last_profile") != self.profile_name:
            self.settings["last_profile"] = self.profile_name
            self._save_settings()
        self.sidebar.refresh_profiles()
        if not initial_load:
            self.broadcast("on_profile_changed")

    def update_profile(self, **fields):
        prof = self.current_profile()
        if prof is None:
            return
        prof.update(fields)
        self._save_profiles()

    def _save_profiles(self):
        try:
            config.save_profiles(self.profiles)
        except Exception as e:
            logging.error(f"Profile konnten nicht gespeichert werden: {e}")
            W.info(self, "Speichern fehlgeschlagen", str(e), "error")

    def _save_settings(self):
        try:
            config.save_settings(self.settings)
        except Exception as e:
            logging.warning(f"Einstellungen konnten nicht gespeichert werden: {e}")

    def _validate_profile_name(self, value):
        if not value:
            return "Bitte einen Namen eingeben."
        if len(value) > 60:
            return "Der Name ist zu lang (max. 60 Zeichen)."
        if config.find_profile(self.profiles, value):
            return "Ein Profil mit diesem Namen gibt es bereits."
        return None

    def new_profile(self):
        if self.busy:
            return
        name = W.ask_string(self, "Neues Profil", "Zum Beispiel „Projekte → Externe Festplatte“.",
                            ok_text="Erstellen", validate=self._validate_profile_name)
        if not name:
            return
        self.profiles[name] = config.normalize_profile({})
        self._save_profiles()
        self.set_profile(name)
        self.show_page("sources")
        self.toast.show(f"Profil „{name}“ erstellt. Füge jetzt Quellen und ein Ziel hinzu.", "success")

    def delete_profile(self):
        name = self.profile_name
        if not name or self.busy:
            return
        runs = self.snapshots.for_profile(name)
        size = sum(self.snapshots.info.get(r["run_id"], {}).get("size") or 0 for r in runs)
        checkbox = f"Auch die {len(runs)} Snapshots dieses Profils löschen ({utils.human_size(size)})" if runs else None
        answer = W.confirm(self, f"Profil „{name}“ löschen?",
                           "Die Einstellungen des Profils werden entfernt. Die gesicherten Dateien im Ziel bleiben erhalten.",
                           "Profil löschen", kind="danger", checkbox=checkbox)
        ok, also_runs = answer if checkbox else (answer, False)
        if not ok:
            return
        del self.profiles[name]
        self._save_profiles()
        remaining = sorted(self.profiles, key=str.lower)
        self.set_profile(remaining[0] if remaining else None)
        self.toast.show(f"Profil „{name}“ gelöscht.", "success")
        if also_runs:
            self.run_delete([r["run_id"] for r in runs])

    def profile_issues(self, prof):
        """Liste von (Ton, Text) mit Problemen der Profil-Konfiguration."""
        if not prof:
            return []
        issues = []
        sources, target = prof["sources"], prof["target"]
        if not sources:
            issues.append(("warning", "Noch keine Quellen hinzugefügt."))
        if not target:
            issues.append(("warning", "Kein Zielordner gewählt."))
        elif not utils.drive_available(target):
            issues.append(("danger", f"Ziel-Laufwerk {utils.drive_of(target)} ist nicht verbunden."))
        missing = [s for s in sources if not os.path.exists(s)]
        if missing:
            more = f" (+{len(missing) - 3} weitere)" if len(missing) > 3 else ""
            issues.append(("danger", f"{len(missing)} Quelle(n) nicht gefunden: " + ", ".join(missing[:3]) + more))
        seen = {}
        for s in sources:
            n = utils.source_name(s).lower()
            if n in seen:
                issues.append(("danger", f"„{seen[n]}“ und „{s}“ haben denselben Ordnernamen und würden im Ziel "
                                         f"im selben Ordner landen. Bitte eine der Quellen umbenennen oder entfernen."))
            seen.setdefault(n, s)
        for s in sources:
            if target and utils.is_subpath(target, s):
                issues.append(("info", f"Das Ziel liegt innerhalb der Quelle „{s}“ – es wird beim Sichern übersprungen."))
            elif target and utils.is_subpath(s, target):
                issues.append(("warning", f"Die Quelle „{s}“ liegt innerhalb des Ziels."))
            if utils.is_subpath(versions.VERSIONS_DIR, s):
                issues.append(("info", f"„{s}“ enthält den Snapshot-Ordner dieses Programms – er wird automatisch "
                                       f"übersprungen, damit das Backup nicht sich selbst sichert."))
        return issues

    # ------------------------------------------------------------------ Vorgänge
    def _check_ready(self, prof):
        if not prof:
            self.new_profile()
            return False
        if not prof["sources"]:
            W.info(self, "Keine Quellen", "Füge zuerst Ordner oder Dateien hinzu, die gesichert werden sollen.", "warning")
            self.show_page("sources")
            return False
        if not prof["target"]:
            W.info(self, "Kein Ziel", "Wähle zuerst einen Zielordner für das Backup.", "warning")
            self.show_page("sources")
            return False
        if not utils.drive_available(prof["target"]):
            W.info(self, "Ziel nicht erreichbar", f"Das Laufwerk {utils.drive_of(prof['target'])} ist nicht verbunden. "
                                                  "Bitte die Festplatte anschließen und erneut versuchen.", "error")
            return False
        return True

    def start_backup(self):
        if self.busy:
            return
        prof = self.current_profile()
        if not self._check_ready(prof):
            return
        issues = [t for tone, t in self.profile_issues(prof) if tone in ("danger", "warning")]
        if issues and not W.confirm(self, "Hinweise vor dem Start", "Bitte prüfe die folgenden Punkte:", "Trotzdem starten",
                                    kind="warning", details=[f"• {t}" for t in issues]):
            return
        self._start_profile_backup(self.profile_name)

    def _start_profile_backup(self, name, show_dashboard=True):
        prof = self.profiles[name]
        sources, target = list(prof["sources"]), prof["target"]
        excludes, hdd, snaps = list(prof["excludes"]), prof["hdd_mode"], prof.get("snapshots", True)
        workers = self.settings["workers"]
        self.run_operation("backup", lambda cb: backup.run_backup(
            progress_callback=cb, profile=name, hdd_mode=hdd, sources=sources, target=target,
            excludes=excludes, workers=workers, snapshots=snaps),
            show_dashboard=show_dashboard, profile=name, label=f"Backup „{name}“")

    def start_recovery(self):
        if self.busy:
            return
        prof = self.current_profile()
        if not self._check_ready(prof):
            return
        ok, overwrite = W.confirm(
            self, "Dateien wiederherstellen?",
            "Kopiert fehlende und abweichende Dateien aus dem Backup zurück in die Quellordner. Jede dabei "
            "überschriebene Datei wird vorher als Snapshot gesichert – die Wiederherstellung lässt sich rückgängig machen.",
            "Wiederherstellen", kind="warning",
            facts=[("Aus dem Backup", prof["target"], None), ("In die Quellen", f"{len(prof['sources'])} Einträge", None)],
            checkbox="Auch Dateien überschreiben, die in der Quelle neuer sind")
        if not ok:
            return
        name, sources, target = self.profile_name, list(prof["sources"]), prof["target"]
        excludes, hdd, workers = list(prof["excludes"]), prof["hdd_mode"], self.settings["workers"]
        self.run_operation("recovery", lambda cb: backup.run_recovery(
            progress_callback=cb, profile=name, hdd_mode=hdd, sources=sources, target=target,
            overwrite_newer=overwrite, excludes=excludes, workers=workers),
            profile=name, label=f"Wiederherstellung „{name}“")

    def run_operation(self, kind, fn, show_dashboard=True, profile=None, label=None):
        from engine.ui.pages.dashboard import OP_TITLES
        self.busy = True
        self.operation = kind
        self.operation_profile = profile
        self.operation_label = label or OP_TITLES.get(kind, "Vorgang")
        self._update_sync_status()
        backup.set_cancel_flag(False)
        self.broadcast("on_busy_changed", True)
        self.sidebar.on_busy_changed(True, kind)
        if show_dashboard:
            self.show_page("dashboard")

        def progress(p):
            self.post(self._on_progress, p)

        def runner():
            try:
                result = fn(progress)
            except Exception as e:
                logging.exception(f"Unerwarteter Fehler ({kind})")
                result = e
            self.post(self._operation_done, kind, result)

        self.worker = threading.Thread(target=runner, daemon=True, name=f"op-{kind}")
        self.worker.start()

    def _on_progress(self, p):
        if self.busy:
            self.pages["dashboard"].update_progress(p)
            self.sidebar.update_activity(p)

    def cancel_operation(self):
        if self.busy and self.operation in ("backup", "recovery"):
            backup.set_cancel_flag(True)
            logging.info("Abbruch angefordert – laufende Kopiervorgänge werden noch beendet.")
            self.pages["dashboard"].on_cancel_requested()

    def _operation_done(self, kind, result):
        profile = self.operation_profile
        self.busy = False
        self.operation = None
        self.worker = None
        self.broadcast("on_busy_changed", False)
        self.sidebar.on_busy_changed(False)
        self.operation_profile = None
        self.operation_label = None
        if self._closing:
            self.destroy()
            return
        if not self._syncing:
            self._flash()
        if kind in ("backup", "recovery"):
            self._finish_copy(kind, result, profile)
        elif kind == "rollback":
            self._finish_rollback(result)
        elif kind == "delete":
            self._finish_delete(result)
        elif kind == "move":
            self._finish_move(result)
        self.snapshots.refresh()
        if self._syncing and kind == "backup":
            self._sync_summary.append((profile, result))
            self.after(500, self._run_next_sync)
        self._update_sync_status()

    def _finish_copy(self, kind, result, profile):
        dash = self.pages["dashboard"]
        is_current = config.same_profile(profile, self.profile_name)
        if is_current or not self._syncing:
            dash.show_result(kind, result)
        if not isinstance(result, backup.RunResult):
            self.toast.show("Vorgang mit Fehler beendet – Details im Protokoll.", "error")
            return
        if result.code in (backup.OK, backup.PARTIAL) and kind == "backup":
            prof = self.profiles.get(profile)
            if prof is not None:
                prof["last_run"] = datetime.now().isoformat(timespec="seconds")
                self._save_profiles()
        dash.refresh()
        tone = {backup.OK: "success", backup.PARTIAL: "warning", backup.CANCELLED: "warning"}.get(result.code, "error")
        self.toast.show(f"„{profile}“: {result.message}" if self._syncing else result.message, tone)
        if result.code == backup.FAILED and not self._syncing:
            W.info(self, "Vorgang nicht möglich", result.message, "error")
        if kind == "backup" and result.code in (backup.OK, backup.PARTIAL) and self.settings["auto_prune"]:
            self.after(300, lambda: self._auto_prune(profile))

    def _auto_prune(self, profile, attempt=0):
        if not profile or profile not in self.profiles:
            return
        if self.busy:
            if attempt < 600:
                self.after(1000, lambda: self._auto_prune(profile, attempt + 1))
            return
        plan = versions.plan_prune(profile, self.settings["keep_snapshots"])
        if plan:
            logging.info(f"Automatisches Aufräumen „{profile}“: {len(plan)} alte Snapshots werden gelöscht.")
            self.run_delete([r["run_id"] for r in plan])

    # ------------------------------------------------------------------ Autostart & Synchronisierung
    def _ask_autostart(self):
        self.settings["autostart_asked"] = True
        self._save_settings()
        if system.autostart_enabled() or not self.tray.running:
            return
        interval = self.settings["sync_interval"]
        if W.confirm(self, "Automatisch im Hintergrund sichern?",
                     "Der Backup Manager kann mit Windows starten. Er läuft dann unauffällig im Infobereich der "
                     "Taskleiste (unten rechts neben der Uhr) und synchronisiert deine Profile automatisch. "
                     "Das kannst du jederzeit unter „Einstellungen“ ändern.",
                     "Ja, aktivieren", kind="question", cancel_text="Nein, danke",
                     facts=[("Mit Windows starten", "minimiert im Infobereich", None),
                            ("Synchronisierung", f"alle {interval} Minuten", None),
                            ("X-Knopf", "minimiert in den Infobereich", None)]):
            self.set_background_mode(True)

    def set_background_mode(self, enabled):
        system.set_autostart(enabled)
        self.settings.update(auto_sync=enabled, close_to_tray=enabled)
        self._save_settings()
        self._reschedule()
        self.broadcast("on_settings_changed")
        if enabled:
            self.toast.show("Autostart und automatische Synchronisierung sind aktiv.", "success")

    def _init_scheduler(self):
        self._reschedule(startup=True)
        self.after(5000, self._scheduler_tick)

    def _reschedule(self, startup=False):
        interval = self.settings["sync_interval"] * 60
        last = utils.parse_timestamp(self.settings.get("last_auto_sync"))
        now = time.time()
        if last and now - last.timestamp() < interval:
            self._next_sync = last.timestamp() + interval
        else:
            self._next_sync = now + (120 if startup else 60)
        self._update_sync_status()

    def _scheduler_tick(self):
        if self.closed:
            return
        if self.settings.get("auto_sync") and not self.busy and time.time() >= self._next_sync:
            self.sync_now(auto=True)
        self._update_sync_status()
        self.after(15000, self._scheduler_tick)

    def next_sync_time(self):
        return datetime.fromtimestamp(self._next_sync) if self.settings.get("auto_sync") else None

    def tray_status_text(self):
        if self.busy and self.operation_label:
            return f"Läuft: {self.operation_label} …"
        if not self.settings.get("auto_sync"):
            return "Automatische Synchronisierung: aus"
        return f"Nächste Synchronisierung: {self.next_sync_time():%H:%M} Uhr"

    def _update_sync_status(self):
        if not hasattr(self, "tray"):
            return
        self.tray.set_tooltip(f"Backup Manager – {self.tray_status_text()}")
        self.tray.refresh()
        self.broadcast("on_sync_status")

    def toggle_auto_sync(self):
        self.settings["auto_sync"] = not self.settings.get("auto_sync")
        self._save_settings()
        self._reschedule()
        self.broadcast("on_settings_changed")
        self.toast.show("Automatische Synchronisierung " + ("eingeschaltet." if self.settings["auto_sync"] else "ausgeschaltet."),
                        "success" if self.settings["auto_sync"] else "info")

    def sync_profile_names(self):
        return [n for n in sorted(self.profiles, key=str.lower)
                if self.profiles[n].get("auto_sync", True) and self.profiles[n]["sources"] and self.profiles[n]["target"]]

    def sync_now(self, auto=False):
        if self.busy or self._syncing:
            if not auto:
                self.toast.show("Es läuft bereits ein Vorgang.", "info")
            return
        names = self.sync_profile_names()
        if not names:
            if not auto:
                W.info(self, "Nichts zu synchronisieren",
                       "Kein Profil ist für die Synchronisierung eingeschaltet und vollständig eingerichtet "
                       "(Quellen und Ziel). Einstellbar unter „Quellen & Ziel → Optionen“.", "info")
            self._mark_synced()
            return
        self._sync_queue, self._sync_summary = list(names), []
        self._syncing, self._sync_auto = True, auto
        logging.info(f"Synchronisierung gestartet ({'automatisch' if auto else 'manuell'}): {', '.join(names)}")
        self._run_next_sync()

    def _run_next_sync(self):
        if self.closed:
            return
        if self.busy:
            self.after(1000, self._run_next_sync)
            return
        while self._sync_queue:
            name = self._sync_queue.pop(0)
            prof = self.profiles.get(name)
            if not prof:
                continue
            if not utils.drive_available(prof["target"]):
                logging.info(f"Synchronisierung: „{name}“ übersprungen – Laufwerk {utils.drive_of(prof['target'])} "
                             f"ist nicht verbunden.")
                self._sync_summary.append((name, None))
                continue
            self._start_profile_backup(name, show_dashboard=False)
            return
        self._syncing = False
        self._mark_synced()
        self._notify_sync_summary()

    def _mark_synced(self):
        self.settings["last_auto_sync"] = datetime.now().isoformat(timespec="seconds")
        self._save_settings()
        self._next_sync = time.time() + self.settings["sync_interval"] * 60
        self._update_sync_status()

    def _notify_sync_summary(self):
        results = [(n, r) for n, r in self._sync_summary if isinstance(r, backup.RunResult)]
        copied = sum(r.copied for _, r in results)
        errors = sum(len(r.errors) for _, r in results)
        failed = [n for n, r in self._sync_summary if isinstance(r, Exception)
                  or (isinstance(r, backup.RunResult) and r.code == backup.FAILED)]
        skipped = [n for n, r in self._sync_summary if r is None]
        parts = [f"{utils.format_count(copied)} Dateien gesichert" if copied else "Alles aktuell"]
        if errors:
            parts.append(f"{utils.format_count(errors)} Fehler")
        if failed:
            parts.append("fehlgeschlagen: " + ", ".join(failed))
        if skipped:
            parts.append("übersprungen (Laufwerk fehlt): " + ", ".join(skipped))
        text = " · ".join(parts)
        logging.info(f"Synchronisierung beendet: {text}")
        if copied or errors or failed:
            self.tray.notify(text, "Synchronisierung abgeschlossen")
        if self.winfo_viewable():
            self.toast.show(f"Synchronisierung: {text}", "warning" if errors or failed else "success")

    # ------------------------------------------------------------------ Snapshot-Ordner
    def change_versions_dir(self, new_dir):
        new_dir = os.path.abspath(new_dir)
        if utils.norm_key(new_dir) == utils.norm_key(versions.VERSIONS_DIR) or self.busy:
            return
        count = len(self.snapshots.summaries)
        if not W.confirm(self, "Snapshot-Ordner ändern?",
                         f"Neue Snapshots werden künftig in „{new_dir}“ gespeichert. Die vorhandenen "
                         f"{count} Snapshots werden dorthin verschoben – je nach Größe kann das dauern.",
                         "Verschieben", kind="warning"):
            return
        self.run_operation("move", lambda cb: versions.move_runs(new_dir, progress_callback=self._count_progress(cb, "move")),
                           show_dashboard=False, label="Snapshots verschieben")
        self._pending_versions_dir = new_dir

    def _finish_move(self, result):
        new_dir = getattr(self, "_pending_versions_dir", None)
        if isinstance(result, Exception) or not new_dir:
            W.info(self, "Verschieben fehlgeschlagen", str(result), "error")
            return
        moved, failed = result
        self.settings["versions_dir"] = None if utils.norm_key(new_dir) == utils.norm_key(config.DEFAULT_VERSIONS_DIR) else new_dir
        self._save_settings()
        self.snapshots.refresh(clear=True)
        self.broadcast("on_settings_changed")
        if failed:
            W.info(self, "Nicht alle Snapshots verschoben", f"{len(failed)} Snapshot(s) konnten nicht verschoben werden "
                                                             "und bleiben im alten Ordner.", "warning", details=failed)
        else:
            self.toast.show(f"{len(moved)} Snapshots verschoben.", "success")

    # ------------------------------------------------------------------ Snapshots
    def _count_progress(self, cb, operation):
        reporter = backup._Reporter(cb)
        prog = backup.Progress(operation=operation, phase="copy")

        def f(done, total):
            prog.files_done, prog.files_total = done, total
            reporter(prog, force=done == total)
        return f

    def confirm_rollback(self, run_id):
        if self.busy:
            return
        self.run_background(lambda: versions.preview_rollback(run_id), lambda pr: self._confirm_rollback(run_id, pr))

    def _confirm_rollback(self, run_id, pr):
        if not pr or isinstance(pr, Exception):
            W.info(self, "Vorschau nicht möglich", f"Die Metadaten von {run_id} konnten nicht gelesen werden.", "error")
            return
        s = self.snapshots.get(run_id)
        when = s["timestamp"].strftime("%d.%m.%Y, %H:%M Uhr") if s and s["timestamp"] else run_id
        if pr["kind"] == "recovery":
            text = (f"Macht die Wiederherstellung vom {when} rückgängig: überschriebene Dateien in den Quellordnern "
                    f"werden zurückgeholt, dabei neu angelegte Dateien gelöscht.")
        else:
            text = (f"Setzt das Backup-Ziel auf den Stand vor dem Lauf vom {when} zurück: überschriebene Dateien werden "
                    f"aus dem Snapshot wiederhergestellt, neu hinzugekommene Dateien gelöscht.")
        n_restore, n_delete, n_missing = len(pr["to_restore"]), len(pr["to_delete"]), len(pr["missing_snapshots"])
        facts = [("Dateien wiederherstellen", utils.format_count(n_restore), None),
                 ("Neu angelegte Dateien löschen", utils.format_count(n_delete), "warning" if n_delete else None),
                 ("Fehlende Snapshot-Dateien", utils.format_count(n_missing), "danger" if n_missing else "success")]
        details = [f"fehlt: {d}" for d, _s in pr["missing_snapshots"][:300]] or None
        if W.confirm(self, "Snapshot zurücksetzen?", text, "Zurücksetzen", kind="warning", facts=facts, details=details):
            self.run_operation("rollback", lambda cb: versions.rollback_run(
                run_id, progress_callback=self._count_progress(cb, "rollback")))

    def _finish_rollback(self, result):
        dash = self.pages["dashboard"]
        if isinstance(result, Exception) or not result or result[1] is None:
            dash.phase.configure(text="Rollback fehlgeschlagen")
            W.info(self, "Rollback fehlgeschlagen", str(result if isinstance(result, Exception) else "Run nicht gefunden"), "error")
            return
        _code, report = result
        problems = len(report["missing"]) + len(report["errors"])
        dash.phase.configure(text="Rollback abgeschlossen")
        text = (f"{utils.format_count(len(report['restored']))} Dateien wiederhergestellt, "
                f"{utils.format_count(len(report['deleted']))} neu angelegte Dateien entfernt.")
        details = [f"fehlt: {p}" for p in report["missing"][:200]] + [f"Fehler: {p} – {e}" for p, e in report["errors"][:200]]
        W.info(self, "Rollback abgeschlossen" if not problems else "Rollback mit Problemen abgeschlossen",
               text + (f"\n{problems} Datei(en) konnten nicht zurückgesetzt werden." if problems else ""),
               "warning" if problems else "success", details=details or None)

    def confirm_delete_runs(self, run_ids):
        runs = [self.snapshots.get(r) for r in run_ids]
        files = sum(r["total"] for r in runs if r)
        sizes = [self.snapshots.info.get(r, {}).get("size") for r in run_ids]
        size = utils.human_size(sum(s for s in sizes if s)) + (" (noch nicht vollständig berechnet)" if None in sizes else "")
        if W.confirm(self, f"{len(run_ids)} Snapshot(s) löschen?",
                     "Die gesicherten älteren Dateiversionen werden endgültig gelöscht. Die aktuellen Dateien im Ziel "
                     "bleiben unverändert.", "Endgültig löschen", kind="danger",
                     facts=[("Snapshots", utils.format_count(len(run_ids)), None),
                            ("Gesicherte Dateiversionen", utils.format_count(files), None),
                            ("Freiwerdender Speicher", size, None)]):
            self.run_delete(run_ids)

    def run_delete(self, run_ids):
        ids = list(run_ids)
        self.run_operation("delete", lambda cb: versions.delete_runs(
            ids, progress_callback=self._count_progress(cb, "delete")), show_dashboard=False)

    def _finish_delete(self, result):
        if isinstance(result, Exception):
            W.info(self, "Löschen fehlgeschlagen", str(result), "error")
            return
        succeeded, failed = result
        for rid in succeeded:
            self.snapshots.info.pop(rid, None)
        if failed:
            W.info(self, "Nicht alle Snapshots gelöscht", f"{len(failed)} Snapshot(s) konnten nicht gelöscht werden "
                                                           "(Dateien evtl. in Benutzung).", "warning", details=failed)
        else:
            self.toast.show(f"{len(succeeded)} Snapshot(s) gelöscht.", "success")

    def prune_dialog(self):
        if self.busy:
            return
        name = self.profile_name
        runs = self.snapshots.for_profile(name)
        dlg = W.Dialog(self, "Snapshots aufräumen", width=520)
        dlg.header("Alte Snapshots aufräumen", f"Behält die neuesten Snapshots von „{name}“ und löscht alle älteren.",
                   "broom", "primary")
        row = ctk.CTkFrame(dlg.body, fg_color="transparent")
        row.pack(fill="x", pady=(16, 0))
        W.label(row, "Neueste behalten:", 13).pack(side="left")
        entry = ctk.CTkEntry(row, width=80, height=36, corner_radius=10, justify="center", font=T.font(13),
                             fg_color=T.INPUT, border_color=T.BORDER_STRONG, text_color=T.TEXT)
        entry.insert(0, str(self.settings["keep_snapshots"]))
        entry.pack(side="left", padx=10)
        preview = W.label(dlg.body, "", 13, "bold", color=T.DANGER)
        preview.pack(anchor="w", pady=(14, 0))
        state = {"plan": []}

        def update(_e=None):
            try:
                keep = max(0, int(entry.get().strip()))
            except ValueError:
                preview.configure(text="Bitte eine Zahl eingeben.")
                state["plan"] = []
                return
            plan = runs[keep:]
            state["plan"] = plan
            size = sum(self.snapshots.info.get(r["run_id"], {}).get("size") or 0 for r in plan)
            preview.configure(text=f"{len(plan)} von {len(runs)} Snapshots werden gelöscht · ca. {utils.human_size(size)} frei"
                              if plan else "Nichts zu löschen.", text_color=T.DANGER if plan else T.MUTED)

        entry.bind("<KeyRelease>", update)
        update()
        dlg.add_button("Aufräumen", "danger", lambda: dlg.ok(True) if state["plan"] else None, "broom")
        dlg.add_button("Abbrechen", "secondary", dlg.cancel)
        if dlg.show():
            self.run_delete([r["run_id"] for r in state["plan"]])

    def open_run_folder(self, run_id):
        W.open_in_explorer(os.path.join(versions.VERSIONS_DIR, run_id))

    def show_run_details(self, run_id):
        def load():
            md = versions.load_metadata(run_id) or {}
            rows = []
            for e in md.get("files") or []:
                dest = e.get("dest") or ""
                snap = e.get("snapshot")
                if e.get("created"):
                    kind, status = "Neu", "–"
                else:
                    kind = "Geändert"
                    status = "vorhanden" if snap and os.path.exists(utils.long_path(snap)) else "fehlt"
                size = e.get("size")
                if size is None and status == "vorhanden":
                    try:
                        size = os.path.getsize(utils.long_path(snap))
                    except OSError:
                        size = None
                rows.append((os.path.basename(dest), os.path.dirname(dest), kind, status,
                             utils.human_size(size) if size is not None else "–", dest, snap or ""))
            return md, rows

        self.toast.show("Snapshot wird geladen …", "info", 1500)
        self.run_background(load, lambda res: self._show_run_details(run_id, res))

    def _show_run_details(self, run_id, res):
        if isinstance(res, Exception):
            W.info(self, "Fehler", str(res), "error")
            return
        md, rows = res
        s = self.snapshots.get(run_id) or {}
        ts = s.get("timestamp")
        created = sum(1 for r in rows if r[2] == "Neu")
        missing = sum(1 for r in rows if r[3] == "fehlt")
        chips = [(f"{utils.format_count(len(rows))} Dateien", "primary"), (f"{utils.format_count(created)} neu", "info"),
                 (f"{utils.format_count(len(rows) - created)} geändert", "warning")]
        if missing:
            chips.append((f"{utils.format_count(missing)} fehlen", "danger"))
        kind = KIND_LABELS.get(md.get("kind") or "backup", md.get("kind"))
        columns = [("name", "DATEI", 230, "w", False), ("folder", "ORDNER IM ZIEL", 380, "w", True),
                   ("kind", "ART", 90, "w", False), ("snap", "SNAPSHOT", 100, "w", False), ("size", "GRÖSSE", 90, "e", False)]

        def save_version(selected, dlg):
            if len(selected) != 1 or selected[0][3] != "vorhanden":
                W.info(dlg, "Version speichern", "Bitte genau eine geänderte Datei mit vorhandenem Snapshot auswählen.", "info")
                return
            row = selected[0]
            path = filedialog.asksaveasfilename(parent=dlg, title="Ältere Version speichern unter",
                                                initialfile=row[0], initialdir=os.path.expanduser("~"))
            if path:
                try:
                    utils.copy_file(row[6], path)
                    self.toast.show(f"Ältere Version gespeichert: {os.path.basename(path)}", "success")
                except Exception as e:
                    W.info(dlg, "Speichern fehlgeschlagen", str(e), "error")

        def reveal(selected, _dlg):
            if selected:
                W.open_in_explorer(selected[0][5], select=True)

        def rollback(_selected, dlg):
            dlg.cancel()
            self.confirm_rollback(run_id)

        actions = [("Zurücksetzen …", "primary_soft", "undo", rollback)] if not self.busy else []
        actions += [("Im Ziel zeigen", "secondary", "open_local", reveal),
                    ("Version speichern …", "secondary", "save_copy", save_version)]
        dlg = W.ListDialog(self, f"Snapshot vom {ts.strftime('%d.%m.%Y, %H:%M') if ts else run_id}",
                           f"Profil: {md.get('profile') or '–'} · {kind}", columns, rows, "history", "primary",
                           actions=actions, on_double=reveal, chips=chips,
                           row_tags=lambda r: "danger" if r[3] == "fehlt" else "")
        dlg.show(height=680)

    def show_changes(self, result):
        rows = [(os.path.basename(dest), os.path.dirname(dest), "Neu" if created else "Geändert", src, dest)
                for src, dest, created in result.changed_files]
        columns = [("name", "DATEI", 240, "w", False), ("folder", "ORDNER IM ZIEL", 480, "w", True), ("kind", "ART", 100, "w", False)]
        title = "Gesicherte Dateien" if result.operation == "backup" else "Wiederhergestellte Dateien"
        W.ListDialog(self, title, f"{utils.format_count(len(rows))} Dateien · {utils.human_size(result.bytes_copied)}",
                     columns, rows, "completed", "success",
                     actions=[("Im Ordner zeigen", "secondary", "open_local",
                               lambda sel, d: sel and W.open_in_explorer(sel[0][4], select=True))],
                     on_double=lambda sel, d: sel and W.open_in_explorer(sel[0][4], select=True)).show(height=640)

    def show_errors(self, result):
        rows = [(p, msg) for p, msg in result.errors]
        columns = [("path", "PFAD", 520, "w", True), ("msg", "FEHLER", 360, "w", True)]
        W.ListDialog(self, "Fehler", f"{len(rows)} Dateien konnten nicht verarbeitet werden. Häufige Ursachen: Datei "
                                     f"ist geöffnet, fehlende Rechte oder Laufwerk voll.",
                     columns, rows, "warning", "warning", row_tags=lambda r: "danger").show(height=600)
