"""Backup- und Recovery-Logik (unabhängig von der GUI, auch per Kommandozeile nutzbar).

Ablauf: 1) Analyse – alle Quelldateien mit dem Ziel vergleichen, 2) Speicherplatz prüfen,
3) Kopieren – vor dem Überschreiben wird die alte Zieldatei als Snapshot gesichert.
"""
import argparse
import logging
import os
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from datetime import datetime
from itertools import islice
from typing import Optional

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from engine import config, versions  # noqa: E402
from engine.utils import (MTIME_TOLERANCE, NET_WAIT, copy_file, disk_usage, drive_of,  # noqa: E402
                          compile_excludes, copy_error_text, force_long_path, human_size, is_connection_lost,
                          is_network_path, is_system_dir, is_system_file, location_name, location_status,
                          needs_copy, long_path, norm_key, source_name, try_remove, format_duration)

LOG_DIR = config.LOG_DIR
APP_VENV_DIR = os.path.join(config.APP_DIR, '.venv')

# Exit-Codes
OK, FAILED, CANCELLED, PARTIAL = 0, 1, 2, 3

SPACE_MARGIN = 64 * 1024 * 1024  # Sicherheitsreserve beim Speicherplatz-Check
_PROBE_MTIME = 1577880000.0       # 01.01.2020 – Testzeitstempel für den Schreibtest auf Netzwerkzielen

_cancel = threading.Event()
_abort = threading.Event()        # Netzwerkverbindung verloren → Lauf beenden statt jede Datei scheitern zu lassen


def set_cancel_flag(value):
    if value:
        _cancel.set()
    else:
        _cancel.clear()


def get_cancel_flag():
    return _cancel.is_set()


# --------------------------------------------------------------------------- Logging

def setup_logging(extra_handler=None, console=True, keep_files=None):
    """Richtet Logging in eine neue Datei unter logs/ ein (plus optional GUI-Handler)."""
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, f"backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log")
    root_logger = logging.getLogger()
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handlers: list = [logging.FileHandler(log_file, encoding='utf-8', delay=True)]
    if console and sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    for h in handlers:
        h.setFormatter(formatter)
        root_logger.addHandler(h)
    if extra_handler:
        root_logger.addHandler(extra_handler)
    root_logger.setLevel(logging.INFO)
    if keep_files:
        prune_logs(keep_files)
    return log_file


def prune_logs(keep):
    """Behält nur die neuesten `keep` Logdateien."""
    try:
        logs = sorted(f for f in os.listdir(LOG_DIR) if f.startswith('backup_') and f.endswith('.log'))
    except OSError:
        return
    for name in logs[:-keep] if keep and len(logs) > keep else []:
        try_remove(os.path.join(LOG_DIR, name))


# --------------------------------------------------------------------------- Datenklassen

@dataclass
class Progress:
    operation: str = 'backup'          # backup | recovery | rollback | delete
    phase: str = 'scan'                # scan | copy | done
    files_done: int = 0
    files_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    current: str = ''
    copied: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass
class RunResult:
    code: int
    changed_files: list = field(default_factory=list)   # (quelle, ziel, neu_angelegt)
    errors: list = field(default_factory=list)          # (pfad, meldung)
    copied: int = 0
    skipped: int = 0
    skipped_newer: int = 0
    bytes_copied: int = 0
    run_id: Optional[str] = None
    duration: float = 0.0
    message: str = ''
    operation: str = 'backup'

    def __iter__(self):
        # Kompatibilität: code, changed_files = run_backup()
        return iter((self.code, self.changed_files))


@dataclass
class _Job:
    src: str
    dest: str
    size: int
    exists: bool
    dest_size: int
    snap_rel: str
    dest_mtime: float = 0.0


class _Reporter:
    """Leitet Fortschritt gedrosselt (max. ~10x pro Sekunde) an die GUI weiter."""

    def __init__(self, callback, interval=0.1):
        self.callback = callback
        self.interval = interval
        self._last = 0.0

    def __call__(self, progress, force=False):
        if not self.callback:
            return
        now = time.monotonic()
        if force or now - self._last >= self.interval:
            self._last = now
            try:
                self.callback(replace(progress))
            except Exception:
                pass


# --------------------------------------------------------------------------- Analyse

