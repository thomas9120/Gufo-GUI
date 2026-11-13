"""Current engine options and migration of older presets."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gui"))
from command import build_command
from presets import load_document, new_document, resolved_settings, save_document
from settings import validate_settings


class EngineAlignmentTest(unittest.TestCase):
    def test_legacy_preservation_and_draft_settings_migrate_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            for old, expected in ((True, "on"), (False, "off")):
                for version in (1, 2):
                    values = {"preserve_thinking": old, "draft_tokens": 3}
                    document = {"version": 1, "settings": values} if version == 1 else new_document()
                    if version == 2:
                        document["presets"][0]["settings"].update(values)
                    before = json.dumps(document).encode()
                    path.write_bytes(before)
                    restored = resolved_settings(load_document(path))
                    self.assertEqual(restored["preserve_thinking"], expected)
                    self.assertNotIn("draft_tokens", restored)
                    self.assertEqual(path.read_bytes(), before)
                    save_document(path, new_document(restored))
                    self.assertEqual(resolved_settings(load_document(path)), restored)

    def test_reasoning_modes_and_ram_off(self):
        for level in ("minimal", "low", "medium", "high", "xhigh", "max"):
            command = build_command({"reasoning_effort": level})
            self.assertEqual(command[command.index("--reasoning-effort") + 1], level)
        for mode in ("auto", "on", "off"):
            command = build_command({"preserve_thinking": mode})
            self.assertEqual(command[command.index("--preserve-thinking") + 1], mode)
        command = build_command({"cache_ram_off": True, "cache_ram_gib": 16, "cache_disk": True})
        self.assertEqual(command[command.index("--cache-ram-bytes") + 1], "off")
        self.assertIn("--cache-disk", command)
        with self.assertRaises(ValueError):
            validate_settings({"cache_ram_off": "off"})

    def test_dspark_checks_support_file_and_emits_only_selected_draft(self):
        with tempfile.TemporaryDirectory(prefix="gufo dspark ") as directory:
            root = Path(directory)
            exe, model, support = (root / name for name in ("gufo.exe", "model.gguf", "support.gguf"))
            exe.touch()
            model.write_bytes(b"GGUF")
            values = {"executable": str(exe), "model": str(model), "model_family": "deepseek_v4_flash",
                      "speculative": "dspark", "dspark_model": str(support), "draft_tokens": 7}
            with self.assertRaisesRegex(ValueError, "DSpark support model"):
                build_command(values, check_files=True)
            support.write_bytes(b"GGUF")
            command = build_command(values, check_files=True)
            self.assertEqual(command[command.index("--dspark-model") + 1], str(support))
            for flag in ("--mtp-model", "--dflash-model", "--draft-tokens"):
                self.assertNotIn(flag, command)
            path = root / "launcher.json"
            save_document(path, new_document(validate_settings(values)))
            self.assertEqual(resolved_settings(load_document(path))["dspark_model"], str(support))
            support.unlink()
            self.assertNotIn("--dspark-model", build_command(values | {"speculative": "off"}, check_files=True))
            for family in ("qwen38_flash_next", "qwen38_27b"):
                with self.assertRaisesRegex(ValueError, "does not support"):
                    validate_settings(values | {"model_family": family})
