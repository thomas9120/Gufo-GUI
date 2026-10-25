"""Named launch configurations with explicit, atomic persistence."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import uuid

from settings import validate_settings


LAUNCHER_FIELDS = ("executable", "models_dir", "host", "port")
MAX_PRESETS = 100
EXPORT_FORMAT = "gufo-presets"


def new_document(settings=None):
    values = validate_settings({} if settings is None else settings)
    return {"version": 2, "revision": 0,
            "launcher": {key: values[key] for key in LAUNCHER_FIELDS},
            "selected_preset": "default",
            "presets": [{"id": "default", "name": "Default",
                         "settings": {key: value for key, value in values.items() if key not in LAUNCHER_FIELDS}}]}


def find_preset(document, preset_id):
    for preset in document["presets"]:
        if preset["id"] == preset_id:
            return preset
    raise ValueError("The selected preset no longer exists. Reload the launcher.")


def resolved_settings(document, preset_id=None):
    preset = find_preset(document, preset_id or document["selected_preset"])
    return validate_settings(preset["settings"] | document["launcher"])


def validate_name(name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
        raise ValueError("Preset name: enter 1 to 80 characters on one line.")
    return name.strip()


def validate_document(document):
    if not isinstance(document, dict) or document.get("version") != 2:
        raise ValueError("Unsupported launcher settings version.")
    if set(document) != {"version", "revision", "launcher", "selected_preset", "presets"}:
        raise ValueError("Invalid launcher settings document.")
    if type(document["revision"]) is not int or document["revision"] < 0:
        raise ValueError("Invalid launcher settings revision.")
    launcher = document["launcher"]
    # Existing version-2 documents predate the configurable bind address.
    if isinstance(launcher, dict):
        launcher = {"host": "127.0.0.1"} | launcher
    if not isinstance(launcher, dict) or set(launcher) != set(LAUNCHER_FIELDS):
        raise ValueError("Invalid shared launcher settings.")
    presets = document["presets"]
    if not isinstance(presets, list) or not 1 <= len(presets) <= MAX_PRESETS:
        raise ValueError(f"Keep between 1 and {MAX_PRESETS} presets.")
    result = deepcopy(document)
    ids, names = set(), set()
    for preset in result["presets"]:
        if not isinstance(preset, dict) or set(preset) != {"id", "name", "settings"}:
            raise ValueError("Invalid preset.")
        preset_id = preset["id"]
        if not isinstance(preset_id, str) or not preset_id or len(preset_id) > 80 or preset_id in ids:
            raise ValueError("Invalid or duplicate preset identity.")
        ids.add(preset_id)
        preset["name"] = validate_name(preset["name"])
        if preset["name"].casefold() in names:
            raise ValueError("Choose a unique preset name.")
        names.add(preset["name"].casefold())
        values = preset["settings"]
        if not isinstance(values, dict) or set(values) & set(LAUNCHER_FIELDS):
            raise ValueError("Preset contains shared launcher settings.")
        values = validate_settings(values | launcher)
        preset["settings"] = {key: value for key, value in values.items() if key not in LAUNCHER_FIELDS}
        result["launcher"] = {key: values[key] for key in LAUNCHER_FIELDS}
    find_preset(result, document["selected_preset"])
    return result


def load_document(path):
    if not path.exists():
        return new_document()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(document, dict) and document.get("version") == 1:
            return new_document(validate_settings(document["settings"]))
        return validate_document(document)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Cannot read saved settings at {path}: {exc}") from exc


def save_document(path, document):
    document = validate_document(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="launcher-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            original = path.read_bytes()
            try:
                validate_document(json.loads(original))
                needs_backup = False
            except (ValueError, KeyError, TypeError):
                needs_backup = True
            if needs_backup:
                # Never replace a previous migration/recovery backup.
                backup = path.with_name(path.name + ".bak")
                try:
                    stream = backup.open("xb")
                except FileExistsError:
                    pass
                else:
                    try:
                        with stream:
                            stream.write(original)
                            stream.flush()
                            os.fsync(stream.fileno())
                    except OSError:
                        backup.unlink(missing_ok=True)
                        raise
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return document


def export_presets(document):
    """Portable backup of every saved preset. Shared launcher paths and ports stay behind."""
    return {"format": EXPORT_FORMAT, "version": 1,
            "presets": [{"name": preset["name"], "settings": deepcopy(preset["settings"])}
                        for preset in document["presets"]]}


def unique_name(name, taken):
    candidate, number = name, 1
    while candidate.casefold() in taken:
        number += 1
        suffix = f" ({number})"
        candidate = name[:80 - len(suffix)].rstrip() + suffix
    return candidate


def import_presets(document, request):
    """Return a validated copy with the file's presets appended. Existing presets never change."""
    if not isinstance(request, dict) or set(request) != {"data", "revision"}:
        raise ValueError("Invalid preset import request.")
    if type(request["revision"]) is not int or request["revision"] != document["revision"]:
        raise ValueError("Presets changed in another tab. Reload before importing.")
    data = request["data"]
    if (not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT or data.get("version") != 1
            or set(data) != {"format", "version", "presets"}):
        raise ValueError("This is not a Gufo preset backup file.")
    incoming = data["presets"]
    if not isinstance(incoming, list) or not 1 <= len(incoming) <= MAX_PRESETS:
        raise ValueError(f"Keep between 1 and {MAX_PRESETS} presets.")
    result = deepcopy(document)
    if len(result["presets"]) + len(incoming) > MAX_PRESETS:
        raise ValueError(f"Importing {len(incoming)} presets would exceed the limit of {MAX_PRESETS}.")
    names = {preset["name"].casefold() for preset in result["presets"]}
    for item in incoming:
        if not isinstance(item, dict) or set(item) != {"name", "settings"}:
            raise ValueError("Invalid preset in the backup file.")
        name = validate_name(item["name"])
        if not isinstance(item["settings"], dict):
            raise ValueError(f'Preset "{name}": invalid settings.')
        try:
            values = validate_settings({key: value for key, value in item["settings"].items()
                                        if key not in LAUNCHER_FIELDS})
        except ValueError as exc:
            raise ValueError(f'Preset "{name}": {exc}') from exc
        name = unique_name(name, names)
        names.add(name.casefold())
        result["presets"].append({"id": uuid.uuid4().hex, "name": name,
                                  "settings": {key: value for key, value in values.items()
                                               if key not in LAUNCHER_FIELDS}})
    result["revision"] += 1
    return validate_document(result)


