"""Übersicht: Kennzahlen, Backup/Wiederherstellung starten, Live-Fortschritt, letzte Snapshots."""
import os
import time
from datetime import datetime

import customtkinter as ctk

from engine import backup, utils
from engine.ui import theme as T
from engine.ui import widgets as W

OP_TITLES = {"backup": "Backup", "recovery": "Wiederherstellung", "rollback": "Rollback",
             "delete": "Snapshots löschen", "move": "Snapshots verschieben"}
BACKGROUND_OPS = ("delete", "move")
KIND_LABELS = {"backup": "Backup", "recovery": "Wiederherstellung", "pre-rollback": "Vor Rollback"}


def elide(text, n=92):
    return text if len(text) <= n else text[: n // 2 - 1] + " … " + text[-(n // 2 - 2):]


class _Metric(ctk.CTkFrame):
    def __init__(self, master, title):
        super().__init__(master, fg_color="transparent")
        W.label(self, title.upper(), 10, "bold", color=T.SUBTLE).pack(anchor="w")
        self.value = W.label(self, "–", 15, "bold")
        self.value.pack(anchor="w", pady=(2, 0))

    def set(self, text):
        self.value.configure(text=text)


class DashboardPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._copy_started = None
        self._mode = "determinate"
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self.header = W.PageHeader(self, "Übersicht", "")
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, 20))

        # --- Kennzahlen
        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        for i in range(4):
            stats.grid_columnconfigure(i, weight=1, uniform="stats")
        self.stat_last = W.StatCard(stats, "Letztes Backup", "clock", "primary", help_key="stat_last")
        self.stat_sources = W.StatCard(stats, "Quellen", "folder", "info", help_key="stat_sources")
        self.stat_snaps = W.StatCard(stats, "Snapshots", "history", "success", help_key="stat_snapshots")
        self.stat_drive = W.StatCard(stats, "Ziel-Laufwerk", "drive", "warning", help_key="stat_drive")
        for i, c in enumerate((self.stat_last, self.stat_sources, self.stat_snaps, self.stat_drive)):
            c.grid(row=0, column=i, sticky="nsew", padx=(0, 0 if i == 3 else 16))

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=2, column=0, sticky="nsew")
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(0, weight=1)
        self._build_action_card(main)
        self._build_recent_card(main)

        self.empty = W.EmptyState(self, "shield", "Willkommen beim Backup Manager",
                                  "Lege ein Profil an, um festzulegen, welche Ordner wohin gesichert werden. "
                                  "Du kannst beliebig viele Profile anlegen – z. B. für externe Festplatten.",
                                  "Profil erstellen", app.new_profile)

    # ------------------------------------------------------------------ Aufbau
    def _build_action_card(self, parent):
        left = ctk.CTkFrame(parent, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)
        card = W.Card(left)
        card.grid(row=0, column=0, sticky="new")
        card.grid_columnconfigure(0, weight=1)
        self.action_card = card
        self._build_sources_card(left)
        left.bind("<Configure>", self._on_left_resize, add="+")
        pad = 24

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=pad, pady=(22, 4))
        W.label(top, "Sicherung", 18, "bold").pack(side="left")
        W.HelpBadge(top, "backup").pack(side="left", padx=(8, 0))
        self.state_badge = W.Badge(top, "Bereit", "success")
        self.state_badge.pack(side="left", padx=12)
        self.snap_badge = W.Badge(top, "Ohne Snapshots", "warning")
        W.HelpBadge(top, "hdd").pack(side="right", padx=(8, 0))
        self.hdd = ctk.CTkSwitch(top, text="HDD-Modus", command=self._toggle_hdd, font=T.font(13),
                                 text_color=T.MUTED, progress_color=T.PRIMARY, fg_color=T.BORDER_STRONG)
        self.hdd.pack(side="right")

        self.desc = W.label(card, "Kopiert neue und geänderte Dateien ins Ziel. Überschriebene Dateien werden vorher "
                                  "als Snapshot gesichert – so lässt sich jeder Lauf wieder zurücksetzen.",
                            13, color=T.MUTED)
        self.desc.grid(row=1, column=0, sticky="ew", padx=pad)
        W.autowrap(self.desc, card, margin=2 * pad)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=2, column=0, sticky="ew", padx=pad, pady=(18, 18))
        self.btn_backup = W.button(row, "Backup starten", "primary", "play", height=46, icon_size=18, width=200,
                                   command=self.app.start_backup)
        self.btn_backup.pack(side="left")
        self.btn_recovery = W.button(row, "Wiederherstellen", "secondary", "download", height=46,
                                     command=self.app.start_recovery)
        self.btn_recovery.pack(side="left", padx=(10, 0))
        W.HelpBadge(row, "recovery").pack(side="left", padx=(8, 0))
        self.btn_cancel = W.button(row, "Abbrechen", "danger_soft", "stop", height=46, command=self.app.cancel_operation)

        ctk.CTkFrame(card, height=1, fg_color=T.BORDER).grid(row=3, column=0, sticky="ew", padx=pad)

        prog = ctk.CTkFrame(card, fg_color="transparent")
        prog.grid(row=4, column=0, sticky="ew", padx=pad, pady=(18, 0))
        prog.grid_columnconfigure(0, weight=1)
        ph = ctk.CTkFrame(prog, fg_color="transparent")
        ph.grid(row=0, column=0, sticky="w")
        self.phase = W.label(ph, "Bereit", 14, "bold")
        self.phase.pack(side="left")
        W.HelpBadge(ph, "progress", size=16).pack(side="left", padx=(8, 0))
        self.percent = W.label(prog, "", 14, "bold", color=T.PRIMARY_TEXT)
        self.percent.grid(row=0, column=1, sticky="e")
        self.bar = ctk.CTkProgressBar(prog, height=10, corner_radius=5, progress_color=T.PRIMARY, fg_color=T.CARD_ALT)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        self.set_bar(0)
        self.current = W.label(prog, "Starte ein Backup, um neue und geänderte Dateien zu sichern.", 12, color=T.MUTED)
        self.current.grid(row=2, column=0, columnspan=2, sticky="ew")

        metrics = ctk.CTkFrame(card, fg_color="transparent")
        metrics.grid(row=5, column=0, sticky="ew", padx=pad, pady=(16, 20))
        for i in range(4):
            metrics.grid_columnconfigure(i, weight=1, uniform="m")
        self.m_files = _Metric(metrics, "Dateien")
        self.m_bytes = _Metric(metrics, "Daten")
        self.m_speed = _Metric(metrics, "Tempo")
        self.m_eta = _Metric(metrics, "Restzeit")
        for i, m in enumerate((self.m_files, self.m_bytes, self.m_speed, self.m_eta)):
            m.grid(row=0, column=i, sticky="w")

        sync = ctk.CTkFrame(card, fg_color=T.CARD_ALT, corner_radius=12)
        sync.grid(row=7, column=0, sticky="ew", padx=pad, pady=(0, 22))
        sync.grid_columnconfigure(1, weight=1)
        self.sync_bubble = W.IconBubble(sync, "sync", "primary", size=32, icon_size=16)
        self.sync_bubble.grid(row=0, column=0, rowspan=2, padx=(12, 10), pady=10)
        sync_head = ctk.CTkFrame(sync, fg_color="transparent")
        sync_head.grid(row=0, column=1, sticky="sw", pady=(10, 0))
        self.sync_title = W.label(sync_head, "Automatische Synchronisierung", 13, "bold")
        self.sync_title.pack(side="left")
        W.HelpBadge(sync_head, "sync_row", size=16).pack(side="left", padx=(8, 0))
        self.sync_text = W.label(sync, "", 12, color=T.MUTED)
        self.sync_text.grid(row=1, column=1, sticky="nw", pady=(0, 10))
        self.btn_sync = W.button(sync, "Jetzt alle synchronisieren", "secondary", "sync", height=32,
                                 command=self.app.sync_now)
        self.btn_sync.grid(row=0, column=2, rowspan=2, padx=12)

        self.result = ctk.CTkFrame(card, corner_radius=12)
        self.result.grid_columnconfigure(1, weight=1)
        self.result_bubble = W.IconBubble(self.result, "completed", "success", size=40)
        self.result_bubble.grid(row=0, column=0, rowspan=2, padx=(14, 12), pady=14)
        self.result_title = W.label(self.result, "", 14, "bold")
        self.result_title.grid(row=0, column=1, sticky="sw", pady=(14, 0))
        self.result_text = W.label(self.result, "", 12, color=T.MUTED)
        W.autowrap(self.result_text, self.result, margin=300)
        self.result_text.grid(row=1, column=1, sticky="nw", pady=(0, 14))
        self.result_btns = ctk.CTkFrame(self.result, fg_color="transparent")
        self.result_btns.grid(row=0, column=2, rowspan=2, padx=(8, 12))

    def _build_sources_card(self, parent):
        card = W.Card(parent)
        card.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        W.heading(head, "Gesicherte Quellen", "sources").pack(side="left")
        W.button(head, "Bearbeiten", "ghost", height=30, text_color=T.PRIMARY_TEXT,
                 command=lambda: self.app.show_page("sources")).pack(side="right")
        self.src_list = ctk.CTkFrame(card, fg_color="transparent")
        self.src_list.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.src_list.grid_columnconfigure(0, weight=1)
        self.sources_card = card
        self._src_capacity = 0

    def _on_left_resize(self, event):
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        avail = (event.height - self.action_card.winfo_height()) / scale - 16
        capacity = int((avail - 70) // 50) if avail > 150 else 0
        if capacity != self._src_capacity:
            self._src_capacity = capacity
            if capacity <= 0:
                self.sources_card.grid_forget()
            else:
                self.sources_card.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
                self._render_sources()

    def _render_sources(self):
        for w in self.src_list.winfo_children():
            w.destroy()
        prof = self.app.current_profile()
        if not prof or self._src_capacity <= 0:
            return
        sources = prof["sources"]
        shown = sources[: self._src_capacity if len(sources) <= self._src_capacity else self._src_capacity - 1]
        if not sources:
            W.label(self.src_list, "Noch keine Quellen – lege fest, was gesichert werden soll.", 13,
                    color=T.MUTED).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        for i, path in enumerate(shown):
            exists = os.path.exists(path)
            is_dir = os.path.isdir(path)
            row = ctk.CTkFrame(self.src_list, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", pady=1)
            row.grid_columnconfigure(1, weight=1)
            W.IconBubble(row, "folder" if is_dir or not exists else "file", "danger" if not exists else "primary",
                         size=32, icon_size=15).grid(row=0, column=0, rowspan=2, padx=(8, 12), pady=5)
            norm = os.path.normpath(path)
            W.label(row, os.path.basename(norm) or norm, 13, "bold").grid(row=0, column=1, sticky="sw")
            W.label(row, os.path.dirname(norm), 11, color=T.MUTED).grid(row=1, column=1, sticky="nw")
            if not exists:
                W.Badge(row, "Nicht gefunden", "danger").grid(row=0, column=2, rowspan=2, padx=8)
        if len(shown) < len(sources):
            W.label(self.src_list, f"+ {len(sources) - len(shown)} weitere", 12, color=T.MUTED).grid(
                row=len(shown), column=0, sticky="w", padx=10, pady=(4, 0))

    def _build_recent_card(self, parent):
        card = W.Card(parent)
        card.grid(row=0, column=1, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        W.heading(head, "Letzte Snapshots", "recent").pack(side="left")
        W.button(head, "Alle anzeigen", "ghost", height=30, text_color=T.PRIMARY_TEXT,
                 command=lambda: self.app.show_page("snapshots")).pack(side="right")
        card.grid_rowconfigure(1, weight=1)
        self.recent = ctk.CTkFrame(card, fg_color="transparent")
        self.recent.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 14))
        self.recent.grid_columnconfigure(0, weight=1)
        self._recent_capacity = 4
        self._recent_runs = []
        self.recent.bind("<Configure>", self._on_recent_resize, add="+")

    # ------------------------------------------------------------------ Aktualisierung
    def on_show(self):
        self.refresh()

    def on_profile_changed(self):
        self.hide_result()
        self.refresh()

    def on_snapshots_changed(self):
        self.refresh_snapshot_info()

    def on_sync_status(self):
        s = self.app.settings
        if self.app._syncing:
            text = f"Läuft gerade: {self.app.operation_label or 'Synchronisierung'} …"
        elif s.get("auto_sync"):
            nxt = self.app.next_sync_time()
            n = len(self.app.sync_profile_names())
            text = (f"Alle {s['sync_interval']} Min. · nächste um {nxt:%H:%M} Uhr · {n} Profil(e) einbezogen"
                    if nxt else "")
        else:
            text = "Ausgeschaltet – in den Einstellungen aktivierbar. Manuell jederzeit möglich."
        self.sync_text.configure(text=text)
        self.sync_bubble.set("sync", "primary" if s.get("auto_sync") else "muted", icon_size=16)
        self.btn_sync.configure(state="disabled" if self.app.busy else "normal")

    def on_settings_changed(self):
        self.on_sync_status()

    def on_snapshot_info(self, run_id):
        # Viele Einzel-Updates während der Hintergrundprüfung → gebündelt neu zeichnen
        if getattr(self, "_info_job", None) is None:
            self._info_job = self.after(600, self._apply_snapshot_info)

    def _apply_snapshot_info(self):
        self._info_job = None
        if self.winfo_ismapped():
            self.refresh_snapshot_info()

    def refresh(self):
        prof = self.app.current_profile()
        if not prof:
            self.empty.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.empty.lift()
            return
        self.empty.place_forget()
        self._render_sources()
        name = self.app.profile_name
        self.header.title.configure(text=name)
        self.header.subtitle.configure(text=f"Ziel: {prof['target']}" if prof['target'] else "Noch kein Ziel gewählt")
        if prof.get("hdd_mode"):
            self.hdd.select()
        else:
            self.hdd.deselect()
        if prof.get("snapshots", True):
            self.snap_badge.pack_forget()
            self.desc.configure(text="Kopiert neue und geänderte Dateien ins Ziel. Überschriebene Dateien werden vorher "
                                     "als Snapshot gesichert – so lässt sich jeder Lauf wieder zurücksetzen.")
        else:
            self.snap_badge.pack(side="left")
            self.desc.configure(text="Kopiert neue und geänderte Dateien ins Ziel. Für dieses Profil sind Snapshots "
                                     "ausgeschaltet: überschriebene Dateien werden nicht aufbewahrt, ein Zurücksetzen "
                                     "ist nicht möglich.")
        self.on_sync_status()

        # Quellen
        srcs = prof["sources"]
        missing = [s for s in srcs if not os.path.exists(s)]
        dirs = sum(1 for s in srcs if os.path.isdir(s))
        if missing:
            self.stat_sources.set(str(len(srcs)), f"{len(missing)} nicht gefunden", "danger")
        else:
            self.stat_sources.set(str(len(srcs)), f"{dirs} Ordner · {len(srcs) - dirs} Dateien" if srcs else "Noch keine Quellen", "info")

        # Laufwerk
        target = prof["target"]
        if not target:
            self.stat_drive.set("–", "Kein Ziel gewählt", "muted")
        elif not utils.drive_available(target):
            self.stat_drive.set("Nicht verbunden", f"Laufwerk {utils.drive_of(target)}", "danger")
        else:
            usage = utils.disk_usage(target)
            if usage:
                free_ratio = usage.free / usage.total if usage.total else 0
                tone = "danger" if free_ratio < 0.05 else "warning" if free_ratio < 0.15 else "success"
                self.stat_drive.set(f"{utils.human_size(usage.free)} frei",
                                    f"von {utils.human_size(usage.total)} ({utils.drive_of(target)})", tone)
            else:
                self.stat_drive.set("–", "Unbekannt", "muted")
        self.refresh_snapshot_info()

    def refresh_snapshot_info(self):
        prof = self.app.current_profile()
        if not prof:
            return
        runs = self.app.snapshots.for_profile(self.app.profile_name)
        # Letztes Backup
        last = utils.parse_timestamp(prof.get("last_run"))
        if last:
            self.stat_last.set(utils.relative_time(last), last.strftime("%d.%m.%Y, %H:%M Uhr"), "primary")
        else:
            backups = [r for r in runs if r["kind"] == "backup" and r["timestamp"]]
            if backups:
                ts = backups[0]["timestamp"]
                self.stat_last.set(utils.relative_time(ts), "laut letztem Snapshot", "primary")
            else:
                self.stat_last.set("Noch nie", "Starte dein erstes Backup", "warning")

        if not self.app.snapshots.loaded:
            self.stat_snaps.set("…", "Wird geladen")
        else:
            sizes = [self.app.snapshots.info.get(r["run_id"], {}).get("size") for r in runs]
            known = sum(s for s in sizes if s)
            pending = any(s is None for s in sizes)
            sub = "Noch keine" if not runs else (f"{utils.human_size(known)}" + (" … wird berechnet" if pending else " belegt"))
            self.stat_snaps.set(str(len(runs)), sub, "success")
        self._recent_runs = runs
        self._render_recent(runs[: self._recent_capacity])

    def _on_recent_resize(self, event):
        scale = ctk.ScalingTracker.get_widget_scaling(self)
        capacity = max(1, int(event.height / scale) // 58)
        if capacity != self._recent_capacity:
            self._recent_capacity = capacity
            self._render_recent(self._recent_runs[:capacity])

    def _render_recent(self, runs):
        for w in self.recent.winfo_children():
            w.destroy()
        if not self.app.snapshots.loaded:
            W.label(self.recent, "Snapshots werden geladen …", 13, color=T.MUTED).grid(row=0, column=0, padx=8, pady=8, sticky="w")
            return
        if not runs:
            W.label(self.recent, "Noch keine Snapshots. Sie entstehen automatisch, sobald ein Backup "
                                 "Dateien ändert.", 13, color=T.MUTED, wraplength=300).grid(row=0, column=0, padx=8, pady=8, sticky="w")
            return
        for i, r in enumerate(runs):
            row = ctk.CTkFrame(self.recent, fg_color="transparent", corner_radius=10)
            row.grid(row=i, column=0, sticky="ew", pady=1)
            row.grid_columnconfigure(1, weight=1)
            tone = "info" if r["kind"] == "recovery" else "primary"
            W.IconBubble(row, "download" if r["kind"] == "recovery" else "history", tone, size=34, icon_size=16).grid(
                row=0, column=0, rowspan=2, padx=(8, 12), pady=8)
            ts = r["timestamp"]
            W.label(row, ts.strftime("%d.%m.%Y  %H:%M") if ts else r["run_id"], 13, "bold").grid(row=0, column=1, sticky="sw", pady=(8, 0))
            parts = [f"{utils.format_count(r['total'])} Dateien"]
            if r["kind"] != "backup":
                parts.insert(0, KIND_LABELS.get(r["kind"], r["kind"]))
            if ts and (datetime.now() - ts).days < 7:
                parts.insert(0, utils.relative_time(ts))
            W.label(row, " · ".join(parts), 12, color=T.MUTED).grid(row=1, column=1, sticky="nw", pady=(0, 8))
            text, tone = self.app.snapshots.status(r)
            W.Badge(row, text.split(" ·")[0], tone).grid(row=0, column=2, rowspan=2, padx=8)

            def enter(_e, f=row):
                f.configure(fg_color=T.HOVER)

            def leave(_e, f=row):
                f.configure(fg_color="transparent")

            def click(_e, rid=r["run_id"]):
                self.app.show_page("snapshots", select=rid)

            for wdg in [row] + row.winfo_children():
                wdg.bind("<Enter>", enter)
                wdg.bind("<Leave>", leave)
                wdg.bind("<Button-1>", click)
                try:
                    wdg.configure(cursor="hand2")
                except Exception:
                    pass

    def _toggle_hdd(self):
        self.app.update_profile(hdd_mode=bool(self.hdd.get()))

    # ------------------------------------------------------------------ Fortschritt
    def on_busy_changed(self, busy):
        state = "disabled" if busy else "normal"
        self.btn_backup.configure(state=state)
        self.btn_recovery.configure(state=state)
        self.btn_sync.configure(state=state)
        if busy:
            op = self.app.operation_label or OP_TITLES.get(self.app.operation, "Vorgang")
            self.state_badge.set(f"{op} läuft", "primary")
            if self.app.operation in BACKGROUND_OPS:
                return  # Löschen läuft im Hintergrund, Ergebnis des letzten Backups bleibt sichtbar
            if self.app.operation in ("backup", "recovery"):
                self.btn_cancel.pack(side="left", padx=(10, 0))
                self.btn_cancel.configure(state="normal", text="Abbrechen")
            self.hide_result()
            self._copy_started = None
            self.set_bar(0)
            self.percent.configure(text="")
            self.phase.configure(text=f"{op} wird vorbereitet …")
            self.current.configure(text="")
            for m in (self.m_files, self.m_bytes, self.m_speed, self.m_eta):
                m.set("–")
        else:
            self.state_badge.set("Bereit", "success")
            self.btn_cancel.pack_forget()
            self._set_mode("determinate")

    def on_cancel_requested(self):
        self.btn_cancel.configure(state="disabled", text="Wird abgebrochen …")

    def set_bar(self, value):
        # Bei 0 % zeichnet CTk einen Punkt – dann Fortschrittsfarbe = Hintergrund
        self.bar.configure(progress_color=T.PRIMARY if value > 0.004 else T.CARD_ALT)
        self.bar.set(value)

    def _set_mode(self, mode):
        if mode == self._mode:
            return
        self._mode = mode
        if mode == "indeterminate":
            self.bar.configure(mode="indeterminate", progress_color=T.PRIMARY)
            self.bar.start()
        else:
            self.bar.stop()
            self.bar.configure(mode="determinate")

    def update_progress(self, p):
        if p.operation in BACKGROUND_OPS:
            return
        op = self.app.operation_label or OP_TITLES.get(p.operation, "Vorgang")
        if p.phase == "scan":
            self._set_mode("indeterminate")
            self.phase.configure(text=f"{op}: Dateien werden analysiert …")
            self.percent.configure(text="")
            self.current.configure(text=elide(p.current))
            self.m_files.set(f"{utils.format_count(p.files_done)} geprüft")
            return
        self._set_mode("determinate")
        if self._copy_started is None:
            self._copy_started = time.monotonic()
        elapsed = max(0.001, time.monotonic() - self._copy_started)
        if p.bytes_total:
            frac = p.bytes_done / p.bytes_total
        else:
            frac = p.files_done / p.files_total if p.files_total else (1.0 if p.phase == "done" else 0.0)
        self.set_bar(min(1.0, frac))
        self.percent.configure(text=f"{int(frac * 100)} %")
        verb = {"rollback": "wird zurückgesetzt", "delete": "wird gelöscht"}.get(p.operation, "wird kopiert")
        self.phase.configure(text=f"{op} · {verb} …" if p.phase != "done" else f"{op} · wird abgeschlossen …")
        self.current.configure(text=elide(p.current) if p.current else "")
        self.m_files.set(f"{utils.format_count(p.files_done)} / {utils.format_count(p.files_total)}")
        if p.bytes_total:
            speed = p.bytes_done / elapsed
            self.m_bytes.set(f"{utils.human_size(p.bytes_done)} / {utils.human_size(p.bytes_total)}")
            self.m_speed.set(f"{utils.human_size(speed)}/s")
            remaining = (p.bytes_total - p.bytes_done) / speed if speed > 0 and elapsed > 1 else None
        else:
            speed = p.files_done / elapsed
            self.m_bytes.set("–")
            self.m_speed.set(f"{speed:.0f} Dateien/s".replace(".", ","))
            remaining = (p.files_total - p.files_done) / speed if speed > 0 and elapsed > 1 else None
        self.m_eta.set(utils.format_duration(remaining) if remaining is not None else "–")

    # ------------------------------------------------------------------ Ergebnis
    def hide_result(self):
        self.result.grid_forget()

    def show_result(self, kind, res):
        for w in self.result_btns.winfo_children():
            w.destroy()
        op = OP_TITLES.get(kind, "Vorgang")
        buttons = []
        if isinstance(res, Exception):
            tone, icon_name, title, text = "danger", "error", f"{op} fehlgeschlagen", str(res)
        elif isinstance(res, backup.RunResult):
            n = res.copied
            word = "gesichert" if kind == "backup" else "wiederhergestellt"
            details = f"{utils.format_count(n)} Dateien {word} · {utils.human_size(res.bytes_copied)} · Dauer {utils.format_duration(res.duration)}"
            if res.skipped_newer:
                details += f" · {utils.format_count(res.skipped_newer)} neuere Dateien behalten"
            if res.code == backup.OK:
                tone, icon_name = "success", "completed"
                title = f"{op} abgeschlossen"
                text = details if n else ("Alles aktuell – es gab keine neuen oder geänderten Dateien."
                                          if kind == "backup" else "Alles aktuell – nichts wiederherzustellen.")
            elif res.code == backup.PARTIAL:
                tone, icon_name = "warning", "warning"
                title = f"{op} mit {utils.format_count(len(res.errors))} Fehler(n) abgeschlossen"
                text = details
            elif res.code == backup.CANCELLED:
                tone, icon_name = "warning", "stop"
                title = f"{op} abgebrochen"
                text = (f"{utils.format_count(n)} Dateien wurden bereits {word} und sind im Snapshot erfasst."
                        if n else "Es wurden keine Dateien verändert.")
            else:
                tone, icon_name, title, text = "danger", "error", f"{op} nicht möglich", res.message
            if res.changed_files:
                buttons.append(("Änderungen", lambda r=res: self.app.show_changes(r)))
            if res.errors:
                buttons.append(("Fehler", lambda r=res: self.app.show_errors(r)))
        else:
            return
        fg, soft = T.TONES[tone]
        self.result.configure(fg_color=soft)
        self.result_bubble.set(icon_name, tone)
        self.result_bubble.configure(fg_color=T.CARD)
        self.result_title.configure(text=title, text_color=fg)
        self.result_text.configure(text=text)
        for text_, cb in buttons:
            W.button(self.result_btns, text_, "secondary", height=32, command=cb).pack(side="left", padx=(6, 0))
        W.button(self.result_btns, "", "ghost", "close", height=32, icon_size=12, command=self.hide_result).pack(side="left", padx=(6, 0))
        self.result.grid(row=6, column=0, sticky="ew", padx=24, pady=(0, 22))
        if kind in ("backup", "recovery"):
            self.phase.configure(text=title)
            self.current.configure(text="")
            if res is not None and isinstance(res, backup.RunResult) and res.code in (backup.OK, backup.PARTIAL):
                self.set_bar(1)
                self.percent.configure(text="100 %")
