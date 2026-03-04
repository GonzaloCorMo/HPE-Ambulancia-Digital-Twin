import asyncio
from amqtt.broker import Broker

# This script acts as a lightweight standalone MQTT broker
# just in case Mosquitto is not installed on the system, for easy testing.

config = {
    'listeners': {
        'default': {
            'type': 'tcp',
            'bind': '0.0.0.0:1883',
            'max_connections': 100
        }
    },
    'sys_interval': 10,
    'auth': {
        'allow-anonymous': True,
    }
}

async def start_broker():
    broker = Broker(config)
    await broker.start()
    print("[LOCAL BROKER] MQTT Broker running on 0.0.0.0:1883")
    print("[LOCAL BROKER] Press Ctrl+C to stop")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
        
if __name__ == '__main__':
    asyncio.run(start_broker())
