"""App-side wiring for the shared model backend (vendored Hoard Link).

Laplace's Hoard uses exactly one shared-model capability, ``llm``, for the
"Ask your data" feature on the Data screen; every other feature (calc, math,
units, dates, SQL) never touches a model and keeps working with nothing
resolved. This module only loads/saves ``data/backend.json`` and builds the
one :class:`~laplaces_hoard.hoard_link.Link` the app uses — no FastAPI
imports, so it is usable from tests and from ``api.py`` alike.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from .hoard_link import Link, LinkConfig

__all__ = ["USED_CAPABILITIES", "load_link", "save_config", "token_set", "app_backends"]

BACKEND_FILE = "backend.json"
USED_CAPABILITIES = ("llm",)


def _backend_path(data_dir: Path) -> Path:
    return Path(data_dir) / BACKEND_FILE


def _read_raw(data_dir: Path) -> dict[str, Any]:
    path = _backend_path(data_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        return {}
    return raw if isinstance(raw, dict) else {}


def load_link(data_dir: Path) -> Link:
    """Build the app's one `Link`, reading `data/backend.json` when it exists."""
    path = _backend_path(data_dir)
    config = LinkConfig.load(path if path.is_file() else None, env=os.environ, app="laplace")
    return Link(config)


def save_config(
    data_dir: Path,
    *,
    faustus_url: Optional[str] = None,
    faustus_token: Optional[str] = None,
    only_resident: Optional[bool] = None,
    capabilities: Optional[dict[str, dict[str, Any]]] = None,
) -> None:
    """Merge overrides into `data/backend.json`, never discarding what is already there.

    `faustus_url`/`faustus_token` of `""` clears that field; `None` leaves it
    untouched. `capabilities` merges per-capability, e.g.
    `{"llm": {"url": "...", "model": "..."}}`; a value of `None` or `""`
    inside a capability's dict removes that key.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    raw = _read_raw(data_dir)

    if only_resident is not None:
        raw["only_resident"] = bool(only_resident)

    if faustus_url is not None or faustus_token is not None:
        faustus = dict(raw.get("faustus") or {})
        if faustus_url is not None:
            if faustus_url:
                faustus["url"] = faustus_url
            else:
                faustus.pop("url", None)
        if faustus_token is not None:
            if faustus_token:
                faustus["token"] = faustus_token
            else:
                faustus.pop("token", None)
        if faustus:
            raw["faustus"] = faustus
        else:
            raw.pop("faustus", None)

    if capabilities:
        caps = dict(raw.get("capabilities") or {})
        for cap, override in capabilities.items():
            entry = dict(caps.get(cap) or {})
            for key, value in override.items():
                if value in (None, ""):
                    entry.pop(key, None)
                else:
                    entry[key] = value
            if entry:
                caps[cap] = entry
            else:
                caps.pop(cap, None)
        if caps:
            raw["capabilities"] = caps
        else:
            raw.pop("capabilities", None)

    _backend_path(data_dir).write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def token_set(data_dir: Path) -> bool:
    """Whether a Faustus token is stored — the API must never echo the token itself."""
    return bool((_read_raw(data_dir).get("faustus") or {}).get("token"))


def app_backends() -> dict[str, Any]:
    """Laplace's own backends that need no shared model — always available, bundled with the app."""
    return {
        "sql_engine": {"name": "DuckDB", "bundled": True},
        "chart_renderer": {"name": "vl-convert-python", "bundled": True},
        "computation_worker": {"name": "SymPy / Pint timeout worker", "bundled": True},
    }
