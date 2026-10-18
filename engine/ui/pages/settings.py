"""Einstellungen: Darstellung, Autostart & Synchronisierung, Backup-Verhalten, Speicherort."""
import threading
from datetime import datetime
from tkinter import filedialog

import customtkinter as ctk

from engine import config, system, utils, version, versions
from engine.ui import theme as T
from engine.ui import widgets as W

APPEARANCE = {"Hell": "light", "Dunkel": "dark", "System": "system"}
INTERVALS = {"15 Min.": 15, "30 Min.": 30, "60 Min.": 60, "2 Std.": 120, "4 Std.": 240}


def _row(parent, row, title, text, help_key=None):
    W.heading(parent, title, help_key, size=13).grid(row=row, column=0, sticky="w", padx=22, pady=(14, 0))
    lbl = W.label(parent, text, 12, color=T.MUTED)
    lbl.grid(row=row + 1, column=0, sticky="ew", padx=22, pady=(0, 14))
    W.autowrap(lbl, parent, margin=260)


def _switch(parent, command):
    return ctk.CTkSwitch(parent, text="", width=46, command=command, progress_color=T.PRIMARY, fg_color=T.BORDER_STRONG)


class SettingsPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent", scrollbar_button_color=T.BORDER_STRONG,
                         scrollbar_button_hover_color=T.SUBTLE)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        s = app.settings

        W.PageHeader(self, "Einstellungen", "Gelten für alle Profile. Ein Klick auf „?“ erklärt jede Option ausführlich."
                     ).grid(row=0, column=0, sticky="ew", pady=(0, 20), padx=(0, 12))

        # --- Darstellung
        card = self._card(1, "Darstellung")
        _row(card, 1, "Farbschema", "Hell, Dunkel oder automatisch wie Windows.", "appearance")
        self.appearance = W.segmented(card, list(APPEARANCE), command=self._set_appearance)
        self.appearance.set(next(k for k, v in APPEARANCE.items() if v == s["appearance"]))
        self.appearance.grid(row=1, column=1, rowspan=2, padx=22, sticky="e")

        # --- Autostart & Synchronisierung
        card = self._card(2, "Autostart & Synchronisierung")
        _row(card, 1, "Mit Windows starten", "Startet beim Anmelden unsichtbar im Infobereich der Taskleiste "
                                             "(unten rechts neben der Uhr).", "autostart")
        self.autostart = _switch(card, self._set_autostart)
        self.autostart.grid(row=1, column=1, rowspan=2, padx=22, sticky="e")

        _row(card, 3, "Automatisch synchronisieren", "Sichert alle dafür eingeschalteten Profile regelmäßig – "
                                                     "auch wenn das Fenster geschlossen ist.", "auto_sync")
        self.auto_sync = _switch(card, self._set_auto_sync)
        self.auto_sync.grid(row=3, column=1, rowspan=2, padx=22, sticky="e")

        _row(card, 5, "Abstand", "Wie oft synchronisiert wird.", "interval")
        self.interval = W.segmented(card, list(INTERVALS), command=self._set_interval)
        self.interval.grid(row=5, column=1, rowspan=2, padx=22, sticky="e")

        _row(card, 7, "Beim Schließen in den Infobereich", "Das X blendet das Fenster nur aus, der Backup Manager "
                                                          "läuft weiter.", "close_to_tray")
        self.close_to_tray = _switch(card, self._set_close_to_tray)
        self.close_to_tray.grid(row=7, column=1, rowspan=2, padx=22, sticky="e")

        status = ctk.CTkFrame(card, fg_color=T.CARD_ALT, corner_radius=12)
        status.grid(row=9, column=0, columnspan=2, sticky="ew", padx=22, pady=(4, 20))
        status.grid_columnconfigure(1, weight=1)
        self.sync_bubble = W.IconBubble(status, "sync", "primary", size=32, icon_size=16)
        self.sync_bubble.grid(row=0, column=0, padx=(12, 10), pady=10)
        self.sync_status = W.label(status, "", 12, color=T.MUTED)
        self.sync_status.grid(row=0, column=1, sticky="ew")
        W.autowrap(self.sync_status, status, margin=280)
        self.btn_sync = W.button(status, "Jetzt synchronisieren", "secondary", "sync", height=32, command=app.sync_now)
        self.btn_sync.grid(row=0, column=2, padx=12)
        if not app.tray.available:
            W.label(card, "Hinweis: Das Infobereich-Symbol ist nicht verfügbar – bitte install.bat erneut ausführen.",
                    12, color=T.WARNING).grid(row=10, column=0, columnspan=2, sticky="w", padx=22, pady=(0, 16))

        # --- Backup
        card = self._card(3, "Backup")
        _row(card, 1, "Parallele Kopiervorgänge", "Mehr ist auf SSDs schneller. Im HDD-Modus wird immer "
                                                  "nacheinander kopiert.", "workers")
        self.workers = W.segmented(card, ["2", "4", "8", "16"], command=self._set_workers)
        self.workers.set(str(s["workers"]) if str(s["workers"]) in ("2", "4", "8", "16") else "8")
        self.workers.grid(row=1, column=1, rowspan=2, padx=22, sticky="e")

        _row(card, 3, "Alte Snapshots automatisch löschen", "Nach jedem Backup nur die neuesten Snapshots des "
                                                            "Profils behalten.", "auto_prune")
        self.auto_prune = _switch(card, self._set_auto_prune)
        if s["auto_prune"]:
            self.auto_prune.select()
        self.auto_prune.grid(row=3, column=1, rowspan=2, padx=22, sticky="e")

        _row(card, 5, "Anzahl behalten", "So viele Snapshots pro Profil bleiben beim Aufräumen erhalten.", "keep")
        self.keep = ctk.CTkEntry(card, width=90, height=34, corner_radius=10, font=T.font(13), justify="center",
                                 fg_color=T.INPUT, border_color=T.BORDER_STRONG, text_color=T.TEXT)
        self.keep.insert(0, str(s["keep_snapshots"]))
        self.keep.bind("<FocusOut>", lambda e: self._set_keep())
        self.keep.bind("<Return>", lambda e: self._set_keep())
        self.keep.grid(row=5, column=1, rowspan=2, padx=22, sticky="e")

        # --- Allgemein
        card = self._card(4, "Allgemein")
        _row(card, 1, "Beim Beenden nachfragen", "Sicherheitsabfrage, bevor das Programm wirklich beendet wird.",
             "confirm_close")
        self.confirm_close = _switch(card, self._set_confirm_close)
        if s["confirm_close"]:
            self.confirm_close.select()
        self.confirm_close.grid(row=1, column=1, rowspan=2, padx=22, sticky="e")

        # --- Speicher
        card = self._card(5, "Speicherort der Snapshots", "versions_dir")
        self.versions_label = W.label(card, versions.VERSIONS_DIR, 13, "bold")
        self.versions_label.grid(row=1, column=0, sticky="ew", padx=22, pady=(10, 2))
        self.storage = W.label(card, "Gesamtgröße: – (auf „Berechnen“ klicken)", 12, color=T.MUTED)
        self.storage.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 6))
        W.label(card, f"Einstellungen und Logs: {config.DATA_DIR}", 12, color=T.SUBTLE).grid(
            row=3, column=0, sticky="ew", padx=22, pady=(0, 18))
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=1, column=1, rowspan=3, padx=22, sticky="e")
        W.button(btns, "Ändern …", "secondary", "folder_open", height=34, command=self._change_versions_dir).pack(side="left")
        W.button(btns, "Berechnen", "secondary", "diagnostic", height=34, command=self._compute_storage).pack(side="left", padx=8)
        W.button(btns, "Öffnen", "secondary", "open_local", height=34,
                 command=lambda: W.open_in_explorer(versions.VERSIONS_DIR)).pack(side="left")

        # --- Updates
        card = self._card(6, "Updates")
        _row(card, 1, "Automatisch nach Updates suchen", "Einmal täglich auf GitHub nachsehen, ob es eine neue "
                                                         "Version gibt.", "update_check")
        self.update_check = _switch(card, self._set_update_check)
        if s.get("update_check"):
            self.update_check.select()
        self.update_check.grid(row=1, column=1, rowspan=2, padx=22, sticky="e")
        status = ctk.CTkFrame(card, fg_color=T.CARD_ALT, corner_radius=12)
        status.grid(row=3, column=0, columnspan=2, sticky="ew", padx=22, pady=(4, 20))
        status.grid_columnconfigure(1, weight=1)
        self.update_bubble = W.IconBubble(status, "download", "muted", size=32, icon_size=16)
        self.update_bubble.grid(row=0, column=0, padx=(12, 10), pady=10)
        self.update_status = W.label(status, "", 12, color=T.MUTED)
        self.update_status.grid(row=0, column=1, sticky="ew")
        W.autowrap(self.update_status, status, margin=280)
        self.btn_update = W.button(status, "Jetzt prüfen", "secondary", "refresh", height=32,
                                   command=self._update_action)
        self.btn_update.grid(row=0, column=2, padx=12)

        self.on_settings_changed()

    def _card(self, row, title, help_key=None):
        card = W.Card(self)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 16), padx=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        W.heading(card, title, help_key).grid(row=0, column=0, sticky="w", padx=22, pady=(18, 0))
        return card

    # ------------------------------------------------------------------ Anzeige
    def on_show(self):
        self.on_settings_changed()

    def on_settings_changed(self):
        s = self.app.settings
        for switch, value in ((self.autostart, system.autostart_enabled()), (self.auto_sync, s.get("auto_sync")),
                              (self.close_to_tray, s.get("close_to_tray"))):
            switch.select() if value else switch.deselect()
        label = next((k for k, v in INTERVALS.items() if v == s["sync_interval"]), None)
        if label:
            self.interval.set(label)
        self.versions_label.configure(text=versions.VERSIONS_DIR)
        self.on_sync_status()
        self.on_update_status()

    def on_update_status(self):
        app, s = self.app, self.app.settings
        info = app.update_info
        if app._updating:
            text, tone, btn, state = f"Version {info.version} wird heruntergeladen und installiert …", "primary", \
                "Jetzt aktualisieren", "disabled"
        elif app._update_checking:
            text, tone, btn, state = "Suche nach Updates …", "primary", "Jetzt prüfen", "disabled"
        elif info:
            text, tone, btn, state = (f"Version {info.version} ist verfügbar (installiert: {version.VERSION}).",
                                      "success", "Jetzt aktualisieren", "normal")
        else:
            last = utils.parse_timestamp(s.get("last_update_check"))
            text = f"Installiert: Version {version.VERSION} · " + (
                f"zuletzt geprüft: {utils.relative_time(last).lower()}" if last else "noch nicht geprüft")
            tone, btn, state = "muted", "Jetzt prüfen", "normal"
        self.update_status.configure(text=text)
        self.update_bubble.set("download", tone, icon_size=16)
        self.btn_update.configure(text=btn, state=state)

    def _update_action(self):
        if self.app.update_info:
            self.app.offer_update()
        else:
            self.app.check_for_updates(manual=True)

    def _set_update_check(self):
        self._save(update_check=bool(self.update_check.get()))

    def on_sync_status(self):
        s = self.app.settings
        last = utils.parse_timestamp(s.get("last_auto_sync"))
        last_text = f"zuletzt {utils.relative_time(last).lower()}" if last else "noch nie synchronisiert"
        if self.app._syncing:
            text = f"Synchronisierung läuft: {self.app.operation_label or ''} …"
        elif s.get("auto_sync"):
            nxt = self.app.next_sync_time()
            text = f"Nächste Synchronisierung um {nxt:%H:%M} Uhr · {last_text} · " \
                   f"{len(self.app.sync_profile_names())} Profil(e) einbezogen"
        else:
            text = f"Automatische Synchronisierung ist aus · {last_text}"
        self.sync_status.configure(text=text)
        self.sync_bubble.set("sync", "primary" if s.get("auto_sync") else "muted", icon_size=16)
        self.btn_sync.configure(state="disabled" if self.app.busy else "normal")

    def on_busy_changed(self, busy):
        self.btn_sync.configure(state="disabled" if busy else "normal")

    # ------------------------------------------------------------------ Änderungen
    def _save(self, **kw):
        self.app.settings.update(kw)
        config.save_settings(self.app.settings)

    def _set_appearance(self, value):
        mode = APPEARANCE[value]
        self._save(appearance=mode)
        self.app.set_appearance(mode)

    def _set_autostart(self):
        enabled = bool(self.autostart.get())
        if not system.set_autostart(enabled):
            W.info(self, "Autostart nicht möglich", "Der Eintrag in der Windows-Registry konnte nicht geändert werden.",
                   "error")
        elif enabled and not self.app.settings.get("close_to_tray"):
            self._save(close_to_tray=True)
        self.on_settings_changed()
        self.app.toast.show("Startet jetzt automatisch mit Windows (im Infobereich)." if enabled
                            else "Autostart ausgeschaltet.", "success" if enabled else "info")

    def _set_auto_sync(self):
        self._save(auto_sync=bool(self.auto_sync.get()))
        self.app._reschedule()
        self.app.broadcast("on_settings_changed")

    def _set_interval(self, value):
        self._save(sync_interval=INTERVALS[value])
        self.app._reschedule()
        self.app.broadcast("on_settings_changed")

    def _set_close_to_tray(self):
        self._save(close_to_tray=bool(self.close_to_tray.get()))

    def _set_workers(self, value):
        self._save(workers=int(value))

    def _set_auto_prune(self):
        self._save(auto_prune=bool(self.auto_prune.get()))

    def _set_confirm_close(self):
        self._save(confirm_close=bool(self.confirm_close.get()))

    def _set_keep(self):
        try:
            value = max(1, int(self.keep.get().strip()))
        except ValueError:
            value = self.app.settings["keep_snapshots"]
        self.keep.delete(0, "end")
        self.keep.insert(0, str(value))
        if value != self.app.settings["keep_snapshots"]:
            self._save(keep_snapshots=value)
            self.app.toast.show(f"Es werden {value} Snapshots pro Profil behalten.", "success", 2000)

    def _change_versions_dir(self):
        path = filedialog.askdirectory(parent=self, title="Neuen Ordner für Snapshots wählen",
                                       initialdir=versions.VERSIONS_DIR)
        if path:
            self.app.change_versions_dir(path)

    def _compute_storage(self):
        self.storage.configure(text="Gesamtgröße: wird berechnet …")

        def work():
            runs = versions.list_run_summaries()
            total = sum(versions.inspect_run(r["run_id"])["size"] for r in runs)
            usage = utils.disk_usage(versions.VERSIONS_DIR)
            free = f" · {utils.human_size(usage.free)} frei auf {utils.drive_of(versions.VERSIONS_DIR)}" if usage else ""
            self.app.post(self.storage.configure,
                          text=f"Gesamtgröße: {utils.human_size(total)} in {utils.format_count(len(runs))} Snapshots{free}"
                               f" · Stand {datetime.now():%H:%M}")

        threading.Thread(target=work, daemon=True).start()
