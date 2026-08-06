import os
import urllib.request
import urllib.error
import urllib.parse
import threading
from src.app_logger import logger
from src.config import AppSettings

TELEMETRY_URL = "https://stats.neosshwinmanager.org/telemetry.php"


def _app_version() -> str:
    """Laufende Version, damit der Server Stände auseinanderhalten kann."""
    try:
        path = os.path.join(os.path.dirname(__file__), "version.txt")
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _resolve_settings() -> AppSettings | None:
    """
    Einstellungen des angemeldeten Nutzers nachschlagen.

    Nur für Aufrufer gedacht, die selbst keinen Zugriff darauf haben (Updater,
    Update-Dialog). Ohne Anmeldung gibt es keine Einwilligung, also auch keine
    Telemetrie. get_connection() öffnet je Aufruf eine eigene Verbindung, der
    Aufruf ist deshalb auch aus einem Hintergrund-Thread unbedenklich.
    """
    try:
        from src.auth_manager import Session, UserConnectionManager
        user = Session.current()
        if user is None:
            return None
        return UserConnectionManager(user).get_settings()
    except Exception as e:
        logger.debug(f"Telemetry: could not resolve settings ({e})")
        return None


def send_telemetry_async(action: str, settings: AppSettings | None = None,
                         wait: float = 0.0, **params):
    """
    Sendet das Telemetrie-Event asynchron an den Server, sofern der Nutzer
    eingewilligt hat.

    Zusätzliche Angaben (source, result, choice, target) landen als
    Query-Parameter in der URL; der Server nimmt nur Werte aus einer festen
    Liste an. Da Open-Source-Software keine Geheimnisse wahren kann, wird
    serverseitiges Rate-Limiting verwendet.

    `wait` gibt dem Sende-Thread so viele Sekunden Zeit, bevor der Aufrufer
    weitermacht. Nur nötig, wenn sich die App gleich darauf beendet – der
    Thread ist ein Daemon und stirbt sonst mitten im Request.
    """
    if settings is None:
        settings = _resolve_settings()

    if settings is None or not settings.telemetry_enabled:
        logger.debug(f"Telemetry is disabled. Not sending action: {action}")
        return

    query = {"action": action}
    version = _app_version()
    if version:
        query["version"] = version
    for key, value in params.items():
        if value:
            query[key] = str(value)

    def _worker():
        try:
            url = f"{TELEMETRY_URL}?{urllib.parse.urlencode(query)}"
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
    if wait > 0:
        thread.join(wait)


def attach_update_telemetry(updater, source: str, settings: AppSettings | None = None) -> None:
    """
    Meldet den Ausgang einer Update-Prüfung.

    `source` unterscheidet die automatische Prüfung beim Programmstart von der
    manuell angestoßenen aus den Einstellungen – erst dadurch ist ablesbar, ob
    Nutzer die Update-Funktion aktiv verwenden oder nur mitlaufen lassen.
    """
    updater.update_available.connect(
        lambda version, _changelog, _url, _kind: send_telemetry_async(
            'update_check', settings, source=source, result='available', target=version
        )
    )
    updater.no_update_available.connect(
        lambda: send_telemetry_async('update_check', settings, source=source, result='uptodate')
    )
    updater.check_failed.connect(
        lambda _msg: send_telemetry_async('update_check', settings, source=source, result='failed')
    )
