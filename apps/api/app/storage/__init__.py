from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import StorageService
from app.storage.local import LocalStorage


@lru_cache
def get_storage() -> StorageService:
    settings = get_settings()
    return LocalStorage(settings.upload_dir)
