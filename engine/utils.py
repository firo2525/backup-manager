"""Hilfsfunktionen: Dateivergleich, robustes Kopieren/Löschen, Pfade und Formatierung."""
import fnmatch
import os
import shutil
import stat
import sys
import threading
import time
from datetime import datetime

# FAT/exFAT speichern Zeitstempel mit bis zu 2 s Auflösung – kleinere Abweichungen ignorieren,
# sonst würden auf solchen Laufwerken bei jedem Lauf alle Dateien erneut kopiert.
MTIME_TOLERANCE = 2.0

_LONG_PREFIX = '\\\\?\\'

# Netzwerkfreigaben (NAS): Ist das Gerät aus, wartet Windows ~20 s, bis ein Zugriff scheitert. Die Erreichbarkeit
# wird deshalb im Hintergrund mit dem echten Windows-Zugriff geprüft (funktioniert so auch für NFS, WebDAV und
# Namen wie „DiskStation“) und kurz gemerkt. Die Oberfläche wartet höchstens UI_WAIT Sekunden auf die Antwort,
# ein Backup-Lauf bis zu NET_WAIT Sekunden – genug, damit ein NAS aus dem Ruhezustand aufwachen kann.
UI_WAIT = 1.5
NET_WAIT = 60.0
_PROBE_TTL = 15.0
_probes = {}
_probe_lock = threading.Lock()
_DRIVE_REMOTE = 4

# Win32-Fehlercodes bei Netzwerkzugriffen (Windows 11 24H2: Signierpflicht, kein Gastzugang, kein SMB1)
_LOGIN_ERRORS = {5, 86, 1244, 1272, 1326, 1327, 1331, 1909}
_LOST_ERRORS = {51, 53, 55, 59, 64, 121, 240, 1231, 1232, 1236, 2250}
_NOT_FOUND_ERRORS = {51, 53, 1231, 1232}
_BAD_SIGNATURE = 0x80090006

# Systemordner von NAS und Betriebssystemen, in die beim Sichern nie hineingegangen wird: Papierkörbe,
# Vorschaubilder und vor allem Snapshot-Ordner (#snapshot, .zfs, …), die komplette Kopien der Freigabe enthalten.
SYSTEM_DIRS = frozenset({
    '@eadir', '#recycle', '#snapshot', '@tmp', '@sharebin', '.synologyworkingdirectory', '@synologycloudsync',
    '@recycle', '@recently-snapshot', '.@__thumb', '.@__qini', '.streams', '@transcode', '.@upload_cache',
    '.zfs', '.recycle', '~snapshot', '.snapshot', '$recycle.bin', 'system volume information',
    '.appledouble', '.spotlight-v100', '.trashes', '.fseventsd',
})
SYSTEM_FILES = frozenset({'.ds_store'})


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
    if not name:  # Laufwerkswurzel wie "D:\\" oder ganze Freigabe wie "\\\\NAS\\Fotos" (→ "Fotos")
        drive = os.path.splitdrive(src)[0]
        name = drive.rstrip('\\/').rsplit('\\', 1)[-1].replace(':', '') or 'root'
    return name


def drive_of(path):
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    return drive.upper() if drive else os.sep


def disk_usage(path):
    """shutil.disk_usage für den nächsten existierenden Elternordner von `path` (oder None)."""
    if not drive_available(path):
        return None
    p = os.path.abspath(path)
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


def _mapped_unc(drive):
    """\\\\server\\freigabe hinter einem verbundenen Netzlaufwerk wie "Z:" (sonst None)."""
    if os.name != 'nt' or len(drive) != 2 or drive[1] != ':':
        return None
    import ctypes
    from ctypes import wintypes
    try:
        if ctypes.windll.kernel32.GetDriveTypeW(drive + os.sep) != _DRIVE_REMOTE:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        rc = ctypes.windll.mpr.WNetGetConnectionW(drive, buf, ctypes.byref(size))
    except (AttributeError, OSError):
        return None
    # 1201 = ERROR_CONNECTION_UNAVAIL: gespeichertes, aber gerade getrenntes Netzlaufwerk
    return buf.value if rc in (0, 1201) and buf.value.startswith('\\\\') else None


