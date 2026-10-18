"""Snapshots (Runs): Metadaten, Vorschau, Rollback, Löschen und Aufräumen.

Jeder Lauf, der mindestens eine Datei ändert, bekommt einen Ordner versions/<run_id>/ mit
metadata.json ({run_id, timestamp, profile, kind, status, files:[{src, dest, snapshot, created, size}]})
und den Sicherungskopien der überschriebenen Dateien.
"""
import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime
from typing import Callable
from uuid import uuid4

from engine import config, utils

# Zentrales Verzeichnis für Versions-Snapshots (in den Einstellungen änderbar)
VERSIONS_DIR = config.versions_dir_from_settings()

_locks_guard = threading.Lock()
_metadata_locks = {}
_last_corrupt_warn = {}
_summary_cache = {}
_inspect_cache = {}


def _get_lock(run_id: str) -> threading.RLock:
    with _locks_guard:
        lock = _metadata_locks.get(run_id)
        if lock is None:
            lock = threading.RLock()
            _metadata_locks[run_id] = lock
        return lock


def _retry(func: Callable, retries: int = 5, base_delay: float = 0.05):
    delay = base_delay
    for i in range(retries):
        try:
            return func()
        except OSError:
            if i == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2


def _atomic_write_json(path: str, data, retries: int = 5):
    def _write_once():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + f".tmp.{os.getpid()}.{threading.get_ident()}"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, path)
    return _retry(_write_once, retries=retries)


def _safe_move(src: str, dst: str, retries: int = 5):
    try:
        return _retry(lambda: shutil.move(src, dst), retries=retries)
    except Exception:
        # Fallback, wenn Move wegen Sharing-Violation fehlschlägt
        shutil.copy2(src, dst)
        try:
            os.remove(src)
        except OSError:
            pass


def _valid_run_id(run_id) -> bool:
    return bool(run_id) and isinstance(run_id, str) and run_id not in ('.', '..') \
        and not any(c in run_id for c in '/\\:')


def ensure_versions_dir():
    os.makedirs(VERSIONS_DIR, exist_ok=True)


def new_run_id():
    base = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_id = base
    while os.path.exists(os.path.join(VERSIONS_DIR, run_id)):
        run_id = f"{base}_{uuid4().hex[:6]}"
    return run_id


def metadata_file_path(run_id):
    return os.path.join(VERSIONS_DIR, run_id, 'metadata.json')


def create_run(run_id, profile=None):
    """Erstellt einen Run-Ordner mit initialer metadata.json (bestehende wird nicht überschrieben)."""
    ensure_versions_dir()
    run_dir = os.path.join(VERSIONS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)
    with _get_lock(run_id):
        if os.path.exists(metadata_file_path(run_id)):
            return run_dir
        metadata = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "profile": profile,
            "files": [],
        }
        try:
            save_metadata(run_id, metadata)
        except Exception as e:
            logging.error(f"Metadaten konnten nicht angelegt werden: {e}")
    return run_dir


def load_metadata(run_id):
    path = metadata_file_path(run_id)
    with _get_lock(run_id):
        try:
            if not os.path.exists(path):
                return None
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            now = time.time()
            if now - _last_corrupt_warn.get(run_id, 0) > 5:
                logging.warning(f"Metadaten fehlerhaft für Run {run_id}: {e}; defekte Datei wird gesichert.")
                _last_corrupt_warn[run_id] = now
            corrupt_path = path + f".corrupt_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            try:
                _safe_move(path, corrupt_path)
                logging.info(f"Defekte Metadaten nach {corrupt_path} verschoben.")
            except Exception as move_e:
                logging.error(f"Konnte defekte Metadaten nicht sichern: {move_e}")
            metadata = {"run_id": run_id, "timestamp": datetime.now().isoformat(), "files": []}
            try:
                save_metadata(run_id, metadata)
            except Exception as save_e:
                logging.error(f"Konnte Minimal-Metadaten nicht schreiben: {save_e}")
            return metadata
        except Exception as e:
            logging.warning(f"Fehler beim Laden der Metadaten für Run {run_id}: {e}")
            return None


