import os
import sys

import pytest

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from engine import config, versions  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_app_data(tmp_path, monkeypatch):
    """Kein Test darf echte Profile, sources.txt/target.txt oder den echten versions-Ordner benutzen."""
    monkeypatch.setattr(versions, 'VERSIONS_DIR', str(tmp_path / 'versions'))
    monkeypatch.setattr(config, 'get_sources', lambda: [])
    monkeypatch.setattr(config, 'get_target', lambda: None)
    for name in ('PROFILES_FILE', 'SETTINGS_FILE', 'SOURCES_FILE', 'TARGET_FILE'):
        monkeypatch.setattr(config, name, str(tmp_path / 'config' / os.path.basename(getattr(config, name))))
    monkeypatch.setattr(config, 'CONFIG_DIR', str(tmp_path / 'config'))
    versions.clear_caches()
    yield