def _walk_files(root_dir, is_excluded, skip_keys, on_error, system_skipped=None):
    """Liefert (voller_pfad, relativer_pfad, stat) aller Dateien unterhalb von root_dir.

    Größe und Änderungszeit kommen direkt aus dem Verzeichnis-Listing (os.scandir) – ohne eigene Anfrage pro
    Datei, was über das Netzwerk um ein Vielfaches schneller ist. Systemordner von NAS (#snapshot, @eaDir, …)
    werden nie betreten; gezählt werden sie in `system_skipped` (Name → Anzahl)."""
    stack = ['']
    while stack:
        if _cancel.is_set():
            return
        rel_dir = stack.pop()
        current = os.path.join(root_dir, rel_dir) if rel_dir else root_dir
        try:
            with os.scandir(force_long_path(current)) as it:
                entries = list(it)
        except OSError as err:
            on_error(current, err)
            continue
        subdirs = []
        for entry in entries:
            name = entry.name
            rel = os.path.join(rel_dir, name) if rel_dir else name
            try:
                is_dir = entry.is_dir()
            except OSError:
                is_dir = False
            if is_dir:
                if is_system_dir(name):
                    if system_skipped is not None:
                        system_skipped[name] = system_skipped.get(name, 0) + 1
                    continue
                if is_excluded(name, rel):
                    continue
                if skip_keys and norm_key(os.path.join(current, name)) in skip_keys:
                    logging.info(f"Übersprungen (Programm-/Zielordner): {os.path.join(current, name)}")
                    continue
                if not entry.is_symlink():
                    subdirs.append(rel)
                continue
            if is_system_file(name) or is_excluded(name, rel):
                continue
            try:
                st = entry.stat()
            except OSError:
                st = None  # _make_job meldet den Fehler
            yield os.path.join(root_dir, rel), rel, st
        stack.extend(reversed(subdirs))


def _log_system_skipped(system_skipped):
    if system_skipped:
        names = ", ".join(f"{n} ({c}×)" if c > 1 else n for n, c in sorted(system_skipped.items()))
        logging.info(f"Systemordner von NAS/Windows übersprungen: {names}")


class _DirIndex:
    """Liest jeden Zielordner einmal komplett ein, statt jede Datei einzeln abzufragen (wichtig bei NAS-Zielen).
    Die Analyse geht Ordner für Ordner vor, daher genügt es, sich den zuletzt gelesenen Ordner zu merken."""

    def __init__(self):
        self._dir = None
        self._entries = {}

    def stat(self, path):
        folder, name = os.path.split(path)
        if folder != self._dir:
            self._dir, self._entries = folder, {}
            try:
                with os.scandir(long_path(folder)) as it:
                    self._entries = {e.name.lower(): e for e in it}
            except OSError:
                pass  # Ordner fehlt im Ziel → alles darin ist neu
        entry = self._entries.get(name.lower())
        if entry is None:
            return None
        try:
            return entry.stat()
        except OSError:
            return None


def _make_job(src_file, dest_file, snap_rel, errors, mode='backup', overwrite_newer=False, src_stat=None,
              dest_index=None):
    """Vergleicht Quelle und Ziel. Rückgabe: _Job, 'skip', 'newer' oder None (Fehler)."""
    s = src_stat
    if s is None:
        try:
            s = os.stat(long_path(src_file))
        except OSError as e:
            errors.append((src_file, f"Nicht lesbar: {e.strerror or e}"))
            return None
    if dest_index is not None:
        d = dest_index.stat(dest_file)
    else:
        try:
            d = os.stat(long_path(dest_file))
        except OSError:
            d = None
    if mode == 'recovery' and d is not None:
        same = s.st_size == d.st_size and abs(s.st_mtime - d.st_mtime) <= MTIME_TOLERANCE
        if same:
            return 'skip'
        if not overwrite_newer and d.st_mtime - s.st_mtime > MTIME_TOLERANCE:
            return 'newer'
    elif not needs_copy(s, d):
        return 'skip'
    return _Job(src_file, dest_file, s.st_size, d is not None, d.st_size if d else 0, snap_rel,
                d.st_mtime if d else 0.0)


