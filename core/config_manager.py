"""
Config manager – reads/writes config.json stored next to the application.
All OSDP session settings (port, baud, address, SCBK key, security mode)
are persisted here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Folder that holds config.json  (same directory as this file's package parent)
_APP_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG: dict[str, Any] = {
    "port": "",
    "baud_rate": 9600,
    "pd_address": 0,
    # 16-byte SCBK stored as 32 hex chars
    "scbk": "00000000000000000000000000000000",
    # True  → Install-mode (no secure channel, PD will accept KEYSET)
    # False → Secure-channel mode (SCBK key is used)
    "install_mode": True,
    # last-used LED defaults (persisted for convenience)
    "led": {
        "reader": 0,
        "led_number": 0,
        "on_color": 2,    # 2 = GREEN
        "off_color": 0,   # 0 = NONE
        "on_count": 5,    # × 100 ms
        "off_count": 5,
        "timer_count": 10  # × 100 ms  (0 = permanent)
    },
    # last-used buzzer defaults
    "buzz": {
        "reader": 0,
        "tone_code": 1,   # 1 = default beep
        "on_count": 3,
        "off_count": 3,
        "rep_count": 3    # 0 = continuous
    },
}


class ConfigManager:
    """Thread-safe(ish) JSON config manager.

    Usage::

        cfg = ConfigManager()          # loads config.json automatically
        cfg.port = "COM3"
        cfg.save()                     # writes back to disk
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path: Path = (
            Path(config_path) if config_path else _APP_DIR / "config.json"
        )
        self._data: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load config from disk, merging with defaults."""
        base = _deep_merge({}, DEFAULT_CONFIG)
        if self.config_path.exists():
            try:
                with open(self.config_path, encoding="utf-8") as fh:
                    on_disk = json.load(fh)
                base = _deep_merge(base, on_disk)
            except (json.JSONDecodeError, OSError):
                pass  # fall back to defaults silently
        self._data = base

    def save(self) -> None:
        """Persist current config to disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2)

    # ------------------------------------------------------------------
    # generic get / set
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, data: dict) -> None:
        self._data.update(data)

    def get_section(self, section: str) -> dict:
        return dict(self._data.get(section, {}))

    def update_section(self, section: str, data: dict) -> None:
        if section not in self._data or not isinstance(self._data[section], dict):
            self._data[section] = {}
        self._data[section].update(data)

    # ------------------------------------------------------------------
    # typed convenience properties
    # ------------------------------------------------------------------

    @property
    def port(self) -> str:
        return self._data.get("port", "")

    @port.setter
    def port(self, value: str) -> None:
        self._data["port"] = value

    @property
    def baud_rate(self) -> int:
        return int(self._data.get("baud_rate", 9600))

    @baud_rate.setter
    def baud_rate(self, value: int) -> None:
        self._data["baud_rate"] = int(value)

    @property
    def pd_address(self) -> int:
        return int(self._data.get("pd_address", 0))

    @pd_address.setter
    def pd_address(self, value: int) -> None:
        self._data["pd_address"] = int(value)

    @property
    def scbk(self) -> str:
        """32 hex-char SCBK string."""
        return self._data.get("scbk", "00000000000000000000000000000000")

    @scbk.setter
    def scbk(self, value: str) -> None:
        # Validate: must be 32 hex chars
        cleaned = value.strip().replace(" ", "").replace("-", "")
        if len(cleaned) != 32:
            raise ValueError("SCBK must be exactly 32 hex characters (16 bytes)")
        int(cleaned, 16)  # raises ValueError if not valid hex
        self._data["scbk"] = cleaned.upper()

    def scbk_bytes(self) -> bytes:
        """Return SCBK as raw 16-byte sequence."""
        return bytes.fromhex(self.scbk)

    @property
    def install_mode(self) -> bool:
        return bool(self._data.get("install_mode", True))

    @install_mode.setter
    def install_mode(self, value: bool) -> None:
        self._data["install_mode"] = bool(value)


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict that is *base* updated recursively with *override*."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