def save_metadata(run_id, metadata):
    with _get_lock(run_id):
        try:
            _atomic_write_json(metadata_file_path(run_id), metadata)
        except Exception as e:
            logging.error(f"Metadaten konnten nicht gespeichert werden ({run_id}): {e}")
            raise


def _entry(src, dest, snapshot_full=None, created=False, size=None):
    entry = {
        "src": os.path.normpath(src) if src else src,
        "dest": os.path.normpath(dest) if dest else dest,
        "snapshot": os.path.normpath(snapshot_full) if snapshot_full else None,
        "created": bool(created),
    }
    if size is not None:
        entry["size"] = int(size)
    return entry


def add_changed_file(run_id, src, dest, snapshot_full=None, created=False, profile=None):
    """Fügt einen Eintrag zur metadata.json hinzu (Laden+Anhängen+Speichern unter einer Sperre)."""
    with _get_lock(run_id):
        metadata = load_metadata(run_id)
        if metadata is None:
            create_run(run_id, profile=profile)
            metadata = load_metadata(run_id) or {"run_id": run_id, "timestamp": datetime.now().isoformat(), "files": []}
        if profile and not metadata.get('profile'):
            metadata['profile'] = profile
        metadata.setdefault('files', []).append(_entry(src, dest, snapshot_full, created))
        save_metadata(run_id, metadata)


class RunRecorder:
    """Sammelt die Änderungen eines Laufs im Speicher und schreibt metadata.json gebündelt
    (alle paar Sekunden und am Ende). Thread-sicher; legt nur dann einen Run an,
    wenn tatsächlich eine Datei geändert wurde."""

    FLUSH_INTERVAL = 15.0
    with_snapshots = True

    def __init__(self, profile=None, kind='backup', run_id=None, extra=None):
        ensure_versions_dir()
        self.run_id = run_id or new_run_id()
        self.profile = profile
        self.kind = kind
        self.extra = extra or {}
        self.started = datetime.now()
        self.snapshot_bytes = 0
        self._files = []
        self._lock = threading.Lock()
        self._last_flush = time.monotonic()
        self._dirty = False

    @property
    def run_dir(self):
        return os.path.join(VERSIONS_DIR, self.run_id)

    @property
    def count(self):
        return len(self._files)

    def snapshot_path(self, rel):
        rel = os.path.normpath(rel or '')
        parts = [p for p in rel.replace('/', os.sep).split(os.sep) if p not in ('', '.', '..')]
        if not parts:
            parts = ['datei']
        parts[0] = parts[0].replace(':', '')
        return os.path.normpath(os.path.join(self.run_dir, *parts))

    def add(self, src, dest, snapshot=None, created=False, size=None):
        entry = _entry(src, dest, snapshot, created, size if snapshot else None)
        with self._lock:
            self._files.append(entry)
            if snapshot and size:
                self.snapshot_bytes += int(size)
            self._dirty = True
            if time.monotonic() - self._last_flush > self.FLUSH_INTERVAL:
                self._flush_locked(status='running')

    def _flush_locked(self, status, stats=None):
        if not self._files or not self._dirty:
            return
        metadata = {
            "run_id": self.run_id,
            "timestamp": self.started.isoformat(),
            "profile": self.profile,
            "kind": self.kind,
            "status": status,
            "snapshot_bytes": self.snapshot_bytes,
            **self.extra,
            "files": self._files,
        }
        if status != 'running':
            metadata["finished"] = datetime.now().isoformat()
        if stats:
            metadata["stats"] = stats
        try:
            save_metadata(self.run_id, metadata)
            self._dirty = False
        except Exception as e:
            logging.error(f"Metadaten für Run {self.run_id} konnten nicht geschrieben werden: {e}")
        self._last_flush = time.monotonic()

    def finalize(self, status='complete', stats=None):
        """Schreibt die endgültigen Metadaten. Gibt True zurück, wenn ein Run angelegt wurde."""
        with self._lock:
            self._dirty = True
            self._flush_locked(status=status, stats=stats)
            has_files = bool(self._files)
        if not has_files and os.path.isdir(self.run_dir):
            # Ordner wurde evtl. für einen fehlgeschlagenen Snapshot angelegt – leere Reste entfernen
            for root, _dirs, _files in os.walk(self.run_dir, topdown=False):
                try:
                    os.rmdir(root)
                except OSError:
                    pass
        return has_files


