"""Farben, Schriften und ttk-Styles der Oberfläche. Farben sind Paare (hell, dunkel)."""
import tkinter.font as tkfont
from tkinter import ttk

import customtkinter as ctk

BG = ("#F3F5FA", "#0B1020")
SIDEBAR = ("#FFFFFF", "#0F1629")
CARD = ("#FFFFFF", "#131B2E")
CARD_ALT = ("#F6F8FC", "#18223A")
INPUT = ("#F8FAFD", "#0F1729")
BORDER = ("#E4E8F0", "#222D47")
BORDER_STRONG = ("#CBD3E1", "#33405F")
HOVER = ("#EEF1F7", "#1B2541")

TEXT = ("#0F172A", "#E6EAF3")
MUTED = ("#5B6880", "#94A0B8")
SUBTLE = ("#94A0B4", "#5E6A85")

PRIMARY = ("#4F46E5", "#6366F1")
PRIMARY_HOVER = ("#4338CA", "#5458E8")
PRIMARY_SOFT = ("#EEF0FF", "#1D2350")
PRIMARY_TEXT = ("#4338CA", "#A5B4FC")

SUCCESS = ("#16A34A", "#22C55E")
SUCCESS_HOVER = ("#15803D", "#16A34A")
SUCCESS_SOFT = ("#E7F8EE", "#0F2A1E")
WARNING = ("#D97706", "#F59E0B")
WARNING_SOFT = ("#FEF5E1", "#2C2211")
DANGER = ("#DC2626", "#EF4444")
DANGER_HOVER = ("#B91C1C", "#DC2626")
DANGER_SOFT = ("#FDECEC", "#2E1519")
INFO = ("#0284C7", "#38BDF8")
INFO_SOFT = ("#E6F4FC", "#0D2433")

WHITE = ("#FFFFFF", "#FFFFFF")

TONES = {
    "primary": (PRIMARY, PRIMARY_SOFT),
    "success": (SUCCESS, SUCCESS_SOFT),
    "warning": (WARNING, WARNING_SOFT),
    "danger": (DANGER, DANGER_SOFT),
    "info": (INFO, INFO_SOFT),
    "muted": (MUTED, CARD_ALT),
}

FAMILY = "Segoe UI"
MONO = "Consolas"


def init_fonts(root):
    """Wählt die beste verfügbare Schrift (Windows 11: Segoe UI Variable)."""
    global FAMILY, MONO
    families = set(tkfont.families(root))
    for fam in ("Segoe UI Variable Text", "Segoe UI", "Helvetica Neue", "Arial"):
        if fam in families:
            FAMILY = fam
            break
    for fam in ("Cascadia Mono", "Consolas", "Courier New"):
        if fam in families:
            MONO = fam
            break


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


def mono(size=12):
    return ctk.CTkFont(family=MONO, size=size)


def is_dark():
    return ctk.get_appearance_mode() == "Dark"


def pick(color):
    """Löst ein (hell, dunkel)-Paar für den aktuellen Modus auf."""
    if isinstance(color, (tuple, list)):
        return color[1] if is_dark() else color[0]
    return color


def style_treeview(widget):
    """Modernes, flaches Aussehen für ttk.Treeview passend zum aktuellen Modus."""
    style = ttk.Style(widget)
    if style.theme_use() != "clam":
        style.theme_use("clam")
    scaling = ctk.ScalingTracker.get_widget_scaling(widget)
    bg, fg = pick(CARD), pick(TEXT)
    head_bg = pick(CARD_ALT)
    style.configure(
        "Modern.Treeview",
        background=bg, fieldbackground=bg, foreground=fg,
        rowheight=int(36 * scaling), borderwidth=0, relief="flat",
        font=(FAMILY, -int(13 * scaling)),
    )
    style.layout("Modern.Treeview", [("Modern.Treeview.treearea", {"sticky": "nswe"})])
    style.map(
        "Modern.Treeview",
        background=[("selected", pick(PRIMARY_SOFT))],
        foreground=[("selected", pick(PRIMARY_TEXT))],
    )
    style.configure(
        "Modern.Treeview.Heading",
        background=head_bg, foreground=pick(MUTED), relief="flat", borderwidth=0,
        font=(FAMILY, -int(11 * scaling), "bold"), padding=(10, int(8 * scaling)),
        bordercolor=head_bg, lightcolor=head_bg, darkcolor=head_bg,
    )
    style.map("Modern.Treeview.Heading", background=[("active", pick(HOVER))])


def tag_treeview(tree):
    tree.tag_configure("odd", background=pick(("#FAFBFE", "#151E33")))
    tree.tag_configure("even", background=pick(CARD))
    tree.tag_configure("warning", foreground=pick(WARNING))
    tree.tag_configure("danger", foreground=pick(DANGER))
    tree.tag_configure("muted", foreground=pick(MUTED))
    tree.tag_configure("success", foreground=pick(SUCCESS))
