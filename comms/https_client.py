import requests
import threading

class HTTPSHandler:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url

    def sync_backup(self, state_dict):
        # Fire-and-forget backup sync so it doesn't block the main thread 
        # normally we would want stronger guarantees or queues, but this is a simpler backup approach
        thread = threading.Thread(target=self._do_post, args=(state_dict,))
        thread.start()

    def _do_post(self, payload):
        try:
            url = f"{self.base_url}/api/backup_state"
            response = requests.post(url, json=payload, timeout=5.0)
            if response.status_code == 200:
                pass # success
            else:
                print(f"[HTTPS] Failed backup sync HTTP {response.status_code}")
        except Exception as e:
            print(f"[HTTPS] Backup sync error: {e}")
