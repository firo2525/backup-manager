import os
import json
from engine import versions


def test_normalize_profiles(tmp_path, monkeypatch):
    vdir = str(tmp_path / 'versions')
    monkeypatch.setattr(versions, 'VERSIONS_DIR', vdir)
    # create runs with various profile fields
    runs = {
        'r1': {'profile': 'Firat ', 'files': []},
        'r2': {'profile': ' alice', 'files': []},
        'r3': {'profile': 'BOB', 'files': []},
        'r4': {'profile': '', 'files': []},
        'r5': {},
    }
    for k, md in runs.items():
        d = os.path.join(vdir, k)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump({'run_id': k, 'timestamp': '2020-01-01T00:00:00', **md}, f)
    changes = versions.normalize_profiles()
    # Check that r1..r4 were processed, r5 unchanged
    changed_runs = [c[0] for c in changes]
    assert 'r1' in changed_runs
    assert 'r2' in changed_runs
    assert 'r3' in changed_runs
    assert 'r4' in changed_runs
    # Verify new values
    md1 = versions.load_metadata('r1')
    assert md1.get('profile') == 'firat'
    md2 = versions.load_metadata('r2')
    assert md2.get('profile') == 'alice'
    md3 = versions.load_metadata('r3')
    assert md3.get('profile') == 'bob'
    md4 = versions.load_metadata('r4')
    assert md4.get('profile') is None or md4.get('profile') == ''
    # Ensure backups exist for changed runs
    for _, _, _, backup in changes:
        if backup:
            assert os.path.exists(backup)