BACKUP MANAGER 2.1.2 – entwickelt von Firat Öztürk · https://konklave.info
=========================================================================

Sichert Ordner und Dateien inkrementell in ein Ziel (z. B. externe Festplatte).
Bevor eine Datei im Ziel überschrieben wird, wird die alte Version als Snapshot
aufbewahrt – jeder Lauf lässt sich später zurücksetzen. Auf Wunsch startet das
Programm mit Windows, läuft im Infobereich der Taskleiste und synchronisiert
regelmäßig automatisch.


INSTALLATION
------------
Variante A – Installationsprogramm (empfohlen, auch für andere PCs)
  dist\BackupManager-Setup-2.1.2.exe starten.
  - Installiert standardmäßig pro Benutzer nach
    %LOCALAPPDATA%\Programs\BackupManager - dafür sind KEINE Administrator-
    rechte nötig. Über "Ändern..." lässt sich auch ein anderer Ordner wählen,
    z. B. C:\Program Files\BackupManager für alle Benutzer (dafür fragt
    Windows dann nach Administratorrechten).
  - Kopiert die Programmdateien und führt install.bat aus: Python wird bei Bedarf
    automatisch installiert (winget bzw. python.org mit Signaturprüfung),
    danach alle Pakete in einer eigenen Umgebung (.venv).
  - Legt Verknüpfungen im Startmenü und (optional) auf dem Desktop an und
    versucht, das Programm an die Taskleiste anzuheften. Windows 11 erlaubt das
    Programmen nicht – dann zeigt der Installer, wie es per Rechtsklick geht.
  - Trägt sich unter Einstellungen → Apps ein (Deinstallation dort möglich).
  - Ohne Fenster: BackupManager-Setup-2.1.2.exe /S   (weitere Optionen:
    /D=Ordner  /nodesktop  /nopin  /nostart)

Variante B – portabel (Ordner kopieren)
  Den Ordner „BackupManager“ an einen beliebigen Ort kopieren und install.bat
  doppelklicken. Liegt der Ordner an einem geschützten Ort, fragt install.bat
  selbst nach Administratorrechten.

Update / Reparatur: Installer oder install.bat erneut ausführen. Pakete werden
aktualisiert; eine defekte oder von einem anderen PC stammende Umgebung wird
automatisch neu erstellt.   install.bat /reset   baut sie komplett neu auf.


WO LIEGEN MEINE DATEN?
----------------------
Installiert (C:\Program Files):  %LOCALAPPDATA%\BackupManager
                                 (config, logs, versions = Snapshots)
Portabel:                        im Programmordner (config, logs, versions)
Der Snapshot-Ordner lässt sich unter Einstellungen → „Speicherort der
Snapshots“ ändern; vorhandene Snapshots werden dabei mitverschoben.
Vor jedem Speichern der Profile wird eine Sicherung in config\backups abgelegt
(die letzten 10 Versionen).


STARTEN & HINTERGRUNDBETRIEB
----------------------------
- Startmenü / Desktop „Backup Manager“ (oder gui\backup_manager.vbs).
- Beim ersten Start fragt das Programm, ob es mit Windows starten soll. Dann
  läuft es unsichtbar im Infobereich (unten rechts neben der Uhr, ggf. hinter
  dem Pfeil ^) und synchronisiert alle dafür eingeschalteten Profile
  automatisch – standardmäßig alle 60 Minuten. Nicht angeschlossene Laufwerke
  werden übersprungen.
- Symbol im Infobereich: Klick = Fenster öffnen; Rechtsklick = Menü mit
  „Jetzt synchronisieren“, „Automatisch synchronisieren“ und „Beenden“.
- Das X minimiert in den Infobereich (abschaltbar in den Einstellungen).
- Ein zweiter Start öffnet einfach das bereits laufende Fenster.
- Ohne Oberfläche (z. B. Aufgabenplanung):  runner\start_backup.bat --profile NAME


BEDIENUNG
---------
Überall stehen kleine „?“-Symbole: Maus darüber zeigt eine ausführliche
Erklärung, ein Klick hält sie offen.

Übersicht       Kennzahlen, „Backup starten“, „Wiederherstellen“, Live-Fortschritt,
                automatische Synchronisierung (Status + „Jetzt alle synchronisieren“).
Quellen & Ziel  Quellen, Ziel, Optionen je Profil: HDD-Modus, Snapshots anlegen
                (abschaltbar), in Synchronisierung einbeziehen, Ausschlüsse.
Snapshots       Alle Läufe mit Größe und Status, Details, ältere Dateiversion
                speichern, Zurücksetzen, Löschen, Aufräumen.
Protokoll       Live-Log mit Filter.
Einstellungen   Farbschema, Autostart, Synchronisierung (15 Min. – 4 Std.),
                Infobereich, parallele Kopien, automatisches Aufräumen,
                Speicherort der Snapshots.
Über            Version, Entwickler, konklave.info.

Tastenkürzel: Strg+B Backup · Strg+1 … 6 Seiten · F5 Snapshots neu laden


SO FUNKTIONIERT ES
------------------
Backup      Kopiert nur fehlende, geänderte oder neuere Dateien (2 s Toleranz für
            FAT/exFAT). Vorher Analyse und Speicherplatz-Prüfung. Der eigene
            Snapshot-Ordner und die .venv werden nie mitgesichert. Kann die alte
            Version nicht gesichert werden, bleibt die Zieldatei unverändert.
            Ohne Snapshots (Profil-Option) wird direkt überschrieben.
Snapshot    versions\<run_id>\metadata.json + gesicherte alte Versionen.
            Status: OK · Teilweise · Fehlend · Leer.
Rollback    Überschriebene Dateien zurück aus dem Snapshot, neu angelegte löschen.
Recovery    Fehlende/abweichende Dateien aus dem Ziel zurück in die Quellen; in
            der Quelle neuere Dateien bleiben erhalten; selbst rückgängig machbar.


DEINSTALLATION
--------------
Einstellungen → Apps → „Backup Manager“ → Deinstallieren (oder Uninstall.exe
im Programmordner). Auf Wunsch werden auch Einstellungen, Logs und Snapshots
gelöscht. Die gesicherten Dateien im Backup-Ziel bleiben immer erhalten.


ENTWICKLUNG
-----------
Tests:        .venv\Scripts\python -m pip install -r requirements-dev.txt
              .venv\Scripts\python -m pytest
              (arbeiten nur in temporären Ordnern, siehe tests\conftest.py)
Installer:    installer\build_installer.bat  →  dist\BackupManager-Setup-<Version>.exe
              (eigene Build-Umgebung installer\.build-venv, PyInstaller)
Version:      engine\version.py
