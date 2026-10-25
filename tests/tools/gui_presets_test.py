"""Preset lifecycle, migration, and model constraints without loading weights."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gui"))
from command import build_command
from presets import (change_preset, export_presets, import_presets, load_document, new_document,
                     resolved_settings, save_document, validate_document)
from settings import DEFAULTS


class PresetsTest(unittest.TestCase):
    def test_bind_address_migration_and_shared_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            legacy = new_document({"context": 8192})
            del legacy["launcher"]["host"]
            path.write_text(json.dumps(legacy), encoding="utf-8")
            before = path.read_bytes()
            document = load_document(path)
            self.assertEqual(resolved_settings(document)["host"], "127.0.0.1")
            self.assertEqual(path.read_bytes(), before)
            values = resolved_settings(document) | {"host": "0.0.0.0"}
            document = self.change(document, action="create", name="Network", settings=values)
            save_document(path, document)
            restored = load_document(path)
            self.assertEqual(resolved_settings(restored)["host"], "0.0.0.0")
            self.assertEqual(resolved_settings(restored, "default")["host"], "0.0.0.0")
            self.assertNotIn("host", restored["presets"][0]["settings"])

    def change(self, document, **request):
        return change_preset(document, {"revision": document["revision"], **request})

    def test_migration_preserves_values_and_original_until_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            legacy = {"mtp": True, "context": 200000, "temperature": 0.7,
                      "mtp_model": str(Path(directory) / "sidecar.gguf")}
            original = json.dumps({"version": 1, "settings": legacy}).encode()
            path.write_bytes(original)
            document = load_document(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(path.with_name("launcher.json.bak").exists())
            values = resolved_settings(document)
            self.assertEqual((values["speculative"], values["context"], values["temperature"]), ("mtp", 200000, 0.7))
            self.assertEqual(values["mtp_model"], legacy["mtp_model"])
            self.assertEqual(document["presets"][0]["name"], "Default")
            self.assertEqual(values["model_family"], "generic")
            save_document(path, document)
            self.assertEqual(load_document(path), document)
            self.assertEqual(path.with_name("launcher.json.bak").read_bytes(), original)

    def test_cache_defaults_upgrade_in_memory_and_save_per_preset(self):
        fields = ("preserve_thinking", "cache_ram_gib", "cache_disk", "cache_disk_dir", "cache_disk_gib", "cache_disk_staging_gib")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            legacy = new_document()
            for key in fields:
                del legacy["presets"][0]["settings"][key]
            original = json.dumps(legacy).encode()
            path.write_bytes(original)
            document = load_document(path)
            values = resolved_settings(document)
            self.assertTrue(values["preserve_thinking"])
            self.assertFalse(values["cache_disk"])
            self.assertEqual(values["cache_ram_gib"], 0)
            self.assertEqual(path.read_bytes(), original)
            changed = values | {"preserve_thinking": False, "cache_ram_gib": 2, "cache_disk": True,
                                "cache_disk_dir": str(Path(directory) / "cache"),
                                "cache_disk_gib": 16, "cache_disk_staging_gib": 8}
            document = self.change(document, action="create", name="Disk cache", settings=changed)
            save_document(path, document)
            restored = load_document(path)
            self.assertEqual(resolved_settings(restored), changed)
            self.assertEqual(resolved_settings(restored, "default"), values)

    def test_lifecycle_keeps_ids_and_shared_settings_separate(self):
        original = new_document()
        values = DEFAULTS | {"context": 65536, "port": 8088, "model_family": "qwen38_27b",
                             "speculative": "dflash2", "temperature": 0.6}
        created = self.change(original, action="create", name="27B · 64K", settings=values)
        preset_id = created["selected_preset"]
        self.assertNotEqual(preset_id, "default")
        self.assertEqual(len(original["presets"]), 1)
        self.assertEqual(resolved_settings(created), values)
        self.assertEqual(resolved_settings(created, "default")["port"], 8088)
        self.assertEqual(resolved_settings(created, "default")["context"], 32768)
        self.assertNotIn("port", created["presets"][1]["settings"])
        renamed = self.change(created, action="rename", id=preset_id, name="Everyday")
        self.assertEqual(renamed["presets"][1]["id"], preset_id)
        self.assertEqual(resolved_settings(renamed), values)
        saved = self.change(renamed, action="save", id=preset_id, settings=values | {"context": 8192})
        self.assertEqual(resolved_settings(saved)["context"], 8192)
        deleted = self.change(saved, action="delete", id=preset_id)
        self.assertEqual(deleted["selected_preset"], "default")
        self.assertEqual(deleted["revision"], 4)
        with self.assertRaisesRegex(ValueError, "at least one"):
            self.change(deleted, action="delete", id="default")

    def test_rejects_stale_unknown_and_duplicate_operations(self):
        document = new_document()
        for request in ({"action": "save", "id": "default", "settings": DEFAULTS, "revision": 9},
                        {"action": "delete", "id": "missing", "revision": 0},
                        {"action": "create", "name": "default", "settings": DEFAULTS, "revision": 0},
                        {"action": "rename", "id": "default", "name": "\nOops", "revision": 0},
                        {"action": "rename", "id": "default", "name": " ", "revision": 0},
                        {"action": "save", "id": "default", "settings": DEFAULTS, "revision": True}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                change_preset(document, request)
        self.assertEqual(document, new_document())

    def test_invalid_documents_and_failed_writes_preserve_saved_state(self):
        document = new_document()
        invalid = deepcopy(document)
        invalid["selected_preset"] = "missing"
        with self.assertRaises(ValueError):
            validate_document(invalid)
        invalid = deepcopy(document)
        invalid["presets"][0]["settings"]["port"] = 8000
        with self.assertRaises(ValueError):
            validate_document(invalid)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            save_document(path, document)
            before = path.read_bytes()
            changed = self.change(document, action="rename", id="default", name="Changed")
            with patch("presets.os.replace", side_effect=OSError("disk error")), self.assertRaises(OSError):
                save_document(path, changed)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_family_constraints_and_inactive_flags(self):
        for family, mode in (("qwen38_flash_next", "dflash2"), ("qwen38_27b", "mtp")):
            with self.subTest(family=family), self.assertRaisesRegex(ValueError, "does not support"):
                build_command(DEFAULTS | {"model_family": family, "speculative": mode})
        values = DEFAULTS | {"model_family": "qwen38_27b", "speculative": "dflash2",
                             "reasoning_effort": "low", "think": "off"}
        command = build_command(values)
        for flag in ("--model-family", "--reasoning-effort", "--mtp-draft-vocab", "--prompt-lookup", "--mtp-model"):
            self.assertNotIn(flag, command)
        self.assertIn("--dflash-model", command)

    def test_corrupt_version_two_is_backed_up_before_explicit_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            original = b'{"version": 2, "presets": "broken"}'
            path.write_bytes(original)
            with self.assertRaises(ValueError):
                load_document(path)
            save_document(path, new_document())
            self.assertEqual(path.with_name("launcher.json.bak").read_bytes(), original)
            path.write_bytes(b"another broken document")
            save_document(path, new_document())
            self.assertEqual(path.with_name("launcher.json.bak").read_bytes(), original)

    def test_export_round_trips_all_presets_without_shared_settings(self):
        document = self.change(new_document(), action="create", name="Long", settings=DEFAULTS | {"context": 65536})
        backup = export_presets(document)
        self.assertEqual([preset["name"] for preset in backup["presets"]], ["Default", "Long"])
        for preset in backup["presets"]:
            self.assertFalse({"executable", "models_dir", "host", "port"} & preset["settings"].keys())
        target = new_document({"context": 4096, "port": 9000})
        imported = import_presets(target, {"revision": 0, "data": json.loads(json.dumps(backup))})
        self.assertEqual(imported["revision"], 1)
        self.assertEqual(imported["launcher"], target["launcher"])
        self.assertEqual(imported["selected_preset"], "default")
        self.assertEqual(imported["presets"][0], target["presets"][0])
        self.assertEqual([preset["name"] for preset in imported["presets"]], ["Default", "Default (2)", "Long"])
        self.assertEqual(resolved_settings(imported, imported["presets"][2]["id"])["context"], 65536)
        self.assertEqual(resolved_settings(imported, imported["presets"][2]["id"])["port"], 9000)
        self.assertEqual(len({preset["id"] for preset in imported["presets"]}), 3)

    def test_import_rejects_bad_files_without_changing_anything(self):
        document = new_document()
        good = {"name": "Good", "settings": {"context": 8192}}
        wrapper = {"format": "gufo-presets", "version": 1}
        bad = (
            {"format": "other", "version": 1, "presets": [good]},
            wrapper | {"version": 2, "presets": [good]},
            wrapper | {"presets": []},
            wrapper | {"presets": [good, {"name": "Bad", "settings": {"context": "huge"}}]},
            wrapper | {"presets": [{"name": "Bad", "settings": {"unknown": 1}}]},
            wrapper | {"presets": [{"name": "", "settings": {}}]},
            wrapper | {"presets": [good | {"extra": 1}]},
            wrapper | {"presets": [good] * 100},
            [good],
        )
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                import_presets(document, {"revision": 0, "data": data})
        with self.assertRaisesRegex(ValueError, "another tab"):
            import_presets(document, {"revision": 7, "data": wrapper | {"presets": [good]}})
        self.assertEqual(document, new_document())

    def test_import_ignores_shared_fields_and_keeps_long_names_unique(self):
        document = new_document()
        name = "x" * 80
        data = {"format": "gufo-presets", "version": 1, "presets": [
            {"name": name, "settings": {"port": 9999, "host": "0.0.0.0"}}, {"name": name, "settings": {}}]}
        imported = import_presets(document, {"revision": 0, "data": data})
        self.assertEqual(imported["launcher"], document["launcher"])
        names = [preset["name"] for preset in imported["presets"]]
        self.assertEqual(len(set(names)), 3)
        self.assertTrue(all(len(item) <= 80 for item in names))

    def test_invalid_legacy_payload_is_not_silently_replaced_with_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "launcher.json"
            for payload in (None, [], "", False):
                path.write_text(json.dumps({"version": 1, "settings": payload}), encoding="utf-8")
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    load_document(path)


if __name__ == "__main__":
    unittest.main()
