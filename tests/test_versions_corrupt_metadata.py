import os
import json
from datetime import datetime
from engine import versions


def test_corrupt_metadata_is_repaired(tmp_path, monkeypatch):
    vdir = str(tmp_path / 'versions')
    monkeypatch.setattr(versions, 'VERSIONS_DIR', vdir)
    run_id = 'corrupt_run'
    run_path = os.path.join(vdir, run_id)
    os.makedirs(run_path, exist_ok=True)
    meta_path = os.path.join(run_path, 'metadata.json')
    # write corrupt JSON (valid JSON + extra data)
    with open(meta_path, 'w', encoding='utf-8') as f:
        f.write('{"run_id": "corrupt_run", "timestamp": "2025-01-01T00:00:00", "files": [} EXTRA')
    # load metadata -> should not raise, should repair and return minimal metadata
    md = versions.get_run_details(run_id)
    assert md is not None
    assert isinstance(md.get('files'), list)
    assert md.get('files') == []
    # check that original corrupt file was moved
    found_corrupt = False
    for name in os.listdir(run_path):
        if name.startswith('metadata.json.corrupt_'):
            found_corrupt = True
    assert found_corrupt
    # check new metadata.json exists and is valid JSON
    with open(os.path.join(run_path, 'metadata.json'), 'r', encoding='utf-8') as f:
        jm = json.load(f)
    assert jm.get('run_id') == run_id
    assert jm.get('files') == []