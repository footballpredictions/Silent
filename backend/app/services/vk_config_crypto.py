"""Encrypt/decrypt VPN config payloads for VK message delivery."""
import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

BOOTSTRAP_PREFIX = "SILENT:boot:"
CONFIG_PREFIX = "SILENT:v1:"
CONFIG_PEPPER = "silent_vpn_config_v1"


def derive_config_key(vk_user_id: int) -> bytes:
    raw = f"{vk_user_id}:{settings.VK_ID_APP_ID}:{CONFIG_PEPPER}".encode()
    return hashlib.sha256(raw).digest()


def encrypt_config_payload(vk_user_id: int, payload: dict[str, Any]) -> str:
    key = derive_config_key(vk_user_id)
    aes = AESGCM(key)
    nonce = os.urandom(12)
    plaintext = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    ciphertext = aes.encrypt(nonce, plaintext, None)
    blob = base64.urlsafe_b64encode(nonce + ciphertext).decode().rstrip("=")
    return f"{CONFIG_PREFIX}{blob}"


def decrypt_config_payload(vk_user_id: int, message: str) -> dict[str, Any] | None:
    if not message.startswith(CONFIG_PREFIX):
        return None
    blob = message[len(CONFIG_PREFIX):]
    pad = "=" * (-len(blob) % 4)
    try:
        raw = base64.urlsafe_b64decode(blob + pad)
        nonce, ciphertext = raw[:12], raw[12:]
        aes = AESGCM(derive_config_key(vk_user_id))
        plaintext = aes.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode())
    except Exception:
        return None