def _check_space(jobs, target, snapshots=True):
    """Prüft freien Speicher für neue Daten (Ziel) und Snapshots (versions-Ordner)."""
    need_target = sum(max(0, j.size - j.dest_size) for j in jobs)
    need_snap = sum(j.dest_size for j in jobs if j.exists) if snapshots else 0
    checks = {}
    t_drive, v_drive = drive_of(target), drive_of(versions.VERSIONS_DIR)
    checks[t_drive] = checks.get(t_drive, 0) + need_target
    checks[v_drive] = checks.get(v_drive, 0) + need_snap
    for drive, need in checks.items():
        if need <= 0:
            continue
        path = target if drive == t_drive else versions.VERSIONS_DIR
        usage = disk_usage(path)
        if usage and usage.free < need + SPACE_MARGIN:
            return (f"Nicht genügend Speicherplatz auf {drive}: benötigt {human_size(need)}, "
                    f"frei {human_size(usage.free)}.")
    return None


# --------------------------------------------------------------------------- Kopieren

class _NoSnapshots:
    """Ersatz für RunRecorder, wenn ein Profil ohne Snapshots arbeitet (es entsteht kein Run)."""
    with_snapshots = False
    run_id = None
    count = 0

    def add(self, *args, **kwargs):
        pass

    def finalize(self, *args, **kwargs):
        return False


def _dest_unchanged(job):
    """True, wenn die Zieldatei noch genau so da ist wie vor dem Kopierversuch."""
    try:
        d = os.stat(long_path(job.dest))
    except OSError:
        return False
    return d.st_size == job.dest_size and abs(d.st_mtime - job.dest_mtime) <= 1.0


def _process_job(job, recorder):
    if _cancel.is_set() or _abort.is_set():
        return 'cancelled', job, None
    snapshot = None
    if job.exists and recorder.with_snapshots:
        snapshot = recorder.snapshot_path(job.snap_rel)
        try:
            copy_file(job.dest, snapshot)
        except Exception as e:
            # Ohne Sicherungskopie wird nicht überschrieben – so geht keine Version verloren.
            logging.error(f"Snapshot fehlgeschlagen, Datei bleibt unverändert: {job.dest}: {e}")
            try_remove(snapshot)
            return 'error', job, f"Snapshot fehlgeschlagen: {e}"
    try:
        copy_file(job.src, job.dest)
    except Exception as e:
        logging.error(f"Fehler beim Kopieren von {job.src} -> {job.dest}: {e}")
        lost = is_connection_lost(e)
        if lost and not _abort.is_set():
            _abort.set()
            logging.error("Netzwerkverbindung unterbrochen – der Lauf wird beendet.")
        if snapshot:
            # Ein abgebrochener Kopiervorgang kann die alte Zieldatei schon gekürzt oder gelöscht haben
            # (z. B. 4-GB-Grenze von FAT32, Verbindungsabbruch). Dann bleibt der Snapshot erhalten und wird
            # im Lauf vermerkt, damit „Zurücksetzen“ die alte Version wiederherstellt.
            if not lost and _dest_unchanged(job):
                try_remove(snapshot)
            else:
                recorder.add(job.src, job.dest, snapshot, created=False, size=job.dest_size)
                logging.warning(f"Alte Version bleibt im Snapshot erhalten: {job.dest}")
        return 'error', job, copy_error_text(e, job.size)
    recorder.add(job.src, job.dest, snapshot, created=not job.exists, size=job.dest_size if snapshot else None)
    return 'copied', job, None


def _execute(jobs, recorder, workers, progress, report, result):
    """Kopiert alle Jobs. Rückgabe: True, wenn wegen verlorener Netzwerkverbindung abgebrochen wurde."""
    _abort.clear()
    progress.phase = 'copy'
    progress.files_done = 0
    progress.files_total = len(jobs)
    progress.bytes_total = sum(j.size for j in jobs)
    report(progress, force=True)

    def handle(outcome):
        status, job, err = outcome
        if status == 'cancelled':
            return
        progress.files_done += 1
        progress.bytes_done += job.size
        progress.current = job.src
        if status == 'copied':
            progress.copied += 1
            result.copied += 1
            result.bytes_copied += job.size
            result.changed_files.append((job.src, job.dest, not job.exists))
        else:
            progress.errors += 1
            result.errors.append((job.src, err))
        report(progress)

    if workers <= 1:
        for job in jobs:
            if _cancel.is_set() or _abort.is_set():
                break
            progress.current = job.src
            handle(_process_job(job, recorder))
        return _abort.is_set()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        it = iter(jobs)
        pending = {ex.submit(_process_job, j, recorder) for j in islice(it, workers * 4)}
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                handle(fut.result())
            if not _cancel.is_set() and not _abort.is_set():
                pending |= {ex.submit(_process_job, j, recorder) for j in islice(it, len(done))}
    return _abort.is_set()


