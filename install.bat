@echo off
rem ===========================================================================
rem  Backup Manager - Installation / Update
rem
rem  Prueft alle Abhaengigkeiten und installiert fehlende automatisch:
rem    1. Python (>= 3.9 mit tkinter) - wird bei Bedarf installiert
rem       (zuerst per winget, sonst Download von python.org mit Signaturpruefung)
rem    2. Eigene virtuelle Umgebung .venv (unabhaengig vom System-Python)
rem    3. Pakete aus requirements.txt (customtkinter, pillow, ...) - immer aktuell
rem    4. Selbsttest
rem    5. Verknuepfungen (Desktop + Startmenue)
rem
rem  Einfach erneut ausfuehren, um Pakete zu aktualisieren oder nach einem
rem  Python-Update / Umzug auf einen anderen PC alles zu reparieren.
rem
rem  Optionen:
rem    install.bat /auto    ohne Rueckfragen (keine Verknuepfungen, kein Start)
rem    install.bat /reset   virtuelle Umgebung komplett neu aufbauen
rem ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion
title Backup Manager - Installation
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"
set "VENV=%APP_DIR%\.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "VPYW=%VENV%\Scripts\pythonw.exe"
set "REQ=%APP_DIR%\requirements.txt"
set "PY_VERSION=3.12.10"
set "PY_WINGET_ID=Python.Python.3.12"
set "PY_CHECK=import sys, tkinter, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
set "TMPF=%TEMP%\backupmanager_install_%RANDOM%.txt"

rem --- Schreibrechte pruefen (z. B. C:\Program Files) - sonst als Administrator neu starten
set "WTEST=%APP_DIR%\.schreibtest_%RANDOM%.tmp"
(echo test> "%WTEST%") >nul 2>&1
if exist "%WTEST%" (
    del "%WTEST%" >nul 2>&1
) else (
    echo.
    echo  Fuer diesen Ordner werden Administratorrechte benoetigt - Windows fragt gleich nach.
    set "BM_SELF=%~f0"
    set "BM_ARGS=%*"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$q=[char]34; Start-Process -FilePath $env:ComSpec -ArgumentList ('/c ' + $q + $q + $env:BM_SELF + $q + ' ' + $env:BM_ARGS + $q) -Verb RunAs"
    exit /b 0
)
set "IS_ADMIN=0"
net session >nul 2>&1 && set "IS_ADMIN=1"

set "AUTO=0"
set "RESET=0"
for %%A in (%*) do (
    if /i "%%~A"=="/auto" set "AUTO=1"
    if /i "%%~A"=="/quiet" set "AUTO=1"
    if /i "%%~A"=="/reset" set "RESET=1"
)

echo.
echo  ==============================================================
echo    Backup Manager - Installation und Update
echo  ==============================================================
echo    Ordner: %APP_DIR%
echo.

rem ---------------------------------------------------------------- 1. Python
echo  [1/5] Python suchen ...
call :find_python
if not defined PY (
    echo        Kein passendes Python gefunden - es wird jetzt installiert.
    call :install_python
    call :find_python
)
if not defined PY (
    echo.
    echo  FEHLER: Python konnte nicht installiert werden.
    echo  Bitte Python 3.12 manuell von https://www.python.org/downloads/ installieren
    echo  ^(Haken bei "tcl/tk" und "Add python.exe to PATH" setzen^) und install.bat erneut starten.
    goto :fail
)
echo        Gefunden: !PY_DESC!

rem ---------------------------------------------------------------- 2. venv
echo.
echo  [2/5] Virtuelle Umgebung pruefen ...
if "%RESET%"=="1" if exist "%VENV%" (
    echo        /reset: Umgebung wird neu aufgebaut.
    rmdir /s /q "%VENV%"
)
if exist "%VPY%" (
    "%VPY%" -c "%PY_CHECK%" >nul 2>&1
    if errorlevel 1 (
        echo        Vorhandene Umgebung ist defekt oder gehoert zu einem anderen PC - wird neu erstellt.
        rmdir /s /q "%VENV%"
    ) else (
        echo        Vorhandene Umgebung ist in Ordnung.
    )
)
if not exist "%VPY%" (
    echo        Erstelle .venv ...
    %PY% -m venv "%VENV%"
    if errorlevel 1 (
        echo  FEHLER: Die virtuelle Umgebung konnte nicht erstellt werden.
        goto :fail
    )
)

rem ---------------------------------------------------------------- 3. Pakete
echo.
echo  [3/5] Pakete installieren / aktualisieren ...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check --quiet
if errorlevel 1 echo        Hinweis: pip konnte nicht aktualisiert werden - wird mit vorhandener Version fortgesetzt.
"%VPY%" -m pip install --upgrade --upgrade-strategy eager -r "%REQ%" --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo  FEHLER: Die Pakete konnten nicht installiert werden.
    echo  Besteht eine Internetverbindung? Bei Firmen-Proxys ggf. HTTPS_PROXY setzen.
    goto :fail
)

