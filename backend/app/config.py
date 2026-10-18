from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NODECRAFT_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    allow_unsafe_remote: bool = False

    def assert_safe_bind(self) -> None:
        """Code nodes run unsandboxed, so refuse non-loopback binds unless explicitly allowed."""
        if self.host not in {"127.0.0.1", "localhost", "::1"} and not self.allow_unsafe_remote:
            raise SystemExit(
                f"Refusing to bind {self.host}: code nodes are not sandboxed. "
                "Set NODECRAFT_ALLOW_UNSAFE_REMOTE=1 to override."
            )


def get_settings() -> Settings:
    return Settings()
