@echo off
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

set "VENV_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo No se encontro el entorno virtual en:
    echo %VENV_PYTHON%
    echo.
    echo Crea el entorno y dependencias antes de empaquetar.
    echo Ejemplo:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

echo [1/5] Validando PyInstaller...
"%VENV_PYTHON%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo PyInstaller no esta instalado. Instalando...
    "%VENV_PYTHON%" -m pip install pyinstaller
    if errorlevel 1 (
        echo Error instalando PyInstaller.
        exit /b 1
    )
)

echo [2/5] Limpiando compilaciones anteriores...
if exist "build\ServiskynetControl" rmdir /s /q "build\ServiskynetControl"
if exist "dist\ServiskynetControl" rmdir /s /q "dist\ServiskynetControl"
if exist "dist\installer" rmdir /s /q "dist\installer"
if exist "dist\ServiskynetControl_portable.zip" del /f /q "dist\ServiskynetControl_portable.zip"

echo [3/5] Compilando ejecutable sin Python externo...
"%VENV_PYTHON%" -m PyInstaller --noconfirm --clean "ServiskynetControl.spec"
if errorlevel 1 (
    echo Error compilando con PyInstaller.
    exit /b 1
)

if not exist "dist\ServiskynetControl\ServiskynetControl.exe" (
    echo No se encontro dist\ServiskynetControl\ServiskynetControl.exe
    exit /b 1
)

copy /Y "iniciar_serviskynet.bat" "dist\ServiskynetControl\" >nul
copy /Y "detener_serviskynet.bat" "dist\ServiskynetControl\" >nul

echo [4/5] Creando paquete portable...
set "ZIP_OK=0"
for /L %%I in (1,1,5) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Compress-Archive -Path 'dist\ServiskynetControl\*' -DestinationPath 'dist\ServiskynetControl_portable.zip' -Force -ErrorAction Stop; exit 0 } catch { exit 1 }"
    if not errorlevel 1 (
        set "ZIP_OK=1"
        goto ZIP_DONE
    )
    timeout /t 2 /nobreak >nul
)

:ZIP_DONE
if not "%ZIP_OK%"=="1" (
    echo No se pudo crear el ZIP portable despues de varios intentos.
)

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if exist "%ISCC%" (
    echo [5/5] Generando instalador .exe...
    "%ISCC%" "installer.iss"
    if errorlevel 1 (
        echo Error generando instalador con Inno Setup.
        exit /b 1
    )
) else (
    echo [5/5] Inno Setup no encontrado. Se omite instalador.
    echo         Puedes instalar Inno Setup 6 para generar dist\installer\Instalador_ServiskynetControl.exe
)

echo.
echo Compilacion finalizada.
if exist "dist\installer\Instalador_ServiskynetControl.exe" (
    echo - Instalador listo: dist\installer\Instalador_ServiskynetControl.exe
)
if exist "dist\ServiskynetControl_portable.zip" (
    echo - Portable listo:   dist\ServiskynetControl_portable.zip
)
echo.
echo En otro PC no necesitas Python.
echo Ejecuta el instalador o descomprime el portable y abre iniciar_serviskynet.bat.
exit /b 0
