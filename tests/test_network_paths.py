import os
import threading
import time

import pytest

from engine import backup, utils, versions

NAS = '\\\\nas\\backup'


@pytest.fixture(autouse=True)
def clear_network_cache():
    utils.forget_network_status()
    yield
    utils.forget_network_status()


def _win_error(code, text='Fehler'):
    return OSError(None, text, None, code)


@pytest.fixture
def fake_nas(monkeypatch):
    """Simuliert ein NAS unter \\\\nas\\…: `fake_nas.error` wird beim Zugriff ausgelöst, `fake_nas.gate`
    lässt den Zugriff hängen, bis es gesetzt wird (wie Windows bei einem ausgeschalteten Gerät)."""
    real_stat = os.stat

    class Nas:
        error = None
        gate = None
        calls = 0

    def fake_stat(path, *a, **kw):
        p = os.fspath(path).replace('\\\\?\\UNC\\', '\\\\').lower()
        if p.startswith('\\\\nas\\'):
            Nas.calls += 1
            if Nas.gate is not None:
                Nas.gate.wait(10)
            if Nas.error is not None:
                raise Nas.error
            return real_stat(os.getcwd())
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(utils.os, 'stat', fake_stat)
    return Nas


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


# --------------------------------------------------------------------------- Pfade

def test_source_name_for_share_root_and_subfolders():
    assert utils.source_name('\\\\NAS\\Fotos') == 'Fotos'
    assert utils.source_name('\\\\NAS\\Fotos\\') == 'Fotos'
    assert utils.source_name('\\\\NAS\\Fotos\\2024') == '2024'
    assert utils.source_name('D:\\') == 'D'


def test_unc_root_and_location_name():
    assert utils.unc_root('\\\\nas\\backup\\PC\\Daten') == NAS
    assert utils.unc_root('//nas/backup/PC') == NAS
    assert utils.server_of(NAS + '\\PC') == 'nas'
    assert utils.is_network_path(NAS + '\\PC')
    assert utils.location_name(NAS + '\\PC') == f"Netzwerkfreigabe {NAS}"


def test_local_paths_unchanged(tmp_path):
    assert utils.location_status(str(tmp_path)) == ('ok', None)
    assert utils.drive_available(str(tmp_path))
    assert not utils.is_network_path(str(tmp_path))
    assert utils.location_name(str(tmp_path)).startswith('Laufwerk ')
    assert utils.path_state(str(tmp_path / 'fehlt')) == 'missing'


# --------------------------------------------------------------------------- Erreichbarkeit

def test_hanging_nas_does_not_block_ui(fake_nas):
    fake_nas.gate = threading.Event()
    fake_nas.error = _win_error(53, 'Der Netzwerkpfad wurde nicht gefunden.')
    started = time.monotonic()
    state, message = utils.location_status(NAS + '\\PC', wait=0.2)
    assert state == 'pending' and 'antwortet nicht' in message
    # Weitere Abfragen während derselben Prüfung warten nicht erneut – insgesamt höchstens UI_WAIT
    assert utils.path_state(NAS + '\\PC\\a.txt', wait=0.2) == 'pending'
    assert time.monotonic() - started < 0.6
    assert utils.disk_usage(NAS + '\\PC') is None
    assert utils.path_state(NAS + '\\PC\\b.txt') == 'pending'
    assert time.monotonic() - started < utils.UI_WAIT + 0.4
    assert fake_nas.calls == 1
    fake_nas.gate.set()
    deadline = time.monotonic() + 5
    while utils.location_status(NAS, wait=0)[0] == 'pending' and time.monotonic() < deadline:
        time.sleep(0.02)
    state, message = utils.location_status(NAS + '\\PC', wait=0)
    assert state == 'error' and 'nicht gefunden' in message and 'IP-Adresse' in message


def test_slow_nas_is_awaited_by_backup_run(fake_nas, monkeypatch):
    fake_nas.gate = threading.Event()
    threading.Timer(0.4, fake_nas.gate.set).start()
    monkeypatch.setattr(backup, 'NET_WAIT', 5.0)
    assert backup._wait_for(NAS + '\\PC') is None


@pytest.mark.parametrize('code,state,text', [
    (1326, 'login', 'anmelden'),
    (5, 'login', 'anmelden'),
    (1272, 'login', 'Gastzugang'),
    (1219, 'error', 'anderen Benutzer'),
    (67, 'error', 'Namen der Freigabe'),
    (384, 'error', 'SMB1'),
    (0x80090006 - 2 ** 32, 'error', 'Signierung'),  # HRESULTs kommen als negative Zahl
])
def test_network_error_messages(fake_nas, code, state, text):
    fake_nas.error = _win_error(code)
    got_state, message = utils.location_status(NAS + '\\PC', wait=2)
    assert got_state == state and text in message


def test_backup_to_unreachable_nas_fails_with_reason(tmp_path, fake_nas):
    fake_nas.error = _win_error(53)
    _write(tmp_path / 'proj' / 'a.txt', 'x')
    result = backup.run_backup(sources=[str(tmp_path / 'proj')], target=NAS + '\\PC', profile='p')
    assert result.code == backup.FAILED and 'nicht gefunden' in result.message


def test_unreachable_network_source_is_skipped_others_are_saved(tmp_path, fake_nas):
    fake_nas.error = _win_error(53)
    src, dest = tmp_path / 'proj', tmp_path / 'ziel'
    _write(src / 'a.txt', 'x')
    result = backup.run_backup(sources=[NAS + '\\Fotos', str(src)], target=str(dest), profile='p')
    assert result.code == backup.PARTIAL and result.copied == 1
    assert (dest / 'proj' / 'a.txt').exists()
    assert any(path == NAS + '\\Fotos' and 'nicht gefunden' in msg for path, msg in result.errors)