# --------------------------------------------------------------------------- Übersicht / Auflistung

def _run_dirs():
    ensure_versions_dir()
    try:
        names = os.listdir(VERSIONS_DIR)
    except OSError as e:
        logging.warning(f"Versions-Verzeichnis kann nicht gelesen werden: {e}")
        return []
    return [n for n in names if os.path.isdir(os.path.join(VERSIONS_DIR, n))]


def run_summary(run_id):
    """Kompakte Zusammenfassung eines Runs (gecacht, solange metadata.json unverändert ist)."""
    path = metadata_file_path(run_id)
    try:
        st = os.stat(path)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    cached = _summary_cache.get(run_id)
    if cached and cached[0] == key and key is not None:
        return cached[1]

    md = load_metadata(run_id) if key else None
    files = (md or {}).get('files') or []
    created = sum(1 for e in files if e.get('created'))
    summary = {
        "run_id": run_id,
        "timestamp": utils.parse_timestamp((md or {}).get('timestamp')) or utils.parse_timestamp(run_id),
        "profile": (md or {}).get('profile'),
        "kind": (md or {}).get('kind') or ('pre-rollback' if run_id.startswith('prerollback_') else 'backup'),
        "status": (md or {}).get('status') or ('complete' if md else 'nometa'),
        "total": len(files),
        "created": created,
        "changed": len(files) - created,
        "snapshot_bytes": (md or {}).get('snapshot_bytes'),
        "rolled_back": bool((md or {}).get('rollbacks')),
    }
    if key is not None:
        _summary_cache[run_id] = (key, summary)
    return summary


def list_run_summaries(profile=None):
    """Alle Runs (inkl. leerer), neueste zuerst; optional nach Profil gefiltert."""
    wanted = profile.strip().lower() if profile else None
    result = []
    for name in _run_dirs():
        try:
            s = run_summary(name)
        except Exception as e:
            logging.warning(f"Run {name} konnte nicht gelesen werden: {e}")
            continue
        if wanted is not None and (s.get('profile') or '').strip().lower() != wanted:
            continue
        result.append(s)
    result.sort(key=lambda s: s['timestamp'] or datetime.min, reverse=True)
    return result


def list_runs(include_empty=False):
    """Run-IDs, neueste zuerst. Runs ohne Dateien werden standardmäßig ausgelassen."""
    return [s['run_id'] for s in list_run_summaries() if include_empty or s['total'] > 0]


def get_run_details(run_id):
    return load_metadata(run_id)


