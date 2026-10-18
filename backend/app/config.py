from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NODECRAFT_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    allow_unsafe_remote: bool = False
    data_dir: Path = Path.home() / ".nodecraft"
    database_url: str | None = None
    max_concurrent_runs: int = 4
    max_run_seconds: int = 300
    node_memory_mb: int | None = 1024  # enforced on Linux only
    node_max_file_mb: int = 10

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'nodecraft.db'}"

    def assert_safe_bind(self) -> None:
        """Code nodes run unsandboxed, so refuse non-loopback binds unless explicitly allowed."""
        if self.host not in {"127.0.0.1", "localhost", "::1"} and not self.allow_unsafe_remote:
            raise SystemExit(
                f"Refusing to bind {self.host}: code nodes are not sandboxed. "
                "Set NODECRAFT_ALLOW_UNSAFE_REMOTE=1 to override."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
