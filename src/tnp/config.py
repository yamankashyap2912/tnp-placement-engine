"""Configuration: paths and database credentials (from environment / .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "sql"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OPTIONAL_DIR = DATA_DIR / "optional"
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
DOCS_DIR = ROOT / "docs"

# SQL files executed by `setup-db`, in order.
SQL_FILES = [
    "01_schema.sql",
    "02_indexes.sql",
    "03_functions.sql",
    "04_triggers.sql",
    "05_procedures.sql",
    "06_views.sql",
    "07_integrity_checks.sql",
    "09_app_layer.sql",
]
SECURITY_FILE = "08_security.sql"


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    """Tiny .env reader (KEY=VALUE per line); real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    socket: str | None
    db_name: str
    admin_user: str
    admin_password: str
    ml_user: str
    ml_password: str
    officer_user: str
    officer_password: str
    readonly_user: str
    readonly_password: str

    def credentials(self, role: str) -> tuple[str, str]:
        table = {
            "admin": (self.admin_user, self.admin_password),
            "ml": (self.ml_user, self.ml_password),
            "officer": (self.officer_user, self.officer_password),
            "readonly": (self.readonly_user, self.readonly_password),
        }
        if role not in table:
            raise ValueError(f"unknown role {role!r}; choose from {sorted(table)}")
        return table[role]


def get_settings() -> Settings:
    e = os.environ.get
    return Settings(
        host=e("TNP_DB_HOST", "127.0.0.1"),
        port=int(e("TNP_DB_PORT", "3306")),
        socket=e("TNP_DB_SOCKET") or None,
        db_name=e("TNP_DB_NAME", "tnp_placement"),
        admin_user=e("TNP_ADMIN_USER", "root"),
        admin_password=e("TNP_ADMIN_PASSWORD", ""),
        ml_user=e("TNP_ML_USER", "tnp_ml_user"),
        ml_password=e("TNP_ML_PASSWORD", "ChangeMe_ml_1"),
        officer_user=e("TNP_OFFICER_USER", "tnp_officer_user"),
        officer_password=e("TNP_OFFICER_PASSWORD", "ChangeMe_officer_1"),
        readonly_user=e("TNP_READONLY_USER", "tnp_readonly_user"),
        readonly_password=e("TNP_READONLY_PASSWORD", "ChangeMe_readonly_1"),
    )
