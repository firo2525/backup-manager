@echo off
rem Baut die Installationsdatei dist\BackupManager-Setup-<Version>.exe
rem Nutzt eine eigene Build-Umgebung (installer\.build-venv) - die App-Umgebung bleibt unberuehrt.
setlocal
cd /d "%~dp0"
set "BV=%~dp0.build-venv"
if not exist "%BV%\Scripts\python.exe" (
    echo Erstelle Build-Umgebung ...
    py -3.12 -m venv "%BV%" 2>nul || python -m venv "%BV%"
)
if not exist "%BV%\Scripts\python.exe" (
    echo FEHLER: Python wurde nicht gefunden. Bitte zuerst ..\install.bat ausfuehren.
    pause
    exit /b 1
)
"%BV%\Scripts\python.exe" -m pip install --upgrade --quiet --disable-pip-version-check pip
"%BV%\Scripts\python.exe" -m pip install --upgrade --quiet --disable-pip-version-check pyinstaller customtkinter pillow darkdetect packaging
"%BV%\Scripts\python.exe" "%~dp0build_installer.py"
if errorlevel 1 (
    echo.
    echo FEHLER beim Bauen.
    pause
    exit /b 1
)
echo.
echo Die Installationsdatei liegt im Ordner dist.
if /i not "%~1"=="/auto" pause
exit /b 0
