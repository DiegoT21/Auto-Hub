Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
setupBat = root & "\scripts\first_run_setup.bat"

If Not fso.FileExists(pythonw) Then
    sh.Run "cmd /c """ & setupBat & """", 0, True
End If

If fso.FileExists(pythonw) Then
    sh.CurrentDirectory = root
    sh.Run """" & pythonw & """ app\main.py", 0, False
End If
