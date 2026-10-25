"""Local file selection and lightweight artifact checks."""

import os
from pathlib import Path
import re


SHARD = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)


def check_gguf(value, label, *, sharded=False):
    path = Path(value)
    if not value or not path.is_file() or path.suffix.lower() != ".gguf":
        raise ValueError(f"{label}: select an existing GGUF file.")
    with path.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise ValueError(f"{label}: the file does not have a GGUF header.")
    match = SHARD.match(path.name)
    if match and sharded:
        prefix, index, count = match.groups()
        if int(index) != 1 or not 1 <= int(count) <= 99999:
            raise ValueError(f"{label}: select the first shard (-00001-of-...).")
        for number in range(1, int(count) + 1):
            sibling = path.with_name(f"{prefix}-{number:05d}-of-{count}{path.suffix}")
            if not sibling.is_file():
                raise ValueError(f"{label}: missing shard {sibling.name}.")


def browse_directory(value, kind="gguf"):
    if kind not in ("gguf", "executable", "folder"):
        raise ValueError("Unknown file picker type.")
    path = Path(value or Path.home()).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("Choose an existing folder using its full path.")
    path = path.resolve()
    entries = []
    with os.scandir(path) as children:
        for child in children:
            if len(entries) >= 2000:
                raise ValueError("This folder has too many entries. Enter a more specific folder.")
            try:
                is_dir = child.is_dir()
                shard = SHARD.match(child.name)
                if not is_dir:
                    if kind == "folder" or not child.is_file():
                        continue
                    if kind == "gguf" and (not child.name.lower().endswith(".gguf") or
                                           (shard and int(shard[2]) != 1)):
                        continue
                    if kind == "executable" and not (child.name.lower().endswith(".exe") or child.name == "gufo"):
                        continue
                entries.append({"name": child.name, "path": str(path / child.name),
                                "directory": is_dir, "shards": int(shard[3]) if shard else 1})
            except OSError:
                continue  # A deleted or inaccessible entry need not hide the folder.
    entries.sort(key=lambda entry: (not entry["directory"], entry["name"].casefold()))
    roots = [str(Path.home())]
    if os.name == "nt":
        roots.extend(f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").is_dir())
    else:
        roots.append("/")
    return {"path": str(path), "parent": str(path.parent), "roots": roots, "entries": entries}
