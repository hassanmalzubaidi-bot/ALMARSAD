@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo مزامنة Excel من الموقع الحيّ...
python pipeline\site_to_excel.py
echo.
echo تم. افتح Power BI واضغط Refresh.
pause
