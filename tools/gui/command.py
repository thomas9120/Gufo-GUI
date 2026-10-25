"""Build native Gufo arguments from validated launch settings."""

from pathlib import Path

from files import check_gguf
from settings import validate_settings


CLI_FIELDS = (
    "context", "max_tokens", "think", "served_model_name", "temperature",
    "top_k", "top_p", "min_p", "seed", "repeat_penalty", "repeat_last_n",
    "frequency_penalty", "presence_penalty",
)


def build_command(values, *, check_files=False):
    settings = validate_settings(values)
    if check_files:
        if not settings["executable"] or not Path(settings["executable"]).is_file():
            raise ValueError("Select gufo.exe from a built Gufo directory, with its runtime DLLs.")
        check_gguf(settings["model"], "Model", sharded=True)
        if settings["mmproj"]:
            check_gguf(settings["mmproj"], "Vision projector")
        if settings["speculative"] == "mtp":
            check_gguf(settings["mtp_model"], "MTP sidecar")
        elif settings["speculative"] == "dflash2":
            check_gguf(settings["dflash_model"], "DFlash2 draft")
        if settings["cache_disk"]:
            directory = Path(settings["cache_disk_dir"])
            if any(path.exists() and not path.is_dir() for path in (directory, *directory.parents)):
                raise ValueError("Disk cache: choose a folder, not a file.")
    command = [settings["executable"], "serve", "--host", settings["host"],
               "--port", str(settings["port"]), "--sessions", str(settings["sessions"]),
               "llm", "--model", settings["model"]]
    for key in CLI_FIELDS:
        command.extend(["--" + key.replace("_", "-"), str(settings[key])])
    command.extend(["--preserve-thinking", "on" if settings["preserve_thinking"] else "off"])
    if settings["cache_ram_gib"]:
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
        for key in ("mtp_model", "draft_tokens"):
            command.extend(["--" + key.replace("_", "-"), str(settings[key])])
    elif settings["speculative"] == "dflash2":
        command.extend(["--dflash-model", settings["dflash_model"]])
    return command
