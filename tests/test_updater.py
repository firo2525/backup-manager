import hashlib
import importlib.util
import io
import json
import os

import pytest

from engine import updater

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PAYLOAD = b'MZ' + b'installer' * 1000


class _Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}


def _release(tag='v99.0.0', digest=None, **extra):
    return {'tag_name': tag, 'name': f'Backup Manager {tag}', 'body': 'Neu: NAS-Unterstützung',
            'html_url': 'https://github.com/firo2525/backup-manager/releases/tag/' + tag,
            'assets': [{'name': 'backup-manager-99.0.0-source.zip', 'browser_download_url': 'https://x/src.zip'},
                       {'name': 'BackupManager-Setup-99.0.0.exe', 'browser_download_url': 'https://x/setup.exe',
                        'size': len(PAYLOAD),
                        'digest': digest or 'sha256:' + hashlib.sha256(PAYLOAD).hexdigest()}], **extra}


@pytest.fixture
def github(monkeypatch):
    state = {'release': _release(), 'payload': PAYLOAD, 'urls': []}

    def fake_open(url, accept=None):
        state['urls'].append(url)
        if url == updater.API_URL:
            return _Response(json.dumps(state['release']).encode())
        return _Response(state['payload'], {'Content-Length': str(len(state['payload']))})

    monkeypatch.setattr(updater, '_open', fake_open)
    monkeypatch.setattr(updater.tempfile, 'gettempdir', lambda: state['tmp'])
    return state


def test_version_comparison():
    assert updater.is_newer('v2.2.0', '2.1.2')
    assert updater.is_newer('2.10', '2.9.9')
    assert not updater.is_newer('v2.1.2', '2.1.2')
    assert not updater.is_newer('v2.1', '2.1.0')
    assert not updater.is_newer('', '2.1.2')


def test_check_finds_newer_release(github):
    info = updater.check()
    assert info.version == '99.0.0' and info.asset_url == 'https://x/setup.exe'
    assert info.sha256 == hashlib.sha256(PAYLOAD).hexdigest()


@pytest.mark.parametrize('release', [_release(tag='v0.1'), _release(prerelease=True), _release(draft=True)])
def test_check_ignores_older_and_unfinished_releases(github, release):
    github['release'] = release
    assert updater.check() is None


def test_download_verifies_checksum(github, tmp_path):
    github['tmp'] = str(tmp_path)
    seen = []
    path = updater.download(updater.check(), lambda done, total: seen.append((done, total)))
    with open(path, 'rb') as f:
        assert f.read() == PAYLOAD
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))


def test_tampered_download_is_rejected_and_removed(github, tmp_path):
    github['tmp'] = str(tmp_path)
    info = updater.check()
    github['payload'] = b'MZ manipuliert'
    with pytest.raises(ValueError, match='Prüfsumme'):
        updater.download(info)
    assert os.listdir(tmp_path / 'BackupManager-Update') == []


def test_release_without_checksum_is_not_installed(github, tmp_path):
    github['tmp'] = str(tmp_path)
    info = updater.check()
    info.sha256 = None
    with pytest.raises(ValueError):
        updater.download(info)
    assert github['urls'] == [updater.API_URL]  # gar nicht erst heruntergeladen


def test_source_checkout_is_not_self_updated():
    assert not updater.can_self_update()  # kein Uninstall.exe im Projektordner


def _load_setup():
    spec = importlib.util.spec_from_file_location('bm_setup', os.path.join(BASE, 'installer', 'setup.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_update_switch():
    setup = _load_setup()
    o = setup.parse_args(['/update', '/D=C:\\Programme\\Backup Manager'])
    assert o['update'] and o['silent'] and not o['pin'] and o['start'] and o['dir'] == 'C:\\Programme\\Backup Manager'
    # Bei nötiger Rechteerhöhung muss /update an die neue Instanz weitergereicht werden
    assert '/update' in setup.build_args(o, o['dir'], ['/elevated'])
    assert '/S' in setup.build_args(setup.parse_args(['/S']), 'C:\\x')
