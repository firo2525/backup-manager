Option Explicit

' Startet den Backup Manager ohne Konsolenfenster.
' Nutzt die von install.bat eingerichtete Umgebung (.venv). Fehlt sie,
' wird angeboten, install.bat auszuführen (installiert auch Python).

Dim sh, fso, basePath, pythonw, script, installer

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

basePath = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
pythonw = fso.BuildPath(basePath, ".venv\Scripts\pythonw.exe")
script = fso.BuildPath(basePath, "engine\start.py")
installer = fso.BuildPath(basePath, "install.bat")

If fso.FileExists(pythonw) Then
    sh.CurrentDirectory = basePath
    sh.Run """" & pythonw & """ """ & script & """", 0, False
Else
    If MsgBox("Der Backup Manager ist auf diesem PC noch nicht eingerichtet." & vbCrLf & vbCrLf & _
              "Jetzt install.bat ausführen? Python und alle benötigten Komponenten werden automatisch installiert.", _
              vbYesNo + vbQuestion, "Backup Manager") = vbYes Then
        sh.CurrentDirectory = basePath
        sh.Run """" & installer & """", 1, False
    End If
End If
