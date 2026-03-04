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

echo [3/3] Iniciando Orquestador con Interfaz Grafica...
start "Gemelos Ambulancias (GUI)" cmd /k "python gui.py"

echo.
echo ========================================================
echo  ¡Todos los servicios iniciados en ventanas separadas!
echo  Revisa la ventana "Gemelos Ambulancias (Main)" para 
echo  inyectar incidentes en el simulador.
echo ========================================================
pause
