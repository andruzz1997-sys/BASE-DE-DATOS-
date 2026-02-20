@echo off
setlocal

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":5000 .*LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1
)

taskkill /IM ServiskynetControl.exe /F >nul 2>&1

endlocal