def unc_root(path):
    """\\\\server\\freigabe, wenn `path` im Netzwerk liegt (UNC-Pfad oder Netzlaufwerk), sonst None."""
    if not path:
        return None
    drive = os.path.splitdrive(os.path.abspath(strip_long_path(path)))[0]
    if drive.startswith('\\\\'):
        return drive
    return _mapped_unc(drive)


def is_network_path(path):
    return unc_root(path) is not None


def location_name(path):
    """Anzeigename für das Laufwerk bzw. die Netzwerkfreigabe eines Pfades."""
    unc = unc_root(path)
    drive = os.path.splitdrive(os.path.abspath(strip_long_path(path)))[0]
    if unc and drive.startswith('\\\\'):
        return f"Netzwerkfreigabe {unc}"
    if unc:
        return f"Netzlaufwerk {drive.upper()} ({unc})"
    return f"Laufwerk {drive_of(path)}"


def server_of(path):
    """Servername eines Netzwerkpfades („nas“ aus \\\\nas\\freigabe), sonst None."""
    unc = unc_root(path)
    return unc[2:].split('\\', 1)[0] if unc else None


def winerror(e):
    """Win32-Fehlercode einer Ausnahme (auch HRESULTs als positive Zahl) oder None."""
    code = getattr(e, 'winerror', None)
    return code & 0xFFFFFFFF if isinstance(code, int) else None


def network_error_text(e, where, host):
    """Verständliche Meldung für einen fehlgeschlagenen Zugriff auf eine Netzwerkfreigabe."""
    code = winerror(e)
    if code == 1272:
        return (f"Windows blockiert den Gastzugang ohne Passwort auf {where}. Bitte mit einem Benutzerkonto "
                f"des NAS anmelden.")
    if code == 1219:
        return (f"Windows ist mit „{host}“ bereits unter einem anderen Benutzer verbunden (z. B. über ein "
                f"Netzlaufwerk). Überall denselben Benutzer verwenden oder die andere Verbindung trennen.")
    if code in _LOGIN_ERRORS or isinstance(e, PermissionError):
        return f"Kein Zugriff auf {where} – bitte mit Benutzer und Passwort des NAS anmelden."
    if code == 67:
        return f"{where} gibt es auf „{host}“ nicht – bitte den Namen der Freigabe prüfen."
    if code == 384:
        return (f"„{host}“ beherrscht nur das veraltete SMB1, das Windows nicht mehr nutzt. Bitte die Firmware "
                f"aktualisieren und SMB2/SMB3 einschalten (FRITZ!Box: ab FRITZ!OS 7.20).")
    if code == _BAD_SIGNATURE:
        return (f"Die von Windows verlangte SMB-Signierung klappt mit „{host}“ nicht. Bitte die Firmware des "
                f"NAS aktualisieren.")
    if code in _NOT_FOUND_ERRORS:
        return (f"„{host}“ wurde im Netzwerk nicht gefunden. Ist das Gerät eingeschaltet? Sonst den Namen prüfen "
                f"oder die IP-Adresse verwenden (z. B. \\\\192.168.178.20\\Freigabe). Sehr alte Geräte, die nur "
                f"SMB1 können (z. B. FRITZ!Box vor FRITZ!OS 7.20), brauchen ein Firmware-Update.")
    if code in _LOST_ERRORS:
        return f"Die Verbindung zu {where} wurde unterbrochen."
    return f"{where} ist nicht erreichbar ({getattr(e, 'strerror', None) or e})."


class _Probe:
    __slots__ = ('started', 'finished', 'done', 'error')

    def __init__(self):
        self.started = time.monotonic()
        self.finished = 0.0
        self.done = threading.Event()
        self.error = None


def _run_probe(probe, root):
    try:
        os.stat(root)
    except OSError as e:
        probe.error = e
    probe.finished = time.monotonic()
    probe.done.set()


def _probe(root, wait):
    """Fragt die Hintergrundprüfung für `root` ab (startet sie bei Bedarf) und wartet, bis sie höchstens
    `wait` Sekunden läuft. Rückgabe: (fertig, OSError oder None)."""
    key = root.lower()
    with _probe_lock:
        probe = _probes.get(key)
        if probe is None or (probe.done.is_set() and time.monotonic() - probe.finished > _PROBE_TTL):
            probe = _probes[key] = _Probe()
            threading.Thread(target=_run_probe, args=(probe, root), name='netz-pruefung', daemon=True).start()
    probe.done.wait(max(0.0, probe.started + wait - time.monotonic()))
    return probe.done.is_set(), probe.error


