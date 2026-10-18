"""Baut dist/BackupManager-Setup-<Version>.exe (Aufruf über build_installer.bat)."""
import os
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from engine.version import APP_NAME, DEVELOPER, VERSION  # noqa: E402

BUILD = os.path.join(HERE, "build")
DIST = os.path.join(ROOT, "dist")
ICON = os.path.join(ROOT, "engine", "ui", "assets", "app.ico")
# Nur Programmdateien – keine Einstellungen, Snapshots, Logs oder .venv
INCLUDE = ["engine", "gui", "runner", "install.bat", "requirements.txt", "README.txt"]
SKIP_DIRS = {"__pycache__"}


def make_payload():
    os.makedirs(BUILD, exist_ok=True)
    path = os.path.join(BUILD, "payload.zip")
    count = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for item in INCLUDE:
            full = os.path.join(ROOT, item)
            if os.path.isfile(full):
                z.write(full, item)
                count += 1
                continue
            for root, dirs, files in os.walk(full):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for f in files:
                    if f.endswith((".pyc", ".pyo")):
                        continue
                    src = os.path.join(root, f)
                    z.write(src, os.path.relpath(src, ROOT).replace(os.sep, "/"))
                    count += 1
    print(f"payload.zip: {count} Dateien, {os.path.getsize(path) // 1024} KB")
    return path


def version_file():
    nums = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704B0', [
      StringStruct('CompanyName', '{DEVELOPER}'),
      StringStruct('FileDescription', '{APP_NAME} – Installation'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'BackupManager-Setup'),
      StringStruct('LegalCopyright', '© {DEVELOPER} · konklave.info'),
      StringStruct('OriginalFilename', 'BackupManager-Setup-{VERSION}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1031, 1200])])
  ]
)
"""
    path = os.path.join(BUILD, "version_info.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def main():
    payload = make_payload()
    vfile = version_file()
    name = f"BackupManager-Setup-{VERSION}"
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
            "--name", name, "--icon", ICON, "--version-file", vfile,
            "--add-data", f"{payload}{os.pathsep}.", "--add-data", f"{ICON}{os.pathsep}.",
            "--collect-data", "customtkinter", "--paths", ROOT,
            "--distpath", DIST, "--workpath", os.path.join(BUILD, "work"), "--specpath", BUILD,
            os.path.join(HERE, "setup.py")]
    print("Starte PyInstaller …")
    subprocess.run(args, check=True)
    exe = os.path.join(DIST, name + ".exe")
    print(f"\nFertig: {exe} ({os.path.getsize(exe) // (1024 * 1024)} MB)")


if __name__ == "__main__":
    main()
