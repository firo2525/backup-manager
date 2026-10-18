"""Wiederverwendbare UI-Bausteine: Karten, Buttons, Badges, Toast und moderne Dialoge."""
import os
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from engine.ui import theme as T
from engine.ui.icons import icon

APP_ICON = None  # wird von der App gesetzt (Pfad zu app.ico)


# --------------------------------------------------------------------------- Grundelemente

class Card(ctk.CTkFrame):
    def __init__(self, master, **kw):
        kw.setdefault("fg_color", T.CARD)
        kw.setdefault("corner_radius", 14)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T.BORDER)
        super().__init__(master, **kw)


_BUTTON_KINDS = {
    #            fg              hover            text        border
    "primary": (T.PRIMARY, T.PRIMARY_HOVER, T.WHITE, None),
    "success": (T.SUCCESS, T.SUCCESS_HOVER, T.WHITE, None),
    "danger": (T.DANGER, T.DANGER_HOVER, T.WHITE, None),
    "secondary": (T.CARD, T.HOVER, T.TEXT, T.BORDER_STRONG),
    "ghost": ("transparent", T.HOVER, T.TEXT, None),
    "danger_soft": (T.DANGER_SOFT, ("#FAD9D9", "#3A1A1F"), T.DANGER, None),
    "primary_soft": (T.PRIMARY_SOFT, ("#E0E3FF", "#262C63"), T.PRIMARY_TEXT, None),
}


def button(master, text="", kind="secondary", icon_name=None, height=36, icon_size=16, **kw):
    fg, hover, text_color, border = _BUTTON_KINDS[kind]
    opts = dict(
        text=text, height=height, corner_radius=10, fg_color=fg, hover_color=hover,
        text_color=text_color, text_color_disabled=T.SUBTLE, font=T.font(13, "bold" if kind in ("primary", "success", "danger") else "normal"),
        border_width=1 if border else 0, border_color=border or T.BORDER,
    )
    if icon_name:
        img = icon(icon_name, icon_size, text_color)
        if img:
            opts.update(image=img, compound="left")
    if not text:
        opts["width"] = height
    opts.update(kw)
    return ctk.CTkButton(master, **opts)


def label(master, text="", size=13, weight="normal", color=T.TEXT, **kw):
    kw.setdefault("anchor", "w")
    kw.setdefault("justify", "left")
    return ctk.CTkLabel(master, text=text, font=T.font(size, weight), text_color=color, **kw)


def segmented(master, values, command=None, height=36):
    seg = ctk.CTkSegmentedButton(master, values=values, command=command, font=T.font(13), height=height,
                                 corner_radius=10, fg_color=T.CARD_ALT, selected_color=T.PRIMARY,
                                 selected_hover_color=T.PRIMARY_HOVER, unselected_color=T.CARD_ALT,
                                 unselected_hover_color=T.HOVER, text_color=T.TEXT, dynamic_resizing=True)
    seg.set(values[0])
    _fix_segment_text(seg)
    return seg


def _fix_segment_text(seg):
    """Weiße Schrift auf dem ausgewählten Segment, normale Schrift auf den anderen."""
    def update(*_):
        for value, btn in seg._buttons_dict.items():
            btn.configure(text_color=T.WHITE if value == seg.get() else T.TEXT)
    original_set = seg.set
    original_cmd = seg._command

    def set_(value, *a, **kw):
        original_set(value, *a, **kw)
        update()

    def cmd(value):
        update()
        if original_cmd:
            original_cmd(value)

    seg.set = set_
    seg.configure(command=cmd)
    update()


def autowrap(lbl, container=None, margin=0):
    """Passt den Zeilenumbruch eines Labels laufend an die Breite des Containers an."""
    container = container or lbl.master

    def on_configure(event):
        scale = ctk.ScalingTracker.get_widget_scaling(lbl)
        width = int(event.width / scale) - margin
        if width > 60 and getattr(lbl, "_wrap_width", None) != width:
            lbl._wrap_width = width
            lbl.configure(wraplength=width)

    container.bind("<Configure>", on_configure, add="+")
    return lbl


