"""Build native Gufo arguments from validated launch settings."""

from pathlib import Path

from files import check_gguf
from settings import validate_settings


CLI_FIELDS = (
    "context", "max_tokens", "think", "served_model_name", "temperature",
    "top_k", "top_p", "min_p", "seed", "repeat_penalty", "repeat_last_n",
    "frequency_penalty", "presence_penalty",
)


def build_command(values, *, check_files=False, extension_info=None):
    settings = validate_settings(values)
    option_specs = {
        opt["name"]: opt for opt in (extension_info or {}).get("options", [])
        if isinstance(opt, dict) and isinstance(opt.get("name"), str)
    }
    draft_options = (extension_info or {}).get("draft_options", {})
    if not isinstance(draft_options, dict):
        draft_options = {}
    if check_files:
        if not settings["executable"] or not Path(settings["executable"]).is_file():
            raise ValueError("Select gufo.exe from a built Gufo directory, with its runtime DLLs.")
        check_gguf(settings["model"], "Model", sharded=True)
        if settings["mmproj"]:
            check_gguf(settings["mmproj"], "Vision projector")
        if settings["speculative"] == "mtp":
            check_gguf(settings["mtp_model"], "MTP sidecar")
        elif settings["speculative"] == "dspark":
            check_gguf(settings["dspark_model"], "DSpark support model")
        elif settings["speculative"] == "dflash2":
            check_gguf(settings["dflash_model"], "DFlash2 draft")
        if settings["cache_disk"]:
            directory = Path(settings["cache_disk_dir"])
            if any(path.exists() and not path.is_dir() for path in (directory, *directory.parents)):
                raise ValueError("Disk cache: choose a folder, not a file.")
    provider_args = []
    for flag, value in settings["provider_options"].items():
        if flag in draft_options and settings["speculative"] != "off":
            raise ValueError(f"{flag}: set Speculative decoding to Off when using this extension's drafter.")
        spec = option_specs.get(flag)
        if spec:
            opt_type = spec.get("type")
            if opt_type == "boolean":
                if type(value) is not bool:
                    raise ValueError(f"{flag}: expected a checkbox value.")
            elif opt_type == "integer":
                if type(value) is not int:
                    raise ValueError(f"{flag}: enter a whole number.")
            elif opt_type == "number":
                if type(value) not in (int, float):
                    raise ValueError(f"{flag}: enter a number.")
            elif opt_type == "path":
                if not isinstance(value, str):
                    raise ValueError(f"{flag}: use a full filesystem path.")
                expanded = Path(value).expanduser()
                if not expanded.is_absolute():
                    raise ValueError(f"{flag}: use a full filesystem path.")
                if check_files and not expanded.exists():
                    raise ValueError(f"{flag}: select an existing file or folder.")
                value = str(expanded)
            elif opt_type == "string":
                if not isinstance(value, str):
                    raise ValueError(f"{flag}: enter a single line of text.")
        if value is True:
            provider_args.append(flag)
        elif value not in (False, None, ""):
            provider_args.append(f"{flag}={value}")
    command = [settings["executable"], "serve", "--host", settings["host"],
               "--port", str(settings["port"]), "--sessions", str(settings["sessions"]),
               "llm", "--model", settings["model"]]
    for key in CLI_FIELDS:
        command.extend(["--" + key.replace("_", "-"), str(settings[key])])
    if settings["reasoning_budget"] >= 0:
        command.extend(["--reasoning-budget", str(settings["reasoning_budget"])])
    command.extend(["--preserve-thinking", settings["preserve_thinking"]])
    if settings["cache_ram_off"]:
        command.extend(["--cache-ram-bytes", "off"])
    elif settings["cache_ram_gib"]:
        command.extend(["--cache-ram-bytes", str(settings["cache_ram_gib"] * 1024**3)])
    if settings["cache_disk"]:
        command.extend(["--cache-disk", settings["cache_disk_dir"],
                        "--cache-disk-bytes", str(settings["cache_disk_gib"] * 1024**3),
                        "--cache-disk-staging-bytes", str(settings["cache_disk_staging_gib"] * 1024**3)])
    if settings["think"] != "off" and settings["reasoning_effort"] != "auto":
        command.extend(["--reasoning-effort", settings["reasoning_effort"]])
    if settings["mmproj"]:
        command.extend(["--mmproj", settings["mmproj"]])
    command.extend(["--speculative", settings["speculative"]])
    if settings["speculative"] == "mtp":
        command.extend(["--mtp-model", settings["mtp_model"]])
    elif settings["speculative"] == "dspark":
        command.extend(["--dspark-model", settings["dspark_model"]])
    elif settings["speculative"] == "dflash2":
        command.extend(["--dflash-model", settings["dflash_model"]])
    command.extend(provider_args)
    return command
