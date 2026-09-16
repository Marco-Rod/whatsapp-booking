"""Send a signed development webhook using the secret from the environment.

Copy whatsapp_message.example.json to whatsapp_message.json (gitignored).
Replace its fictional IDs and recipient with your test configuration. The receiving
display_phone_number must match Business.phone_number after normalization with '+',
and phone_number_id must match WHATSAPP_PHONE_NUMBER_ID. The example receiver is
+15555550100; configure that business for mocks or use your seeded receiver locally.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path

import httpx


WEBHOOK_URL = "http://localhost:8000/api/v1/webhooks/whatsapp"
PAYLOAD_FILE = Path(__file__).parent / "whatsapp_message.json"


def create_signature(body: bytes, app_secret: str) -> str:
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def main() -> None:
    app_secret = os.getenv("META_APP_SECRET")
    if not app_secret:
        raise RuntimeError("META_APP_SECRET no está definido en el entorno.")
    payload = json.loads(PAYLOAD_FILE.read_text(encoding="utf-8"))
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = create_signature(body, app_secret)
    print(f"POST {WEBHOOK_URL}")
    print(f"Payload: {PAYLOAD_FILE}")
    print(f"Signature: {signature[:20]}...")
    # Send precisely the bytes signed above; do not reserialize via json=payload.
    response = httpx.post(WEBHOOK_URL, content=body, headers={
        "Content-Type": "application/json", "X-Hub-Signature-256": signature,
    }, timeout=10.0)
    print()
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
    response.raise_for_status()


if __name__ == "__main__":
    main()
