from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value)


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except Exception:
        return default


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except Exception:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def env_path(name: str, default: str) -> Path:
    value = os.environ.get(name, default)
    return Path(str(value)).expanduser().resolve()


def env_list(name: str, default: Optional[list[str]] = None, *, sep: str = ",") -> list[str]:
    value = env_str(name)
    if not value:
        return list(default or [])
    return [p for p in (s.strip() for s in value.split(sep)) if p]


def env_json(name: str, default: Any = None) -> Any:
    value = env_str(name)
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default
