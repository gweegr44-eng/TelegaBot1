import hmac
import hashlib
import time
import logging
from urllib.parse import parse_qsl
from config import MAX_BOT_TOKEN

logger = logging.getLogger(__name__)


def verify_init_data(init_data: str) -> dict | None:
    if not init_data:
        return None

    try:
        params = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = params.pop("hash", None)
    if not received_hash:
        return None

    sorted_keys = sorted(params.keys())
    launch_params = "\n".join(f"{key}={params[key]}" for key in sorted_keys)

    secret_key = hmac.new(b"WebAppData", MAX_BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, launch_params.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    try:
        auth_date = int(params.get("auth_date", 0))
    except (ValueError, TypeError):
        return None

    if auth_date == 0:
        return None

    current_time = int(time.time())
    if current_time - auth_date > 3600:
        return None
    if auth_date - current_time > 60:
        return None

    return params