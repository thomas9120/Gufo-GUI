"""Local discovery of built-in and installed Gufo extensions and serve options."""

import json
import os
from pathlib import Path
import re
import subprocess
import threading

from settings import CORE_CLI_FLAGS, PROVIDER_OPTION_NAME


_INSPECT_TIMEOUT_SECONDS = 5
_CACHE_LOCK = threading.Lock()
_CACHE = {}
_CACHE_LIMIT = 16

_OPTION_TYPES = {"path", "integer", "number", "string", "boolean"}
_HELP_HINT_TO_TYPE = {
    "N": "integer",
    "X": "number",
    "PATH": "path",
    "VALUE": "string",
    None: "boolean",
}
_HELP_OPTION_LINE = re.compile(
    r"^\s+(--[a-z0-9][a-z0-9-]*)(?:\s+(N|X|PATH|VALUE)(?=\s|$))?(?:\s+(.*))?$"
)
_HELP_PROVIDERS_SUFFIX = re.compile(
    r"\s*\(([a-zA-Z0-9_.-]+(?:,\s*[a-zA-Z0-9_.-]+)*)\)\s*$"
)
_SECTION_HEADER = re.compile(r"^[A-Z][A-Za-z0-9 _/-]*:\s*$")


def extension_store_dir():
    """Match Gufo's extension store directory resolution without running gufo."""
    override = os.environ.get("GUFO_EXTENSIONS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "gufo" / "extensions"


def _module_suffix():
    return ".dll" if os.name == "nt" else ".so"


def _read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _locate_sdk_build_id(executable):
    candidates = []
    override = os.environ.get("GUFO_SDK_DIR", "").strip()
    if override:
        candidates.append(Path(override).expanduser())
    elif executable:
        directory = Path(executable).parent
        candidates.extend((directory.parent / "lib" / "gufo" / "sdk", directory / "sdk"))
    for candidate in candidates:
        sdk = _read_json(candidate / "sdk.json")
        if sdk and isinstance(sdk.get("build_id"), str) and sdk["build_id"]:
            return sdk["build_id"]
    return ""


def _option_applies_to_serve(option):
    commands = option.get("commands")
    if not isinstance(commands, list) or not commands:
        return True
    return any(command in ("serve", "serve llm") for command in commands if isinstance(command, str))


def read_local_store(store_dir, build_id=""):
    """Read locally installed extension metadata and manifests without network access."""
    installed_path = Path(store_dir) / "installed.json"
    installed_doc = _read_json(installed_path)
    if not installed_doc or installed_doc.get("schema") != 1:
        return {"installed": {}, "manifests": {}}
    entries = installed_doc.get("extensions")
    if not isinstance(entries, list):
        return {"installed": {}, "manifests": {}}

    installed = {}
    manifests = {}
    suffix = _module_suffix()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"]:
            continue
        name = entry["name"]
        source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        status = "unknown"
        if build_id:
            module_path = Path(store_dir) / name / "modules" / f"{build_id}{suffix}"
            status = "ready" if module_path.is_file() else "needs update"
        installed[name] = {
            "name": name,
            "version": entry.get("version", "") if isinstance(entry.get("version"), str) else "",
            "source_kind": source.get("kind", "") if isinstance(source.get("kind"), str) else "",
            "source": source.get("location", "") if isinstance(source.get("location"), str) else "",
            "revision": source.get("revision", "") if isinstance(source.get("revision"), str) else "",
            "replace_builtin": bool(entry.get("replace_builtin", False)),
            "status": status,
        }
        manifest = _read_json(Path(store_dir) / name / "source" / "extension.json")
        if manifest:
            manifests[name] = manifest
    return {"installed": installed, "manifests": manifests}


def parse_provider_options_help(help_text):
    """Parse Gufo's `serve llm --help` Provider options section."""
    if not isinstance(help_text, str) or not help_text:
        return []
    in_section = False
    options = []
    current = None
    for raw_line in help_text.splitlines():
        line = raw_line.rstrip()
        if not in_section:
            if line.strip() == "Provider options:":
                in_section = True
            continue
        if not line:
            continue
        if _SECTION_HEADER.match(line):
            break
        match = _HELP_OPTION_LINE.match(line)
        if match and raw_line.startswith("  ") and not raw_line.startswith("          "):
            flag, hint, rest = match.groups()
            if not PROVIDER_OPTION_NAME.match(flag) or flag in CORE_CLI_FLAGS:
                current = None
                continue
            description = (rest or "").strip()
            providers = []
            suffix = _HELP_PROVIDERS_SUFFIX.search(description)
            if suffix:
                providers = [item.strip() for item in suffix.group(1).split(",") if item.strip()]
                description = description[:suffix.start()].strip()
            current = {
                "name": flag,
                "type": _HELP_HINT_TO_TYPE.get(hint, "string"),
                "help": description,
                "providers": providers,
            }
            options.append(current)
        elif current is not None and raw_line.startswith(" "):
            continuation = line.strip()
            if continuation:
                combined = f"{current['help']} {continuation}".strip()
                suffix = _HELP_PROVIDERS_SUFFIX.search(combined)
                if suffix and not current["providers"]:
                    current["providers"] = [item.strip() for item in suffix.group(1).split(",") if item.strip()]
                    combined = combined[:suffix.start()].strip()
                current["help"] = combined
    return options


def _run_gufo(executable, arguments):
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        [str(executable), *arguments],
        cwd=Path(executable).parent,
        shell=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_INSPECT_TIMEOUT_SECONDS,
        creationflags=creationflags,
    )


