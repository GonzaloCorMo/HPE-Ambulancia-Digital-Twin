@echo off
echo ========================================================
echo   Simulador de Gemelos Digitales de Ambulancias
echo ========================================================
echo.

echo [1/3] Iniciando Broker MQTT Local...
start "Broker MQTT" cmd /k "python local_broker.py"

echo Esperando a que el broker este listo...
timeout /t 2 /nobreak > nul
echo.

echo [2/3] Iniciando Servidor de la Centralita...
start "Centralita Dashboard" cmd /k "python central\server.py"

echo Esperando a que la centralita este lista...
timeout /t 3 /nobreak > nul
echo.

echo [3/3] Iniciando Servidor Web FastAPI (Backend)...
start "Gemelos Ambulancias (Web)" cmd /k "python app.py"

echo Esperando despliegue web...
timeout /t 2 /nobreak > nul
start http://localhost:5000

echo.
echo ========================================================
echo  ¡Todos los servicios iniciados en ventanas separadas!
echo  Revisa el navegador para interactuar con la consola táctica.
echo ========================================================
pause
