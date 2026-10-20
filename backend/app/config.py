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
    node_plugins: str = ""  # comma-separated module paths exposing register(registry)
    http_allow_private: bool = False  # dev only: lets http.request reach localhost/LAN
    max_concurrent_node_tests: int = 4
    api_token: str | None = None  # when set, every route except /health needs "Bearer <token>"
    allowed_hosts: str = "127.0.0.1,localhost,[::1]"  # Host header allowlist (DNS-rebinding guard)
    allowed_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173"  # browser Origin allowlist (+ CORS)
    )
    secret_backend: str = (
        "keyring"  # "keyring" (system keychain) or "memory" (tests, nothing persists)
    )
    reload: bool = False  # dev only; the reloader child can outlive its parent
    log_dir: Path | None = None  # desktop: rotating backend.log lives here
    backup_dir: Path | None = None  # default: <data_dir>/backups
    keep_backups: int = 5
    keep_runs_per_workflow: int = 200  # older finished runs are deleted
    legacy_data_dir: Path | None = None  # desktop: older location to import a database from
    parent_pid: int | None = None  # desktop: exit if this process disappears
    explorer_max_download_mb: int = 100
    explorer_max_files: int = 20_000
    explorer_max_file_kb: int = 1024
    explorer_max_total_mb: int = 300
    explorer_analysis_seconds: int = 120
    explorer_max_graph_edges: int = 20_000
    shutdown_endpoint: bool = False  # desktop shell stops the backend through this

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'nodecraft.db'}"

    @property
    def effective_backup_dir(self) -> Path:
        return self.backup_dir or self.data_dir / "backups"

    @property
    def plugin_modules(self) -> list[str]:
        return [m.strip() for m in self.node_plugins.split(",") if m.strip()]

    @property
    def host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    def assert_safe_bind(self) -> None:
        """Code nodes run unsandboxed, so refuse non-loopback binds unless explicitly allowed."""
        if self.host not in {"127.0.0.1", "localhost", "::1"} and not self.allow_unsafe_remote:
            raise SystemExit(
                f"Refusing to bind {self.host}: code nodes are not sandboxed. "
                "Set NODECRAFT_ALLOW_UNSAFE_REMOTE=1 to override."
            )
        if self.host not in {"127.0.0.1", "localhost", "::1"} and not self.api_token:
            raise SystemExit("A non-loopback bind requires NODECRAFT_API_TOKEN to be set.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