def _stat_signature(path):
    try:
        info = Path(path).stat()
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return None


def _empty_result(executable, error=""):
    return {
        "available": False,
        "executable": str(executable or ""),
        "error": error,
        "api_version": "",
        "extensions": [],
        "excluded": [],
        "providers": [],
        "options": [],
        "draft_options": {},
    }


def _merge_discovery(executable, diagnose, help_options, store_data):
    installed_map = store_data["installed"]
    manifests = store_data["manifests"]

    # Map provider -> extension metadata from diagnose and local manifests.
    provider_to_extension = {}
    providers_out = []
    manifest_providers = {}
    draft_options = {}
    manifest_options = {}

    for ext_name, manifest in manifests.items():
        for provider in manifest.get("providers", []) if isinstance(manifest.get("providers"), list) else []:
            if not isinstance(provider, dict) or not isinstance(provider.get("id"), str):
                continue
            pid = provider["id"]
            manifest_providers[pid] = (ext_name, provider)
            serving = provider.get("serving")
            if isinstance(serving, dict) and isinstance(serving.get("draft_options"), dict):
                for mode, flag in serving["draft_options"].items():
                    if isinstance(mode, str) and isinstance(flag, str) and PROVIDER_OPTION_NAME.match(flag):
                        draft_options[flag] = {"provider": pid, "extension": ext_name, "mode": mode}
        for opt in manifest.get("options", []) if isinstance(manifest.get("options"), list) else []:
            if not isinstance(opt, dict) or not _option_applies_to_serve(opt):
                continue
            flag = opt.get("name")
            opt_type = opt.get("type")
            if not isinstance(flag, str) or not PROVIDER_OPTION_NAME.match(flag) or flag in CORE_CLI_FLAGS:
                continue
            if opt_type not in _OPTION_TYPES:
                opt_type = "string"
            opt_providers = [p for p in opt.get("providers", []) if isinstance(p, str)] if isinstance(opt.get("providers"), list) else []
            manifest_options[flag] = {
                "name": flag,
                "type": opt_type,
                "help": opt.get("help", "") if isinstance(opt.get("help"), str) else "",
                "providers": opt_providers,
                "extension": ext_name,
            }

    for entry in diagnose.get("providers", []) if isinstance(diagnose.get("providers"), list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        pid = entry["id"]
        ext_name = entry.get("extension", "") if isinstance(entry.get("extension"), str) else ""
        provider_to_extension[pid] = ext_name
        item = {
            "id": pid,
            "extension": ext_name,
            "available": bool(entry.get("available", False)),
            "reason": entry.get("reason", "") if isinstance(entry.get("reason"), str) else "",
        }
        if pid in manifest_providers:
            _, mprov = manifest_providers[pid]
            if isinstance(mprov.get("capability"), str):
                item["capability"] = mprov["capability"]
            if isinstance(mprov.get("model_ids"), list):
                item["model_ids"] = [m for m in mprov["model_ids"] if isinstance(m, str)]
            if isinstance(mprov.get("speculative"), list):
                item["speculative"] = [s for s in mprov["speculative"] if isinstance(s, str)]
        providers_out.append(item)

    extensions_by_name = {}
    for entry in diagnose.get("builtExtensions", []) if isinstance(diagnose.get("builtExtensions"), list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        name = entry["name"]
        source = entry.get("source", "") if isinstance(entry.get("source"), str) else ""
        installed = installed_map.get(name)
        manifest = manifests.get(name, {})
        platforms = [p for p in manifest.get("platforms", []) if isinstance(p, str)] if isinstance(manifest.get("platforms"), list) else []
        is_module = source == "module" or installed is not None
        extensions_by_name[name] = {
            "name": name,
            "version": entry.get("version", "") if isinstance(entry.get("version"), str) else "",
            "source": source,
            "revision": entry.get("revision", "") if isinstance(entry.get("revision"), str) else "",
            "dirty": bool(entry.get("dirty", False)),
            "builtin": source != "module",
            "installed": is_module,
            "status": "ready",
            "platforms": platforms,
        }

    # Include installed extensions that are not currently loaded (for example, `needs update`).
    for name, installed in installed_map.items():
        if name in extensions_by_name:
            if installed.get("revision") and not extensions_by_name[name]["revision"]:
                extensions_by_name[name]["revision"] = installed["revision"]
            continue
        manifest = manifests.get(name, {})
        platforms = [p for p in manifest.get("platforms", []) if isinstance(p, str)] if isinstance(manifest.get("platforms"), list) else []
        extensions_by_name[name] = {
            "name": name,
            "version": installed["version"],
            "source": installed["source_kind"] or "module",
            "revision": installed["revision"],
            "dirty": False,
            "builtin": False,
            "installed": True,
            "status": installed["status"] if installed["status"] != "unknown" else "not loaded",
            "platforms": platforms,
        }

    excluded_out = []
    for entry in diagnose.get("excludedExtensions", []) if isinstance(diagnose.get("excludedExtensions"), list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        excluded_out.append({
            "name": entry["name"],
            "version": entry.get("version", "") if isinstance(entry.get("version"), str) else "",
            "source": entry.get("source", "") if isinstance(entry.get("source"), str) else "",
            "reason": entry.get("reason", "") if isinstance(entry.get("reason"), str) else "",
        })

    # Build final serve provider options from what the running binary actually accepts.
    options_out = []
    active_draft_options = {}
    seen_flags = set()
    for opt in help_options:
        flag = opt["name"]
        if flag in seen_flags:
            continue
        seen_flags.add(flag)
        mopt = manifest_options.get(flag)
        providers = opt["providers"] or (mopt["providers"] if mopt else [])
        opt_type = mopt["type"] if mopt else opt["type"]
        help_text = mopt["help"] if (mopt and mopt["help"]) else opt["help"]
        exts = sorted({
            provider_to_extension[p] for p in providers if p in provider_to_extension and provider_to_extension[p]
        } | ({mopt["extension"]} if mopt and mopt.get("extension") else set()))
        draft_meta = draft_options.get(flag)
        if draft_meta:
            active_draft_options[flag] = draft_meta
        options_out.append({
            "name": flag,
            "type": opt_type,
            "help": help_text,
            "providers": providers,
            "extensions": exts,
            "draft_mode": draft_meta["mode"] if draft_meta else "",
        })
    options_out.sort(key=lambda item: (",".join(item["extensions"] or item["providers"]), item["name"]))

    return {
        "available": True,
        "executable": str(executable),
        "error": "",
        "api_version": diagnose.get("extensionApiVersion", "") if isinstance(diagnose.get("extensionApiVersion"), str) else "",
        "extensions": sorted(extensions_by_name.values(), key=lambda item: item["name"].casefold()),
        "excluded": excluded_out,
        "providers": providers_out,
        "options": options_out,
        "draft_options": active_draft_options,
    }


def inspect_executable(executable, *, refresh=False, store_dir=None):
    """Discover loaded extensions and serve llm provider options for a Gufo binary."""
    if not isinstance(executable, str) or not executable.strip():
        return _empty_result("")
    exe_path = Path(executable.strip()).expanduser()
    if not exe_path.is_absolute() or not exe_path.is_file():
        return _empty_result(str(exe_path), "Gufo executable not found.")

    resolved_store = Path(store_dir) if store_dir is not None else extension_store_dir()
    cache_key = (
        str(exe_path),
        _stat_signature(exe_path),
        str(resolved_store),
        _stat_signature(resolved_store / "installed.json"),
    )
    if not refresh:
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached is not None:
                return cached

    try:
        diag_proc = _run_gufo(exe_path, ["diagnose", "--section", "extensions", "--json"])
    except (OSError, subprocess.SubprocessError) as exc:
        result = _empty_result(str(exe_path), f"Could not inspect Gufo extensions: {exc}")
    else:
        if diag_proc.returncode != 0:
            detail = (diag_proc.stderr or diag_proc.stdout or "").strip().splitlines()
            message = detail[0] if detail else f"exit code {diag_proc.returncode}"
            result = _empty_result(str(exe_path), f"Extension diagnostics unavailable: {message}")
        else:
            try:
                diagnose = json.loads(diag_proc.stdout)
                if not isinstance(diagnose, dict):
                    raise ValueError("unexpected JSON payload")
            except ValueError:
                result = _empty_result(str(exe_path), "Extension diagnostics returned invalid JSON.")
            else:
                help_options = []
                try:
                    help_proc = _run_gufo(exe_path, ["serve", "llm", "--help"])
                    if help_proc.returncode == 0:
                        help_options = parse_provider_options_help(help_proc.stdout)
                except (OSError, subprocess.SubprocessError):
                    pass
                build_id = _locate_sdk_build_id(exe_path)
                store_data = read_local_store(resolved_store, build_id=build_id)
                result = _merge_discovery(exe_path, diagnose, help_options, store_data)

    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_LIMIT:
            _CACHE.clear()
        _CACHE[cache_key] = result
    return result


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()