class Badge(ctk.CTkLabel):
    def __init__(self, master, text="", tone="muted", **kw):
        fg, soft = T.TONES[tone]
        super().__init__(master, text=text, font=T.font(11, "bold"), text_color=fg, fg_color=soft,
                         corner_radius=8, height=22, padx=8, **kw)

    def set(self, text, tone="muted"):
        fg, soft = T.TONES[tone]
        self.configure(text=text, text_color=fg, fg_color=soft)


class HelpBadge(ctk.CTkLabel):
    """Kleines „?“: zeigt beim Überfahren eine ausführliche Erklärung, Klick hält sie offen."""

    _open = None

    def __init__(self, master, key=None, title=None, text=None, size=18):
        from engine.ui.help import HELP
        if key:
            title, text = HELP[key]
        super().__init__(master, text="?", width=size, height=size, corner_radius=size // 2,
                         fg_color=T.PRIMARY_SOFT, text_color=T.PRIMARY_TEXT, font=T.font(11, "bold"), cursor="hand2")
        self.help_title, self.help_text = title, text
        self._tip = None
        self._show_job = None
        self._hide_job = None
        self._pinned = False
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)

    def _enter(self, _e=None):
        if self._hide_job:
            self.after_cancel(self._hide_job)
            self._hide_job = None
        if not self._tip and not self._show_job:
            self._show_job = self.after(220, self.show)

    def _leave(self, _e=None):
        if self._show_job:
            self.after_cancel(self._show_job)
            self._show_job = None
        if not self._pinned and self._tip:
            self._hide_job = self.after(150, self.hide)

    def _click(self, _e=None):
        if self._tip and self._pinned:
            self.hide()
        else:
            self._pinned = True
            self.show()

    def show(self):
        self._show_job = None
        if self._tip:
            return
        if HelpBadge._open and HelpBadge._open is not self:
            HelpBadge._open.hide()
        tip = tk.Toplevel(self)
        tip.overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tip.configure(bg=T.pick(T.BORDER_STRONG))
        box = ctk.CTkFrame(tip, fg_color=T.CARD, corner_radius=0)
        box.pack(padx=1, pady=1)
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 6))
        IconBubble(head, "info", "primary", size=26, icon_size=13).pack(side="left", padx=(0, 10))
        label(head, self.help_title or "", 14, "bold", wraplength=330).pack(side="left", fill="x")
        label(box, self.help_text or "", 12, color=T.MUTED, wraplength=380).pack(anchor="w", padx=16, pady=(0, 10))
        hint = "Klick zum Schließen" if self._pinned else "Klick aufs ? hält diese Erklärung offen"
        label(box, hint, 10, color=T.SUBTLE).pack(anchor="w", padx=16, pady=(0, 12))
        tip.update_idletasks()
        w, h = tip.winfo_reqwidth(), tip.winfo_reqheight()
        x = self.winfo_rootx() + self.winfo_width() + 8
        y = self.winfo_rooty() - 6
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if x + w > sw - 8:
            x = max(8, self.winfo_rootx() - w - 8)
        if y + h > sh - 56:
            y = max(8, sh - h - 56)
        tip.geometry(f"+{x}+{y}")
        for wdg in (tip, box):
            wdg.bind("<Button-1>", lambda e: self.hide())
        self._tip = tip
        HelpBadge._open = self

    def hide(self):
        self._pinned = False
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
        if HelpBadge._open is self:
            HelpBadge._open = None

    @classmethod
    def hide_all(cls):
        if cls._open:
            cls._open.hide()


def heading(master, text, help_key=None, size=16, weight="bold", color=T.TEXT):
    """Überschrift mit optionalem „?“-Badge. Gibt den Rahmen zurück."""
    row = ctk.CTkFrame(master, fg_color="transparent")
    label(row, text, size, weight, color=color).pack(side="left")
    if help_key:
        HelpBadge(row, help_key).pack(side="left", padx=(8, 0))
    return row


