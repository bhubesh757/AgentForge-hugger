"""SecretCipher abstraction (Fernet now; AWS KMS envelope encryption can replace it)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretCipher(ABC):
    @abstractmethod
    def encrypt(self, plaintext: str) -> str: ...

    @abstractmethod
    def decrypt(self, ciphertext: str) -> str: ...


class FernetCipher(SecretCipher):
    def __init__(self, key: bytes) -> None:
        self._f = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._f.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._f.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt secret (wrong CREDENTIAL_ENCRYPTION_KEY?)") from exc


@lru_cache(maxsize=1)
def get_cipher() -> SecretCipher:
    return FernetCipher(settings.fernet_key)