def _wait_for(path, progress=None, report=None):
    """Prüft Laufwerk bzw. Freigabe; ein NAS bekommt bis zu NET_WAIT Sekunden, um zu antworten
    (z. B. beim Aufwachen aus dem Ruhezustand). Rückgabe: Fehlermeldung oder None."""
    state, message = location_status(path, wait=0.5)
    if state == 'pending':
        logging.info(f"Warte auf {location_name(path)} …")
        if progress is not None and report is not None:
            progress.current = f"Warte auf {location_name(path)} …"
            report(progress, force=True)
        state, message = location_status(path, wait=NET_WAIT)
    return None if state == 'ok' else message


def _probe_target(target):
    """Schreibtest auf Netzwerkzielen: deckt fehlende Schreibrechte vor dem ersten Kopieren auf und prüft, ob das
    NAS Änderungszeiten übernimmt. Rückgabe: Fehlermeldung oder None."""
    probe = os.path.join(target, f".backupmanager-test-{os.getpid()}.tmp")
    p = long_path(probe)
    try:
        with open(p, 'wb') as f:
            f.write(b'Backup Manager - Schreibtest')
        os.utime(p, (_PROBE_MTIME, _PROBE_MTIME))
        delta = os.stat(p).st_mtime - _PROBE_MTIME
    except OSError as e:
        try_remove(probe)
        return f"Im Ziel kann nicht geschrieben werden ({copy_error_text(e)}). Hat der NAS-Benutzer Schreibrechte?"
    try_remove(probe)
    if abs(delta) > MTIME_TOLERANCE:
        logging.warning(f"Das Ziel übernimmt Änderungszeiten nicht genau (Abweichung {delta:+.0f} s). Geänderte "
                        f"Dateien werden trotzdem erkannt, sobald sich ihre Größe ändert oder sie neuer sind.")
    return None


def _prepare_target(target, progress=None, report=None):
    if not target:
        return "Kein Zielordner angegeben."
    problem = _wait_for(target, progress, report)
    if problem:
        return problem
    try:
        os.makedirs(long_path(target), exist_ok=True)
    except OSError as e:
        return f"Zielordner kann nicht angelegt werden: {copy_error_text(e)}"
    if is_network_path(target):
        return _probe_target(target)
    return None


def _finish(result, recorder, progress, report, started, cancelled, label, connection_lost=False):
    result.duration = time.monotonic() - started
    stats = {"copied": result.copied, "errors": len(result.errors), "skipped": result.skipped,
             "bytes": result.bytes_copied, "duration": round(result.duration, 1)}
    if recorder.finalize(status='cancelled' if cancelled else 'complete', stats=stats):
        result.run_id = recorder.run_id
    if cancelled:
        result.code = CANCELLED
        result.message = f"{label} abgebrochen."
    elif connection_lost:
        result.code = PARTIAL if result.copied else FAILED
        result.message = (f"Netzwerkverbindung unterbrochen – {label} nach {result.copied} Datei(en) beendet. "
                          f"Beim nächsten Lauf geht es an dieser Stelle weiter.")
    elif result.errors:
        result.code = PARTIAL
        result.message = f"{label} mit {len(result.errors)} Fehler(n) abgeschlossen."
    else:
        result.code = OK
        result.message = f"{label} erfolgreich abgeschlossen."
    progress.phase = 'done'
    report(progress, force=True)
    logging.info(f"{result.message} Kopiert: {result.copied} ({human_size(result.bytes_copied)}), "
                 f"unverändert: {result.skipped}, Fehler: {len(result.errors)}, Dauer: {format_duration(result.duration)}")
    return result


# --------------------------------------------------------------------------- Backup