class IconBubble(ctk.CTkLabel):
    """Rundes Symbol mit getöntem Hintergrund."""

    def __init__(self, master, icon_name, tone="primary", size=40, icon_size=20):
        fg, soft = T.TONES[tone]
        super().__init__(master, text="", image=icon(icon_name, icon_size, fg), width=size, height=size,
                         fg_color=soft, corner_radius=size // 2)

    def set(self, icon_name, tone="primary", icon_size=20):
        fg, soft = T.TONES[tone]
        self.configure(image=icon(icon_name, icon_size, fg), fg_color=soft)


class StatCard(Card):
    def __init__(self, master, title, icon_name, tone="primary", help_key=None):
        super().__init__(master)
        self.icon_name = icon_name
        self.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        self.bubble = IconBubble(head, icon_name, tone, size=30, icon_size=15)
        self.bubble.pack(side="left")
        label(head, title, 12, color=T.MUTED).pack(side="left", padx=(10, 0))
        if help_key:
            HelpBadge(head, help_key, size=16).pack(side="right")
        self.value = label(self, "–", 19, "bold")
        self.value.grid(row=1, column=0, sticky="ew", padx=16)
        self.sub = label(self, "", 12, color=T.MUTED)
        self.sub.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))
        autowrap(self.sub, self, margin=32)

    def set(self, value, sub="", tone=None):
        self.value.configure(text=value)
        self.sub.configure(text=sub)
        if tone:
            self.bubble.set(self.icon_name, tone, icon_size=15)


class PageHeader(ctk.CTkFrame):
    def __init__(self, master, title, subtitle="", help_key=None):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="w")
        self.title = label(head, title, 26, "bold")
        self.title.pack(side="left")
        if help_key:
            HelpBadge(head, help_key, size=20).pack(side="left", padx=(10, 0), pady=(4, 0))
        self.subtitle = label(self, subtitle, 13, color=T.MUTED)
        self.subtitle.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.actions = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        self.actions.grid(row=0, column=1, rowspan=2, sticky="e")


class EmptyState(ctk.CTkFrame):
    def __init__(self, master, icon_name, title, text, action_text=None, action=None):
        super().__init__(master, fg_color="transparent")
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.place(relx=0.5, rely=0.45, anchor="center")
        IconBubble(inner, icon_name, "primary", size=72, icon_size=34).pack(pady=(0, 16))
        label(inner, title, 20, "bold", anchor="center", justify="center").pack()
        label(inner, text, 13, color=T.MUTED, anchor="center", justify="center", wraplength=420).pack(pady=(6, 18))
        if action_text:
            button(inner, action_text, "primary", "add", height=40, command=action).pack()


def tree_with_scrollbar(master, columns, height=10, selectmode="extended"):
    """Treeview im modernen Stil inklusive CTk-Scrollbar. Rückgabe: (frame, tree)."""
    frame = ctk.CTkFrame(master, fg_color="transparent")
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(0, weight=1)
    T.style_treeview(frame)
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height,
                        style="Modern.Treeview", selectmode=selectmode)
    scale = ctk.ScalingTracker.get_widget_scaling(frame)
    for key, title, width, anchor, stretch in columns:
        tree.heading(key, text=title, anchor=anchor)
        tree.column(key, width=int(width * scale), minwidth=int(40 * scale), anchor=anchor, stretch=stretch)
    tree.grid(row=0, column=0, sticky="nsew")
    sb = ctk.CTkScrollbar(frame, command=tree.yview, button_color=T.BORDER_STRONG, button_hover_color=T.SUBTLE)
    sb.grid(row=0, column=1, sticky="ns", padx=(4, 0))
    tree.configure(yscrollcommand=sb.set)
    T.tag_treeview(tree)
    return frame, tree


def open_in_explorer(path, select=False):
    try:
        if select and os.path.exists(path):
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            target = path if os.path.isdir(path) else os.path.dirname(path)
            os.startfile(target)  # type: ignore[attr-defined]
    except Exception:
        pass


# --------------------------------------------------------------------------- Toast

class Toast:
    """Kurze, nicht blockierende Benachrichtigung unten rechts im Fenster."""

    _ICONS = {"info": ("info", "info"), "success": ("completed", "success"),
              "warning": ("warning", "warning"), "error": ("error", "danger")}

    def __init__(self, root):
        self.root = root
        self.frame = None
        self._job = None

    def show(self, text, kind="info", duration=3500):
        self.hide()
        icon_name, tone = self._ICONS.get(kind, self._ICONS["info"])
        f = ctk.CTkFrame(self.root, fg_color=T.CARD, corner_radius=12, border_width=1, border_color=T.BORDER_STRONG)
        IconBubble(f, icon_name, tone, size=30, icon_size=15).pack(side="left", padx=(12, 10), pady=10)
        label(f, text, 13, wraplength=360).pack(side="left", padx=(0, 16), pady=10)
        f.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
        f.lift()
        self.frame = f
        self._job = self.root.after(duration, self.hide)

    def hide(self):
        if self._job:
            try:
                self.root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        if self.frame is not None:
            try:
                self.frame.destroy()
            except Exception:
                pass
            self.frame = None


