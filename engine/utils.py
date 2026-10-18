"""Hilfsfunktionen: Dateivergleich, robustes Kopieren/Löschen, Pfade und Formatierung."""
import fnmatch
import os
import shutil
import stat
import sys
from datetime import datetime

# FAT/exFAT speichern Zeitstempel mit bis zu 2 s Auflösung – kleinere Abweichungen ignorieren,
# sonst würden auf solchen Laufwerken bei jedem Lauf alle Dateien erneut kopiert.
MTIME_TOLERANCE = 2.0

_LONG_PREFIX = '\\\\?\\'


# --------------------------------------------------------------------------- Pfade

def long_path(path):
    """Gibt unter Windows einen absoluten Pfad zurück, bei Bedarf mit \\\\?\\-Präfix,
    damit auch Pfade mit mehr als 260 Zeichen funktionieren."""
    if os.name != 'nt' or not path:
        return path
    p = os.path.abspath(path)
    if p.startswith(_LONG_PREFIX) or len(p) < 240:
        return p
    if p.startswith('\\\\'):
        return _LONG_PREFIX + 'UNC\\' + p[2:]
    return _LONG_PREFIX + p


def force_long_path(path):
    """Wie long_path, aber immer mit Präfix (zum rekursiven Durchlaufen tiefer Ordner)."""
    if os.name != 'nt' or not path:
        return path
    p = os.path.abspath(path)
    if p.startswith(_LONG_PREFIX):
        return p
    if p.startswith('\\\\'):
        return _LONG_PREFIX + 'UNC\\' + p[2:]
    return _LONG_PREFIX + p


def strip_long_path(path):
    if path and path.startswith(_LONG_PREFIX + 'UNC\\'):
        return '\\\\' + path[8:]
    if path and path.startswith(_LONG_PREFIX):
        return path[4:]
    return path


def norm_key(path):
    """Vergleichsschlüssel für Pfade (normalisiert, unter Windows ohne Groß/Klein)."""
    return os.path.normcase(os.path.normpath(os.path.abspath(strip_long_path(path))))


def is_subpath(child, parent):
    """True, wenn `child` gleich `parent` ist oder darin liegt."""
    try:
        c, p = norm_key(child), norm_key(parent)
        return os.path.commonpath([c, p]) == p
    except ValueError:  # verschiedene Laufwerke
        return False


def source_name(src):
    """Ordnername, unter dem eine Quelle im Ziel abgelegt wird."""
    src = os.path.normpath(src)
    name = os.path.basename(src)
    if not name:  # Laufwerkswurzel wie "D:\\"
        name = os.path.splitdrive(src)[0].replace(':', '').strip('\\/') or 'root'
    return name


def drive_of(path):
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    return drive.upper() if drive else os.sep


def disk_usage(path):
    """shutil.disk_usage für den nächsten existierenden Elternordner von `path` (oder None)."""
    p = os.path.abspath(path) if path else ''
    while p:
        if os.path.exists(p):
            try:
                return shutil.disk_usage(p)
            except OSError:
                return None
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return None


def drive_available(path):
    """Prüft, ob das Laufwerk bzw. die Freigabe eines Pfades erreichbar ist."""
    if not path:
        return False
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive:
        return True
    return os.path.exists(drive + os.sep)


# --------------------------------------------------------------------------- Dateien

def needs_copy(src_stat, dest_stat):
    """Vergleicht zwei os.stat-Ergebnisse (dest_stat=None → Ziel fehlt)."""
    if dest_stat is None:
        return True
    if src_stat.st_size != dest_stat.st_size:
        return True
    return src_stat.st_mtime - dest_stat.st_mtime > MTIME_TOLERANCE


def should_copy(src_file, dest_file):
    """True, wenn die Datei fehlt, eine andere Größe hat oder die Quelle neuer ist."""
    try:
        dest_stat = os.stat(long_path(dest_file))
    except FileNotFoundError:
        return True
    return needs_copy(os.stat(long_path(src_file)), dest_stat)


