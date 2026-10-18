import os
import json
import tempfile
import shutil
from engine import versions


def test_delete_run_removes_directory(tmp_path, monkeypatch):
    temp_dir = str(tmp_path / "versions")
    monkeypatch.setattr(versions, 'VERSIONS_DIR', temp_dir)
    run_id = 'run_to_delete'
    run_path = os.path.join(temp_dir, run_id)
    os.makedirs(run_path, exist_ok=True)
    # create dummy metadata
    with open(os.path.join(run_path, 'metadata.json'), 'w', encoding='utf-8') as f:
        json.dump({"run_id": run_id, "timestamp": "2020-01-01T00:00:00", "files": [{"src":"a","dest":"b"}]}, f)
    assert os.path.exists(run_path)
    success = versions.delete_run(run_id)
    assert success is True
    assert not os.path.exists(run_path)


def test_delete_runs_multiple(tmp_path, monkeypatch):
    temp_dir = str(tmp_path / "versions")
    monkeypatch.setattr(versions, 'VERSIONS_DIR', temp_dir)
    runs = ['r1', 'r2']
    for r in runs:
        p = os.path.join(temp_dir, r)
        os.makedirs(p, exist_ok=True)
        with open(os.path.join(p, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump({"run_id": r, "timestamp": "2020-01-01T00:00:00", "files": [{"src":"a","dest":"b"}]}, f)
    succeeded, failed = versions.delete_runs(runs)
    assert set(succeeded) == set(runs)
    assert failed == []