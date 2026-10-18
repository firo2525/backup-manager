import json
import os
import stat
import threading
import time

from engine import backup, versions


def _write(path, text, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_backup_creates_snapshot_and_rollback_restores(tmp_path):
    src, dest = tmp_path / 'proj', tmp_path / 'ziel'
    _write(src / 'a.txt', 'v1')
    r1 = backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    assert r1.code == backup.OK and r1.copied == 1
    assert (dest / 'proj' / 'a.txt').read_text(encoding='utf-8') == 'v1'

    _write(src / 'a.txt', 'version2', mtime=time.time() + 10)
    _write(src / 'neu.txt', 'neu')
    r2 = backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    assert r2.code == backup.OK and r2.copied == 2 and r2.run_id
    md = versions.load_metadata(r2.run_id)
    assert md['status'] == 'complete' and md['profile'] == 'p' and len(md['files']) == 2

    code, report = versions.rollback_run(r2.run_id)
    assert code == 0 and len(report['restored']) == 1 and len(report['deleted']) == 1
    assert (dest / 'proj' / 'a.txt').read_text(encoding='utf-8') == 'v1'
    assert not (dest / 'proj' / 'neu.txt').exists()


def test_backup_skips_versions_dir_and_excludes(tmp_path):
    src, dest = tmp_path / 'app', tmp_path / 'ziel'
    _write(src / 'keep.txt', 'x')
    _write(src / '.git' / 'HEAD', 'x')
    _write(src / 'cache' / 'x.tmp', 'x')
    versions.VERSIONS_DIR = str(src / 'versions')  # versions-Ordner liegt in der Quelle
    _write(src / 'versions' / 'old' / 'big.bin', 'x')
    r = backup.run_backup(sources=[str(src)], target=str(dest), excludes=['.git', '*.tmp'])
    copied = sorted(os.path.relpath(d, dest) for _s, d, _n in r.changed_files)
    assert copied == [os.path.join('app', 'keep.txt')]


def test_backup_overwrites_readonly_target(tmp_path):
    src, dest = tmp_path / 'q', tmp_path / 'z'
    _write(src / 'ro.txt', 'alt')
    backup.run_backup(sources=[str(src)], target=str(dest))
    target_file = dest / 'q' / 'ro.txt'
    os.chmod(target_file, stat.S_IREAD)
    _write(src / 'ro.txt', 'neu-inhalt', mtime=time.time() + 10)
    r = backup.run_backup(sources=[str(src)], target=str(dest))
    assert r.code == backup.OK, r.errors
    assert target_file.read_text(encoding='utf-8') == 'neu-inhalt'
    assert versions.delete_run(r.run_id)  # schreibgeschützter Snapshot lässt sich löschen


def test_missing_target_drive_fails_cleanly(tmp_path):
    src = tmp_path / 'q'
    _write(src / 'a.txt', 'x')
    r = backup.run_backup(sources=[str(src)], target=r'Q:\gibt\es\nicht' if os.name == 'nt' else '/proc/x/y')
    assert r.code == backup.FAILED and r.message


def test_recovery_does_not_mix_similar_folder_names(tmp_path):
    a, b, dest = tmp_path / 'cam ki', tmp_path / 'cam ki - Kopie', tmp_path / 'ziel'
    _write(a / 'x.txt', 'A')
    _write(b / 'y.txt', 'B')
    backup.run_backup(sources=[str(a), str(b)], target=str(dest))
    (a / 'x.txt').unlink()
    r = backup.run_recovery(sources=[str(a)], target=str(dest))
    assert r.code == backup.OK
    assert (a / 'x.txt').read_text(encoding='utf-8') == 'A'
    assert not (a / 'y.txt').exists() and not (tmp_path / 'cam ki' / '..' / 'cam ki - Kopie' / 'x.txt').exists()


def test_recovery_keeps_newer_source_files_and_is_undoable(tmp_path):
    src, dest = tmp_path / 'q', tmp_path / 'z'
    _write(src / 'a.txt', 'backup-stand')
    backup.run_backup(sources=[str(src)], target=str(dest))
    _write(src / 'a.txt', 'neuer-lokal', mtime=time.time() + 100)
    r = backup.run_recovery(sources=[str(src)], target=str(dest))
    assert r.skipped_newer == 1 and (src / 'a.txt').read_text(encoding='utf-8') == 'neuer-lokal'

    r = backup.run_recovery(sources=[str(src)], target=str(dest), overwrite_newer=True)
    assert (src / 'a.txt').read_text(encoding='utf-8') == 'backup-stand' and r.run_id
    versions.rollback_run(r.run_id)
    assert (src / 'a.txt').read_text(encoding='utf-8') == 'neuer-lokal'


def test_recorder_is_thread_safe():
    rec = versions.RunRecorder(profile='p')
    threads = [threading.Thread(target=lambda i=i: [rec.add(f's{i}_{j}', f'd{i}_{j}') for j in range(200)])
               for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert rec.finalize()
    with open(versions.metadata_file_path(rec.run_id), encoding='utf-8') as f:
        assert len(json.load(f)['files']) == 1600


def test_cancel_stops_backup(tmp_path):
    src, dest = tmp_path / 'q', tmp_path / 'z'
    for i in range(50):
        _write(src / f'{i}.txt', 'x')

    def cb(p):
        if p.phase == 'copy' and p.files_done >= 5:
            backup.set_cancel_flag(True)

    r = backup.run_backup(sources=[str(src)], target=str(dest), hdd_mode=True, progress_callback=None)
    assert r.code == backup.OK
    for i in range(50):
        _write(src / f'{i}.txt', 'geändert', mtime=time.time() + 10)
    orig = backup._Reporter.__call__

    def eager(self, progress, force=False):
        return orig(self, progress, force=True)

    backup._Reporter.__call__ = eager
    try:
        r = backup.run_backup(sources=[str(src)], target=str(dest), hdd_mode=True, progress_callback=cb)
    finally:
        backup._Reporter.__call__ = orig
    assert r.code == backup.CANCELLED and 0 < r.copied < 50
    assert versions.load_metadata(r.run_id)['status'] == 'cancelled'


def test_backup_without_snapshots_creates_no_run(tmp_path):
    src, dest = tmp_path / 'q', tmp_path / 'z'
    _write(src / 'a.txt', 'v1')
    backup.run_backup(sources=[str(src)], target=str(dest), snapshots=False)
    _write(src / 'a.txt', 'version-2', mtime=time.time() + 10)
    r = backup.run_backup(sources=[str(src)], target=str(dest), snapshots=False)
    assert r.code == backup.OK and r.copied == 1 and r.run_id is None
    assert (dest / 'q' / 'a.txt').read_text(encoding='utf-8') == 'version-2'
    assert versions.list_run_summaries() == []


def test_move_runs_updates_snapshot_paths(tmp_path):
    src, dest = tmp_path / 'q', tmp_path / 'z'
    _write(src / 'a.txt', 'v1')
    backup.run_backup(sources=[str(src)], target=str(dest))
    _write(src / 'a.txt', 'v2', mtime=time.time() + 10)
    r = backup.run_backup(sources=[str(src)], target=str(dest))
    moved, failed = versions.move_runs(str(tmp_path / 'neu'))
    assert failed == [] and r.run_id in moved and versions.VERSIONS_DIR == str(tmp_path / 'neu')
    code, report = versions.rollback_run(r.run_id)
    assert report['restored'] and (dest / 'q' / 'a.txt').read_text(encoding='utf-8') == 'v1'


def test_profiles_are_backed_up_before_save():
    from engine import config
    config.save_profiles({"a": config.normalize_profile({})})
    config.save_profiles({})
    folder = os.path.join(config.CONFIG_DIR, 'backups')
    assert len(os.listdir(folder)) == 1
