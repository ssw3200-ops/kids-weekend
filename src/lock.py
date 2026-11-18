"""페이지 데이터 비밀번호 잠금 (AES-256-GCM + PBKDF2)

브라우저 WebCrypto 로 같은 방식으로 풀 수 있게 맞춰 둡니다.
비밀번호가 없으면 아무도 행사 목록을 볼 수 없고, 저장소에도 암호문만 올라갑니다.
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ITER = 200_000


def encrypt(obj: dict, password: str) -> dict:
    salt, iv = os.urandom(16), os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER)
    key = kdf.derive(password.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), None)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"v": 1, "iter": ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}
