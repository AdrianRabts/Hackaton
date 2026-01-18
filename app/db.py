import json
import os
import time
import random
from typing import Any, Dict, Optional
from pathlib import Path

DB_PATH = Path("data/db.json")

DEFAULT_DB: Dict[str, Any] = {
    "listings": [],
    "bookings": [],
    "users": [],
    "businesses": [],
}


class JsonStore:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._atomic_write(DEFAULT_DB)

    def read(self) -> Dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("DB JSON no es dict")

            data.setdefault("listings", [])
            data.setdefault("bookings", [])
            data.setdefault("users", [])
            data.setdefault("businesses", [])
            return data
        except Exception:
            self._atomic_write(DEFAULT_DB)
            return dict(DEFAULT_DB)

    def write(self, data: Dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ValueError("data debe ser dict")
        data.setdefault("listings", [])
        data.setdefault("bookings", [])
        data.setdefault("users", [])
        data.setdefault("businesses", [])
        self._atomic_write(data)

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)


def new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def find_by_id(items: list[dict], item_id: str) -> Optional[dict]:
    return next((x for x in items if x.get("id") == item_id), None)


def find_index_by_id(items: list[dict], item_id: str) -> Optional[int]:
    for i, x in enumerate(items):
        if x.get("id") == item_id:
            return i
    return None


def find_user_by_email(users: list[dict], email: str) -> Optional[dict]:
    e = normalize_email(email)
    return next((u for u in users if normalize_email(u.get("email", "")) == e), None)


def find_user_by_id(users: list[dict], user_id: str) -> Optional[dict]:
    return next((u for u in users if u.get("id") == user_id), None)


def find_user_by_email_and_role(users: list[dict], email: str, role: str) -> Optional[dict]:
    e = normalize_email(email)
    r = (role or "").strip().lower()
    return next(
        (u for u in users
         if normalize_email(u.get("email", "")) == e and (u.get("role", "") or "").strip().lower() == r),
        None,
    )


def email_exists_with_other_role(users: list[dict], email: str, role: str) -> Optional[dict]:
    e = normalize_email(email)
    r = (role or "").strip().lower()
    return next(
        (u for u in users
         if normalize_email(u.get("email", "")) == e and (u.get("role", "") or "").strip().lower() != r),
        None,
    )


def find_business_by_owner(businesses: list[dict], owner_user_id: str) -> Optional[dict]:
    return next((b for b in businesses if b.get("owner_user_id") == owner_user_id), None)
