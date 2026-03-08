@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul 2>&1

:: ============================================================
::   HPE Ambulancia Digital Twin — Setup completo + Arranque
::   Incluye: OSRM Docker (España + Colombia + México), broker
::   MQTT, centralita, backend FastAPI y apertura del dashboard
:: ============================================================

title HPE Digital Twin — Setup y Arranque

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║      HPE Ambulancia Digital Twin — Setup Completo       ║
echo  ║   OSRM (España + Colombia + México) + Aplicación Web    ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.

:: ── Directorio del script (independiente del CWD) ─────────────
set "SCRIPT_DIR=%~dp0"
set "DATA_DIR=%SCRIPT_DIR%osrm_data"
set "MAP_MERGED=hpe-alianza.osm.pbf"
set "MAP_OSRM=hpe-alianza.osrm"
set "OSRM_CONTAINER=osrm-hpe"
set "OSRM_PORT=5001"

:: ── Menú principal ─────────────────────────────────────────────
echo  Elige una opción:
echo.
echo    [1] Setup COMPLETO  — Descargar mapas + OSRM + Iniciar app
echo    [2] Solo iniciar    — OSRM ya procesado, arrancar servicio
echo    [3] Solo la app     — Sin OSRM (modo offline / OSRM externo)
echo    [4] Test OSRM       — Verificar que el servidor responde
echo    [5] Limpiar Docker  — Eliminar contenedor OSRM y datos
echo.
set /p OPCION="Opción (1-5): "

if "%OPCION%"=="1" goto SETUP_COMPLETO
if "%OPCION%"=="2" goto INICIAR_OSRM
if "%OPCION%"=="3" goto INICIAR_APP
if "%OPCION%"=="4" goto TEST_OSRM
if "%OPCION%"=="5" goto LIMPIAR
echo [ERROR] Opción no válida.
goto FIN

:: ════════════════════════════════════════════════════════════════
:SETUP_COMPLETO
:: ════════════════════════════════════════════════════════════════
echo.
echo ════════════════════════════════════════════════════════════
echo  PASO 0 — Verificando requisitos previos
echo ════════════════════════════════════════════════════════════
echo.

:: Verificar Docker
docker --version > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker no encontrado. Instala Docker Desktop desde:
    echo         https://www.docker.com/products/docker-desktop
    echo  Luego vuelve a ejecutar este script.
    goto FIN
)
docker info > nul 2>&1
if errorlevel 1 (
    echo [ERROR] El servicio Docker no está en ejecución.
    echo  Abre Docker Desktop y espera a que el motor arranque,
    echo  luego vuelve a ejecutar este script.
    goto FIN
)
echo [OK] Docker está disponible y en ejecución.

:: Detectar herramienta de descarga
where curl > nul 2>&1
if not errorlevel 1 (
    set "DOWNLOADER=curl"
    echo [OK] Descargador: curl
) else (
    where powershell > nul 2>&1
    if not errorlevel 1 (
        set "DOWNLOADER=powershell"
        echo [OK] Descargador: PowerShell (Invoke-WebRequest^)
    ) else (
        echo [ERROR] No se encontró curl ni PowerShell para descargar mapas.
        goto FIN
    )
)

:: Detectar osmium (WSL o nativo)
set "OSMIUM_ENGINE="
wsl osmium --version > nul 2>&1
if not errorlevel 1 (
    set "OSMIUM_ENGINE=wsl"
    echo [OK] osmium-tool encontrado: WSL
) else (
    osmium --version > nul 2>&1
    if not errorlevel 1 (
        set "OSMIUM_ENGINE=native"
        echo [OK] osmium-tool encontrado: nativo
    ) else (
        :: Intentar instalar osmium en WSL si WSL está disponible
        wsl uname > nul 2>&1
        if not errorlevel 1 (
            echo [INFO] Instalando osmium-tool en WSL...
            wsl sudo apt-get update -qq && wsl sudo apt-get install -y osmium-tool -qq
            wsl osmium --version > nul 2>&1
            if not errorlevel 1 (
                set "OSMIUM_ENGINE=wsl"
                echo [OK] osmium-tool instalado correctamente en WSL.
            ) else (
                echo [WARN] No se pudo instalar osmium en WSL.
                goto OSMIUM_DOCKER
            )
        ) else (
            goto OSMIUM_DOCKER
        )
    )
)
goto OSMIUM_OK