def run_backup(progress_callback=None, profile=None, hdd_mode: bool = False, sources=None, target=None,
               excludes=None, workers: int = 8, snapshots: bool = True):
    """Sichert alle Quellen ins Ziel. Ohne `sources`/`target` werden sources.txt/target.txt verwendet.
    snapshots=False: Dateien werden ohne Sicherung der alten Version überschrieben (kein Rollback möglich).
    Rückgabe: RunResult (entpackbar als `code, changed_files`)."""
    started = time.monotonic()
    set_cancel_flag(False)
    sources = list(sources) if sources is not None else config.get_sources()
    target = target if target is not None else config.get_target()
    result = RunResult(code=FAILED, operation='backup')
    progress = Progress(operation='backup')
    report = _Reporter(progress_callback)
    logging.info(f"Backup gestartet{f' (Profil: {profile})' if profile else ''} → {target}")

    if not sources:
        result.message = "Keine Quellen angegeben."
        logging.error(result.message)
        return result
    error = _prepare_target(target, progress, report)
    if error:
        result.message = error
        logging.error(error)
        return result

    target = os.path.normpath(str(target))
    is_excluded = compile_excludes(excludes)
    skip_keys = {norm_key(p) for p in (versions.VERSIONS_DIR, APP_VENV_DIR, target)}
    used_names = {}
    jobs = []
    system_skipped = {}

    def on_walk_error(path, err):
        result.errors.append((path, f"Ordner nicht lesbar: {getattr(err, 'strerror', None) or err}"))
        logging.warning(f"Ordner nicht lesbar: {path}: {err}")

    for src in sources:
        if _cancel.is_set():
            break
        src_n = os.path.normpath(src)
        name = source_name(src_n)
        if name.lower() in used_names and norm_key(used_names[name.lower()]) != norm_key(src_n):
            logging.warning(f"Achtung: '{src_n}' und '{used_names[name.lower()]}' landen im selben Zielordner '{name}'.")
        used_names.setdefault(name.lower(), src_n)
        problem = _wait_for(src_n, progress, report)
        if problem:
            result.errors.append((src_n, problem))
            logging.warning(f"Quelle übersprungen: {src_n} – {problem}")
            continue
        if os.path.isdir(long_path(src_n)):
            dest_index = _DirIndex()
            for src_file, rel, st in _walk_files(src_n, is_excluded, skip_keys, on_walk_error, system_skipped):
                dest = os.path.join(target, name, rel)
                job = _make_job(src_file, dest, os.path.join(name, rel), result.errors, src_stat=st,
                                dest_index=dest_index)
                progress.files_done += 1
                progress.current = src_file
                if isinstance(job, _Job):
                    jobs.append(job)
                elif job == 'skip':
                    result.skipped += 1
                report(progress)
        elif os.path.isfile(long_path(src_n)):
            job = _make_job(src_n, os.path.join(target, name), name, result.errors)
            if isinstance(job, _Job):
                jobs.append(job)
            elif job == 'skip':
                result.skipped += 1
        else:
            result.errors.append((src_n, "Quelle nicht gefunden"))
            logging.warning(f"Quelle nicht gefunden: {src_n}")

    progress.skipped = result.skipped
    _log_system_skipped(system_skipped)
    recorder = versions.RunRecorder(profile=profile, kind='backup') if snapshots else _NoSnapshots()
    if _cancel.is_set():
        return _finish(result, recorder, progress, report, started, True, 'Backup')

    logging.info(f"Analyse fertig: {len(jobs)} Datei(en) zu kopieren "
                 f"({human_size(sum(j.size for j in jobs))}), {result.skipped} unverändert."
                 + ("" if snapshots else " Snapshots sind für dieses Profil ausgeschaltet."))
    space_error = _check_space(jobs, target, snapshots)
    if space_error:
        result.message = space_error
        result.code = FAILED
        logging.error(space_error)
        return result

    lost = _execute(jobs, recorder, 1 if hdd_mode else max(1, int(workers)), progress, report, result)
    return _finish(result, recorder, progress, report, started, _cancel.is_set(), 'Backup', lost)


# --------------------------------------------------------------------------- Recovery

