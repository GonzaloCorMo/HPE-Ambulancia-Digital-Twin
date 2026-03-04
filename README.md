# Sistema de Gemelos Digitales de Ambulancias

¡Bienvenido al simulador de Ambulancias Inteligentes! 🚑

Este proyecto simula virtualmente una flota de ambulancias (lo que llamamos "Gemelos Digitales"). El objetivo es monitorear todo lo que pasa dentro y fuera del vehículo en tiempo real y asegurar que los datos médicos y mecánicos nunca se pierden, incluso si fallan las comunicaciones o hay un accidente.

## ¿Qué simula cada ambulancia?
Cada vehículo simulado tiene tres "motores" que generan datos continuamente:
1. **Motor Mecánico 🛞**: Simula cuánto combustible queda, la temperatura del motor e incluso si se pincha una rueda.
2. **Motor de Constantes Vitales 🫀**: Simula al paciente que va dentro. Genera datos de pulsaciones, presión arterial, y oxígeno. El paciente puede estabilizarse o empeorar.
3. **Motor Logístico 🗺️**: Simula por dónde va la ambulancia (GPS), la velocidad a la que va y si está parada en un atasco.

## ¿Cómo se comunican?
En este sistema la información médica es vital, por lo tanto, no podemos depender de una sola conexión:

- **La Vía Principal (MQTT)**: Las ambulancias envían datos en vivo (cada segundo) a un Centro de Mando usando tecnología rápida de Internet de las Cosas (IoT).
- **El Respaldo (HTTPS)**: Por si acaso, cada 10 segundos suben un "paquete resumen" pesado a una base de datos segura para que quede constancia médica trazable pase lo que pase.
- **Modo S.O.S (Red P2P)**: ¿Qué pasa si el servidor central se cae o entran en un túnel sin cobertura? Las ambulancias encienden una red local y "gritan" sus datos a las ambulancias cercanas directamente para evitar choques y avisar de emergencias.

## El Centro de Mando (Centralita)
La centralita recibe datos de toda la flota. Además, cuenta con una Inteligencia artificial simple que detecta **Atascos**: Si ve dos ambulancias muy cerca y circulando muy despacio, lanza una notificación de alerta.

## ¿Listos para usarlo?
Solo tienes que instalar las dependencias y ejecutar el orquestador mágico `main.py`. Tienes controles interactivos para pinchar ruedas de ambulancias, empeorar a sus pacientes o provocar atascos en la ciudad simulada.