rem ---------------------------------------------------------------- 4. Selbsttest
echo.
echo  [4/5] Selbsttest ...
"%VPY%" "%APP_DIR%\engine\start.py" --selftest
if errorlevel 1 (
    echo  FEHLER: Der Selbsttest ist fehlgeschlagen ^(siehe Meldungen oben^).
    goto :fail
)
rem Programmdateien vorkompilieren (im schreibgeschuetzten Programmordner schneller Start)
"%VPY%" -m compileall -q "%APP_DIR%\engine" >nul 2>&1

rem ---------------------------------------------------------------- 5. Verknuepfungen
echo.
echo  [5/5] Verknuepfungen ...
if "%AUTO%"=="1" (
    echo        Uebersprungen ^(/auto^).
) else (
    choice /c JN /n /m "       Verknuepfung auf dem Desktop und im Startmenue anlegen? [J/N] "
    if errorlevel 2 (
        echo        Uebersprungen.
    ) else (
        set "SC_ARGS=--pin"
        if "%IS_ADMIN%"=="1" set "SC_ARGS=--pin --all-users"
        "%VPY%" "%APP_DIR%\engine\start.py" --create-shortcuts !SC_ARGS!
    )
)

echo.
echo  ==============================================================
echo    Fertig - der Backup Manager ist einsatzbereit.
echo    Start: Desktop-Verknuepfung oder gui\backup_manager.vbs
echo  ==============================================================
echo.
if "%AUTO%"=="0" (
    choice /c JN /n /m "  Backup Manager jetzt starten? [J/N] "
    if not errorlevel 2 start "" "%VPYW%" "%APP_DIR%\engine\start.py"
)
if exist "%TMPF%" del "%TMPF%" >nul 2>&1
endlocal
exit /b 0

:fail
echo.
if exist "%TMPF%" del "%TMPF%" >nul 2>&1
if "%AUTO%"=="0" pause
endlocal
exit /b 1


rem ===========================================================================
rem  Unterprogramme
rem ===========================================================================

:find_python
rem Sucht ein Python >= 3.9 mit tkinter/venv. Bevorzugt 3.12 (am besten getestet).
set "PY="
set "PY_DESC="
for %%V in (3.12 3.13 3.11 3.14 3.10) do if not defined PY call :try_python py -%%V
if not defined PY call :try_python py -3
if not defined PY call :try_python python
if not defined PY call :try_python python3
if not defined PY (
    for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "%SystemDrive%\Python3*") do (
        if not defined PY if exist "%%~D\python.exe" call :try_python "%%~D\python.exe"
    )
)
exit /b 0

:try_python
rem %* = Aufruf, z. B.  py -3.12  oder  "C:\Pfad\python.exe"
%* -c "%PY_CHECK%" >nul 2>&1
if errorlevel 1 exit /b 1
%* -c "import sys; print(sys.version.split()[0] + '  (' + sys.executable + ')')" > "%TMPF%" 2>nul
set /p PY_DESC=<"%TMPF%"
set "PY=%*"
exit /b 0

:install_python
rem Mit Administratorrechten fuer alle Benutzer installieren (noetig fuer C:\Program Files)
set "WG_SCOPE=user"
set "PY_ALLUSERS=0"
if "%IS_ADMIN%"=="1" (
    set "WG_SCOPE=machine"
    set "PY_ALLUSERS=1"
)
rem --- Variante 1: winget (Windows 10/11)
where winget >nul 2>&1
if not errorlevel 1 (
    echo        Installiere Python %PY_WINGET_ID% per winget ...
    winget install -e --id %PY_WINGET_ID% --scope !WG_SCOPE! --silent --accept-package-agreements --accept-source-agreements
    call :find_python
    if defined PY exit /b 0
    echo        winget hat nicht funktioniert - versuche den Download von python.org.
)
rem --- Variante 2: offizieller Installer von python.org
set "ARCH=amd64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ARCH=arm64"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "ARCH=x86"
set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%-%ARCH%.exe"
if "%ARCH%"=="x86" set "PY_URL=https://www.python.org/ftp/python/%PY_VERSION%/python-%PY_VERSION%.exe"
set "PY_SETUP=%TEMP%\python-%PY_VERSION%-setup.exe"
echo        Lade %PY_URL% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:PY_URL -OutFile $env:PY_SETUP"
if not exist "%PY_SETUP%" (
    echo        Download fehlgeschlagen.
    exit /b 1
)
rem Nur einen gueltig signierten Installer der Python Software Foundation ausfuehren
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = Get-AuthenticodeSignature $env:PY_SETUP; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'Python Software Foundation') { exit 1 }"
if errorlevel 1 (
    echo        Signatur des Installers ist ungueltig - Abbruch.
    del "%PY_SETUP%" >nul 2>&1
    exit /b 1
)
echo        Installiere Python %PY_VERSION% ^(dauert ca. 1 Minute^) ...
"%PY_SETUP%" /quiet InstallAllUsers=%PY_ALLUSERS% PrependPath=1 Include_tcltk=1 Include_pip=1 Include_launcher=1 Include_test=0
set "PY_RC=%ERRORLEVEL%"
del "%PY_SETUP%" >nul 2>&1
if not "%PY_RC%"=="0" echo        Python-Installer meldete Code %PY_RC%.
exit /b 0
