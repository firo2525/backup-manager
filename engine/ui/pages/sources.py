"""Quellen & Ziel: was wird wohin gesichert, Ausschlüsse und HDD-Modus (alles wird automatisch gespeichert)."""
import os
import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from engine import config, utils
from engine.ui import theme as T
from engine.ui import widgets as W
from engine.ui.icons import icon


class SourceRow(ctk.CTkFrame):
    def __init__(self, master, path, on_remove):
        super().__init__(master, fg_color=T.CARD_ALT, corner_radius=10)
        self.path = path
        self.grid_columnconfigure(1, weight=1)
        self.state = utils.path_state(path)
        exists = self.state == "ok"
        is_dir = exists and os.path.isdir(path)
        tone = W.PATH_BADGES[self.state][1] if not exists else ("primary" if is_dir else "info")
        W.IconBubble(self, "folder" if is_dir or not exists else "file", tone, size=34, icon_size=16).grid(
            row=0, column=0, rowspan=2, padx=(10, 12), pady=8)
        norm = os.path.normpath(path)
        name = os.path.basename(norm) or norm
        W.label(self, name, 13, "bold").grid(row=0, column=1, sticky="sw", pady=(7, 0))
        W.label(self, os.path.dirname(norm), 11, color=T.MUTED).grid(row=1, column=1, sticky="nw", pady=(0, 7))
        if not exists:
            W.Badge(self, *W.PATH_BADGES[self.state]).grid(row=0, column=2, rowspan=2, padx=6)
        btn = W.button(self, "", "ghost", "delete", height=32, icon_size=14, command=lambda: on_remove(path))
        btn.configure(hover_color=T.DANGER_SOFT)
        btn.grid(row=0, column=3, rowspan=2, padx=(0, 8))


class SourcesPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.rows = {}
        self._exclude_job = None
        self._pending_job = None
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(1, weight=1)

        header = W.PageHeader(self, "Quellen & Ziel", "Lege fest, was gesichert wird und wohin. Änderungen werden automatisch gespeichert.")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 20))
        self._build_sources(self)
        right = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=T.BORDER_STRONG,
                                       scrollbar_button_hover_color=T.SUBTLE)
        right.grid(row=1, column=1, sticky="nsew", padx=(16, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)
        self._build_target(right)
        self._build_options(right)
        self._build_issues(right)

        self.empty = W.EmptyState(self, "folder", "Kein Profil ausgewählt",
                                  "Erstelle ein Profil, um Quellen und Ziel festzulegen.", "Profil erstellen", app.new_profile)

    # ------------------------------------------------------------------ Aufbau
    def _build_sources(self, parent):
        card = W.Card(parent)
        card.grid(row=1, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 12))
        W.heading(head, "Quellen", "sources").pack(side="left")
        self.count_badge = W.Badge(head, "0", "primary")
        self.count_badge.pack(side="left", padx=10)
        tools = ctk.CTkFrame(card, fg_color="transparent")
        tools.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        W.button(tools, "Ordner hinzufügen", "primary", "new_folder", height=36, command=self._add_folder).pack(side="left")
        W.button(tools, "Inhalt auswählen", "secondary", "list", height=36, command=self._add_folder_contents).pack(side="left", padx=8)
        W.button(tools, "Dateien", "secondary", "open_file", height=36, command=self._add_file).pack(side="left")

        self.list = ctk.CTkScrollableFrame(card, fg_color="transparent", scrollbar_button_color=T.BORDER_STRONG,
                                           scrollbar_button_hover_color=T.SUBTLE)
        self.list.grid(row=1, column=0, sticky="nsew", padx=(14, 6))
        self.list.grid_columnconfigure(0, weight=1)
        self.list_empty = W.label(self.list, "Noch keine Quellen. Füge Ordner oder Dateien hinzu, die gesichert werden sollen.",
                                  13, color=T.MUTED, wraplength=420)

        add = ctk.CTkFrame(card, fg_color="transparent")
        add.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 10))
        add.grid_columnconfigure(0, weight=1)
        self.path_entry = ctk.CTkEntry(add, placeholder_text="Pfad einfügen, z. B. D:\\Projekte oder \\\\NAS\\Fotos", height=36,
                                       corner_radius=10, font=T.font(13), fg_color=T.INPUT, border_color=T.BORDER_STRONG,
                                       text_color=T.TEXT)
        self.path_entry.grid(row=0, column=0, sticky="ew")
        self.path_entry.bind("<Return>", lambda e: self._add_typed())
        W.button(add, "Hinzufügen", "secondary", "add", height=36, command=self._add_typed).grid(row=0, column=1, padx=(8, 0))

    def _build_target(self, parent):
        card = W.Card(parent)
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        W.heading(card, "Ziel", "target").grid(row=0, column=0, sticky="w", padx=20, pady=(18, 10))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=20)
        row.grid_columnconfigure(0, weight=1)
        self.target_var = tk.StringVar()
        self.target_entry = ctk.CTkEntry(row, textvariable=self.target_var, height=36, corner_radius=10, font=T.font(13),
                                         fg_color=T.INPUT, border_color=T.BORDER_STRONG, text_color=T.TEXT)
        self.target_entry.grid(row=0, column=0, sticky="ew")
        self.target_entry.bind("<Return>", lambda e: self._commit_target())
        self.target_entry.bind("<FocusOut>", lambda e: self._commit_target())
        W.button(row, "", "secondary", "folder_open", height=36, command=self._select_target).grid(row=0, column=1, padx=(8, 0))

        self.target_status = W.autowrap(W.label(card, "", 12, color=T.MUTED), card, margin=40)
        self.target_status.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 4))
        self.usage = ctk.CTkProgressBar(card, height=6, corner_radius=3, progress_color=T.PRIMARY, fg_color=T.CARD_ALT)
        self.usage.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 18))
        self.login_btn = W.button(card, "Am NAS anmelden …", "secondary", "lock", height=32, command=self._login_target)
        self.login_btn.grid(row=4, column=0, sticky="w", padx=20, pady=(0, 18))
        self.login_btn.grid_remove()

    def _build_options(self, parent):
        card = W.Card(parent)
        card.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        card.grid_columnconfigure(0, weight=1)
        W.label(card, "Optionen", 16, "bold").grid(row=0, column=0, sticky="w", padx=20, pady=(18, 4))

        self.hdd = self._switch_row(card, 1, "HDD-Modus", "Kopiert nacheinander statt parallel – schont externe "
                                    "Festplatten.", "hdd", lambda: self.app.update_profile(hdd_mode=bool(self.hdd.get())))
        self.snaps = self._switch_row(card, 2, "Snapshots anlegen", "Alte Versionen vor dem Überschreiben aufbewahren, "
                                      "damit sich jeder Lauf zurücksetzen lässt.", "snapshots_option", self._toggle_snapshots)
        self.sync = self._switch_row(card, 3, "Automatisch synchronisieren", "Dieses Profil bei der regelmäßigen "
                                     "Synchronisierung mitsichern.", "auto_sync_profile", self._toggle_sync)

        ex_head = ctk.CTkFrame(card, fg_color="transparent")
        ex_head.grid(row=4, column=0, sticky="ew", padx=20, pady=(16, 0))
        W.heading(ex_head, "Ausschließen", "excludes", size=13).pack(side="left")
        W.button(ex_head, "Vorschläge", "ghost", "add", height=28, icon_size=12, command=self._suggest_excludes).pack(side="right")
        W.autowrap(W.label(card, "Ein Muster pro Zeile, z. B. .git, node_modules, *.tmp oder logs/archiv", 12,
                           color=T.MUTED), card, margin=40).grid(row=5, column=0, sticky="w", padx=20)
        self.excludes = ctk.CTkTextbox(card, height=96, corner_radius=10, font=T.mono(12), fg_color=T.INPUT,
                                       border_width=1, border_color=T.BORDER_STRONG, text_color=T.TEXT)
        self.excludes.grid(row=6, column=0, sticky="ew", padx=20, pady=(8, 18))
        self.excludes.bind("<KeyRelease>", lambda e: self._schedule_excludes())
        self.excludes.bind("<FocusOut>", lambda e: self._save_excludes())

    def _switch_row(self, card, row, title, text, help_key, command):
        frame = ctk.CTkFrame(card, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=20, pady=(10, 0))
        frame.grid_columnconfigure(0, weight=1)
        W.heading(frame, title, help_key, size=13).grid(row=0, column=0, sticky="w")
        W.autowrap(W.label(frame, text, 12, color=T.MUTED), frame, margin=70).grid(row=1, column=0, sticky="w")
        switch = ctk.CTkSwitch(frame, text="", width=46, command=command, progress_color=T.PRIMARY,
                               fg_color=T.BORDER_STRONG)
        switch.grid(row=0, column=1, rowspan=2, sticky="e")
        return switch

    def _toggle_snapshots(self):
        enabled = bool(self.snaps.get())
        if not enabled and not W.confirm(
                self, "Snapshots ausschalten?",
                "Ohne Snapshots werden Dateien im Ziel einfach überschrieben – die alte Version geht dabei verloren und "
                "ein Lauf kann nicht mehr zurückgesetzt werden. Vorhandene Snapshots bleiben erhalten.",
                "Ausschalten", kind="warning"):
            self.snaps.select()
            return
        self.app.update_profile(snapshots=enabled)
        self.app.toast.show("Snapshots " + ("eingeschaltet." if enabled else "ausgeschaltet – Dateien werden ohne "
                                                                          "Sicherung überschrieben."),
                            "success" if enabled else "warning")

    def _toggle_sync(self):
        self.app.update_profile(auto_sync=bool(self.sync.get()))
        self.app.broadcast("on_sync_status")

    def _build_issues(self, parent):
        self.issues = W.Card(parent)
        self.issues.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ Anzeige
    def on_show(self):
        self.refresh()

    def on_profile_changed(self):
        self.refresh()

    def refresh(self):
        prof = self.app.current_profile()
        if not prof:
            self.empty.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.empty.lift()
            return
        self.empty.place_forget()
        self.target_var.set(prof["target"])
        for switch, value in ((self.hdd, prof["hdd_mode"]), (self.snaps, prof.get("snapshots", True)),
                              (self.sync, prof.get("auto_sync", True))):
            switch.select() if value else switch.deselect()
        self.excludes.delete("1.0", "end")
        self.excludes.insert("1.0", "\n".join(prof["excludes"]))
        self._refresh_status()

    def _refresh_status(self):
        """Quellenliste, Zielanzeige und Hinweise neu aufbauen (alles, was von der Erreichbarkeit abhängt)."""
        prof = self.app.current_profile()
        if not prof:
            return
        for row in self.rows.values():
            row.destroy()
        self.rows = {}
        for p in prof["sources"]:
            self._add_row(p)
        self._update_list_state()
        self._update_target_status()
        self._update_issues()
        self._watch_pending()

    def _watch_pending(self):
        """Läuft im Hintergrund noch eine NAS-Prüfung, die Anzeige aktualisieren, sobald sie fertig ist."""
        if self._pending_job:
            return
        prof = self.app.current_profile()
        paths = [p for p in [prof["target"]] + list(prof["sources"]) if p] if prof else []
        if any(utils.location_status(p, wait=0)[0] == "pending" for p in paths):
            self._pending_job = self.after(1000, self._pending_tick)

    def _pending_tick(self):
        self._pending_job = None
        prof = self.app.current_profile()
        paths = [p for p in [prof["target"]] + list(prof["sources"]) if p] if prof else []
        if any(utils.location_status(p, wait=0)[0] == "pending" for p in paths):
            self._pending_job = self.after(1000, self._pending_tick)
        else:
            self._refresh_status()

    def _add_row(self, path):
        row = SourceRow(self.list, path, self._remove)
        row.grid(row=len(self.rows) + 1, column=0, sticky="ew", pady=3, padx=(0, 6))
        self.rows[path] = row

    def _update_list_state(self):
        n = len(self.rows)
        self.count_badge.set(str(n), "primary")
        if n:
            self.list_empty.grid_forget()
        else:
            self.list_empty.grid(row=0, column=0, sticky="w", padx=6, pady=10)

    def _update_target_status(self):
        target = self.app.current_profile()["target"]
        if not target:
            self.target_status.configure(text="Bitte einen Zielordner wählen – auch ein Netzwerkpfad wie "
                                              "\\\\NAS\\Backup ist möglich.", text_color=T.WARNING)
            self.usage.set(0)
            return
        state, problem = utils.location_status(target)
        self.login_btn.grid_remove()
        if problem:
            self.target_status.configure(text=problem, text_color=T.MUTED if state == "pending" else T.DANGER)
            self.usage.set(0)
            if state == "login":
                self.login_btn.grid()
            return
        usage = utils.disk_usage(target)
        exists = os.path.isdir(target)
        if usage:
            used = 1 - usage.free / usage.total if usage.total else 0
            self.usage.set(used)
            self.usage.configure(progress_color=T.DANGER if used > 0.95 else T.WARNING if used > 0.85 else T.PRIMARY)
            text = f"{utils.human_size(usage.free)} frei von {utils.human_size(usage.total)}"
            if utils.is_network_path(target):
                text += f" · {utils.location_name(target)}"
            if not exists:
                text += " · Ordner wird beim ersten Backup angelegt"
            self.target_status.configure(text=text, text_color=T.MUTED)

    def _update_issues(self):
        for w in self.issues.winfo_children():
            w.destroy()
        issues = self.app.profile_issues(self.app.current_profile())
        if not issues:
            self.issues.grid_forget()
            return
        W.heading(self.issues, "Hinweise", "issues").grid(row=0, column=0, sticky="w", padx=20, pady=(18, 6))
        icons_ = {"danger": "error", "warning": "warning", "info": "info"}
        for i, (tone, text) in enumerate(issues, start=1):
            row = ctk.CTkFrame(self.issues, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=16, pady=(0, 18 if i == len(issues) else 6))
            W.IconBubble(row, icons_[tone], tone, size=28, icon_size=14).pack(side="left", anchor="n", padx=(4, 10))
            W.autowrap(W.label(row, text, 12, color=T.TEXT), row, margin=50).pack(side="left", fill="x", expand=True)
        self.issues.grid(row=2, column=0, sticky="new", pady=(16, 0))

    # ------------------------------------------------------------------ Quellen bearbeiten
    def _sources(self):
        return list(self.app.current_profile()["sources"])

    def add_paths(self, paths):
        sources = self._sources()
        known = {utils.norm_key(s) for s in sources}
        added = 0
        for p in paths:
            p = os.path.normpath(p.strip().strip('"'))
            if not p or utils.norm_key(p) in known:
                continue
            sources.append(p)
            known.add(utils.norm_key(p))
            self._add_row(p)
            added += 1
        if added:
            self.app.update_profile(sources=sources)
            self._update_list_state()
            self._update_issues()
            self._watch_pending()
            self.app.toast.show(f"{added} Quelle(n) hinzugefügt.", "success")
        elif paths:
            self.app.toast.show("Diese Quelle ist bereits vorhanden.", "info")
        return added

    def _remove(self, path):
        sources = [s for s in self._sources() if s != path]
        self.app.update_profile(sources=sources)
        row = self.rows.pop(path, None)
        if row:
            row.destroy()
        for i, r in enumerate(self.rows.values(), start=1):
            r.grid(row=i)
        self._update_list_state()
        self._update_issues()

    def _add_folder(self):
        path = filedialog.askdirectory(parent=self, title="Ordner zum Sichern auswählen")
        if path:
            self.add_paths([path])

    def _add_file(self):
        paths = filedialog.askopenfilenames(parent=self, title="Dateien zum Sichern auswählen")
        if paths:
            self.add_paths(list(paths))

    def _add_typed(self):
        path = self.path_entry.get().strip().strip('"')
        if not path:
            return
        state, problem = utils.location_status(path)
        if state == "login" and not self.app.network_login(path, problem):
            return
        if not utils.path_exists(path):
            W.info(self, "Pfad nicht gefunden", utils.unavailable_reason(path)
                   or f"„{path}“ existiert nicht oder ist nicht erreichbar.", "warning")
            return
        if self.add_paths([path]):
            self.path_entry.delete(0, "end")

    def _add_folder_contents(self):
        folder = filedialog.askdirectory(parent=self, title="Ordner auswählen, dessen Inhalt du einzeln wählen möchtest")
        if not folder:
            return
        try:
            entries = sorted(os.listdir(folder), key=lambda x: (not os.path.isdir(os.path.join(folder, x)), x.lower()))
        except OSError as e:
            W.info(self, "Ordner nicht lesbar", str(e), "error")
            return
        if not entries:
            W.info(self, "Ordner ist leer", folder, "info")
            return
        dlg = W.Dialog(self, "Inhalt auswählen", width=600, resizable=True)
        dlg.header("Inhalt auswählen", folder, "list", "primary")
        bar = ctk.CTkFrame(dlg.body, fg_color="transparent")
        bar.pack(fill="x", pady=(12, 6))
        lst = ctk.CTkScrollableFrame(dlg.body, height=320, fg_color=T.CARD, corner_radius=12, border_width=1,
                                     border_color=T.BORDER)
        lst.pack(fill="both", expand=True)
        vars_ = []
        for name in entries:
            full = os.path.join(folder, name)
            v = tk.BooleanVar(value=False)
            is_dir = os.path.isdir(full)
            line = ctk.CTkFrame(lst, fg_color="transparent")
            line.pack(fill="x", padx=10, pady=3)
            ctk.CTkCheckBox(line, text="", width=24, variable=v, fg_color=T.PRIMARY, hover_color=T.PRIMARY_HOVER,
                            border_color=T.BORDER_STRONG, corner_radius=6).pack(side="left")
            ctk.CTkLabel(line, text="  " + name, image=icon("folder" if is_dir else "file", 16,
                                                             T.PRIMARY if is_dir else T.MUTED),
                         compound="left", font=T.font(13), text_color=T.TEXT, anchor="w").pack(side="left")
            vars_.append((v, full))
        W.button(bar, "Alle", "secondary", "check", height=30, command=lambda: [v.set(True) for v, _ in vars_]).pack(side="left")
        W.button(bar, "Keine", "secondary", height=30, command=lambda: [v.set(False) for v, _ in vars_]).pack(side="left", padx=6)
        dlg.add_button("Hinzufügen", "primary", lambda: dlg.ok([p for v, p in vars_ if v.get()]), "add")
        dlg.add_button("Abbrechen", "secondary", dlg.cancel)
        chosen = dlg.show(height=560)
        if chosen:
            self.add_paths(chosen)

    # ------------------------------------------------------------------ Ziel & Optionen
    def _select_target(self):
        path = filedialog.askdirectory(parent=self, title="Zielordner für das Backup auswählen")
        if path:
            self.target_var.set(os.path.normpath(path))
            self._commit_target()

    def _login_target(self):
        target = self.app.current_profile()["target"]
        self.app.network_login(target, utils.unavailable_reason(target))

    def _commit_target(self):
        if not self.app.current_profile():
            return
        value = self.target_var.get().strip().strip('"')
        value = os.path.normpath(value) if value else ""
        if value != self.app.current_profile()["target"]:
            self.app.update_profile(target=value)
            self.app.toast.show("Ziel gespeichert.", "success", 2000)
        self._update_target_status()
        self._update_issues()
        self._watch_pending()

    def _schedule_excludes(self):
        if self._exclude_job:
            self.after_cancel(self._exclude_job)
        self._exclude_job = self.after(900, self._save_excludes)

    def _save_excludes(self):
        self._exclude_job = None
        prof = self.app.current_profile()
        if not prof:
            return
        lines = [ln.strip() for ln in self.excludes.get("1.0", "end").splitlines() if ln.strip()]
        if lines != prof["excludes"]:
            self.app.update_profile(excludes=lines)

    def _suggest_excludes(self):
        current = [ln.strip() for ln in self.excludes.get("1.0", "end").splitlines() if ln.strip()]
        merged = current + [s for s in config.SUGGESTED_EXCLUDES if s not in current]
        self.excludes.delete("1.0", "end")
        self.excludes.insert("1.0", "\n".join(merged))
        self._save_excludes()