def inspect_run(run_id):
    """Ermittelt Größe des Snapshot-Ordners und fehlende Snapshot-Dateien (gecacht)."""
    path = metadata_file_path(run_id)
    try:
        key = os.stat(path).st_mtime_ns
    except OSError:
        key = None
    cached = _inspect_cache.get(run_id)
    if cached and cached[0] == key:
        return cached[1]

    run_dir = os.path.join(VERSIONS_DIR, run_id)
    found = set()
    total = 0
    stack = [utils.force_long_path(run_dir)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            total += e.stat(follow_symlinks=False).st_size
                            found.add(utils.norm_key(e.path))
                    except OSError:
                        pass
        except OSError:
            pass

    run_key = utils.norm_key(run_dir) + os.sep
    missing = 0
    with_snapshot = 0
    md = load_metadata(run_id) or {}
    for entry in md.get('files') or []:
        snap = entry.get('snapshot')
        if not snap:
            continue
        with_snapshot += 1
        k = utils.norm_key(snap)
        if k.startswith(run_key):
            if k not in found:
                missing += 1
        elif not os.path.exists(utils.long_path(snap)):
            missing += 1
    info = {"size": total, "missing": missing, "with_snapshot": with_snapshot}
    _inspect_cache[run_id] = (key, info)
    return info


def clear_caches():
    _summary_cache.clear()
    _inspect_cache.clear()


# --------------------------------------------------------------------------- Rollback

def preview_rollback(run_id):
    """Vorschau: welche Dateien ein Rollback löschen bzw. wiederherstellen würde."""
    metadata = load_metadata(run_id)
    if not metadata:
        return None
    files = metadata.get('files', [])
    to_delete, to_restore, missing = [], [], []
    for entry in reversed(files):
        dest = os.path.normpath(entry['dest']) if entry.get('dest') else entry.get('dest')
        if entry.get('created'):
            to_delete.append(dest)
        else:
            snapshot = entry.get('snapshot')
            snapshot = os.path.normpath(snapshot) if snapshot else snapshot
            to_restore.append((dest, snapshot))
            if not snapshot or not os.path.exists(utils.long_path(snapshot)):
                missing.append((dest, snapshot))
    return {
        'run_id': run_id,
        'total': len(files),
        'to_delete': to_delete,
        'to_restore': to_restore,
        'missing_snapshots': missing,
        'profile': metadata.get('profile'),
        'kind': metadata.get('kind') or 'backup',
    }


def rollback_run(run_id, progress_callback=None):
    """Stellt Dateien aus dem Snapshot wieder her bzw. entfernt neu angelegte Dateien.
    Rückgabe: (code, report) mit Listen restored, deleted, missing, errors."""
    metadata = load_metadata(run_id)
    if not metadata:
        logging.error(f"Run {run_id} nicht gefunden.")
        return 1, None
    files = metadata.get('files', [])
    total = len(files)
    report = {'restored': [], 'deleted': [], 'missing': [], 'errors': []}

    # Umgekehrte Reihenfolge (zuletzt geänderte zuerst)
    for processed, entry in enumerate(reversed(files), start=1):
        dest = os.path.normpath(entry['dest'])
        if entry.get('created'):
            try:
                if os.path.exists(utils.long_path(dest)):
                    utils.remove_file(dest)
                    logging.info(f"Entfernt (Rollback): {dest}")
                    report['deleted'].append(dest)
            except Exception as e:
                logging.error(f"Fehler beim Entfernen {dest}: {e}")
                report['errors'].append((dest, str(e)))
        else:
            snapshot = entry.get('snapshot')
            snapshot = os.path.normpath(snapshot) if snapshot else None
            if snapshot and os.path.exists(utils.long_path(snapshot)):
                try:
                    utils.copy_file(snapshot, dest)
                    logging.info(f"Wiederhergestellt aus Snapshot: {snapshot} -> {dest}")
                    report['restored'].append(dest)
                except Exception as e:
                    logging.error(f"Fehler beim Wiederherstellen {dest} aus {snapshot}: {e}")
                    report['errors'].append((dest, str(e)))
            else:
                logging.warning(f"Snapshot nicht gefunden für {dest}: {snapshot}")
                report['missing'].append(dest)
        if progress_callback:
            progress_callback(processed, total)

    try:
        with _get_lock(run_id):
            md = load_metadata(run_id)
            if md is not None:
                md.setdefault('rollbacks', []).append(datetime.now().isoformat())
                save_metadata(run_id, md)
    except Exception as e:
        logging.warning(f"Rollback-Vermerk konnte nicht gespeichert werden: {e}")
    return 0, report


# --------------------------------------------------------------------------- Pflege

def normalize_profiles():
    """Bereinigt das Profil-Feld in allen Runs (trim + lowercase); sichert Originale als .bak_<zeit>.
    Rückgabe: Liste [(run_id, alt, neu, backup_pfad), ...]"""
    changes = []
    for name in _run_dirs():
        md = load_metadata(name)
        if md is None:
            continue
        original = md.get('profile')
        if original is None:
            continue
        new_profile = original.strip().lower() if isinstance(original, str) else original
        if new_profile == original and new_profile != '':
            continue
        bak = metadata_file_path(name) + '.bak_' + datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = bak
        try:
            _retry(lambda: shutil.copy2(metadata_file_path(name), bak))
        except Exception as e:
            logging.warning(f"Konnte Backup der Metadaten für {name} nicht erstellen: {e}")
            backup_path = None
        if new_profile == '':
            md.pop('profile', None)
            new_profile = None
        else:
            md['profile'] = new_profile
        save_metadata(name, md)
        changes.append((name, original, new_profile, backup_path))
    return changes


def delete_run(run_id):
    """Löscht einen Run vollständig (auch schreibgeschützte Snapshot-Dateien)."""
    if not _valid_run_id(run_id):
        logging.error(f"Ungültige Run-ID: {run_id!r}")
        return False
    run_path = os.path.join(VERSIONS_DIR, run_id)
    if not os.path.exists(run_path):
        logging.error(f"Run-Verzeichnis {run_path} existiert nicht.")
        return False
    try:
        utils.rmtree(run_path)
        _summary_cache.pop(run_id, None)
        _inspect_cache.pop(run_id, None)
        logging.info(f"Run {run_id} gelöscht.")
        return True
    except Exception as e:
        logging.error(f"Fehler beim Löschen von {run_path}: {e}")
        return False


def delete_runs(run_ids, progress_callback=None):
    """Löscht mehrere Runs. Rückgabe: (erfolgreich, fehlgeschlagen)."""
    succeeded, failed = [], []
    total = len(run_ids)
    for i, r in enumerate(run_ids, start=1):
        (succeeded if delete_run(r) else failed).append(r)
        if progress_callback:
            progress_callback(i, total)
    return succeeded, failed


def move_runs(new_dir, progress_callback=None):
    """Verschiebt alle Runs in einen neuen Snapshot-Ordner und stellt VERSIONS_DIR um.
    Rückgabe: (verschoben, fehlgeschlagen)."""
    global VERSIONS_DIR
    new_dir = os.path.abspath(new_dir)
    os.makedirs(new_dir, exist_ok=True)
    runs = _run_dirs()
    moved, failed = [], []
    for i, run_id in enumerate(runs, start=1):
        src = os.path.join(VERSIONS_DIR, run_id)
        dst = os.path.join(new_dir, run_id)
        try:
            if os.path.exists(dst):
                raise FileExistsError(dst)
            shutil.move(utils.force_long_path(src), utils.force_long_path(dst))
            # absolute Snapshot-Pfade in den Metadaten anpassen
            md_path = os.path.join(dst, 'metadata.json')
            if os.path.exists(md_path):
                with open(md_path, 'r', encoding='utf-8') as f:
                    md = json.load(f)
                old_prefix = os.path.normcase(os.path.normpath(src)) + os.sep
                for e in md.get('files') or []:
                    snap = e.get('snapshot')
                    if snap and os.path.normcase(os.path.normpath(snap)).startswith(old_prefix):
                        e['snapshot'] = os.path.join(dst, os.path.normpath(snap)[len(old_prefix):])
                _atomic_write_json(md_path, md)
            moved.append(run_id)
        except Exception as e:
            logging.error(f"Run {run_id} konnte nicht verschoben werden: {e}")
            failed.append(run_id)
        if progress_callback:
            progress_callback(i, len(runs))
    VERSIONS_DIR = new_dir
    clear_caches()
    return moved, failed


def plan_prune(profile, keep):
    """Runs eines Profils, die beim Behalten der neuesten `keep` gelöscht würden."""
    runs = list_run_summaries(profile)
    return runs[max(0, int(keep)):]
