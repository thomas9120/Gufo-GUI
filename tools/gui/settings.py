"""Common launcher fields and validation; no persistence or process operations."""

import ipaddress
import json
import math
import os
from pathlib import Path

from models import MODEL_FAMILIES, REASONING_LEVELS, SPECULATIVE_MODES, validate_model_settings


ROOT = Path(__file__).resolve().parents[2]
PATH_FIELDS = ("executable", "models_dir", "model", "mtp_model", "dflash_model", "mmproj", "cache_disk_dir")


def default_executable():
    """Find the official checkout without changing any saved preset selection."""
    name = "gufo.exe" if os.name == "nt" else "gufo"
    source = ROOT / "gufo"
    # Each platform's setup records its checkout; prefer this platform's record.
    states = ("windows-setup.json",) if os.name == "nt" else ("linux-setup.json", "windows-setup.json")
    for state_name in states:
        try:
            state = json.loads((ROOT / "build" / state_name).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(state, dict) and isinstance(state.get("GufoPath"), str) and Path(state["GufoPath"]).is_absolute():
            source = Path(state["GufoPath"])
            break
    for preset in ("windows-release", "release", "gpu-test", "cpu-test"):
        candidate = source / "build" / preset / name
        if candidate.is_file():
            return str(candidate)
    return str(source / "build" / ("windows-release" if os.name == "nt" else "release") / name)


DEFAULTS = {
    "executable": default_executable(),
    "models_dir": str(Path.home()),
    "model": "",
    "model_family": "generic",
    "mtp_model": "",
    "dflash_model": "",
    "mmproj": "",  # Empty means engine auto-discovery, not disabled vision.
    "context": 32768,
    "max_tokens": 2048,
    "think": "on",
    "reasoning_effort": "auto",
    "preserve_thinking": True,
    "cache_ram_gib": 0,
    "cache_disk": False,
    "cache_disk_dir": str(Path(os.environ["LOCALAPPDATA"]) / "Gufo" / "cache"
                          if os.environ.get("LOCALAPPDATA") else Path.home() / ".cache" / "gufo"),
    "cache_disk_gib": 8,
    "cache_disk_staging_gib": 0,
    "host": "127.0.0.1",
    "port": 8080,
    "served_model_name": "gufo",
    "sessions": 1,
    "temperature": 1.0,
    "top_k": 20,
    "top_p": 0.95,
    "min_p": 0.0,
    "seed": -1,
    "repeat_penalty": 1.0,
    "repeat_last_n": 64,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
    "speculative": "off",
    "draft_tokens": 7,
}
INTEGER_LIMITS = {
    "context": (0, 2**32 - 1), "max_tokens": (-1, 2**32 - 1),
    "port": (1, 65535), "sessions": (1, 64), "top_k": (0, 2**31 - 1),
    "seed": (-1, 2**53 - 1), "repeat_last_n": (0, 2**32 - 1),
    "draft_tokens": (1, 7),
    "cache_ram_gib": (0, 65536),
    "cache_disk_gib": (1, 65536), "cache_disk_staging_gib": (0, 65536),
}
FLOAT_LIMITS = {
    "temperature": (0, 2), "top_p": (0, 1), "min_p": (0, 1),
    "repeat_penalty": (0, 100), "frequency_penalty": (-2, 2),
    "presence_penalty": (-2, 2),
}
ENUMS = {"model_family": tuple(MODEL_FAMILIES), "think": ("auto", "on", "off"),
         "reasoning_effort": REASONING_LEVELS, "speculative": tuple(SPECULATIVE_MODES)}

# Fields older launchers saved; validate_settings migrates or ignores them.
LEGACY_FIELDS = {"mtp", "mtp_policy", "mtp_draft_vocab", "prompt_lookup",
                 "debug_tool_calls"}


def settings_path():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config"))
    return base / "Gufo" / "launcher.json"


def validate_settings(values):
    if not isinstance(values, dict) or set(values) - DEFAULTS.keys() - LEGACY_FIELDS:
        raise ValueError("Settings must contain only the supported launcher fields.")
    # Options from the Windows-fork launcher that this engine does not expose
    # are ignored without rewriting saved settings on load.
    retired = {"mtp_policy", "mtp_draft_vocab", "prompt_lookup", "debug_tool_calls"}
    if retired & values.keys():
        values = {key: value for key, value in values.items() if key not in retired}
    # Migrate the original MTP checkbox without rewriting saved settings on load.
    if "mtp" in values:
        values = dict(values)
        mtp = values.pop("mtp")
        if type(mtp) is not bool:
            raise ValueError("mtp: expected a checkbox value.")
        values.setdefault("speculative", "mtp" if mtp else "off")
    result = DEFAULTS | values
    for key, default in DEFAULTS.items():
        value = result[key]
        if isinstance(default, str):
            if not isinstance(value, str) or any(ord(c) < 32 for c in value):
                raise ValueError(f"{key}: enter a single line of text.")
            result[key] = value = value.strip()
        elif isinstance(default, bool) and type(value) is not bool:
            raise ValueError(f"{key}: expected a checkbox value.")
        if key in INTEGER_LIMITS:
            low, high = INTEGER_LIMITS[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key}: enter a whole number from {low} to {high}.")
        if key in FLOAT_LIMITS:
            low, high = FLOAT_LIMITS[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{key}: enter a number from {low} to {high}.")
        if key in ENUMS and value not in ENUMS[key]:
            raise ValueError(f"{key}: choose one of {', '.join(ENUMS[key])}.")
        if key in PATH_FIELDS and value:
            path = Path(value).expanduser()
            if not path.is_absolute():
                raise ValueError(f"{key}: use a full filesystem path.")
            result[key] = str(path)
    try:
        ipaddress.IPv4Address(result["host"])
    except ipaddress.AddressValueError as exc:
        raise ValueError("host: enter an IPv4 address, such as 127.0.0.1 or 0.0.0.0.") from exc
    if result["max_tokens"] == 0:
        raise ValueError("max_tokens: use -1 for unlimited output, or a positive limit.")
    if result["repeat_penalty"] == 0:
        raise ValueError("repeat_penalty: must be greater than zero; 1 disables it.")
    if result["top_p"] == 0:
        raise ValueError("top_p: must be greater than zero; 1 disables it.")
    if not result["served_model_name"]:
        raise ValueError("served_model_name: enter the model name your API client will use.")
    if result["cache_disk"] and not result["cache_disk_dir"]:
        raise ValueError("cache_disk_dir: choose a folder when disk caching is enabled.")
    validate_model_settings(result)
    return result
