"""Формат .dmmap (SPEC §9): DMMAP1 | соль 16 | nonce 12 | AES-256-GCM(zlib(JSON))."""

from __future__ import annotations

import os
import zlib
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from datamask.core.models import UserError

MAGIC = b"DMMAP1"
SALT, NONCE = 16, 12
MIN_PASSWORD = 10


class MappingError(UserError):
    """Сообщение безопасно показывать пользователю."""


def _key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode("utf-8"))


def encrypt(plain: bytes, password: str) -> bytes:
    salt, nonce = os.urandom(SALT), os.urandom(NONCE)
    header = MAGIC + salt + nonce
    # Заголовок — associated data: подмена соли или nonce тоже даст ошибку расшифровки.
    return header + AESGCM(_key(password, salt)).encrypt(nonce, zlib.compress(plain), header)


def decrypt(blob: bytes, password: str) -> bytes:
    bad = MappingError("Неверный пароль или файл повреждён")
    head = len(MAGIC) + SALT + NONCE
    if len(blob) <= head or not blob.startswith(MAGIC):
        raise bad
    salt, nonce = blob[len(MAGIC) : len(MAGIC) + SALT], blob[len(MAGIC) + SALT : head]
    try:
        return zlib.decompress(
            AESGCM(_key(password, salt)).decrypt(nonce, blob[head:], blob[:head])
        )
    except (InvalidTag, zlib.error) as e:
        raise bad from e


def write_atomic(path: Path, data: bytes) -> None:
    """Во временный файл рядом, затем переименование: сбой не испортит прежний файл."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
