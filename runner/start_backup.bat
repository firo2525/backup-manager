@echo off
rem Backup ohne Oberflaeche, z. B. fuer die Windows-Aufgabenplanung.
rem   start_backup.bat --profile camki      Profil aus config\profiles.json sichern
rem   start_backup.bat                      Quellen/Ziel aus config\sources.txt und target.txt
rem   start_backup.bat --profile Extern --hdd
rem Exit-Code: 0 = OK, 1 = Fehler, 2 = abgebrochen, 3 = mit Fehlern bei einzelnen Dateien
setlocal
set "BASE=%~dp0.."
set "PY=%BASE%\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo FEHLER: Die Programmumgebung fehlt. Bitte zuerst install.bat ausfuehren.
    exit /b 1
)
"%PY%" "%BASE%\engine\backup.py" %*
exit /b %ERRORLEVEL%
