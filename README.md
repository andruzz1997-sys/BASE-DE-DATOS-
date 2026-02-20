# SERVISKYNET TELECOMUNICACIONES S.A.S.

Sistema web local para control empresarial con base de datos SQLite (`empresa.db`).

## Funciones principales

- Inicio de sesion con usuario y contrasena.
- Roles:
  - `admin`: acceso total.
  - `usuario`: registra ventas y base inicial.
- Registro de ventas diarias.
- Registro de base inicial.
- Control del sobre (admin).
- Guardado/cierre de cuenta diaria y reinicio de contadores abiertos.
- Verificacion semanal caja vs sobre (admin).
- Reportes semanal, quincenal y mensual (admin).
- Estadisticas de ventas y certificados con filtro por fechas (admin).
- Descarga de PDF de estadisticas por rango de fechas (admin).
- Historial de cuentas guardadas con edicion solo admin.
- Gestion de productos (admin).
- Control de certificados (admin).
- Control de internet (admin).

## Credenciales iniciales

- `admin` / `Pisoton5920`
- `usuario` / `usuario123`

Al iniciar por primera vez, cambia estas contrasenas directamente en base de datos si deseas mayor seguridad.

## Requisitos

- Python 3.10+ (recomendado)

## Instalacion

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecucion

```bash
python app.py
```

Tambien puedes usar doble clic en:

- `iniciar_sistema.bat` para arrancar la app.
- `iniciar_sistema_red.bat` para arrancar en red local (acceso desde otros PCs).
- `detener_sistema.bat` para detenerla.

Abrir en navegador:

`http://127.0.0.1:5000`

## Clonar y ejecutar en otro PC (desde GitHub)

1. Clona el repositorio completo.
2. Abre la carpeta del proyecto.
3. Ejecuta `iniciar_serviskynet.bat`.

El script ahora hace esto automaticamente:
- Si existe ejecutable standalone, lo usa.
- Si no existe, arranca en modo Python.
- Detecta Python 3.10+ sin depender de una ruta fija (3.12/3.13/3.14).
- Crea `.venv` e instala dependencias.
- Valida que existan `templates\login.html` y `static\style.css` antes de iniciar.

Si aparece error de plantilla faltante (`TemplateNotFound: login.html`), el problema no es Flask:
faltan carpetas del repositorio. Debes tener en el clon:
- `templates\`
- `static\`
- `app.py`

## Ejecutar en otro PC sin instalar Python

Tu proyecto ya puede ejecutarse sin Python en la maquina destino usando el ejecutable compilado.
Flujo principal recomendado: `preparar_entrega_sin_python.bat`

### Flujo principal (recomendado)

1. En el PC principal ejecuta:

```bat
preparar_entrega_sin_python.bat
```

2. Se crea la carpeta:

`dist\entrega_sin_python`

3. Copia esa carpeta al otro PC.
4. En el otro PC usa:
- `ServiskynetControl_portable.zip` (recomendado), o
- `Instalador_ServiskynetControl.exe` (si fue generado).

### Opcion recomendada: instalador

1. En el PC de desarrollo, ejecuta:

```bat
generar_instalador.bat
```

2. Si tienes Inno Setup 6 instalado, se genera:

`dist\installer\Instalador_ServiskynetControl.exe`

3. Copia ese archivo al otro PC y ejecutalo.
4. En el otro PC abre el acceso directo "Serviskynet Control".

No necesitas instalar Python en el otro PC.

### Opcion portable (sin instalar)

El mismo script genera:

`dist\ServiskynetControl_portable.zip`

1. Copia ese ZIP al otro PC.
2. Descomprime.
3. Ejecuta `iniciar_serviskynet.bat`.

Tampoco requiere Python en el otro PC.

### Nota de datos

- La app instalada guarda su base en:
  `%LOCALAPPDATA%\ServiskynetControl\empresa.db`
- Si cambias de PC y quieres llevar historial, copia esa base al nuevo equipo.

## Servidor estable (todo el dia)

- El arranque usa `waitress` (servidor de produccion) si esta instalado.
- `iniciar_sistema.bat` ahora reinicia automaticamente el servidor si se cae.
- Para cerrarlo de forma manual, usa `detener_sistema.bat`.

## Actualizaciones entre PCs

- Si ejecutas `ServiskynetControl.exe`, los cambios de codigo **no** se reflejan hasta recompilar y volver a copiar/instalar.
- Para ver cambios sin reinstalar, ejecuta desde codigo fuente con `iniciar_sistema.bat` en la carpeta sincronizada (por ejemplo OneDrive/Git).
- Si quieres usar el sistema desde otros PCs sin copiar carpetas, levanta el servidor en red:

```bat
set SERVISKYNET_HOST=0.0.0.0
set SERVISKYNET_PORT=5000
iniciar_sistema.bat
```

- Luego en el otro PC abre `http://IP_DEL_PC_SERVIDOR:5000`.

## Estructura

- `app.py`: backend, seguridad, rutas y consultas.
- `templates/index.html`: operacion diaria.
- `templates/reportes.html`: reportes.
- `templates/productos.html`: gestion de productos.
- `templates/certificados.html`: gestion de certificados.
- `templates/internet.html`: gestion de internet.
- `templates/login.html`: acceso al sistema.
- `static/style.css`: estilos.
- `empresa.db`: base de datos.
