"""Update-Prüfung über GitHub-Releases und Ein-Klick-Update.

Abgefragt wird nur die öffentliche Angabe zur neuesten Version (höchstens einmal täglich, in den Einstellungen
abschaltbar) – es werden keine Daten über den Nutzer oder seine Backups übertragen. Ein heruntergeladener Installer
wird nur gestartet, wenn seine SHA-256-Prüfsumme mit der von GitHub angegebenen übereinstimmt.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Optional

from engine import config
from engine.version import VERSION

REPO = "firo2525/backup-manager"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
CHECK_INTERVAL = 24 * 3600  # Sekunden zwischen automatischen Prüfungen
TIMEOUT = 20
_ASSET = re.compile(r"^BackupManager-Setup-[\d.]+\.exe$", re.IGNORECASE)


@dataclass
class UpdateInfo:
    version: str
    title: str
    notes: str
    page_url: str
    asset_url: Optional[str] = None
    size: int = 0
    sha256: Optional[str] = None


def parse_version(text):
    parts = tuple(int(n) for n in re.findall(r"\d+", text or "")[:4])
    return parts + (0,) * (4 - len(parts))


def is_newer(remote, local=VERSION):
    return parse_version(remote) > parse_version(local)


def can_self_update():
    """Ein-Klick-Update nur bei Installationen über den Installer – einen portablen bzw. Git-Ordner
    aktualisiert man selbst."""
    return os.name == "nt" and os.path.exists(os.path.join(config.APP_DIR, "Uninstall.exe"))


def _open(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"User-Agent": f"BackupManager/{VERSION}", "Accept": accept})
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def check():
    """Fragt die neueste Version ab. Rückgabe: UpdateInfo, wenn sie neuer ist als die installierte, sonst None.
    Wirft OSError bzw. ValueError bei Netzwerk- oder Formatfehlern."""
    with _open(API_URL) as r:
        data = json.load(r)
    tag = data.get("tag_name") or ""
    if data.get("draft") or data.get("prerelease") or not is_newer(tag):
        return None
    asset = next((a for a in data.get("assets") or [] if _ASSET.match(a.get("name") or "")), None) or {}
    digest = asset.get("digest") or ""
    return UpdateInfo(version=tag.lstrip("vV"), title=data.get("name") or tag, notes=(data.get("body") or "").strip(),
                      page_url=data.get("html_url") or RELEASES_URL, asset_url=asset.get("browser_download_url"),
                      size=int(asset.get("size") or 0),
                      sha256=digest[7:].lower() if digest.startswith("sha256:") else None)


def download(info, progress=None):
    """Lädt den Installer in den Temp-Ordner und prüft die Prüfsumme. `progress(geladen, gesamt)` wird
    zwischendurch aufgerufen. Rückgabe: Pfad der geprüften .exe."""
    if not info.asset_url or not info.sha256:
        raise ValueError("Für dieses Release fehlt der Installer oder seine Prüfsumme.")
    folder = os.path.join(tempfile.gettempdir(), "BackupManager-Update")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"BackupManager-Setup-{info.version}.exe")
    part = path + ".part"
    digest, done = hashlib.sha256(), 0
    try:
        with _open(info.asset_url, accept="application/octet-stream") as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.size or 0)
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if digest.hexdigest() != info.sha256:
            raise ValueError("Die Prüfsumme des heruntergeladenen Installers stimmt nicht – Update abgebrochen.")
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return path


def start_install(installer):
    """Startet den Installer im Update-Modus (still, Verknüpfungen bleiben wie sie sind, danach Neustart).
    Das Programm sollte sich direkt danach selbst beenden – sonst beendet der Installer es."""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([installer, "/update", f"/D={config.APP_DIR}"], close_fds=True, creationflags=flags)
