from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