:OSMIUM_DOCKER
echo [INFO] WSL/osmium no disponibles. Se usará Docker para osmium.
docker pull minio/osmium-tool > nul 2>&1
if errorlevel 1 (
    echo [WARN] La imagen Docker de osmium no está disponible.
    echo        Ejecuta Paso B manualmente con Osmium instalado en Linux/WSL:
    echo.
    echo   osmium merge spain-latest.osm.pbf colombia-latest.osm.pbf ^
    echo          mexico-latest.osm.pbf -o hpe-alianza.osm.pbf
    echo.
    echo  Si solo necesitas España, escoge [2] para saltar la fusión.
    pause
    goto SUBOPCION_SOLO_SPAIN
)
set "OSMIUM_ENGINE=docker"
echo [OK] Usando imagen Docker para osmium.

:OSMIUM_OK

:: ── Crear directorio de datos ──────────────────────────────────
if not exist "%DATA_DIR%" (
    mkdir "%DATA_DIR%"
    echo [OK] Directorio de mapas creado: %DATA_DIR%
) else (
    echo [OK] Directorio de mapas existente: %DATA_DIR%
)

echo.
echo ════════════════════════════════════════════════════════════
echo  PASO A — Descarga de mapas OSM (puede tardar varios minutos)
echo ════════════════════════════════════════════════════════════
echo.
echo  Nota: Los tres ficheros pesan ~4-5 GB en total.
echo        Asegúrate de tener al menos 20 GB libres en disco.
echo.

call :DOWNLOAD_MAP "https://download.geofabrik.de/europe/spain-latest.osm.pbf"       "spain-latest.osm.pbf"
call :DOWNLOAD_MAP "https://download.geofabrik.de/south-america/colombia-latest.osm.pbf" "colombia-latest.osm.pbf"
call :DOWNLOAD_MAP "https://download.geofabrik.de/north-america/mexico-latest.osm.pbf"   "mexico-latest.osm.pbf"

echo.
echo ════════════════════════════════════════════════════════════
echo  PASO B — Fusionar mapas con Osmium
echo ════════════════════════════════════════════════════════════
echo.

if exist "%DATA_DIR%\%MAP_MERGED%" (
    echo [OK] Mapa fusionado ya existe (%MAP_MERGED%^). Saltando fusión.
    goto SKIP_MERGE
)

echo [INFO] Fusionando Spain + Colombia + Mexico → %MAP_MERGED%
echo        (Puede tardar 10-30 minutos según el hardware)...
echo.

if "%OSMIUM_ENGINE%"=="wsl" (
    :: Convertir ruta Windows → ruta WSL
    set "WSL_DATA=!DATA_DIR:\=/!"
    set "WSL_DATA=!WSL_DATA:C:=/mnt/c!"
    set "WSL_DATA=!WSL_DATA:D:=/mnt/d!"
    set "WSL_DATA=!WSL_DATA:E:=/mnt/e!"
    wsl osmium merge "!WSL_DATA!/spain-latest.osm.pbf" "!WSL_DATA!/colombia-latest.osm.pbf" "!WSL_DATA!/mexico-latest.osm.pbf" -o "!WSL_DATA!/%MAP_MERGED%"
) else if "%OSMIUM_ENGINE%"=="native" (
    osmium merge "%DATA_DIR%\spain-latest.osm.pbf" "%DATA_DIR%\colombia-latest.osm.pbf" "%DATA_DIR%\mexico-latest.osm.pbf" -o "%DATA_DIR%\%MAP_MERGED%"
) else if "%OSMIUM_ENGINE%"=="docker" (
    docker run --rm -v "%DATA_DIR%:/data" minio/osmium-tool merge /data/spain-latest.osm.pbf /data/colombia-latest.osm.pbf /data/mexico-latest.osm.pbf -o /data/%MAP_MERGED%
)

