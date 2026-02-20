@echo off
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

echo ===============================================
echo   SERVISKYNET - PREPARAR ENTREGA SIN PYTHON
echo ===============================================
echo.

call "%PROJECT_DIR%generar_instalador.bat"
if errorlevel 1 (
    echo.
    echo Fallo la generacion de paquetes.
    pause
    exit /b 1
)

set "DELIVERY_DIR=dist\entrega_sin_python"
if exist "%DELIVERY_DIR%" rmdir /s /q "%DELIVERY_DIR%"
mkdir "%DELIVERY_DIR%" >nul 2>nul

if exist "dist\ServiskynetControl_portable.zip" (
    copy /Y "dist\ServiskynetControl_portable.zip" "%DELIVERY_DIR%\" >nul
)

if exist "dist\installer\Instalador_ServiskynetControl.exe" (
    copy /Y "dist\installer\Instalador_ServiskynetControl.exe" "%DELIVERY_DIR%\" >nul
)

(
echo ENTREGA SIN PYTHON - PASOS
echo ==========================
echo.
echo Opcion recomendada:
echo 1. Copiar ServiskynetControl_portable.zip al otro PC.
echo 2. Descomprimir.
echo 3. Ejecutar iniciar_serviskynet.bat.
echo.
echo Opcion instalador ^(si existe^):
echo 1. Ejecutar Instalador_ServiskynetControl.exe.
echo 2. Abrir acceso directo "Serviskynet Control".
echo.
echo Nota:
echo - En el PC destino NO se necesita Python.
) > "%DELIVERY_DIR%\LEEME_ENTREGA.txt"

echo.
echo Entrega lista en: %PROJECT_DIR%%DELIVERY_DIR%
if exist "%DELIVERY_DIR%\ServiskynetControl_portable.zip" echo - ServiskynetControl_portable.zip
if exist "%DELIVERY_DIR%\Instalador_ServiskynetControl.exe" echo - Instalador_ServiskynetControl.exe
echo - LEEME_ENTREGA.txt
echo.
pause
exit /b 0

