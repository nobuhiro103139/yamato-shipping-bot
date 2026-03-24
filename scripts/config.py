from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings

from scripts.models import PackageSize


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    kuroneko_login_id: str = ""
    kuroneko_password: str = ""
    sender_name: str = ""
    sender_postal_code: str = ""
    sender_address1: str = ""
    sender_address2: str = ""
    sender_phone: str = ""
    default_package_size: str = "compact"
    preferred_shipping_location: str = ""
    line_notify_token: str = ""
    headless_browser: bool = True
    shopify_store: str = ""
    shopify_client_id: str = ""
    shopify_client_secret: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @field_validator("default_package_size")
    @classmethod
    def validate_package_size(cls, v: str) -> str:
        allowed = {size.value for size in PackageSize}
        if v not in allowed:
            raise ValueError(f"default_package_size must be one of {allowed}, got '{v}'")
        return v

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def kuroneko_configured(self) -> bool:
        return bool(self.kuroneko_login_id and self.kuroneko_password)

    @property
    def line_notify_configured(self) -> bool:
        return bool(self.line_notify_token)

    @property
    def shopify_configured(self) -> bool:
        return bool(self.shopify_store and self.shopify_client_id and self.shopify_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
