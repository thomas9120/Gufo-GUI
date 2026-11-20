"""Extension discovery, provider option validation, command building, and HTTP routes."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gui"))
from command import build_command
import extensions
from files import browse_directory
from launcher_process import ProcessManager
from presets import export_presets, import_presets, load_document, new_document, resolved_settings, save_document
from server import create_app
from settings import DEFAULTS, validate_settings


HY4_HELP = """Usage: gufo serve llm [OPTIONS]

Speculative:
      --speculative MODE       HTTP draft backend: dspark, dflash2, mtp, or off

Provider options:
      --dfly-draft-tokens N    Most tokens DFly2 drafts per step, 1 to 7 (default 7) (hy4flash)
      --dfly-model PATH        DFly2 drafter: its safetensors file or checkpoint directory (hy4flash)
      --custom-scale X         Scale factor
                               for testing wrapped lines (hy4flash)
      --custom-tag VALUE       Tag text (hy4flash, other)
      --enable-fast            Fast mode toggle (hy4flash)

General:
  -h, --help                   Show this help message
"""

HY4_MANIFEST = {
    "schema": 1,
    "name": "hy4flash",
    "version": "0.1.0",
    "platforms": ["linux"],
    "providers": [
        {
            "id": "hy4flash",
            "capability": "text_generation",
            "keys": ["gguf:hy_v4_flash"],
            "model_ids": ["Hy4 Flash"],
            "speculative": ["dfly"],
            "serving": {"draft_options": {"dfly": "--dfly-model"}},
        }
    ],
    "options": [
        {
            "name": "--dfly-model",
            "type": "path",
            "commands": ["serve"],
            "providers": ["hy4flash"],
            "help": "DFly2 drafter: its safetensors file or checkpoint directory",
        },
        {
            "name": "--dfly-draft-tokens",
            "type": "integer",
            "commands": ["serve"],
            "providers": ["hy4flash"],
            "help": "Most tokens DFly2 drafts per step, 1 to 7 (default 7)",
        },
    ],
}

HY4_DIAGNOSE = {
    "extensionApiVersion": "0.3.29",
    "selectionMode": "all",
    "builtExtensions": [
        {"name": "qwen38", "version": "0.3.29", "source": "official"},
        {"name": "hy4flash", "version": "0.1.0", "source": "module", "revision": "abc1234", "dirty": False},
    ],
    "excludedExtensions": [],
    "providers": [
        {"id": "hy4flash", "extension": "hy4flash", "available": True, "reason": ""},
    ],
    "sharedKeys": [],
}


class ExtensionsTest(unittest.TestCase):
    def setUp(self):
        extensions.clear_cache()
        self.addCleanup(extensions.clear_cache)

    def test_parse_provider_options_help_extracts_types_and_providers(self):
        parsed = extensions.parse_provider_options_help(HY4_HELP)
        by_name = {opt["name"]: opt for opt in parsed}
        self.assertEqual(
            set(by_name),
            {"--dfly-draft-tokens", "--dfly-model", "--custom-scale", "--custom-tag", "--enable-fast"},
        )
        self.assertEqual(by_name["--dfly-draft-tokens"]["type"], "integer")
        self.assertEqual(by_name["--dfly-draft-tokens"]["providers"], ["hy4flash"])
        self.assertEqual(by_name["--dfly-model"]["type"], "path")
        self.assertEqual(by_name["--custom-scale"]["type"], "number")
        self.assertIn("wrapped lines", by_name["--custom-scale"]["help"])
        self.assertEqual(by_name["--custom-scale"]["providers"], ["hy4flash"])
        self.assertEqual(by_name["--custom-tag"]["type"], "string")
        self.assertEqual(by_name["--custom-tag"]["providers"], ["hy4flash", "other"])
        self.assertEqual(by_name["--enable-fast"]["type"], "boolean")
        self.assertNotIn("--help", by_name)
        self.assertNotIn("--speculative", by_name)

    def test_inspect_executable_merges_diagnose_help_and_local_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / ("gufo.exe" if os.name == "nt" else "gufo")
            exe.write_bytes(b"binary")
            sdk = root / "sdk"
            sdk.mkdir()
            (sdk / "sdk.json").write_text(json.dumps({"schema": 1, "build_id": "build-123"}), encoding="utf-8")

            store = root / "store"
            (store / "hy4flash" / "source").mkdir(parents=True)
            (store / "hy4flash" / "modules").mkdir(parents=True)
            suffix = ".dll" if os.name == "nt" else ".so"
            (store / "hy4flash" / "modules" / f"build-123{suffix}").write_bytes(b"mod")
            (store / "hy4flash" / "source" / "extension.json").write_text(json.dumps(HY4_MANIFEST), encoding="utf-8")
            (store / "installed.json").write_text(
                json.dumps({
                    "schema": 1,
                    "extensions": [
                        {
                            "name": "hy4flash",
                            "version": "0.1.0",
                            "source": {"kind": "git", "location": "https://github.com/franzmoca/hy4-gufo-extension", "revision": "abc1234"},
                            "digest": "deadbeef",
                            "replace_builtin": False,
                        },
                        {
                            "name": "stale_ext",
                            "version": "0.2.0",
                            "source": {"kind": "registry", "location": "stale_ext", "revision": "0.2.0"},
                            "digest": "1234",
                            "replace_builtin": False,
                        },
                    ],
                }),
                encoding="utf-8",
            )

            def fake_run(cmd, **kwargs):
                if "diagnose" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(HY4_DIAGNOSE), stderr="")
                if "serve" in cmd:
                    return subprocess.CompletedProcess(cmd, 0, stdout=HY4_HELP, stderr="")
                raise AssertionError(f"Unexpected command {cmd}")

            with patch("extensions.subprocess.run", side_effect=fake_run) as mocked:
                info = extensions.inspect_executable(str(exe), store_dir=store)
                self.assertTrue(info["available"])
                self.assertEqual(info["api_version"], "0.3.29")
                exts = {item["name"]: item for item in info["extensions"]}
                self.assertEqual(exts["hy4flash"]["status"], "ready")
                self.assertTrue(exts["hy4flash"]["installed"])
                self.assertEqual(exts["hy4flash"]["platforms"], ["linux"])
                self.assertEqual(exts["qwen38"]["builtin"], True)
                self.assertEqual(exts["stale_ext"]["status"], "needs update")
                opts = {opt["name"]: opt for opt in info["options"]}
                self.assertEqual(opts["--dfly-model"]["draft_mode"], "dfly")
                self.assertEqual(opts["--dfly-model"]["extensions"], ["hy4flash"])
                self.assertIn("--dfly-model", info["draft_options"])
                self.assertEqual(mocked.call_count, 2)
                # Cached call does not re-run subprocess.
                self.assertEqual(extensions.inspect_executable(str(exe), store_dir=store), info)
                self.assertEqual(mocked.call_count, 2)
                # Explicit refresh re-runs subprocess.
                extensions.inspect_executable(str(exe), refresh=True, store_dir=store)
                self.assertEqual(mocked.call_count, 4)

    def test_inspect_executable_degrades_gracefully(self):
        missing = extensions.inspect_executable(str(Path(tempfile.gettempdir()) / "nonexistent-gufo-binary"))
        self.assertFalse(missing["available"])
        self.assertEqual(missing["options"], [])
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / "gufo.exe"
            exe.touch()
            with patch("extensions.subprocess.run", side_effect=OSError("not executable")):
                failed = extensions.inspect_executable(str(exe), store_dir=Path(directory) / "store")
            self.assertFalse(failed["available"])
            self.assertIn("Could not inspect", failed["error"])

    def test_provider_options_validation_and_preset_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft_dir = root / "tencent-dfly2"
            draft_dir.mkdir()
            settings = DEFAULTS | {
                "provider_options": {
                    "--dfly-model": f"  {draft_dir}  ",
                    "--dfly-draft-tokens": 5,
                    "--enable-fast": True,
                    "--ignored-empty": "   ",
                    "--ignored-false": False,
                    "--ignored-none": None,
                }
            }
            validated = validate_settings(settings)
            self.assertEqual(
                validated["provider_options"],
                {"--dfly-draft-tokens": 5, "--dfly-model": str(draft_dir), "--enable-fast": True},
            )
            path = root / "launcher.json"
            doc = save_document(path, new_document(validated))
            self.assertEqual(resolved_settings(load_document(path))["provider_options"], validated["provider_options"])
            backup = export_presets(doc)
            imported = import_presets(doc, {"data": backup, "revision": doc["revision"]})
            self.assertEqual(imported["presets"][1]["settings"]["provider_options"], validated["provider_options"])

            # Existing presets without provider_options still load untouched.
            doc["presets"][0]["settings"].pop("provider_options")
            raw = json.dumps(doc).encode()
            path.write_bytes(raw)
            self.assertEqual(resolved_settings(load_document(path))["provider_options"], {})
            self.assertEqual(path.read_bytes(), raw)

        for bad in (
            {"provider_options": ["--dfly-model"]},
            {"provider_options": {"dfly-model": "x"}},
            {"provider_options": {"--Bad": "x"}},
            {"provider_options": {"--model": "/tmp/a.gguf"}},
            {"provider_options": {"--speculative": "dfly"}},
            {"provider_options": {"--dfly-model": "line\nbreak"}},
            {"provider_options": {"--custom-scale": float("nan")}},
            {"provider_options": {"--dfly-model": ["nested"]}},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_settings(bad)

    def test_build_command_emits_provider_options_and_checks_paths_and_conflicts(self):
        with tempfile.TemporaryDirectory(prefix="gufo ext ") as directory:
            root = Path(directory)
            exe = root / "gufo.exe"
            model = root / "Hy4-flash-00001-of-00002.gguf"
            shard2 = root / "Hy4-flash-00002-of-00002.gguf"
            dfly_dir = root / "tencent-dfly2"
            dfly_file = dfly_dir / "model-00148-of-00148.safetensors"
            exe.touch()
            model.write_bytes(b"GGUF")
            shard2.write_bytes(b"GGUF")
            dfly_dir.mkdir()
            dfly_file.write_bytes(b"weights")

            ext_info = {
                "available": True,
                "options": [
                    {"name": "--dfly-model", "type": "path"},
                    {"name": "--dfly-draft-tokens", "type": "integer"},
                    {"name": "--enable-fast", "type": "boolean"},
                ],
                "draft_options": {"--dfly-model": {"provider": "hy4flash", "mode": "dfly"}},
            }
            for target in (dfly_dir, dfly_file):
                values = DEFAULTS | {
                    "executable": str(exe),
                    "model": str(model),
                    "speculative": "off",
                    "provider_options": {
                        "--dfly-model": str(target),
                        "--dfly-draft-tokens": 6,
                        "--enable-fast": True,
                    },
                }
                cmd = build_command(values, check_files=True, extension_info=ext_info)
                self.assertIn(f"--dfly-model={target}", cmd)
                self.assertIn("--dfly-draft-tokens=6", cmd)
                self.assertIn("--enable-fast", cmd)

            # Missing path rejected on launch.
            with self.assertRaisesRegex(ValueError, "existing file or folder"):
                build_command(
                    DEFAULTS | {
                        "executable": str(exe),
                        "model": str(model),
                        "provider_options": {"--dfly-model": str(root / "missing")},
                    },
                    check_files=True,
                    extension_info=ext_info,
                )

            # Relative path rejected for path option.
            with self.assertRaisesRegex(ValueError, "full filesystem path"):
                build_command(
                    DEFAULTS | {"provider_options": {"--dfly-model": "relative/dfly"}},
                    extension_info=ext_info,
                )

            # Core speculative mode conflicts with extension draft option.
            with self.assertRaisesRegex(ValueError, "Speculative decoding to Off"):
                build_command(
                    DEFAULTS | {
                        "speculative": "mtp",
                        "provider_options": {"--dfly-model": str(dfly_dir)},
                    },
                    extension_info=ext_info,
                )

            # Type mismatch caught against discovered option spec.
            with self.assertRaisesRegex(ValueError, "whole number"):
                build_command(
                    DEFAULTS | {"provider_options": {"--dfly-draft-tokens": "six"}},
                    extension_info=ext_info,
                )

    def test_browse_directory_path_kind_shows_non_gguf_files_and_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "checkpoint").mkdir()
            (root / "model-00148-of-00148.safetensors").touch()
            (root / "config.json").touch()
            result = browse_directory(directory, kind="path")
            self.assertEqual(
                [entry["name"] for entry in result["entries"]],
                ["checkpoint", "config.json", "model-00148-of-00148.safetensors"],
            )

    def test_extensions_http_route_and_launch_integration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "gufo.exe"
            model = root / "Hy4.gguf"
            dfly = root / "dfly.safetensors"
            exe.touch()
            model.write_bytes(b"GGUF")
            dfly.write_bytes(b"data")

            manager = Mock(spec=ProcessManager)
            manager.snapshot.return_value = {"state": "stopped"}
            manager.start.return_value = {"state": "loading"}
            manager.stop.return_value = {"state": "stopped"}

            ext_info = {
                "available": True,
                "executable": str(exe),
                "error": "",
                "api_version": "0.3.29",
                "extensions": [{"name": "hy4flash", "version": "0.1.0", "status": "ready", "installed": True, "builtin": False}],
                "excluded": [],
                "providers": [{"id": "hy4flash", "extension": "hy4flash", "available": True, "reason": ""}],
                "options": [
                    {"name": "--dfly-model", "type": "path", "help": "DFly2 drafter", "providers": ["hy4flash"], "extensions": ["hy4flash"], "draft_mode": "dfly"},
                    {"name": "--dfly-draft-tokens", "type": "integer", "help": "Draft tokens", "providers": ["hy4flash"], "extensions": ["hy4flash"], "draft_mode": ""},
                ],
                "draft_options": {"--dfly-model": {"provider": "hy4flash", "extension": "hy4flash", "mode": "dfly"}},
            }
            with patch("server.inspect_executable", return_value=ext_info) as mocked:
                app = create_app(root / "settings.json", manager, threading.Event())
                client = app.test_client()
                page = client.get("/")
                token = re.search(r'name="gufo-token" content="([^"]+)"', page.text)[1]
                headers = {"X-Gufo-Token": token}

                # Token and origin protections apply to /api/extensions.
                self.assertEqual(client.post("/api/extensions").status_code, 403)
                self.assertEqual(
                    client.post("/api/extensions", headers=headers | {"Origin": "https://evil.example"}).status_code,
                    403,
                )

                initial = client.get("/api/settings", headers=headers)
                self.assertEqual(initial.status_code, 200)
                self.assertEqual(initial.json["extensions"]["options"][0]["name"], "--dfly-model")

                refreshed = client.post("/api/extensions", json={"executable": str(exe), "refresh": True}, headers=headers)
                self.assertEqual(refreshed.status_code, 200)
                self.assertEqual(refreshed.json["api_version"], "0.3.29")
                mocked.assert_any_call(str(exe), refresh=True)

                # Invalid payloads rejected cleanly.
                self.assertEqual(client.post("/api/extensions", json={"executable": "relative/gufo"}, headers=headers).status_code, 400)
                self.assertEqual(client.post("/api/extensions", json={"unknown": 1}, headers=headers).status_code, 400)

                settings = DEFAULTS | {
                    "executable": str(exe),
                    "model": str(model),
                    "provider_options": {"--dfly-model": str(dfly), "--dfly-draft-tokens": 4},
                }
                preview = client.post("/api/preview", json=settings, headers=headers)
                self.assertEqual(preview.status_code, 200)
                self.assertIn("--dfly-model=", preview.json["command"])
                self.assertIn("--dfly-draft-tokens=4", preview.json["command"])

                started = client.post("/api/start", json={"settings": settings, "preset_id": "default"}, headers=headers)
                self.assertEqual(started.status_code, 200)
                argv = manager.start.call_args.args[0]
                self.assertIn(f"--dfly-model={dfly}", argv)
                self.assertIn("--dfly-draft-tokens=4", argv)


if __name__ == "__main__":
    unittest.main()
