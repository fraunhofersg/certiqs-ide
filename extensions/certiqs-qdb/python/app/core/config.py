from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    internal_auth_secret: str
    internal_auth_ttl_seconds: int = 60
    blob_read_write_token: str | None = None

    # DEV-ONLY: when true, route every DB query through Neon's "SQL over HTTPS"
    # endpoint (port 443) instead of asyncpg (port 5432). Escape hatch for
    # networks that block the raw Postgres port. Read paths + single-statement
    # writes work; multi-statement INSERT...RETURNING transactions don't (see
    # app/db_http.py). Default off — production/CI keep asyncpg untouched.
    neon_http_fallback: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