def change_preset(document, request):
    """Return a validated copy. The caller persists it before replacing live state."""
    if not isinstance(request, dict) or set(request) - {"action", "id", "name", "settings", "revision"}:
        raise ValueError("Invalid preset request.")
    if type(request.get("revision")) is not int or request["revision"] != document["revision"]:
        raise ValueError("Presets changed in another tab. Reload before saving.")
    result = deepcopy(document)
    action = request.get("action")
    if action == "create":
        preset = {"id": uuid.uuid4().hex, "name": validate_name(request.get("name")), "settings": {}}
        result["presets"].append(preset)
    else:
        preset = find_preset(result, request.get("id"))
    if action in ("save", "create"):
        values = validate_settings(request.get("settings"))
        result["launcher"] = {key: values[key] for key in LAUNCHER_FIELDS}
        preset["settings"] = {key: value for key, value in values.items() if key not in LAUNCHER_FIELDS}
        result["selected_preset"] = preset["id"]
    elif action == "rename":
        preset["name"] = validate_name(request.get("name"))
    elif action == "delete":
        if len(result["presets"]) == 1:
            raise ValueError("Keep at least one preset.")
        result["presets"].remove(preset)
        if result["selected_preset"] == preset["id"]:
            result["selected_preset"] = result["presets"][0]["id"]
    else:
        raise ValueError("Unknown preset action.")
    result["revision"] += 1
    return validate_document(result)
