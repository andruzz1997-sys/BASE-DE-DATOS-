@echo off
setlocal EnableExtensions

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":5000 .*LISTENING"') do set RUNNING_PID=%%p

if defined RUNNING_PID (
    start "" "http://127.0.0.1:5000/login"
    exit /b 0
)

if exist "%~dp0ServiskynetControl.exe" (
    start "" "%~dp0ServiskynetControl.exe"
    timeout /t 2 /nobreak >nul
    start "" "http://127.0.0.1:5000/login"
    exit /b 0
)

if exist "%~dp0dist\ServiskynetControl\ServiskynetControl.exe" (
    start "" "%~dp0dist\ServiskynetControl\ServiskynetControl.exe"
    timeout /t 2 /nobreak >nul
    start "" "http://127.0.0.1:5000/login"
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    echo No se encontro ejecutable standalone.
    echo Iniciando modo desarrollo con Python...
    call "%~dp0iniciar_sistema.bat"
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if not errorlevel 1 (
    echo No se encontro ejecutable standalone.
    echo Iniciando modo desarrollo con Python...
    call "%~dp0iniciar_sistema.bat"
    exit /b %ERRORLEVEL%
)

echo No se encontro ServiskynetControl.exe y este equipo no tiene Python.
echo.
echo Para ejecutar sin Python:
echo 1. En el PC principal ejecuta generar_instalador.bat
echo 2. Copia al otro PC:
echo    - dist\ServiskynetControl_portable.zip   (recomendado), o
echo    - dist\installer\Instalador_ServiskynetControl.exe
echo 3. En el otro PC descomprime y usa iniciar_serviskynet.bat del paquete portable.
pause

endlocal