# --------------------------------------------------------------------------- NAS-Systemordner

def test_nas_system_folders_are_never_copied(tmp_path):
    src, dest = tmp_path / 'share', tmp_path / 'ziel'
    _write(src / 'foto.jpg', 'bild')
    _write(src / 'ordner' / 'notiz.txt', 'text')
    _write(src / 'ordner' / '@eaDirectory.txt', 'echte Datei mit ähnlichem Namen')
    for junk in ('#snapshot/GMT+01_2026-01-01/foto.jpg', '#recycle/alt.txt', 'ordner/@eaDir/foto.jpg/SYNOFILE',
                 '@Recently-Snapshot/x.txt', '.zfs/snapshot/daily/foto.jpg', '$RECYCLE.BIN/x', '.DS_Store',
                 'ordner/.Trash-1000/files/x'):
        _write(src / junk, 'system')
    result = backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    assert result.code == backup.OK
    copied = sorted(os.path.relpath(os.path.join(r, f), dest) for r, _d, fs in os.walk(dest) for f in fs)
    assert copied == [os.path.join('share', 'foto.jpg'), os.path.join('share', 'ordner', '@eaDirectory.txt'),
                      os.path.join('share', 'ordner', 'notiz.txt')]


def test_recovery_does_not_bring_back_nas_thumbnails(tmp_path):
    src, dest = tmp_path / 'proj', tmp_path / 'ziel'
    _write(src / 'a.txt', 'x')
    backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    _write(dest / 'proj' / '@eaDir' / 'a.txt' / 'SYNOPHOTO_THUMB_M.jpg', 'thumb')
    (src / 'a.txt').unlink()
    result = backup.run_recovery(sources=[str(src)], target=str(dest), profile='p')
    assert result.code == backup.OK and (src / 'a.txt').exists()
    assert not (src / '@eaDir').exists()


# --------------------------------------------------------------------------- Kopierfehler

def _fail_copies_into(monkeypatch, folder, error, damage):
    real = backup.copy_file

    def fake_copy(src, dst):
        if os.path.normcase(str(dst)).startswith(os.path.normcase(str(folder))):
            if damage:
                with open(dst, 'wb') as f:  # wie ein abgebrochener Kopiervorgang: Ziel schon gekürzt
                    f.write(b'halb')
            raise error
        return real(src, dst)

    monkeypatch.setattr(backup, 'copy_file', fake_copy)


def test_failed_copy_keeps_snapshot_when_target_was_damaged(tmp_path, monkeypatch):
    src, dest = tmp_path / 'proj', tmp_path / 'ziel'
    _write(src / 'film.mkv', 'alte Version')
    backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    _write(src / 'film.mkv', 'neue, längere Version')
    _fail_copies_into(monkeypatch, dest, _win_error(223, 'Datei zu groß'), damage=True)
    result = backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    assert result.code == backup.PARTIAL and result.copied == 0
    assert '4 GB' in result.errors[0][1]
    assert result.run_id, "der Snapshot der alten Version muss als Lauf erhalten bleiben"
    code, _report = versions.rollback_run(result.run_id)
    assert code == 0 and (dest / 'proj' / 'film.mkv').read_text(encoding='utf-8') == 'alte Version'


def test_failed_copy_without_damage_drops_snapshot(tmp_path, monkeypatch):
    src, dest = tmp_path / 'proj', tmp_path / 'ziel'
    _write(src / 'a.txt', 'alt')
    backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    _write(src / 'a.txt', 'neu und länger')
    _fail_copies_into(monkeypatch, dest, _win_error(32, 'Datei wird verwendet'), damage=False)
    result = backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    assert result.code == backup.PARTIAL and result.run_id is None
    assert 'anderen Programm' in result.errors[0][1]
    assert (dest / 'proj' / 'a.txt').read_text(encoding='utf-8') == 'alt'


def test_lost_connection_ends_run_instead_of_failing_every_file(tmp_path, monkeypatch):
    src, dest = tmp_path / 'proj', tmp_path / 'ziel'
    for i in range(20):
        _write(src / f'{i:02}.txt', 'x')
    _fail_copies_into(monkeypatch, dest, _win_error(64, 'Netzwerkname nicht mehr verfügbar'), damage=False)
    result = backup.run_backup(sources=[str(src)], target=str(dest), profile='p', hdd_mode=True)
    assert result.code == backup.FAILED and len(result.errors) == 1
    assert 'Netzwerkverbindung unterbrochen' in result.message


def test_unwritable_target_is_detected_before_copying(tmp_path):
    assert 'kann nicht geschrieben werden' in backup._probe_target(str(tmp_path / 'gibt-es-nicht'))
    assert backup._probe_target(str(tmp_path)) is None
    assert os.listdir(tmp_path) == []  # Testdatei wieder entfernt


# --------------------------------------------------------------------------- Geschwindigkeit

def test_analysis_reads_target_folders_instead_of_every_file(tmp_path, monkeypatch):
    src, dest = tmp_path / 'proj', tmp_path / 'ziel'
    for i in range(30):
        _write(src / 'sub' / f'{i}.txt', 'x')
    backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    real_stat, calls = os.stat, []

    def counting_stat(path, *a, **kw):
        calls.append(os.fspath(path))
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(os, 'stat', counting_stat)
    result = backup.run_backup(sources=[str(src)], target=str(dest), profile='p')
    assert result.code == backup.OK and result.skipped == 30
    assert not [c for c in calls if c.lower().endswith('.txt')]
