@echo off
setlocal

set "PROJECT_DIR=%~dp0"
set "STOP_FLAG=%PROJECT_DIR%serviskynet.stop"
type nul > "%STOP_FLAG%"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /PID %%P /F >nul 2>nul
)

echo Solicitud de cierre enviada.
echo Sistema detenido (puerto 5000 liberado).
pause

endlocal
