"""Snapshots: frühere Dateiversionen anzeigen, zurücksetzen, löschen und aufräumen."""
import tkinter as tk

import customtkinter as ctk

from engine import utils
from engine.ui import theme as T
from engine.ui import widgets as W

KIND_LABELS = {"backup": "Backup", "recovery": "Wiederherstellung", "pre-rollback": "Vor Rollback"}

COLUMNS = [
    ("time", "ZEITPUNKT", 150, "w", False),
    ("kind", "ART", 125, "w", False),
    ("profile", "PROFIL", 110, "w", False),
    ("files", "DATEIEN", 75, "e", False),
    ("created", "NEU", 62, "e", False),
    ("changed", "GEÄNDERT", 82, "e", False),
    ("size", "GRÖSSE", 85, "e", False),
    ("status", "STATUS", 150, "w", True),
]


class SnapshotsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._search_job = None
        self._pending_select = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = W.PageHeader(self, "Snapshots", "Vor jedem Überschreiben wird die alte Datei gesichert. "
                                                 "Jeder Lauf lässt sich einzeln zurücksetzen.", help_key="snapshots_page")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.scope = W.segmented(bar, ["Dieses Profil", "Alle Profile"], command=lambda v: self.render())
        self.scope.set("Dieses Profil")
        self.scope.pack(side="left")
        W.HelpBadge(bar, "scope").pack(side="left", padx=(8, 0))
        self.search = ctk.CTkEntry(bar, placeholder_text="Suchen (Datum, Profil, Status …)", width=280, height=36,
                                   corner_radius=10, font=T.font(13), fg_color=T.CARD, border_color=T.BORDER_STRONG,
                                   text_color=T.TEXT)
        self.search.pack(side="left", padx=12)
        self.search.bind("<KeyRelease>", lambda e: self._schedule_render())
        W.HelpBadge(bar, "prune").pack(side="right", padx=(8, 0))
        W.button(bar, "Aufräumen", "secondary", "broom", height=36, command=self.prune).pack(side="right")
        W.button(bar, "", "secondary", "refresh", height=36, command=lambda: self.app.snapshots.refresh(clear=True)).pack(side="right", padx=8)

        card = W.Card(self)
        card.grid(row=2, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)
        frame, self.tree = W.tree_with_scrollbar(card, COLUMNS, height=12)
        frame.grid(row=0, column=0, sticky="nsew", padx=2, pady=(2, 0))
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_actions())
        self.tree.bind("<Double-1>", lambda e: self.details())
        self.tree.bind("<Delete>", lambda e: self.delete())
        self.tree.bind("<Button-3>", self._context_menu)

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=16, pady=12)
        self.sel_label = W.label(actions, "", 12, color=T.MUTED)
        self.btn_delete = W.button(actions, "Löschen", "danger_soft", "delete", height=34, command=self.delete)
        self.btn_delete.pack(side="right")
        W.HelpBadge(actions, "rollback").pack(side="right", padx=(0, 8))
        self.btn_rollback = W.button(actions, "Zurücksetzen", "primary_soft", "undo", height=34, command=self.rollback)
        self.btn_rollback.pack(side="right", padx=8)
        self.btn_folder = W.button(actions, "Ordner", "secondary", "folder_open", height=34, command=self.open_folder)
        self.btn_folder.pack(side="right")
        self.btn_details = W.button(actions, "Details", "secondary", "list", height=34, command=self.details)
        self.btn_details.pack(side="right", padx=8)
        self.sel_label.pack(side="left", fill="x", expand=True)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        W.HelpBadge(foot, "snapshot_status", size=16).pack(side="left", padx=(0, 8))
        self.footer = W.label(foot, "", 12, color=T.MUTED)
        self.footer.pack(side="left", fill="x", expand=True)
        self._update_actions()

    # ------------------------------------------------------------------ Daten
    def _visible_runs(self):
        store = self.app.snapshots
        if self.scope.get() == "Dieses Profil" and self.app.profile_name:
            runs = store.for_profile(self.app.profile_name)
        else:
            runs = list(store.summaries)
        q = self.search.get().strip().lower()
        if q:
            runs = [r for r in runs if q in " ".join(str(v) for v in self._values(r)).lower()]
        return runs

    def _values(self, r):
        info = self.app.snapshots.info.get(r["run_id"])
        status, _tone = self.app.snapshots.status(r)
        ts = r["timestamp"]
        return (
            ts.strftime("%d.%m.%Y  %H:%M:%S") if ts else r["run_id"],
            KIND_LABELS.get(r["kind"], r["kind"]) + (" (abgebrochen)" if r["status"] == "cancelled" else ""),
            r["profile"] or "–",
            utils.format_count(r["total"]),
            utils.format_count(r["created"]),
            utils.format_count(r["changed"]),
            utils.human_size(info["size"]) if info else "…",
            "   " + status,
        )

    def _tags(self, r, index):
        _status, tone = self.app.snapshots.status(r)
        tags = ["odd" if index % 2 else "even"]
        if tone in ("warning", "danger") or (tone == "muted" and r["total"] == 0):
            tags.append(tone)
        return tags

    def render(self):
        selected = set(self.tree.selection())
        if self._pending_select:
            selected = {self._pending_select}
        self.tree.delete(*self.tree.get_children())
        all_profiles = self.scope.get() != "Dieses Profil" or not self.app.profile_name
        self.tree["displaycolumns"] = [c[0] for c in COLUMNS if all_profiles or c[0] != "profile"]
        runs = self._visible_runs()
        for i, r in enumerate(runs):
            self.tree.insert("", "end", iid=r["run_id"], values=self._values(r), tags=self._tags(r, i))
        keep = [s for s in selected if self.tree.exists(s)]
        if keep:
            self.tree.selection_set(keep)
            self.tree.see(keep[0])
            if self._pending_select in keep:
                self._pending_select = None
        self._update_footer(runs)
        self._update_actions()

    def _update_footer(self, runs):
        store = self.app.snapshots
        if not store.loaded:
            self.footer.configure(text="Snapshots werden geladen …")
            return
        sizes = [store.info.get(r["run_id"], {}).get("size") for r in runs]
        total = sum(s for s in sizes if s)
        pending = any(s is None for s in sizes)
        files = sum(r["total"] for r in runs)
        text = f"{utils.format_count(len(runs))} Snapshots · {utils.format_count(files)} Dateieinträge · {utils.human_size(total)}"
        if pending:
            text += " (Größe wird noch berechnet …)"
        text += "   ·   Doppelklick zeigt die Dateien, Rechtsklick öffnet das Menü"
        self.footer.configure(text=text)

    def _schedule_render(self):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(250, self.render)

    def on_show(self, select=None):
        if select:
            self._pending_select = select
            r = next((s for s in self.app.snapshots.summaries if s["run_id"] == select), None)
            if r and not self.app.snapshots.matches_profile(r, self.app.profile_name):
                self.scope.set("Alle Profile")
        self.render()

    def on_profile_changed(self):
        self.render()

    def on_snapshots_changed(self):
        if self.winfo_ismapped():
            self.render()

    def on_snapshot_info(self, run_id):
        if self.tree.exists(run_id):
            r = self.app.snapshots.get(run_id)
            if r:
                idx = self.tree.index(run_id)
                self.tree.item(run_id, values=self._values(r), tags=self._tags(r, idx))
        if self.winfo_ismapped():
            self._update_footer(self._visible_runs())

    def restyle(self):
        T.style_treeview(self.tree)
        T.tag_treeview(self.tree)

    def on_busy_changed(self, busy):
        self._update_actions()

    # ------------------------------------------------------------------ Aktionen
    def selected(self):
        return list(self.tree.selection())

    def _update_actions(self):
        sel = self.selected()
        n = len(sel)
        busy = self.app.busy
        self.sel_label.configure(text=f"{n} ausgewählt" if n else "")
        self.btn_details.configure(state="normal" if n == 1 else "disabled")
        self.btn_folder.configure(state="normal" if n == 1 else "disabled")
        self.btn_rollback.configure(state="normal" if n == 1 and not busy else "disabled")
        self.btn_delete.configure(state="normal" if n and not busy else "disabled")

    def _context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self.tree.selection():
            self.tree.selection_set(iid)
        menu = tk.Menu(self, tearoff=0, bg=T.pick(T.CARD), fg=T.pick(T.TEXT), activebackground=T.pick(T.PRIMARY_SOFT),
                       activeforeground=T.pick(T.PRIMARY_TEXT), bd=0,
                       font=(T.FAMILY, -int(13 * ctk.ScalingTracker.get_widget_scaling(self))))
        single = len(self.tree.selection()) == 1
        menu.add_command(label="Details anzeigen", command=self.details, state="normal" if single else "disabled")
        menu.add_command(label="Ordner öffnen", command=self.open_folder, state="normal" if single else "disabled")
        menu.add_separator()
        menu.add_command(label="Zurücksetzen …", command=self.rollback, state="normal" if single and not self.app.busy else "disabled")
        menu.add_command(label="Löschen …", command=self.delete, state="disabled" if self.app.busy else "normal")
        menu.tk_popup(event.x_root, event.y_root)

    def details(self):
        sel = self.selected()
        if len(sel) == 1:
            self.app.show_run_details(sel[0])

    def open_folder(self):
        sel = self.selected()
        if len(sel) == 1:
            self.app.open_run_folder(sel[0])

    def rollback(self):
        sel = self.selected()
        if len(sel) != 1:
            self.app.toast.show("Bitte genau einen Snapshot auswählen.", "info")
            return
        self.app.confirm_rollback(sel[0])

    def delete(self):
        sel = self.selected()
        if sel and not self.app.busy:
            self.app.confirm_delete_runs(sel)

    def prune(self):
        if not self.app.profile_name:
            self.app.toast.show("Bitte zuerst ein Profil wählen.", "info")
            return
        self.app.prune_dialog()