def run_recovery(progress_callback=None, hdd_mode: bool = False, sources=None, target=None, profile=None,
                 overwrite_newer: bool = False, excludes=None, workers: int = 8):
    """Kopiert Dateien aus dem Backup-Ziel zurück zu den Quellen.

    Es werden nur fehlende oder abweichende Dateien kopiert. In der Quelle neuere Dateien bleiben
    erhalten (außer `overwrite_newer`). Überschriebene Quelldateien werden als Snapshot gesichert,
    sodass sich eine Wiederherstellung per Rollback rückgängig machen lässt."""
    started = time.monotonic()
    set_cancel_flag(False)
    sources = list(sources) if sources is not None else config.get_sources()
    target = target if target is not None else config.get_target()
    result = RunResult(code=FAILED, operation='recovery')
    progress = Progress(operation='recovery')
    report = _Reporter(progress_callback)
    logging.info(f"Wiederherstellung gestartet{f' (Profil: {profile})' if profile else ''} ← {target}")

    if not sources:
        result.message = "Keine Quellen angegeben."
        return result
    problem = _wait_for(target, progress, report)
    if problem or not os.path.isdir(long_path(target)):
        result.message = problem or f"Backup-Ziel nicht gefunden: {target}"
        logging.error(result.message)
        return result

    is_excluded = compile_excludes(excludes)
    jobs = []
    system_skipped = {}

    def on_walk_error(path, err):
        result.errors.append((path, f"Ordner nicht lesbar: {getattr(err, 'strerror', None) or err}"))

    for src in sources:
        if _cancel.is_set():
            break
        src_n = os.path.normpath(src)
        name = source_name(src_n)
        backup_path = os.path.join(target, name)
        problem = _wait_for(src_n, progress, report)
        if problem:
            result.errors.append((src_n, problem))
            logging.warning(f"Quelle übersprungen: {src_n} – {problem}")
            continue
        if os.path.isdir(long_path(backup_path)):
            dest_index = _DirIndex()
            for backup_file, rel, st in _walk_files(backup_path, is_excluded, None, on_walk_error, system_skipped):
                outcome = _make_job(backup_file, os.path.join(src_n, rel), os.path.join(name, rel),
                                    result.errors, mode='recovery', overwrite_newer=overwrite_newer, src_stat=st,
                                    dest_index=dest_index)
                progress.files_done += 1
                progress.current = backup_file
                if isinstance(outcome, _Job):
                    jobs.append(outcome)
                elif outcome == 'newer':
                    result.skipped_newer += 1
                elif outcome == 'skip':
                    result.skipped += 1
                report(progress)
        elif os.path.isfile(long_path(backup_path)):
            outcome = _make_job(backup_path, src_n, name, result.errors, mode='recovery',
                                overwrite_newer=overwrite_newer)
            if isinstance(outcome, _Job):
                jobs.append(outcome)
            elif outcome == 'newer':
                result.skipped_newer += 1
            elif outcome == 'skip':
                result.skipped += 1
        else:
            logging.warning(f"Im Backup nicht vorhanden: {backup_path}")

    result.skipped += result.skipped_newer
    progress.skipped = result.skipped
    _log_system_skipped(system_skipped)
    recorder = versions.RunRecorder(profile=profile, kind='recovery')
    if _cancel.is_set():
        return _finish(result, recorder, progress, report, started, True, 'Wiederherstellung')
    if result.skipped_newer:
        logging.info(f"{result.skipped_newer} Datei(en) in der Quelle sind neuer als im Backup und bleiben erhalten.")
    space_error = _check_space(jobs, sources[0])
    if space_error:
        result.message = space_error
        logging.error(space_error)
        return result
    lost = _execute(jobs, recorder, 1 if hdd_mode else max(1, int(workers)), progress, report, result)
    return _finish(result, recorder, progress, report, started, _cancel.is_set(), 'Wiederherstellung', lost)


# --------------------------------------------------------------------------- Kommandozeile

def main(argv=None):
    parser = argparse.ArgumentParser(description="Backup Manager – Backup ohne Oberfläche ausführen")
    parser.add_argument('--profile', help="Profilname aus config/profiles.json (sonst sources.txt/target.txt)")
    parser.add_argument('--hdd', action='store_true', help="HDD-Modus: Dateien nacheinander kopieren")
    args = parser.parse_args(argv)

    settings = config.load_settings()
    setup_logging(keep_files=settings.get('log_keep'))
    if args.profile:
        profiles = config.load_profiles()
        key = config.find_profile(profiles, args.profile)
        if not key:
            logging.error(f"Profil '{args.profile}' nicht gefunden.")
            return FAILED
        prof = profiles[key]
        result = run_backup(profile=key, sources=prof['sources'], target=prof['target'],
                            hdd_mode=prof['hdd_mode'] or args.hdd, excludes=prof['excludes'],
                            workers=settings['workers'], snapshots=prof['snapshots'])
        if result.code in (OK, PARTIAL):
            profiles = config.load_profiles()
            if key in profiles:
                profiles[key]['last_run'] = datetime.now().isoformat(timespec='seconds')
                config.save_profiles(profiles)
    else:
        result = run_backup(hdd_mode=args.hdd, workers=settings['workers'])
    print(result.message)
    return result.code


if __name__ == '__main__':
    sys.exit(main())
