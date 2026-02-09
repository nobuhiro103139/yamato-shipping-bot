from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings

from app.models.order import PackageSize


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    shopify_store_url: str = ""
    shopify_access_token: str = ""
    kuroneko_login_id: str = ""
    kuroneko_password: str = ""
    sender_name: str = ""
    sender_postal_code: str = ""
    sender_address1: str = ""
    sender_address2: str = ""
    sender_phone: str = ""
    default_package_size: str = "M"
    headless_browser: bool = False
    auth_state_path: str = "auth.json"
    cors_allowed_origins: str = "http://localhost:5173,http://localhost:3000"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    llm_api_key: str = ""
    shipments_path: str = "shipments.json"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("default_package_size")
    @classmethod
    def validate_package_size(cls, v: str) -> str:
        """Validate that package size is one of the allowed values."""
        allowed = {size.value for size in PackageSize}
        if v not in allowed:
            raise ValueError(f"default_package_size must be one of {allowed}, got '{v}'")
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def shopify_configured(self) -> bool:
        """Check whether Shopify credentials are set."""
        return bool(self.shopify_store_url and self.shopify_access_token)

    @property
    def kuroneko_configured(self) -> bool:
        """Check whether Kuroneko Members credentials are set."""
        return bool(self.kuroneko_login_id and self.kuroneko_password)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
