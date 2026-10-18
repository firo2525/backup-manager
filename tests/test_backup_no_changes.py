import os
import time
import tempfile
from engine import backup, versions, config


def test_run_backup_no_changes_does_not_create_run(tmp_path, monkeypatch):
    # Setup source and target where files are identical
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    dest_dir.mkdir()
    src_file = src_dir / "file.txt"
    (dest_dir / "src").mkdir()
    dest_file = dest_dir / "src" / "file.txt"  # Ordner-Quellen landen unter Ziel/<Ordnername>/
    content = b"hello"
    src_file.write_bytes(content)
    dest_file.write_bytes(content)
    # Ensure mtimes are same
    now = time.time()
    os.utime(src_file, (now, now))
    os.utime(dest_file, (now, now))

    # point config functions to these
    monkeypatch.setattr(config, 'get_sources', lambda: [str(src_dir)])
    monkeypatch.setattr(config, 'get_target', lambda: str(dest_dir))
    # Use temp versions dir
    monkeypatch.setattr(versions, 'VERSIONS_DIR', str(tmp_path / 'versions'))

    code, changed_files = backup.run_backup(profile='testprofile')
    assert code == 0
    # Since files are unchanged, no runs should be created
    runs = versions.list_runs()
    assert runs == []
    assert changed_files == []