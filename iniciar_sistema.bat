@echo off
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"
set "STOP_FLAG=%PROJECT_DIR%serviskynet.stop"
set "PYTHON_BIN="
set "PYTHON_ARGS="

if not exist "templates\login.html" (
    echo ERROR: No se encontro templates\login.html
    echo El repositorio esta incompleto. Debe incluir carpetas templates y static.
    echo Vuelve a clonar el proyecto completo y ejecuta de nuevo.
    pause
    exit /b 1
)

if not exist "static\style.css" (
    echo ERROR: No se encontro static\style.css
    echo El repositorio esta incompleto. Debe incluir carpetas templates y static.
    echo Vuelve a clonar el proyecto completo y ejecuta de nuevo.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" goto HAVE_VENV

for %%P in (
    "%LocalAppData%\Programs\Python\Python314\python.exe"
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python314\python.exe"
    "%ProgramFiles%\Python313\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
) do (
    if not defined PYTHON_BIN if exist %%~P set "PYTHON_BIN=%%~P"
)

if not defined PYTHON_BIN (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_BIN=py"
        set "PYTHON_ARGS=-3"
    )
)

if not defined PYTHON_BIN (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_BIN=python"
)

if not defined PYTHON_BIN (
    echo No se encontro Python 3 en el equipo.
    echo Instala Python 3.10 o superior y vuelve a intentar.
    pause
    exit /b 1
)

echo Creando entorno virtual...
"%PYTHON_BIN%" %PYTHON_ARGS% -m venv .venv
if errorlevel 1 (
    echo No fue posible crear el entorno virtual.
    pause
    exit /b 1
)

:HAVE_VENV
echo Instalando/actualizando dependencias...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo Error instalando dependencias.
    pause
    exit /b 1
)

if not defined SERVISKYNET_HOST set "SERVISKYNET_HOST=127.0.0.1"
if not defined SERVISKYNET_PORT set "SERVISKYNET_PORT=5000"
if not defined SERVISKYNET_THREADS set "SERVISKYNET_THREADS=8"

if exist "%STOP_FLAG%" del /f /q "%STOP_FLAG%" >nul 2>nul

echo.
echo Iniciando sistema en http://%SERVISKYNET_HOST%:%SERVISKYNET_PORT%
echo (deja esta ventana abierta mientras usas el sistema).
echo Usa detener_sistema.bat para cerrar correctamente.
echo.

:RUN_LOOP
if exist "%STOP_FLAG%" goto END

".venv\Scripts\python.exe" app.py
set "LAST_EXIT=%ERRORLEVEL%"

if exist "%STOP_FLAG%" goto END

echo.
echo El servidor se cerro inesperadamente (codigo %LAST_EXIT%).
echo Reintentando en 3 segundos...
timeout /t 3 /nobreak >nul
echo.
goto RUN_LOOP

:END
if exist "%STOP_FLAG%" del /f /q "%STOP_FLAG%" >nul 2>nul
echo Sistema detenido.
endlocal