if errorlevel 1 (
    echo [ERROR] Falló la fusión de mapas. Revisa los ficheros descargados.
    goto FIN
)
echo [OK] Mapa fusionado → %MAP_MERGED%

:SKIP_MERGE

:: ════════════════════════════════════════════════════════════════
:PROCESAR_OSRM
:: ════════════════════════════════════════════════════════════════
echo.
echo ════════════════════════════════════════════════════════════
echo  PASO C — Preprocesar mapa con OSRM
echo ════════════════════════════════════════════════════════════
echo.
echo  NOTA: Cada paso puede tardar varios minutos y requiere RAM.
echo        El paso osrm-extract para un mapa de 3 países puede
echo        necesitar 16-32 GB de RAM en función del sistema.
echo.

:: Detener y eliminar contenedor existente si lo hay
docker stop %OSRM_CONTAINER% > nul 2>&1
docker rm   %OSRM_CONTAINER% > nul 2>&1

:: — Paso C.1: Extract ——————————————————————————————————
if not exist "%DATA_DIR%\%MAP_OSRM%" (
    echo [C.1/3] osrm-extract — Construyendo grafo de rutas...
    docker run -t -v "%DATA_DIR%:/data" osrm/osrm-backend ^
        osrm-extract -p /opt/car.lua /data/%MAP_MERGED%
    if errorlevel 1 (
        echo [ERROR] osrm-extract falló. Comprueba memoria disponible.
        goto FIN
    )
    echo [OK] Extract completado.
) else (
    echo [OK] Fichero .osrm ya existe, saltando extract.
)

:: — Paso C.2: Partition ———————————————————————————————
if not exist "%DATA_DIR%\%MAP_OSRM%.partition" (
    echo [C.2/3] osrm-partition — Particionando el grafo...
    docker run -t -v "%DATA_DIR%:/data" osrm/osrm-backend ^
        osrm-partition /data/%MAP_OSRM%
    if errorlevel 1 (
        echo [ERROR] osrm-partition falló.
        goto FIN
    )
    echo [OK] Partition completado.
) else (
    echo [OK] Partición ya existe, saltando.
)

:: — Paso C.3: Customize ———————————————————————————————
if not exist "%DATA_DIR%\%MAP_OSRM%.cell_metrics" (
    echo [C.3/3] osrm-customize — Personalizando pesos de rutas...
    docker run -t -v "%DATA_DIR%:/data" osrm/osrm-backend ^
        osrm-customize /data/%MAP_OSRM%
    if errorlevel 1 (
        echo [ERROR] osrm-customize falló.
        goto FIN
    )
    echo [OK] Customize completado.
) else (
    echo [OK] Métricas de celda ya existen, saltando.
)

goto INICIAR_OSRM

:: ════════════════════════════════════════════════════════════════
:INICIAR_OSRM
:: ════════════════════════════════════════════════════════════════
echo.
echo ════════════════════════════════════════════════════════════
echo  PASO D — Levantar servidor OSRM en Docker
echo ════════════════════════════════════════════════════════════
echo.

:: Verificar que los ficheros OSRM existen
if not exist "%DATA_DIR%\%MAP_OSRM%" (
    echo [ERROR] No se encontró el fichero OSRM procesado:
    echo         %DATA_DIR%\%MAP_OSRM%
    echo  Ejecuta la opción [1] (Setup completo) primero.
    goto FIN
)

:: Parar contenedor viejo si existe
docker stop %OSRM_CONTAINER% > nul 2>&1
docker rm   %OSRM_CONTAINER% > nul 2>&1

echo [INFO] Iniciando contenedor OSRM (puerto %OSRM_PORT%)...
docker run -d ^
    --name %OSRM_CONTAINER% ^
    -p %OSRM_PORT%:5000 ^
    -v "%DATA_DIR%:/data" ^
    osrm/osrm-backend ^
    osrm-routed --algorithm mld /data/%MAP_OSRM%

if errorlevel 1 (
    echo [ERROR] No se pudo iniciar el contenedor OSRM.
    goto FIN
)

echo [OK] Contenedor OSRM "%OSRM_CONTAINER%" arrancando en puerto %OSRM_PORT%...
echo [INFO] Esperando 8 segundos a que el servidor esté listo...
timeout /t 8 /nobreak > nul

