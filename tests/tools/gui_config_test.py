"""Settings survive restarts, and GUI choices generate a safe native argv."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gui"))
from command import build_command
from files import browse_directory, check_gguf
from presets import load_document, new_document, resolved_settings, save_document
from settings import DEFAULTS, validate_settings


class ConfigTest(unittest.TestCase):
    def test_bind_address_validation_and_command(self):
        self.assertEqual(validate_settings({})["host"], "127.0.0.1")
        for host in ("127.0.0.1", "0.0.0.0", "192.168.1.10"):
            command = build_command({"host": host})
            self.assertEqual(command[command.index("--host") + 1], host)
        for host in ("", "localhost", "::1", "http://127.0.0.1", "127.0.0.1:8080", "256.1.1.1", None, True):
            with self.subTest(host=host), self.assertRaises(ValueError):
                validate_settings({"host": host})

    def test_round_trip_and_failed_write_preserves_previous_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings/launcher.json"
            self.assertEqual(resolved_settings(load_document(path)), DEFAULTS)
            settings = DEFAULTS | {"model": str(Path(directory) / "模型 & test.gguf"), "speculative": "mtp"}
            save_document(path, new_document(settings))
            self.assertEqual(resolved_settings(load_document(path)), settings)
            before = path.read_bytes()
            with patch("presets.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    save_document(path, new_document(settings | {"context": 8192}))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            path.write_text('{"version": 99, "settings": {}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                resolved_settings(load_document(path))
            path.write_text("{bad json", encoding="utf-8")
            with self.assertRaises(ValueError):
                resolved_settings(load_document(path))

    def test_retired_windows_options_are_ignored_without_writing(self):
        for key, flag in (("debug_tool_calls", "--debug-tool-calls"),
                          ("mtp_draft_vocab", "--mtp-draft-vocab"),
                          ("prompt_lookup", "--prompt-lookup")):
            with self.subTest(key=key):
                self.assertNotIn(key, validate_settings({key: True}))
                self.assertNotIn(flag, build_command({key: True}))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            legacy = {"debug_tool_calls": True, "mtp_draft_vocab": "latin",
                      "prompt_lookup": True}
            path.write_text(json.dumps({"version": 1, "settings": legacy}), encoding="utf-8")
            before = path.read_bytes()
            settings = resolved_settings(load_document(path))
            for key in legacy:
                self.assertNotIn(key, settings)
            for flag in ("--debug-tool-calls", "--mtp-draft-vocab", "--prompt-lookup"):
                self.assertNotIn(flag, build_command(settings))
            self.assertEqual(path.read_bytes(), before)

    def test_rejects_invalid_values_before_save_or_launch(self):
        for change in ({"port": True}, {"port": 0}, {"port": 65536}, {"context": -1},
                       {"temperature": float("nan")}, {"temperature": 2.1}, {"top_p": 1.1}, {"top_p": 0},
                       {"top_k": 2.5}, {"seed": 2**60}, {"max_tokens": 0}, {"repeat_penalty": 0},
                       {"think": "yes"}, {"mtp": "false"}, {"speculative": "unknown"},
                       {"preserve_thinking": "true"}, {"cache_disk": 1},
                       {"cache_disk": True, "cache_disk_dir": ""}, {"cache_disk_dir": "relative"},
                       {"cache_disk_gib": 0}, {"cache_disk_gib": 1.5},
                       {"cache_disk_staging_gib": -1}, {"cache_disk_staging_gib": True},
                       {"cache_ram_gib": -1}, {"cache_ram_gib": True},
                       {"cache_ram_gib": 1.5}, {"cache_ram_gib": 65537},
                       {"dflash_model": "relative.gguf"}, {"model": "relative.gguf"},
                       {"served_model_name": "line\nbreak"}, {"extra_args": "--anything"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_settings(change)

    def test_ram_cap_is_independent_of_disk_cache_and_saved_per_preset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            document = new_document()
            # Older presets gain the automatic default without a write on load.
            document["presets"][0]["settings"].pop("cache_ram_gib")
            path.write_text(json.dumps(document), encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(resolved_settings(load_document(path))["cache_ram_gib"], 0)
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn("--cache-ram-bytes", build_command(DEFAULTS))
            for disk_enabled in (False, True):
                settings = DEFAULTS | {"cache_ram_gib": 2, "cache_disk": disk_enabled}
                save_document(path, new_document(settings))
                restored = resolved_settings(load_document(path))
                self.assertEqual(restored, settings)
                command = build_command(restored)
                self.assertEqual(command[command.index("--cache-ram-bytes") + 1], str(2 * 1024**3))

    def test_shards_sidecars_and_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="gufo files ") as directory:
            root = Path(directory)
            model = root / "模型-00001-of-00003.gguf"
            model.write_bytes(b"GGUF")  # Metadata-only first shards are valid.
            exe = root / "gufo.exe"
            exe.touch()
            settings = DEFAULTS | {"model": str(model), "executable": str(exe)}
            with self.assertRaisesRegex(ValueError, "missing shard"):
                build_command(settings, check_files=True)
            for index in (2, 3):
                (root / f"模型-{index:05d}-of-00003.gguf").write_bytes(b"GGUF")
            command = build_command(settings, check_files=True)
            self.assertEqual(command[0], str(exe))
            self.assertEqual(command[command.index("--model") + 1], str(model))
            self.assertNotIn("--mmproj", command)
            self.assertNotIn("--mtp-model", command)
            with self.assertRaisesRegex(ValueError, "first shard"):
                check_gguf(str(root / "模型-00002-of-00003.gguf"), "Model", sharded=True)
            settings.update(speculative="mtp")
            with self.assertRaisesRegex(ValueError, "MTP sidecar"):
                build_command(settings, check_files=True)
            sidecar = root / "mtp & sidecar.gguf"
            sidecar.write_bytes(b"GGUF")
            settings.update(mtp_model=str(sidecar), mmproj=str(sidecar))
            command = build_command(settings, check_files=True)
            for flag in ("--mtp-draft-vocab", "--prompt-lookup"):
                self.assertNotIn(flag, command)
            self.assertEqual(command[command.index("--mtp-model") + 1], str(sidecar))
            self.assertEqual(command[command.index("--mmproj") + 1], str(sidecar))
            sidecar.write_text("not a model")
            with self.assertRaisesRegex(ValueError, "GGUF header"):
                build_command(settings, check_files=True)

    def test_legacy_mtp_settings_migrate_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            for enabled, mode in ((True, "mtp"), (False, "off")):
                legacy = {"mtp": enabled, "context": 200000, "draft_tokens": 3,
                          "mtp_model": str(Path(directory) / "mtp.gguf"),
                          "mtp_policy": "survival"}
                path.write_text(json.dumps({"version": 1, "settings": legacy}), encoding="utf-8")
                before = path.read_bytes()
                settings = resolved_settings(load_document(path))
                self.assertEqual(settings["speculative"], mode)
                self.assertNotIn("mtp", settings)
                self.assertNotIn("mtp_policy", settings)
                self.assertEqual(settings["mtp_model"], legacy["mtp_model"])
                self.assertEqual(settings["context"], 200000)
                self.assertEqual(settings["draft_tokens"], 3)
                self.assertEqual(path.read_bytes(), before)
                save_document(path, new_document(settings))
                self.assertEqual(resolved_settings(load_document(path)), settings)

    def test_dflash_and_off_do_not_inherit_mtp_flags(self):
        with tempfile.TemporaryDirectory(prefix="gufo draft ") as directory:
            root = Path(directory)
            exe, model, draft = (root / name for name in ("gufo.exe", "main.gguf", "DFlash2.gguf"))
            exe.touch()
            model.write_bytes(b"GGUF")
            settings = DEFAULTS | {
                "executable": str(exe), "model": str(model), "speculative": "dflash2",
                "dflash_model": str(draft), "mtp_model": str(root / "missing-mtp.gguf"),
            }
            with self.assertRaisesRegex(ValueError, "DFlash2 draft"):
                build_command(settings, check_files=True)
            draft.write_bytes(b"GGUF")
            command = build_command(settings, check_files=True)
            self.assertEqual(command[command.index("--speculative") + 1], "dflash2")
            self.assertEqual(command[command.index("--dflash-model") + 1], str(draft))
            for flag in ("--mtp-model", "--draft-tokens"):
                self.assertNotIn(flag, command)
            path = root / "launcher.json"
            save_document(path, new_document(settings))
            self.assertEqual(resolved_settings(load_document(path)), settings)
            draft.unlink()
            command = build_command(settings | {"speculative": "off"}, check_files=True)
            self.assertEqual(command[command.index("--speculative") + 1], "off")
            self.assertNotIn("--dflash-model", command)
            self.assertNotIn("--mtp-model", command)

    def test_reasoning_and_disk_cache_arguments(self):
        command = build_command({})
        self.assertEqual(command[command.index("--preserve-thinking") + 1], "on")
        self.assertNotIn("--cache-disk", command)
        with tempfile.TemporaryDirectory(prefix="gufo cache ") as directory:
            root = Path(directory)
            exe, model = root / "gufo.exe", root / "model.gguf"
            exe.touch()
            model.write_bytes(b"GGUF")
            cache = root / "new cache" / "snapshots"
            settings = DEFAULTS | {"executable": str(exe), "model": str(model),
                                  "preserve_thinking": False, "think": "off",
                                  "cache_disk": True, "cache_disk_dir": str(cache),
                                  "cache_disk_gib": 16, "cache_disk_staging_gib": 8}
            command = build_command(settings, check_files=True)
            for flag, value in (("--preserve-thinking", "off"), ("--cache-disk", str(cache)),
                                ("--cache-disk-bytes", str(16 * 1024**3)),
                                ("--cache-disk-staging-bytes", str(8 * 1024**3))):
                self.assertEqual(command[command.index(flag) + 1], value)
            self.assertFalse(cache.exists())  # Preview/validation must not create folders.
            automatic = build_command(settings | {"cache_disk_staging_gib": 0})
            self.assertEqual(automatic[automatic.index("--cache-disk-staging-bytes") + 1], "0")
            disabled = build_command(settings | {"cache_disk": False, "preserve_thinking": True})
            self.assertEqual(disabled[disabled.index("--preserve-thinking") + 1], "on")
            self.assertFalse(any(arg.startswith("--cache-disk") for arg in disabled))
            for invalid in (model, model / "child"):
                with self.assertRaisesRegex(ValueError, "folder, not a file"):
                    build_command(settings | {"cache_disk_dir": str(invalid)}, check_files=True)

    def test_folder_picker_groups_shards_without_loading_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "subfolder").mkdir()
            for name in ("model-00001-of-00002.gguf", "model-00002-of-00002.gguf", "mtp.gguf", "gufo.exe", "notes.txt"):
                (root / name).touch()
            result = browse_directory(directory)
            self.assertEqual([entry["name"] for entry in result["entries"]],
                             ["subfolder", "model-00001-of-00002.gguf", "mtp.gguf"])
            self.assertEqual(result["entries"][1]["shards"], 2)
            self.assertEqual([entry["name"] for entry in browse_directory(directory, "executable")["entries"]],
                             ["subfolder", "gufo.exe"])
            with self.assertRaises(ValueError):
                browse_directory("relative")


if __name__ == "__main__":
    unittest.main()
