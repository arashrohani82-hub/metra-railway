import os
import time
import requests


class BellSMSClient:
    """Minimal Bell Notification API client for Metra follow-up SMS.

    Production endpoint/credentials are supplied by Bell after API onboarding.
    """

    def __init__(self):
        self.api_base_url = os.environ.get("BELL_SMS_API_BASE_URL", "").strip().rstrip("/")
        self.token_url = os.environ.get("BELL_SMS_TOKEN_URL", "").strip()
        self.client_id = os.environ.get("BELL_SMS_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("BELL_SMS_CLIENT_SECRET", "").strip()
        self.scope = os.environ.get("BELL_SMS_SCOPE", "sms").strip() or "sms"
        self.enabled = os.environ.get("BELL_SMS_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.timeout = int(os.environ.get("BELL_SMS_TIMEOUT", "20"))
        self._access_token = None
        self._token_expires_at = 0

    def configured(self):
        return bool(
            self.enabled
            and self.api_base_url
            and self.token_url
            and self.client_id
            and self.client_secret
        )

    def _get_access_token(self):
        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token

        if not all([self.token_url, self.client_id, self.client_secret]):
            raise RuntimeError("Bell SMS OAuth credentials are incomplete")

        response = requests.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": self.scope,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("Bell OAuth response did not include access_token")
        self._access_token = token
        self._token_expires_at = now + int(data.get("expires_in", 3600))
        return token

    def send_sms(self, destination, message, require_delivery_receipt=True):
        if not self.configured():
            raise RuntimeError("Bell SMS is not enabled/configured")
        if not destination:
            raise ValueError("SMS destination is required")
        if not message or not message.strip():
            raise ValueError("SMS message is required")

        token = self._get_access_token()
        response = requests.post(
            f"{self.api_base_url}/notifications/sms",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "destinations": [destination],
                "message": message.strip(),
                "requireDeliveryReceipt": bool(require_delivery_receipt),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return {"ok": True, "status_code": response.status_code}
        try:
            return {"ok": True, "status_code": response.status_code, "data": response.json()}
        except ValueError:
            return {"ok": True, "status_code": response.status_code, "text": response.text[:500]}


bell_sms = BellSMSClient()
