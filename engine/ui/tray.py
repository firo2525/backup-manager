"""Symbol im Infobereich der Taskleiste (unten rechts) mit Menü und Benachrichtigungen.

pystray läuft in einem eigenen Thread; alle Aktionen werden per app.post() im Tk-Haupt-Thread ausgeführt.
"""
import logging
import threading

from engine.ui.icons import app_icon_image

try:
    import pystray
except Exception:  # pragma: no cover - fehlt nur, wenn install.bat nicht gelaufen ist
    pystray = None


class TrayIcon:
    def __init__(self, app):
        self.app = app
        self.icon = None

    @property
    def available(self):
        return pystray is not None

    @property
    def running(self):
        return self.icon is not None

    def start(self):
        if not pystray or self.icon:
            return bool(self.icon)
        Item, Menu = pystray.MenuItem, pystray.Menu
        app = self.app
        menu = Menu(
            Item("Backup Manager öffnen", lambda icon, item: app.post(app.show_window), default=True),
            Item(lambda item: app.tray_status_text(), None, enabled=False),
            Menu.SEPARATOR,
            Item("Jetzt synchronisieren", lambda icon, item: app.post(app.sync_now),
                 enabled=lambda item: not app.busy),
            Item(lambda item: f"Automatisch synchronisieren (alle {app.settings['sync_interval']} Min.)",
                 lambda icon, item: app.post(app.toggle_auto_sync),
                 checked=lambda item: bool(app.settings.get("auto_sync"))),
            Menu.SEPARATOR,
            Item("Beenden", lambda icon, item: app.post(app.quit_app)),
        )
        try:
            self.icon = pystray.Icon("BackupManager", app_icon_image(64), "Backup Manager", menu)
        except Exception:
            logging.exception("Infobereich-Symbol konnte nicht erstellt werden")
            self.icon = None
            return False
        threading.Thread(target=self._run, daemon=True, name="tray").start()
        return True

    def _run(self):
        try:
            self.icon.run()
        except Exception:
            logging.exception("Infobereich-Symbol beendet")
            self.icon = None

    def set_tooltip(self, text):
        if self.icon:
            try:
                self.icon.title = text[:120]
            except Exception:
                pass

    def refresh(self):
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def notify(self, message, title="Backup Manager"):
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                logging.debug("Benachrichtigung nicht möglich", exc_info=True)

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