# --------------------------------------------------------------------------- Dialoge

class Dialog(ctk.CTkToplevel):
    """Modaler Dialog, zentriert über dem Hauptfenster."""

    def __init__(self, master, title, width=480, resizable=False):
        super().__init__(master, fg_color=T.BG)
        self.withdraw()
        self._min_width = width
        self.title(title)
        if APP_ICON:
            # CTkToplevel setzt nach 200 ms sein eigenes Symbol – danach unseres setzen
            self.after(260, self._set_icon)
        self.resizable(resizable, resizable)
        self.transient(master.winfo_toplevel())
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=26, pady=(24, 6))
        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(fill="x", padx=26, pady=(10, 22))

    def _set_icon(self):
        try:
            self.iconbitmap(APP_ICON)
        except Exception:
            pass

    def header(self, title, text=None, icon_name="info", tone="primary"):
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=(0, 6))
        IconBubble(row, icon_name, tone, size=42, icon_size=20).pack(side="left", anchor="n", padx=(0, 14))
        col = ctk.CTkFrame(row, fg_color="transparent")
        col.pack(side="left", fill="x", expand=True)
        label(col, title, 17, "bold", wraplength=self._min_width - 120).pack(anchor="w")
        if text:
            label(col, text, 13, color=T.MUTED, wraplength=self._min_width - 120).pack(anchor="w", pady=(4, 0))
        return col

    def add_button(self, text, kind="secondary", command=None, icon_name=None):
        b = button(self.footer, text, kind, icon_name, command=command)
        b.pack(side="right", padx=(8, 0))
        return b

    def ok(self, value=True):
        self.result = value
        self._close()

    def cancel(self):
        self._close()

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def show(self, width=None, height=None):
        """Zeigt den Dialog modal an und gibt self.result zurück."""
        self.update_idletasks()
        scale = ctk.ScalingTracker.get_window_scaling(self)
        w = max(self.winfo_reqwidth(), int((width or self._min_width) * scale))
        h = max(self.winfo_reqheight(), int(height * scale) if height else 0)
        master = self.master.winfo_toplevel()
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + max(20, (master.winfo_height() - h) // 3)
        self.wm_geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        self.lift()
        self.focus_force()
        self.after(60, self._grab)
        self.wait_window()
        return self.result

    def _grab(self):
        try:
            self.grab_set()
        except tk.TclError:
            self.after(60, self._grab)


_KIND_STYLE = {
    "info": ("info", "info"), "success": ("completed", "success"), "warning": ("warning", "warning"),
    "error": ("error", "danger"), "danger": ("delete", "danger"), "question": ("info", "primary"),
}


def _details_box(parent, lines, height=150):
    box = ctk.CTkTextbox(parent, height=height, font=T.mono(12), fg_color=T.INPUT, border_width=1,
                         border_color=T.BORDER, corner_radius=10, text_color=T.MUTED, wrap="none")
    box.insert("1.0", "\n".join(lines))
    box.configure(state="disabled")
    box.pack(fill="both", expand=True, pady=(12, 0))
    return box


def info(master, title, text="", kind="info", details=None):
    dlg = Dialog(master, title)
    icon_name, tone = _KIND_STYLE[kind]
    dlg.header(title, text, icon_name, tone)
    if details:
        _details_box(dlg.body, details)
    b = dlg.add_button("OK", "primary", dlg.ok)
    dlg.bind("<Return>", lambda e: dlg.ok())
    b.focus_set()
    dlg.show()


def confirm(master, title, text="", ok_text="OK", kind="question", details=None, checkbox=None, cancel_text="Abbrechen",
            facts=None):
    """Bestätigungsdialog. Mit `checkbox` (Text) ist die Rückgabe (bestätigt, häkchen), sonst bool."""
    dlg = Dialog(master, title, width=520)
    icon_name, tone = _KIND_STYLE[kind]
    col = dlg.header(title, text, icon_name, tone)
    if facts:
        grid = ctk.CTkFrame(dlg.body, fg_color=T.CARD, corner_radius=12, border_width=1, border_color=T.BORDER)
        grid.pack(fill="x", pady=(14, 0))
        grid.grid_columnconfigure(1, weight=1)
        for i, (k, v, ftone) in enumerate(facts):
            label(grid, k, 13, color=T.MUTED).grid(row=i, column=0, sticky="w", padx=16, pady=(10 if i == 0 else 4, 10 if i == len(facts) - 1 else 4))
            fg = T.TONES[ftone][0] if ftone else T.TEXT
            label(grid, v, 13, "bold", color=fg, anchor="e").grid(row=i, column=1, sticky="e", padx=16)
    if details:
        _details_box(dlg.body, details)
    var = tk.BooleanVar(value=False)
    if checkbox:
        ctk.CTkCheckBox(dlg.body, text=checkbox, variable=var, font=T.font(13), text_color=T.TEXT,
                        fg_color=T.PRIMARY, hover_color=T.PRIMARY_HOVER, border_color=T.BORDER_STRONG,
                        corner_radius=6).pack(anchor="w", pady=(16, 0))
    ok_kind = "danger" if kind in ("danger", "error") else "primary"
    b = dlg.add_button(ok_text, ok_kind, dlg.ok)
    dlg.add_button(cancel_text, "secondary", dlg.cancel)
    dlg.bind("<Return>", lambda e: dlg.ok())
    b.focus_set()
    ok = bool(dlg.show())
    return (ok, var.get()) if checkbox else ok


def ask_string(master, title, text="", initial="", ok_text="OK", validate=None):
    """Eingabedialog. `validate(wert)` kann eine Fehlermeldung (str) zurückgeben."""
    dlg = Dialog(master, title)
    dlg.header(title, text, "add", "primary")
    var = tk.StringVar(value=initial)
    entry = ctk.CTkEntry(dlg.body, textvariable=var, height=38, corner_radius=10, font=T.font(13),
                         fg_color=T.INPUT, border_color=T.BORDER_STRONG, text_color=T.TEXT)
    entry.pack(fill="x", pady=(14, 0))
    err = label(dlg.body, "", 12, color=T.DANGER)
    err.pack(anchor="w", pady=(6, 0))

    def submit(_e=None):
        value = var.get().strip()
        msg = validate(value) if validate else (None if value else "Bitte einen Namen eingeben.")
        if msg:
            err.configure(text=msg)
            return
        dlg.ok(value)

    dlg.add_button(ok_text, "primary", submit)
    dlg.add_button("Abbrechen", "secondary", dlg.cancel)
    entry.bind("<Return>", submit)
    dlg.after(120, lambda: (entry.focus_set(), entry.select_range(0, "end")))
    return dlg.show()


# Kennzeichnung von Quellen, die gerade nicht verfügbar sind (Zustände aus utils.path_state)
PATH_BADGES = {"missing": ("Nicht gefunden", "danger"), "unreachable": ("Nicht erreichbar", "danger"),
               "pending": ("Wird geprüft …", "info")}


def ask_login(master, share, reason=None):
    """Anmeldedialog für eine Netzwerkfreigabe. Rückgabe: (benutzer, passwort, merken) oder None."""
    dlg = Dialog(master, "Am NAS anmelden", width=500)
    dlg.header("Am NAS anmelden", (reason + "\n\n" if reason else "") +
               f"Benutzer und Passwort für {share} – z. B. dein Synology- oder QNAP-Konto.", "lock", "primary")
    user_var, pw_var, remember = tk.StringVar(), tk.StringVar(), tk.BooleanVar(value=True)
    entries = []
    for text, var, show in (("Benutzername", user_var, ""), ("Passwort", pw_var, "•")):
        label(dlg.body, text, 12, color=T.MUTED).pack(anchor="w", pady=(12, 4))
        e = ctk.CTkEntry(dlg.body, textvariable=var, show=show, height=38, corner_radius=10, font=T.font(13),
                         fg_color=T.INPUT, border_color=T.BORDER_STRONG, text_color=T.TEXT)
        e.pack(fill="x")
        entries.append(e)
    ctk.CTkCheckBox(dlg.body, text="Anmeldedaten speichern (in Windows, auch für die automatische "
                                   "Synchronisierung)", variable=remember, font=T.font(12), text_color=T.TEXT,
                    fg_color=T.PRIMARY, hover_color=T.PRIMARY_HOVER, border_color=T.BORDER_STRONG,
                    corner_radius=6).pack(anchor="w", pady=(14, 0))
    err = label(dlg.body, "", 12, color=T.DANGER)
    err.pack(anchor="w", pady=(6, 0))

    def submit(_e=None):
        if not user_var.get().strip():
            err.configure(text="Bitte einen Benutzernamen eingeben.")
            return
        dlg.ok((user_var.get().strip(), pw_var.get(), bool(remember.get())))

    dlg.add_button("Anmelden", "primary", submit, "lock")
    dlg.add_button("Abbrechen", "secondary", dlg.cancel)
    for e in entries:
        e.bind("<Return>", submit)
    dlg.after(120, entries[0].focus_set)
    return dlg.show()


class ListDialog(Dialog):
    """Großer, durchsuchbarer Listen-Dialog (z. B. geänderte Dateien, Fehler, Snapshot-Inhalt)."""

    MAX_ROWS = 5000

    def __init__(self, master, title, subtitle, columns, rows, icon_name="list", tone="primary",
                 actions=None, on_double=None, row_tags=None, chips=None):
        super().__init__(master, title, width=980, resizable=True)
        self.rows = rows
        self.row_tags = row_tags
        self.minsize(720, 460)
        head = self.header(title, subtitle, icon_name, tone)
        if chips:
            chip_row = ctk.CTkFrame(head, fg_color="transparent")
            chip_row.pack(anchor="w", pady=(8, 0))
            for text, ctone in chips:
                Badge(chip_row, text, ctone).pack(side="left", padx=(0, 6))

        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.pack(fill="x", pady=(14, 8))
        self.search = ctk.CTkEntry(bar, placeholder_text="Suchen …", height=36, corner_radius=10, width=340,
                                   font=T.font(13), fg_color=T.CARD, border_color=T.BORDER_STRONG, text_color=T.TEXT)
        self.search.pack(side="left")
        self.search.bind("<KeyRelease>", lambda e: self._schedule_filter())
        self.count_label = label(bar, "", 12, color=T.MUTED)
        self.count_label.pack(side="right")
        self._filter_job = None

        card = Card(self.body)
        card.pack(fill="both", expand=True)
        frame, self.tree = tree_with_scrollbar(card, columns, height=14)
        frame.pack(fill="both", expand=True, padx=2, pady=2)
        if on_double:
            self.tree.bind("<Double-1>", lambda e: self._call(on_double))

        for text, kind, icon_name_, cb in actions or []:
            self.add_button(text, kind, lambda c=cb: self._call(c), icon_name_)
        self.add_button("Schließen", "primary", self.cancel)
        self.add_button("Liste kopieren", "ghost", self._copy, "copy")
        self._fill()

    def selected_rows(self):
        return [self.rows[int(i)] for i in self.tree.selection()]

    def _call(self, cb):
        cb(self.selected_rows(), self)

    def _schedule_filter(self):
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(200, self._fill)

    def _fill(self):
        self._filter_job = None
        self.tree.delete(*self.tree.get_children())
        q = self.search.get().strip().lower()
        shown = matched = 0
        for idx, row in enumerate(self.rows):
            if q and q not in " ".join(str(v) for v in row).lower():
                continue
            matched += 1
            if shown >= self.MAX_ROWS:
                continue
            tags = ["odd" if shown % 2 else "even"]
            if self.row_tags:
                tags.append(self.row_tags(row))
            self.tree.insert("", "end", iid=str(idx), values=row, tags=tags)
            shown += 1
        text = f"{matched:,} Einträge".replace(",", ".")
        if matched > shown:
            text += f" – {shown:,} angezeigt, Filter verwenden".replace(",", ".")
        self.count_label.configure(text=text)

    def _copy(self):
        rows = self.selected_rows() or self.rows
        self.clipboard_clear()
        self.clipboard_append("\n".join("\t".join(str(v) for v in r) for r in rows))
