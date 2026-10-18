"""Protokoll: Live-Log mit Filter nach Schweregrad."""
import logging
import os
from datetime import datetime

import customtkinter as ctk

from engine import backup
from engine.ui import theme as T
from engine.ui import widgets as W

MAX_LINES = 4000
FILTERS = {"Alle": logging.DEBUG, "Warnungen": logging.WARNING, "Fehler": logging.ERROR}
LEVEL_TEXT = {logging.DEBUG: "DEBUG", logging.INFO: "INFO", logging.WARNING: "WARNUNG", logging.ERROR: "FEHLER",
              logging.CRITICAL: "KRITISCH"}


class LogPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.lines = 0
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = W.PageHeader(self, "Protokoll", "Alle Vorgänge dieser Sitzung. Vollständige Logdateien liegen im "
                                                 "Ordner „logs“.", help_key="log")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.filter = W.segmented(bar, list(FILTERS), command=lambda v: self.rebuild())
        self.filter.pack(side="left")
        W.button(bar, "Log-Ordner", "secondary", "folder_open", height=36,
                 command=lambda: W.open_in_explorer(backup.LOG_DIR)).pack(side="right")
        W.button(bar, "Leeren", "secondary", "delete", height=36, command=self.clear).pack(side="right", padx=8)
        W.button(bar, "Kopieren", "secondary", "copy", height=36, command=self.copy).pack(side="right")

        card = W.Card(self)
        card.grid(row=2, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)
        self.text = ctk.CTkTextbox(card, font=T.mono(12), fg_color="transparent", text_color=T.TEXT, wrap="none",
                                   corner_radius=12, scrollbar_button_color=T.BORDER_STRONG)
        self.text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.text.configure(state="disabled")
        self.restyle()

    def restyle(self):
        self.text.tag_config("ts", foreground=T.pick(T.SUBTLE))
        self.text.tag_config("INFO", foreground=T.pick(T.INFO))
        self.text.tag_config("WARNUNG", foreground=T.pick(T.WARNING))
        self.text.tag_config("FEHLER", foreground=T.pick(T.DANGER))
        self.text.tag_config("KRITISCH", foreground=T.pick(T.DANGER))
        self.text.tag_config("msg_warn", foreground=T.pick(T.WARNING))
        self.text.tag_config("msg_err", foreground=T.pick(T.DANGER))

    def _level_min(self):
        return FILTERS.get(self.filter.get(), logging.DEBUG)

    def _insert(self, records):
        level_min = self._level_min()
        records = [r for r in records if r[1] >= level_min]
        if not records:
            return
        at_end = self.text.yview()[1] > 0.995
        self.text.configure(state="normal")
        for created, levelno, msg in records:
            lvl = LEVEL_TEXT.get(levelno, str(levelno))
            self.text.insert("end", datetime.fromtimestamp(created).strftime("%H:%M:%S  "), "ts")
            self.text.insert("end", f"{lvl:<8} ", lvl)
            tag = "msg_err" if levelno >= logging.ERROR else "msg_warn" if levelno >= logging.WARNING else None
            self.text.insert("end", msg + "\n", tag)
            self.lines += 1
        if self.lines > MAX_LINES:
            excess = self.lines - MAX_LINES
            self.text.delete("1.0", f"{excess + 1}.0")
            self.lines = MAX_LINES
        self.text.configure(state="disabled")
        if at_end:
            self.text.see("end")

    def append(self, records):
        self._insert(records)

    def rebuild(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.lines = 0
        self._insert(list(self.app.log_records)[-MAX_LINES * 2:])
        self.text.see("end")

    def clear(self):
        self.app.log_records.clear()
        self.rebuild()

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end"))
        self.app.toast.show("Protokoll in die Zwischenablage kopiert.", "success", 2000)

    def on_show(self):
        self.text.see("end")
