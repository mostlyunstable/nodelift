from typing import Any

from app.config import Settings
from app.domain.secrets import MemorySecretStore, SecretStore, SecretsUnavailable

SERVICE = "Nodecraft"


class KeyringSecretStore:
    """Values live in the OS credential store (the macOS Keychain), not in our database."""

    def get(self, name: str) -> str | None:
        keyring = self._keyring()
        try:
            value: str | None = keyring.get_password(SERVICE, name)
            return value
        except Exception as e:  # keychain locked, denied, missing backend...
            raise SecretsUnavailable(f"Cannot read from the system keychain: {e}") from e

    def set(self, name: str, value: str) -> None:
        keyring = self._keyring()
        try:
            keyring.set_password(SERVICE, name, value)
        except Exception as e:
            raise SecretsUnavailable(f"Cannot write to the system keychain: {e}") from e

    def delete(self, name: str) -> None:
        keyring = self._keyring()
        try:
            keyring.delete_password(SERVICE, name)
        except keyring.errors.PasswordDeleteError:
            pass  # already gone
        except Exception as e:
            raise SecretsUnavailable(f"Cannot delete from the system keychain: {e}") from e

    @staticmethod
    def _keyring() -> Any:
        try:
            import keyring
            import keyring.errors
        except Exception as e:
            raise SecretsUnavailable(f"The keyring library is unavailable: {e}") from e
        return keyring


def make_secret_store(settings: Settings) -> SecretStore:
    if settings.secret_backend == "memory":
        return MemorySecretStore()
    return KeyringSecretStore()
