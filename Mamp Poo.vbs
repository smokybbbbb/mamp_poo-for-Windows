Option Explicit
On Error Resume Next

Dim oShell, oFSO, strDir

Set oShell  = CreateObject("WScript.Shell")
Set oFSO    = CreateObject("Scripting.FileSystemObject")
strDir      = oFSO.GetParentFolderName(WScript.ScriptFullName)

oShell.CurrentDirectory = strDir

' run pythonw (no console window)
oShell.Run "pythonw.exe """ & strDir & "\main.py""", 0, False

If Err.Number <> 0 Then
    Err.Clear
    ' fallback to python
    oShell.Run "python """ & strDir & "\main.py""", 1, False
    If Err.Number <> 0 Then
        MsgBox "Python not found. Please install Python 3.10+ first." & Chr(13) & Chr(13) & _
               "Download: python.org/downloads" & Chr(13) & _
               "(check 'Add python.exe to PATH' during install)", _
               16, "Mamp Poo"
    End If
End If