def make_writable(path):
    """Entfernt das Schreibschutz-Attribut (z. B. bei .git-Objekten), falls gesetzt."""
    try:
        mode = os.stat(path).st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(path, mode | stat.S_IWRITE)
    except (FileNotFoundError, NotADirectoryError):
        pass


def copy_file(src, dest):
    """Kopiert inkl. Zeitstempel, legt Zielordner an und überschreibt auch schreibgeschützte Ziele."""
    s, d = long_path(src), long_path(dest)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    make_writable(d)
    shutil.copy2(s, d)


def remove_file(path):
    p = long_path(path)
    make_writable(p)
    os.remove(p)


def try_remove(path):
    try:
        if path and os.path.exists(long_path(path)):
            remove_file(path)
    except OSError:
        pass


def rmtree(path):
    """shutil.rmtree, das auch schreibgeschützte Dateien entfernt."""
    def _retry_writable(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    target = force_long_path(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=_retry_writable)
    else:
        shutil.rmtree(target, onerror=_retry_writable)


def compile_excludes(patterns):
    """Erzeugt eine Funktion is_excluded(name, rel_path) aus Glob-Mustern.

    Muster ohne '/' prüfen nur den Datei-/Ordnernamen (z. B. ``.git``, ``*.tmp``),
    Muster mit '/' den Pfad relativ zur Quelle (z. B. ``logs/archive``)."""
    cleaned = []
    for p in patterns or []:
        p = (p or '').strip()
        if not p or p.startswith('#'):
            continue
        p = p.replace('\\', '/').strip('/').lower()
        if p:
            cleaned.append(p)
    name_pats = [p for p in cleaned if '/' not in p]
    path_pats = [p for p in cleaned if '/' in p]
    if not cleaned:
        return lambda name, rel: False

    def is_excluded(name, rel):
        n = name.lower()
        if any(fnmatch.fnmatchcase(n, p) for p in name_pats):
            return True
        if path_pats:
            r = rel.replace('\\', '/').lower()
            return any(fnmatch.fnmatchcase(r, p) for p in path_pats)
        return False

    return is_excluded


# --------------------------------------------------------------------------- Formatierung

def human_size(num_bytes):
    if num_bytes is None:
        return '–'
    n = float(num_bytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(n) < 1024 or unit == 'TB':
            if unit == 'B':
                return f"{int(n)} B"
            return f"{n:.1f} {unit}".replace('.', ',')
        n /= 1024
    return f"{n:.1f} TB"


def format_count(n):
    return f"{int(n):,}".replace(',', '.')


def format_duration(seconds):
    if seconds is None or seconds < 0:
        return '--:--'
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_timestamp(value):
    """Wandelt ISO-Zeitstempel oder Run-IDs (YYYYMMDD_HHMMSS[_ffffff]) in datetime um."""
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    parts = value.replace('prerollback_', '').split('_')
    if len(parts) >= 2:
        try:
            return datetime.strptime(parts[0] + parts[1][:6], '%Y%m%d%H%M%S')
        except ValueError:
            pass
    return None


def relative_time(dt, now=None):
    if not dt:
        return 'Noch nie'
    now = now or datetime.now()
    secs = (now - dt).total_seconds()
    if secs < 0:
        return dt.strftime('%d.%m.%Y %H:%M')
    if secs < 60:
        return 'Gerade eben'
    if secs < 3600:
        return f"Vor {int(secs // 60)} Min."
    if secs < 86400 and dt.date() == now.date():
        return f"Vor {int(secs // 3600)} Std."
    days = (now.date() - dt.date()).days
    if days == 1:
        return f"Gestern, {dt:%H:%M}"
    if days < 7:
        return f"Vor {days} Tagen"
    return dt.strftime('%d.%m.%Y')


def format_datetime(dt):
    return dt.strftime('%d.%m.%Y  %H:%M:%S') if dt else '–'
