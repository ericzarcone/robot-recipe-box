"""Runtime settings, read from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

MCP_PATH = "/mcp"


class ConfigError(RuntimeError):
    pass


def normalize_team_domain(value: str) -> str:
    """'myteam', 'myteam.cloudflareaccess.com', or 'https://myteam.cloudflareaccess.com/' -> the bare host."""
    value = value.strip().removeprefix("https://").removeprefix("http://").strip("/")
    if value and "." not in value:
        value = f"{value}.cloudflareaccess.com"
    return value


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    public_base_url: str
    db_path: Path
    # Cloudflare Access. Every request except /healthz must carry a valid Access JWT.
    access_team_domain: str = ""
    access_aud: str = ""
    allowed_emails: frozenset[str] = frozenset()
    # Local development only: no authentication at all.
    dev_no_auth: bool = False
    extra_allowed_hosts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.public_base_url.startswith(("http://", "https://")):
            raise ConfigError("PUBLIC_BASE_URL must start with http:// or https://")
        access_set = bool(self.access_team_domain or self.access_aud)
        if self.dev_no_auth and access_set:
            raise ConfigError("Set either DEV_NO_AUTH=true or the CF_ACCESS_* settings, not both")
        if not self.dev_no_auth and not (self.access_team_domain and self.access_aud):
            raise ConfigError(
                "Set CF_ACCESS_TEAM_DOMAIN and CF_ACCESS_AUD (see README), or DEV_NO_AUTH=true for local development"
            )

    @property
    def base_url(self) -> str:
        return self.public_base_url.rstrip("/")

    @property
    def access_issuer(self) -> str:
        return f"https://{self.access_team_domain}"

    @property
    def allowed_hosts(self) -> list[str]:
        """Host header values the MCP endpoint accepts (DNS rebinding protection)."""
        public_host = urlsplit(self.public_base_url).netloc
        return [public_host, "localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", *self.extra_allowed_hosts]

    @property
    def allowed_origins(self) -> list[str]:
        parts = urlsplit(self.public_base_url)
        return [f"{parts.scheme}://{parts.netloc}", "http://localhost:*", "http://127.0.0.1:*"]

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("DATA_DIR", "./data"))
        emails = os.environ.get("ALLOWED_EMAILS", "")
        return cls(
            public_base_url=os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000"),
            db_path=Path(os.environ.get("DB_PATH", data_dir / "recipes.db")),
            access_team_domain=normalize_team_domain(os.environ.get("CF_ACCESS_TEAM_DOMAIN", "")),
            access_aud=os.environ.get("CF_ACCESS_AUD", "").strip(),
            allowed_emails=frozenset(e.strip().lower() for e in emails.split(",") if e.strip()),
            dev_no_auth=_flag("DEV_NO_AUTH"),
            extra_allowed_hosts=[h.strip() for h in os.environ.get("EXTRA_ALLOWED_HOSTS", "").split(",") if h.strip()],
        )
