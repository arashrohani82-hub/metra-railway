import requests
import app as command_center


def resilient_bot_status(bot):
    url = command_center.bot_service_url(bot)
    if not url:
        return "⚪ Not connected"
    try:
        response = requests.get(f"{url}/status", timeout=4)
        if response.ok:
            return "🟢 Online"
        if response.status_code in (401, 403, 404):
            root = requests.get(url, timeout=4)
            if root.ok:
                return "🟢 Online"
        return f"🟡 HTTP {response.status_code}"
    except Exception:
        return "🔴 Offline"


command_center.bot_status = resilient_bot_status
app = command_center.app
