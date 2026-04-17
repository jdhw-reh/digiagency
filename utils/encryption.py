"""Fernet symmetric encryption helpers for sensitive per-user tokens stored in Redis.

Usage:
    from utils.encryption import encrypt, decrypt

    stored = encrypt(plaintext_token)   # store this in Redis
    token   = decrypt(stored)           # retrieve the original token

The ENCRYPTION_KEY env var must be a URL-safe base64-encoded 32-byte key.
Generate one (run once, then set it in your environment / Railway variables):

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import os

from cryptography.fernet import Fernet, InvalidToken


class TokenDecryptionError(Exception):
    """Raised when a stored token cannot be decrypted.

    This typically means the value in Redis is legacy plaintext data that was
    written before encryption was introduced.  The caller should clear the
    field and prompt the user to reconnect their integration.
    """


def get_fernet_key() -> bytes:
    """Return the raw Fernet key bytes from the ENCRYPTION_KEY env var.

    Raises RuntimeError if the variable is missing, so the app fails fast at
    startup rather than silently at the point a user tries to use Notion.
    """
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY environment variable is not set. "
            "Generate a key and add it to your environment with:\n"
            '    python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return key.encode()


def _fernet() -> Fernet:
    return Fernet(get_fernet_key())


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* and return a URL-safe base64 ciphertext string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt *ciphertext* and return the original plaintext string.

    Raises:
        TokenDecryptionError: if decryption fails (e.g. the value is legacy
            plaintext or was encrypted with a different key).
    """
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptionError(
            "Failed to decrypt stored token — it may be legacy plaintext data "
            "written before encryption was introduced. "
            "The user should reconnect their integration."
        ) from exc
