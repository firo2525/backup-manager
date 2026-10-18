"""Konfiguration: Profile, App-Einstellungen sowie sources.txt/target.txt (für den Kommandozeilen-Modus).

Datenablage:
  - portabel (z. B. D:\\server\\...\\BackupManager): config/, logs/, versions/ im Programmordner
  - installiert unter C:\\Program Files: %LOCALAPPDATA%\\BackupManager (Programmordner ist schreibgeschützt)
"""
import copy
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime

APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BASE_DIR = APP_DIR  # Kompatibilität


def _is_protected_location(path):
    p = os.path.normcase(os.path.abspath(path)) + os.sep
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        root = os.environ.get(var)
        if root and p.startswith(os.path.normcase(os.path.abspath(root)) + os.sep):
            return True
    return False


def _default_data_dir():
    if os.environ.get("BACKUPMANAGER_DATA"):
        return os.path.abspath(os.environ["BACKUPMANAGER_DATA"])
    if _is_protected_location(APP_DIR):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "BackupManager")
    return APP_DIR


DATA_DIR = _default_data_dir()
INSTALLED = DATA_DIR != APP_DIR
CONFIG_DIR = os.path.join(DATA_DIR, 'config')
LOG_DIR = os.path.join(DATA_DIR, 'logs')
DEFAULT_VERSIONS_DIR = os.path.join(DATA_DIR, 'versions')
SOURCES_FILE = os.path.join(CONFIG_DIR, 'sources.txt')
TARGET_FILE = os.path.join(CONFIG_DIR, 'target.txt')
PROFILES_FILE = os.path.join(CONFIG_DIR, 'profiles.json')
SETTINGS_FILE = os.path.join(CONFIG_DIR, 'settings.json')
PROFILE_BACKUPS = 10

DEFAULT_SETTINGS = {
    "appearance": "system",     # system | light | dark
    "last_profile": None,
    "confirm_close": True,
    "workers": 8,               # parallele Kopiervorgänge (ohne HDD-Modus)
    "auto_prune": False,        # nach jedem Backup alte Snapshots löschen
    "keep_snapshots": 30,       # so viele Snapshots pro Profil behalten
    "log_keep": 500,            # so viele Logdateien behalten (ältere werden gelöscht)
    "versions_dir": None,       # eigener Snapshot-Ordner (None = Standard)
    "auto_sync": False,         # alle Profile regelmäßig automatisch sichern
    "sync_interval": 60,        # Minuten
    "last_auto_sync": None,
    "close_to_tray": False,     # Schließen-Knopf minimiert in den Infobereich
    "autostart_asked": False,   # Frage beim ersten Start schon gestellt?
    "tray_hint_shown": False,
}

DEFAULT_PROFILE = {
    "sources": [],
    "target": "",
    "hdd_mode": False,
    "excludes": [],
    "snapshots": True,          # alte Versionen vor dem Überschreiben sichern
    "auto_sync": True,          # in die automatische Synchronisierung einbeziehen
    "last_run": None,
}

SUGGESTED_EXCLUDES = [
    ".git", "__pycache__", "node_modules", ".venv", "*.tmp", "~$*", "Thumbs.db", "desktop.ini",
]


def _atomic_write_json(path, data):
    """Schreibt JSON über eine temporäre Datei, damit nie eine halbe Datei entsteht."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + '.', suffix='.tmp', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logging.warning(f"Konfigurationsdatei {os.path.basename(path)} konnte nicht gelesen werden: {e}")
        return default


# --------------------------------------------------------------------------- sources.txt / target.txt

def get_sources():
    """Liest die Quellpfade aus sources.txt."""
    if not os.path.exists(SOURCES_FILE):
        return []
    with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]


def get_target():
    """Liest den Zielpfad aus target.txt."""
    if not os.path.exists(TARGET_FILE):
        return None
    with open(TARGET_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip() or None


def save_sources(sources):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(SOURCES_FILE, 'w', encoding='utf-8') as f:
        for source in sources:
            f.write(f"{source}\n")


def save_target(target):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TARGET_FILE, 'w', encoding='utf-8') as f:
        f.write(target or '')


# --------------------------------------------------------------------------- Profile

def normalize_profile(data):
    profile = copy.deepcopy(DEFAULT_PROFILE)
    if isinstance(data, dict):
        profile.update(data)
    profile["sources"] = [str(s).strip() for s in profile.get("sources") or [] if str(s).strip()]
    profile["target"] = (profile.get("target") or "").strip()
    profile["hdd_mode"] = bool(profile.get("hdd_mode"))
    profile["snapshots"] = bool(profile.get("snapshots", True))
    profile["auto_sync"] = bool(profile.get("auto_sync", True))
    profile["excludes"] = [str(e).strip() for e in profile.get("excludes") or [] if str(e).strip()]
    if profile.get("last_run") in ("Nie", ""):
        profile["last_run"] = None
    return profile


def load_profiles():
    """Lädt alle Profile aus profiles.json (fehlende Felder werden ergänzt)."""
    data = _read_json(PROFILES_FILE, {})
    if not isinstance(data, dict):
        return {}
    return {str(name): normalize_profile(p) for name, p in data.items()}


def _backup_profiles_file():
    """Bewahrt die letzten Versionen von profiles.json in config/backups auf."""
    if not os.path.exists(PROFILES_FILE) or os.path.getsize(PROFILES_FILE) <= 2:
        return
    folder = os.path.join(CONFIG_DIR, 'backups')
    try:
        os.makedirs(folder, exist_ok=True)
        shutil.copy2(PROFILES_FILE, os.path.join(folder, f"profiles_{datetime.now():%Y%m%d_%H%M%S_%f}.json"))
        old = sorted(f for f in os.listdir(folder) if f.startswith('profiles_') and f.endswith('.json'))
        for name in old[:-PROFILE_BACKUPS]:
            os.remove(os.path.join(folder, name))
    except OSError as e:
        logging.warning(f"Sicherung der Profile fehlgeschlagen: {e}")


def save_profiles(profiles):
    _backup_profiles_file()
    _atomic_write_json(PROFILES_FILE, profiles)


def find_profile(profiles, name):
    """Sucht einen Profilnamen ohne Beachtung von Groß/Kleinschreibung; gibt den echten Schlüssel zurück."""
    if not name:
        return None
    wanted = name.strip().lower()
    for key in profiles:
        if key.strip().lower() == wanted:
            return key
    return None


def same_profile(a, b):
    return (a or '').strip().lower() == (b or '').strip().lower()


# --------------------------------------------------------------------------- Einstellungen

def load_settings():
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    data = _read_json(SETTINGS_FILE, {})
    if isinstance(data, dict):
        settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    if settings["appearance"] not in ("system", "light", "dark"):
        settings["appearance"] = "system"
    for key, lo, hi in (("workers", 1, 32), ("keep_snapshots", 1, 100000), ("sync_interval", 5, 24 * 60),
                        ("log_keep", 10, 100000)):
        try:
            settings[key] = max(lo, min(hi, int(settings[key])))
        except (TypeError, ValueError):
            settings[key] = DEFAULT_SETTINGS[key]
    return settings


def save_settings(settings):
    _atomic_write_json(SETTINGS_FILE, settings)


def versions_dir_from_settings():
    """Snapshot-Ordner laut Einstellungen (oder Standard im Datenordner)."""
    custom = _read_json(SETTINGS_FILE, {}).get("versions_dir") if os.path.exists(SETTINGS_FILE) else None
    return os.path.abspath(custom) if custom else DEFAULT_VERSIONS_DIR
