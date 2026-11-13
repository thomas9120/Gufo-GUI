"""Thinking budgets survive preset switches and reach the native server."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gui"))
from command import build_command
from presets import change_preset, load_document, new_document, resolved_settings, save_document
from settings import DEFAULTS, validate_settings


class ReasoningBudgetTest(unittest.TestCase):
    def test_legacy_presets_keep_native_defaults_without_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            document = new_document()
            document["presets"][0]["settings"].pop("reasoning_budget")
            path.write_text(json.dumps(document), encoding="utf-8")
            before = path.read_bytes()
            loaded = resolved_settings(load_document(path))
            self.assertEqual(loaded["reasoning_budget"], -1)
            self.assertNotIn("--reasoning-budget", build_command(loaded))
            self.assertEqual(path.read_bytes(), before)

    def test_budget_roundtrip_keeps_other_preset_and_mtp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            original = new_document(DEFAULTS | {"model_family": "qwen38_27b", "speculative": "dflash2"})
            flash = DEFAULTS | {"model_family": "qwen38_flash_next", "speculative": "mtp",
                                "max_tokens": 8192, "reasoning_budget": 4096}
            changed = change_preset(original, {"action": "create", "name": "Flash", "settings": flash,
                                               "revision": original["revision"]})
            save_document(path, changed)
            restored = load_document(path)
            self.assertEqual(resolved_settings(restored, "default"), resolved_settings(original))
            self.assertEqual(resolved_settings(restored), flash)
            command = build_command(resolved_settings(restored))
            for flag, expected in [("--max-tokens", "8192"), ("--reasoning-budget", "4096"),
                                   ("--speculative", "mtp")]:
                self.assertEqual(command[command.index(flag) + 1], expected)

    def test_budget_boundaries_match_engine_contract(self):
        for value in [-1, 0, 4096, 2**31 - 1]:
            command = build_command({"reasoning_budget": value})
            if value >= 0:
                self.assertEqual(command[command.index("--reasoning-budget") + 1], str(value))
            else:
                self.assertNotIn("--reasoning-budget", command)
        for value in [-2, 1.5, True, "4096", 2**31]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_settings({"reasoning_budget": value})


if __name__ == "__main__":
    unittest.main()
