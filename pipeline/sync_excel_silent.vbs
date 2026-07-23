' تشغيل مزامنة Excel بصمت (بلا نافذة سوداء) — تستدعيه مهمة Windows المجدولة
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
proj = "C:\Users\roa44\OneDrive\Työpöytä\موقع المرصد - نشر محدث"
py = "C:\Users\roa44\AppData\Local\Programs\Python\Python313\python.exe"
log = proj & "\pipeline\sync_excel.log"
sh.CurrentDirectory = proj
sh.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
' 0 = نافذة مخفية · True = انتظر الانتهاء
cmd = """" & py & """ """ & proj & "\pipeline\site_to_excel.py"" > """ & log & """ 2>&1"
sh.Run "cmd /c " & cmd, 0, True
