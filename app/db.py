import json
import os
import time
import random
from typing import Any, Dict, Optional
from pathlib import Path

DB_PATH = Path("data/db.json")

DEFAULT_DB: Dict[str, Any] = {"listings": [], "bookings": []}


class JsonStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._atomic_write(DEFAULT_DB)

    def read(self) -> Dict[str, Any]:
        """Lee la DB. Si el JSON está corrupto/vacío, lo re-crea."""
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("DB JSON no es dict")
            # Asegura llaves mínimas
            data.setdefault("listings", [])
            data.setdefault("bookings", [])
            return data
        except Exception:
            # Fallback: recrea DB mínima (hackathon > llorar)
            self._atomic_write(DEFAULT_DB)
            return {"listings": [], "bookings": []}

    def write(self, data: Dict[str, Any]) -> None:
        # Asegura estructura mínima antes de guardar
        if not isinstance(data, dict):
            raise ValueError("data debe ser dict")
        data.setdefault("listings", [])
        data.setdefault("bookings", [])
        self._atomic_write(data)

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)


def new_id(prefix: str) -> str:
    # Más único que solo time (evita choques en el mismo ms)
    return f"{prefix}_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"


# Helpers CRUD (para mantener main.py limpio)

def find_by_id(items: list[dict], item_id: str) -> Optional[dict]:
    return next((x for x in items if x.get("id") == item_id), None)

def find_index_by_id(items: list[dict], item_id: str) -> Optional[int]:
    for i, x in enumerate(items):
        if x.get("id") == item_id:
            return i
    return None
