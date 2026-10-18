import os
import json
import tempfile
from engine import versions


def test_preview_rollback_detects_missing(tmp_path, monkeypatch):
    vdir = str(tmp_path / 'versions')
    monkeypatch.setattr(versions, 'VERSIONS_DIR', vdir)
    run_id = 'r1'
    run_path = os.path.join(vdir, run_id)
    os.makedirs(run_path, exist_ok=True)
    # create two file entries: one with existing snapshot, one missing
    existing_snap = os.path.join(run_path, 'file1.txt')
    os.makedirs(os.path.dirname(existing_snap), exist_ok=True)
    with open(existing_snap, 'w', encoding='utf-8') as f:
        f.write('data')
    metadata = {
        'run_id': run_id,
        'timestamp': '2020-01-01T00:00:00',
        'files': [
            {'src': 'src1', 'dest': 'dest1', 'snapshot': existing_snap, 'created': False},
            {'src': 'src2', 'dest': 'dest2', 'snapshot': os.path.join(run_path, 'missing.txt'), 'created': False}
        ]
    }
    with open(os.path.join(run_path, 'metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(metadata, f)
    pr = versions.preview_rollback(run_id)
    assert pr['total'] == 2
    assert len(pr['missing_snapshots']) == 1