:: Verificación rápida
curl -s "http://localhost:%OSRM_PORT%/route/v1/driving/-3.7038,40.4168;-3.6868,40.4812?overview=false" > nul 2>&1
if not errorlevel 1 (
    echo [OK] OSRM responde correctamente en http://localhost:%OSRM_PORT%
) else (
    echo [WARN] OSRM puede aún estar inicializando. Comprueba con:
    echo        curl "http://localhost:%OSRM_PORT%/route/v1/driving/-3.7038,40.4168;-3.6868,40.4812?overview=false"
)

goto INICIAR_APP

:: ════════════════════════════════════════════════════════════════
:INICIAR_APP
:: ════════════════════════════════════════════════════════════════
echo.
echo ════════════════════════════════════════════════════════════
echo  PASO E — Arrancando componentes de la aplicación
echo ════════════════════════════════════════════════════════════
echo.

cd /d "%SCRIPT_DIR%"

:: Detectar Python (python / python3)
python --version > nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
) else (
    python3 --version > nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=python3"
    ) else (
        echo [ERROR] Python no encontrado en el PATH.
        echo  Instala Python 3.10+ desde https://www.python.org/downloads/
        goto FIN
    )
)
echo [OK] Python: !PYTHON!

:: Instalar dependencias si no están
echo [INFO] Verificando dependencias Python...
!PYTHON! -c "import fastapi, socketio, sklearn" > nul 2>&1
if errorlevel 1 (
    echo [INFO] Instalando dependencias desde requirements.txt...
    !PYTHON! -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo [ERROR] Falló la instalación de dependencias.
        goto FIN
    )
    echo [OK] Dependencias instaladas.
) else (
    echo [OK] Dependencias ya instaladas.
)

echo.
echo [E.1/3] Iniciando Broker MQTT Local...
start "HPE — Broker MQTT" cmd /k "!PYTHON! local_broker.py"
timeout /t 3 /nobreak > nul

echo [E.2/3] Iniciando Servidor de Centralita...
start "HPE — Centralita" cmd /k "!PYTHON! central\server.py"
timeout /t 4 /nobreak > nul

echo [E.3/3] Iniciando Backend FastAPI (puerto 5000)...
start "HPE — Backend Web" cmd /k "!PYTHON! app.py"
timeout /t 6 /nobreak > nul

echo.
echo [INFO] Abriendo dashboard en el navegador...
start http://localhost:5000
timeout /t 1 /nobreak > nul
start http://localhost:5000/backup_dashboard

echo.
echo ════════════════════════════════════════════════════════════
echo  TODOS LOS SERVICIOS ACTIVOS
echo ════════════════════════════════════════════════════════════
echo.
echo   OSRM (Docker):    http://localhost:%OSRM_PORT%
echo   Dashboard:        http://localhost:5000
echo   Dashboard backup: http://localhost:5000/backup_dashboard
echo   Centralita API:   http://localhost:8000/api/backups/health
echo.
echo  Para verificar OSRM (Puerta del Sol → Hospital La Paz):
echo  curl "http://localhost:%OSRM_PORT%/route/v1/driving/-3.7038,40.4168;-3.6868,40.4812?overview=full^&geometries=geojson"
echo.
echo ════════════════════════════════════════════════════════════
goto FIN

:: ════════════════════════════════════════════════════════════════
:TEST_OSRM
:: ════════════════════════════════════════════════════════════════
echo.
echo ════════════════════════════════════════════════════════════
echo  TEST OSRM — Rutas de prueba (España, Colombia, México)
echo ════════════════════════════════════════════════════════════
echo.

where curl > nul 2>&1
if errorlevel 1 (
    echo [ERROR] curl es necesario para este test. Usa PowerShell manualmente.
    goto FIN
)

echo [1/3] España — Puerta del Sol → Hospital La Paz (Madrid):
curl -s "http://localhost:%OSRM_PORT%/route/v1/driving/-3.7038,40.4168;-3.6868,40.4812?overview=false" 2>&1 | find "Ok"
if not errorlevel 1 (echo     ✔ Ruta OK) else (echo     ✗ Sin respuesta)

