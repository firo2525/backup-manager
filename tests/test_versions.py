import os
import json
import tempfile
import shutil
from engine import versions


def test_add_changed_file_creates_run_and_profile(tmp_path, monkeypatch):
    temp_dir = str(tmp_path / "versions")
    monkeypatch.setattr(versions, 'VERSIONS_DIR', temp_dir)
    run_id = 'testrun1'
    # Ensure no runs exist
    assert not os.path.exists(temp_dir)
    # Add a changed file (should create run and metadata)
    versions.add_changed_file(run_id, src='a.txt', dest='b.txt', snapshot_full=None, created=True, profile='myprofile')
    md = versions.load_metadata(run_id)
    assert md is not None
    assert md.get('profile') == 'myprofile'
    assert len(md.get('files', [])) == 1


def test_list_runs_filters_empty(tmp_path, monkeypatch):
    temp_dir = str(tmp_path / "versions")
    monkeypatch.setattr(versions, 'VERSIONS_DIR', temp_dir)
    # create an empty run folder with metadata having zero files
    os.makedirs(os.path.join(temp_dir, 'empty_run'), exist_ok=True)
    with open(os.path.join(temp_dir, 'empty_run', 'metadata.json'), 'w', encoding='utf-8') as f:
        json.dump({"run_id": "empty_run", "timestamp": "2020-01-01T00:00:00", "files": []}, f)
    # create a proper run with one file
    os.makedirs(os.path.join(temp_dir, 'run_with_files'), exist_ok=True)
    with open(os.path.join(temp_dir, 'run_with_files', 'metadata.json'), 'w', encoding='utf-8') as f:
        json.dump({"run_id": "run_with_files", "timestamp": "2020-01-02T00:00:00", "files": [{"src":"a","dest":"b"}]}, f)
    runs = versions.list_runs()
    assert 'empty_run' not in runs
    assert 'run_with_files' in runs