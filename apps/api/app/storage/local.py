import os
from pathlib import Path
from typing import BinaryIO

from app.storage.base import StorageService


class LocalStorage(StorageService):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("Invalid storage key")
        return candidate

    def save(self, key: str, source: BinaryIO, max_bytes: int) -> int:
        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.tmp")
        size = 0
        try:
            with temporary_path.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("File exceeds the maximum allowed size")
                    target.write(chunk)
            os.replace(temporary_path, path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return size

    def read(self, key: str) -> bytes:
        return self._path_for_key(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path_for_key(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path_for_key(key).is_file()
