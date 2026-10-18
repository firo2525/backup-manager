"""Über: Programm, Entwickler und Link zu konklave.info."""
import platform
import webbrowser
from datetime import datetime

import customtkinter as ctk

from engine import backup, versions
from engine.version import DEVELOPER, WEBSITE, WEBSITE_LABEL
from engine.ui import theme as T
from engine.ui import widgets as W
from engine.ui.icons import app_icon_image



def open_website():
    webbrowser.open(WEBSITE)


def link(master, text, command, size=13):
    """Text-Link: Akzentfarbe, beim Überfahren unterstrichen."""
    normal, hover = T.font(size, "bold"), ctk.CTkFont(family=T.FAMILY, size=size, weight="bold", underline=True)
    lbl = ctk.CTkLabel(master, text=text, font=normal, text_color=T.PRIMARY_TEXT, cursor="hand2")
    lbl.bind("<Button-1>", lambda e: command())
    lbl.bind("<Enter>", lambda e: lbl.configure(font=hover))
    lbl.bind("<Leave>", lambda e: lbl.configure(font=normal))
    return lbl


class AboutPage(ctk.CTkScrollableFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent", scrollbar_button_color=T.BORDER_STRONG,
                         scrollbar_button_hover_color=T.SUBTLE)
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        W.PageHeader(self, "Über", "Informationen zum Programm und zum Entwickler.").grid(
            row=0, column=0, sticky="ew", pady=(0, 20), padx=(0, 12))

        # --- Hauptkarte
        hero = W.Card(self)
        hero.grid(row=1, column=0, sticky="ew", padx=(0, 12))
        hero.grid_columnconfigure(1, weight=1)
        logo = ctk.CTkImage(light_image=app_icon_image(192), dark_image=app_icon_image(192), size=(92, 92))
        ctk.CTkLabel(hero, text="", image=logo).grid(row=0, column=0, rowspan=4, padx=(28, 24), pady=28, sticky="n")
        W.label(hero, app.APP_NAME, 26, "bold").grid(row=0, column=1, sticky="sw", pady=(30, 0))
        W.label(hero, f"Version {app.APP_VERSION}", 13, color=T.MUTED).grid(row=1, column=1, sticky="nw")

        dev = ctk.CTkFrame(hero, fg_color="transparent")
        dev.grid(row=2, column=1, sticky="w", pady=(14, 0))
        W.label(dev, "Entwickelt von", 14, color=T.MUTED).pack(side="left")
        W.label(dev, f" {DEVELOPER}", 14, "bold").pack(side="left")

        btns = ctk.CTkFrame(hero, fg_color="transparent")
        btns.grid(row=3, column=1, sticky="w", pady=(18, 30))
        W.button(btns, f"{WEBSITE_LABEL} besuchen", "primary", "globe", height=40, command=open_website).pack(side="left")
        W.button(btns, "Logdateien", "secondary", "folder_open", height=40,
                 command=lambda: W.open_in_explorer(backup.LOG_DIR)).pack(side="left", padx=(10, 0))

        # --- Beschreibung
        card = W.Card(self)
        card.grid(row=2, column=0, sticky="ew", pady=(16, 0), padx=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        W.label(card, "Was macht der Backup Manager?", 16, "bold").grid(row=0, column=0, sticky="w", padx=24, pady=(20, 8))
        text = W.label(card, "Er sichert deine Ordner inkrementell – nur neue und geänderte Dateien werden kopiert. "
                             "Bevor eine Datei im Ziel überschrieben wird, wird die alte Version als Snapshot "
                             "aufbewahrt. So lässt sich jeder Lauf zurücksetzen und jede ältere Dateiversion "
                             "wiederherstellen.", 13, color=T.MUTED)
        text.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 20))
        W.autowrap(text, card, margin=48)

        # --- Technik
        card = W.Card(self)
        card.grid(row=3, column=0, sticky="ew", pady=(16, 0), padx=(0, 12))
        card.grid_columnconfigure(1, weight=1)
        W.label(card, "Technische Informationen", 16, "bold").grid(row=0, column=0, columnspan=2, sticky="w",
                                                                   padx=24, pady=(20, 8))
        import customtkinter
        facts = [
            ("Python", platform.python_version()),
            ("CustomTkinter", customtkinter.__version__),
            ("Snapshots", versions.VERSIONS_DIR),
            ("Aktualisieren", "install.bat erneut ausführen"),
        ]
        for i, (k, v) in enumerate(facts, start=1):
            W.label(card, k, 13, color=T.MUTED).grid(row=i, column=0, sticky="nw", padx=(24, 20),
                                                    pady=(0, 20 if i == len(facts) else 6))
            W.label(card, v, 13).grid(row=i, column=1, sticky="nw", padx=(0, 24))

        # --- Fußzeile
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=4, column=0, pady=(22, 6))
        W.label(foot, f"© {datetime.now().year} {DEVELOPER}  ·  ", 12, color=T.SUBTLE).pack(side="left")
        link(foot, WEBSITE_LABEL, open_website, 12).pack(side="left")

    def on_show(self):
        pass
