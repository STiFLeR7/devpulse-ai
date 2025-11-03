import hmac, hashlib, base64

def sign_event(secret: str, payload: str) -> str:
    mac = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")

def verify_event(secret: str, payload: str, signature: str) -> bool:
    try:
        return hmac.compare_digest(sign_event(secret, payload), signature)
    except Exception:
        return False
