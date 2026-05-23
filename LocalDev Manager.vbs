Option Explicit
On Error Resume Next

Dim oShell, oFSO, strDir

Set oShell  = CreateObject("WScript.Shell")
Set oFSO    = CreateObject("Scripting.FileSystemObject")
strDir      = oFSO.GetParentFolderName(WScript.ScriptFullName)

oShell.CurrentDirectory = strDir

' รัน pythonw (ไม่แสดง console window)
oShell.Run "pythonw.exe """ & strDir & "\main.py""", 0, False

If Err.Number <> 0 Then
    Err.Clear
    ' ลอง python ปกติ
    oShell.Run "python """ & strDir & "\main.py""", 1, False
    If Err.Number <> 0 Then
        MsgBox "ไม่พบ Python กรุณาติดตั้ง Python 3.10+ ก่อน" & Chr(13) & Chr(13) & _
               "ดาวน์โหลดได้ที่: python.org/downloads" & Chr(13) & _
               "(เลือก 'Add python.exe to PATH' ตอนติดตั้ง)", _
               16, "LocalDev Manager"
    End If
End If
