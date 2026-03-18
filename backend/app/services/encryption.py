import logging

from fastapi import HTTPException
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

# Validate encryption key at import time
_encryption_key = settings.encryption_key
if not _encryption_key or not _encryption_key.strip():
    logger.critical(
        "ENCRYPTION_KEY is not set. The application cannot store credentials securely. "
        "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )
    raise RuntimeError("ENCRYPTION_KEY is not configured. Cannot start without a valid encryption key.")

try:
    fernet = Fernet(_encryption_key.encode())
except (ValueError, InvalidToken) as e:
    logger.critical(
        "ENCRYPTION_KEY is invalid (not a valid Fernet key). "
        "Generate a new one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    )
    raise RuntimeError(f"ENCRYPTION_KEY is not a valid Fernet key: {e}")


def encrypt_value(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    return fernet.decrypt(value.encode()).decode()