echo.
echo [2/3] Colombia — Centro Bogotá → Hospital El Tunal:
curl -s "http://localhost:%OSRM_PORT%/route/v1/driving/-74.0721,4.7110;-74.1275,4.5960?overview=false" 2>&1 | find "Ok"
if not errorlevel 1 (echo     ✔ Ruta OK) else (echo     ✗ Sin respuesta)

echo.
echo [3/3] México — Zócalo → Hospital General (CDMX):
curl -s "http://localhost:%OSRM_PORT%/route/v1/driving/-99.1332,19.4326;-99.1510,19.4205?overview=false" 2>&1 | find "Ok"
if not errorlevel 1 (echo     ✔ Ruta OK) else (echo     ✗ Sin respuesta)

echo.
goto FIN

:: ════════════════════════════════════════════════════════════════
:LIMPIAR
:: ════════════════════════════════════════════════════════════════
echo.
echo [WARN] Esta opción eliminará el contenedor OSRM.
echo        Los ficheros de mapa en %DATA_DIR% NO se borrarán.
set /p CONFIRM="¿Confirmas? (s/N): "
if /i not "%CONFIRM%"=="s" goto FIN

docker stop %OSRM_CONTAINER% > nul 2>&1
docker rm   %OSRM_CONTAINER% > nul 2>&1
echo [OK] Contenedor "%OSRM_CONTAINER%" eliminado.
echo  Para borrar también los mapas (>20 GB), elimina manualmente:
echo  %DATA_DIR%
goto FIN

:: ════════════════════════════════════════════════════════════════
:SUBOPCION_SOLO_SPAIN
:: ════════════════════════════════════════════════════════════════
echo.
echo  Sin osmium no es posible fusionar los tres mapas en Windows.
echo  Opciones:
echo    A) Instala osmium-tool nativo (via Chocolatey):
echo       choco install osmium-tool
echo    B) Activa WSL2 y ejecuta el script de nuevo.
echo    C) Usa solo el mapa de España renombrándolo:
echo       copy "%DATA_DIR%\spain-latest.osm.pbf" "%DATA_DIR%\%MAP_MERGED%"
echo.
set /p SOLO="¿Continuar solo con el mapa de España? (s/N): "
if /i not "%SOLO%"=="s" goto FIN

if not exist "%DATA_DIR%\spain-latest.osm.pbf" (
    echo [ERROR] Descarga primero el mapa de España (opción 1 del menú).
    goto FIN
)
copy "%DATA_DIR%\spain-latest.osm.pbf" "%DATA_DIR%\%MAP_MERGED%"
echo [OK] Usando solo España como mapa base.
goto PROCESAR_OSRM

:: ════════════════════════════════════════════════════════════════
:: Función helper: descarga un fichero si no existe ya
:: Uso: call :DOWNLOAD_MAP <URL> <NOMBRE_FICHERO>
:: ════════════════════════════════════════════════════════════════
:DOWNLOAD_MAP
set "DL_URL=%~1"
set "DL_FILE=%~2"
set "DL_DEST=%DATA_DIR%\!DL_FILE!"

if exist "!DL_DEST!" (
    echo [OK] Ya existe: !DL_FILE! — saltando descarga.
    goto :EOF
)

echo [INFO] Descargando: !DL_FILE!
echo        Fuente: !DL_URL!

if "%DOWNLOADER%"=="curl" (
    curl -L --progress-bar -o "!DL_DEST!" "!DL_URL!"
) else (
    powershell -Command "Invoke-WebRequest -Uri '!DL_URL!' -OutFile '!DL_DEST!' -UseBasicParsing"
)

if errorlevel 1 (
    echo [ERROR] Falló la descarga de !DL_FILE!.
    echo  Comprueba tu conexión a internet e inténtalo de nuevo.
    goto FIN
)
echo [OK] Descargado: !DL_FILE!
goto :EOF

:: ════════════════════════════════════════════════════════════════
:FIN
:: ════════════════════════════════════════════════════════════════
echo.
echo Presiona cualquier tecla para cerrar...
pause > nul
endlocal
