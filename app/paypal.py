import os
import base64
import requests
from typing import Dict, Any


def _paypal_base_url() -> str:
    env = os.getenv("PAYPAL_ENV", "sandbox").lower().strip()
    if env not in ("sandbox", "live"):
        env = "sandbox"
    return "https://api-m.sandbox.paypal.com" if env == "sandbox" else "https://api-m.paypal.com"


def _get_credentials():
    client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Faltan PAYPAL_CLIENT_ID o PAYPAL_CLIENT_SECRET en .env")
    return client_id, client_secret


def get_client_id() -> str:
    client_id = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError("Falta PAYPAL_CLIENT_ID en .env")
    return client_id


def get_access_token() -> str:
    client_id, client_secret = _get_credentials()
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    url = f"{_paypal_base_url()}/v1/oauth2/token"
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials"}

    try:
        r = requests.post(url, headers=headers, data=data, timeout=20)
        r.raise_for_status()
        return r.json()["access_token"]
    except requests.RequestException as e:
        raise RuntimeError(f"PayPal token error: {e}")


def create_order(amount_usd: float, reference_id: str) -> Dict[str, Any]:
    token = get_access_token()
    url = f"{_paypal_base_url()}/v2/checkout/orders"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [
            {
                "reference_id": reference_id,
                "amount": {
                    "currency_code": "USD",
                    "value": f"{amount_usd:.2f}"
                }
            }
        ]
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise RuntimeError(f"PayPal create_order error: {e}")


def capture_order(order_id: str) -> Dict[str, Any]:
    token = get_access_token()
    url = f"{_paypal_base_url()}/v2/checkout/orders/{order_id}/capture"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(url, headers=headers, json={}, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise RuntimeError(f"PayPal capture_order error: {e}")
