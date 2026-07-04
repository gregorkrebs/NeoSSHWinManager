import urllib.request
import urllib.error
import urllib.parse
import threading
from src.app_logger import logger
from src.config import AppSettings

TELEMETRY_URL = "https://stats.neosshwinmanager.org/telemetry.php"

def send_telemetry_async(action: str, settings: AppSettings):
    """
    Sendet das Telemetrie-Event asynchron an den Server, sofern der Nutzer eingewilligt hat.
    Da Open-Source-Software keine Geheimnisse wahren kann, wird serverseitiges Rate-Limiting verwendet.
    """
    if not settings.telemetry_enabled:
        logger.debug(f"Telemetry is disabled. Not sending action: {action}")
        return

    def _worker():
        try:
            url = f"{TELEMETRY_URL}?action={urllib.parse.quote(action, safe='')}"
            req = urllib.request.Request(url, method='POST')
            req.add_header('User-Agent', 'NeoSSHWinManager/1.0')
            
            # Timeout kurz halten, damit es sich nicht aufhängt falls Server down
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    logger.debug(f"Telemetry sent successfully: {action}")
                else:
                    logger.warning(f"Telemetry server returned status: {response.status}")
        except urllib.error.URLError as e:
            logger.warning(f"Failed to send telemetry ({action}): {e.reason}")
        except Exception as e:
            logger.warning(f"Unexpected error sending telemetry ({action}): {e}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
