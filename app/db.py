import json
import os
import time
from typing import Any, Dict
from pathlib import Path

DB_PATH = Path("data/db.json")

class JsonStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._atomic_write({"listings": [], "bookings": []})

    def read(self) -> Dict[str, Any]:
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def write(self, data: Dict[str, Any]) -> None:
        self._atomic_write(data)

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)

def new_id(prefix: str) -> str:
    # Id simple para hackathon (suficiente)
    return f"{prefix}_{int(time.time() * 1000)}"