def forget_network_status(path=None):
    """Verwirft gemerkte Prüfergebnisse (z. B. nach einer Anmeldung), damit neu geprüft wird."""
    with _probe_lock:
        if path is None:
            _probes.clear()
            return
        drive = os.path.splitdrive(os.path.abspath(strip_long_path(path)))[0]
        probe = _probes.get((drive + os.sep).lower())
        if probe and probe.done.is_set():
            del _probes[(drive + os.sep).lower()]


def location_status(path, wait=UI_WAIT):
    """Erreichbarkeit von Laufwerk bzw. Freigabe eines Pfades als (Zustand, Meldung).

    Zustände: 'ok' · 'pending' (Netzwerkprüfung läuft noch) · 'login' (Anmeldung am NAS nötig) · 'error'."""
    if not path:
        return 'error', "Kein Zielordner angegeben."
    drive = os.path.splitdrive(os.path.abspath(strip_long_path(path)))[0]
    if not drive:
        return 'ok', None
    where = location_name(path)
    if not unc_root(path):
        if os.path.exists(drive + os.sep):
            return 'ok', None
        return 'error', f"{where} ist nicht verbunden – bitte die Festplatte anschließen."
    finished, error = _probe(drive + os.sep, wait)
    if not finished:
        return 'pending', f"{where} antwortet nicht – ist das NAS bzw. der Server eingeschaltet und im selben Netzwerk?"
    if error is None:
        return 'ok', None
    state = 'login' if winerror(error) in _LOGIN_ERRORS or isinstance(error, PermissionError) else 'error'
    return state, network_error_text(error, where, server_of(path))


def unavailable_reason(path, wait=UI_WAIT):
    """None, wenn Laufwerk bzw. Freigabe eines Pfades erreichbar sind, sonst eine verständliche Begründung."""
    return location_status(path, wait)[1]


def drive_available(path, wait=UI_WAIT):
    """Prüft, ob das Laufwerk bzw. die Freigabe eines Pfades erreichbar ist."""
    return bool(path) and location_status(path, wait)[0] == 'ok'


def path_state(path, wait=UI_WAIT):
    """'ok', 'missing' (Laufwerk da, Pfad nicht), 'pending' (NAS-Prüfung läuft) oder 'unreachable'."""
    state = location_status(path, wait)[0]
    if state == 'ok':
        return 'ok' if os.path.exists(long_path(path)) else 'missing'
    return 'pending' if state == 'pending' else 'unreachable'


def path_exists(path, wait=UI_WAIT):
    """os.path.exists, das bei nicht erreichbarem NAS nach kurzer Zeit False liefert, statt ~20 s zu hängen."""
    return bool(path) and path_state(path, wait) == 'ok'


def is_system_dir(name):
    n = name.lower()
    return n in SYSTEM_DIRS or n.startswith('.trash-')


def is_system_file(name):
    return name.lower() in SYSTEM_FILES


def is_connection_lost(e):
    return winerror(e) in _LOST_ERRORS


def copy_error_text(e, size=0):
    """Verständliche Meldung für einen fehlgeschlagenen Kopiervorgang."""
    code = winerror(e)
    if code == 223 or (code in (39, 112) and size >= 4 * 1024 ** 3):
        return ("Datei ist größer als 4 GB – das Ziel kann so große Dateien nicht speichern (z. B. FAT32-Speicher "
                "an der FRITZ!Box). Den Datenträger mit exFAT oder NTFS formatieren.")
    if code in (39, 112):
        return "Kein Speicherplatz mehr im Ziel (oder das Kontingent auf dem NAS ist erschöpft)."
    if code in (123, 206):
        return ("Name zu lang oder mit Zeichen, die das Ziel nicht erlaubt (NAS: meist höchstens 255 Byte pro Name, "
                "verschlüsselte Synology-Ordner nur ca. 143 Zeichen).")
    if code in (32, 33):
        return "Datei wird gerade von einem anderen Programm verwendet."
    if code in _LOST_ERRORS:
        return "Netzwerkverbindung unterbrochen."
    return getattr(e, 'strerror', None) or str(e)


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
