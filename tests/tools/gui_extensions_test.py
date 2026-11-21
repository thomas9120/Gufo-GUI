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
import extension_manager
import extensions
from files import browse_directory
from launcher_process import ProcessManager
from presets import export_presets, import_presets, load_document, new_document, resolved_settings, save_document
from server import create_app
from settings import DEFAULTS, validate_settings


HY4_HELP = """Usage: gufo serve llm [OPTIONS]

Speculative:
      --speculative <MODE>     HTTP draft backend: dspark, dflash2, mtp, or off

Provider options:
      --dfly-draft-tokens <N>  Most tokens DFly2 drafts per step, 1 to 7 (default 7) (hy4flash)
      --dfly-model <PATH>      DFly2 drafter: its safetensors file or checkpoint directory (hy4flash)
      --custom-scale <X>       Scale factor
                               for testing wrapped lines (hy4flash)
      --custom-tag <VALUE>     Tag text (hy4flash, other)
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

            # Explicit numeric zero (int 0 and float 0.0) must not be dropped as False.
            zero_cmd = build_command(
                DEFAULTS | {
                    "provider_options": {
                        "--dfly-draft-tokens": 0,
                        "--custom-scale": 0.0,
                        "--enable-fast": False,
                    }
                },
                extension_info={
                    "available": True,
                    "options": [
                        {"name": "--dfly-draft-tokens", "type": "integer"},
                        {"name": "--custom-scale", "type": "number"},
                        {"name": "--enable-fast", "type": "boolean"},
                    ],
                    "draft_options": {},
                },
            )
            self.assertIn("--dfly-draft-tokens=0", zero_cmd)
            self.assertIn("--custom-scale=0.0", zero_cmd)
            self.assertNotIn("--enable-fast", zero_cmd)

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

    def test_parse_extension_source_enforces_pinning_and_trust(self):
        self.assertEqual(
            extension_manager.parse_extension_source("lfm3"),
            {"kind": "registry", "source": "lfm3", "trusted": True},
        )
        self.assertEqual(
            extension_manager.parse_extension_source("lfm3@0.4.0"),
            {"kind": "registry", "source": "lfm3@0.4.0", "trusted": True},
        )
        git_url = "https://github.com/franzmoca/hy4-gufo-extension@967f5e13ad501e4a505988f20694fed1e442ead1"
        self.assertEqual(
            extension_manager.parse_extension_source(git_url),
            {"kind": "git", "source": git_url, "trusted": False},
        )
        with tempfile.TemporaryDirectory() as directory:
            local = extension_manager.parse_extension_source(directory)
            self.assertEqual(local["kind"], "path")
            self.assertFalse(local["trusted"])
            self.assertEqual(local["source"], str(Path(directory).resolve()))
        for invalid in (
            "",
            "   ",
            "--yes",
            "install",
            "https://github.com/franzmoca/hy4-gufo-extension",
            "https://github.com/franzmoca/hy4-gufo-extension@",
            "git@github.com:franzmoca/hy4-gufo-extension.git",
            "relative/dir",
            "bad\nline",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                extension_manager.parse_extension_source(invalid)
        # A browser page URL is rejected with the pinned form to paste instead.
        with self.assertRaises(ValueError) as caught:
            extension_manager.parse_extension_source(
                "https://github.com/franzmoca/hy4-gufo-extension/commit/d229a727eb26e9868e0daa08860c83591239d30f"
            )
        self.assertEqual(
            str(caught.exception),
            "Pin a commit or tag: use https://github.com/franzmoca/hy4-gufo-extension@d229a727eb26e9868e0daa08860c83591239d30f.",
        )

    def test_windows_toolchain_wrapper_is_used_for_builds_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "gufo.exe"
            exe.touch()
            vs = root / "vs"
            vcvars = vs / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
            vcvars.parent.mkdir(parents=True)
            vcvars.touch()
            wrapper = root / "tools" / "windows" / "run-extension.cmd"
            wrapper.parent.mkdir(parents=True)
            wrapper.touch()
            (root / "build").mkdir()
            (root / "build" / "windows-setup.json").write_text(
                json.dumps({
                    "VS": str(vs),
                    "Rocm": str(root / "rocm"),
                    "Vcpkg": str(root / "vcpkg"),
                    "Xrt": str(root / "xrt"),
                    "Git": str(root / "git" / "git.exe"),
                    "CMake": str(root / "cmake" / "cmake.exe"),
                    "Ninja": str(root / "ninja" / "ninja.exe"),
                }),
                encoding="utf-8",
            )
            argv, env, cwd = extension_manager.build_extension_invocation(
                str(exe), ["install", "lfm3"], root=root, windows=True
            )
            self.assertEqual(argv, ["cmd.exe", "/d", "/c", "call", str(wrapper)])
            self.assertEqual(json.loads(env["GUFO_EXTENSION_ARGV_JSON"]), [str(exe), "extension", "install", "lfm3"])
            self.assertEqual(env["GUFO_VCVARS"], str(vcvars))
            self.assertEqual(env["GUFO_EXE"], str(exe))
            self.assertEqual(env["GUFO_PYTHON"], sys.executable)
            self.assertEqual(env["HIP_PATH"], str(root / "rocm").replace("\\", "/"))
            self.assertEqual(env["VCPKG_ROOT"], str(root / "vcpkg").replace("\\", "/"))
            self.assertEqual(cwd, root)

            # Remove does not require MSVC wrapper.
            rm_argv, _, _ = extension_manager.build_extension_invocation(
                str(exe), ["remove", "lfm3"], root=root, windows=True
            )
            self.assertEqual(rm_argv, [str(exe), "extension", "remove", "lfm3"])

            # Linux invocation runs gufo directly.
            linux_argv, _, _ = extension_manager.build_extension_invocation(
                str(exe), ["install", "lfm3"], root=root, windows=False
            )
            self.assertEqual(linux_argv, [str(exe), "extension", "install", "lfm3"])

    @unittest.skipUnless(os.name == "nt", "Windows cmd.exe wrapper test")
    def test_windows_wrapper_executes_when_both_wrapper_and_extension_paths_have_spaces(self):
        repo_wrapper = Path(__file__).resolve().parents[2] / "tools/windows/run-extension.cmd"
        with tempfile.TemporaryDirectory(prefix="gufo launcher & space ") as directory:
            root = Path(directory)
            wrapper = root / "tools" / "windows" / "run-extension.cmd"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text(repo_wrapper.read_text(encoding="utf-8"), encoding="utf-8")
            vs = root / "vs & dir"
            vcvars = vs / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
            vcvars.parent.mkdir(parents=True)
            vcvars.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
            ext_dir = root / "my extension & folder"
            ext_dir.mkdir()
            recorded = root / "argv.json"
            fake_gufo = root / "fake gufo.cmd"
            fake_gufo.write_text(
                f'@echo off\r\n"{sys.executable}" -c "import json, sys; open(r\'{recorded}\', \'w\').write(json.dumps(sys.argv[1:]))" %*\r\n',
                encoding="utf-8",
            )
            (root / "build").mkdir()
            (root / "build" / "windows-setup.json").write_text(json.dumps({"VS": str(vs)}), encoding="utf-8")
            argv, env, cwd = extension_manager.build_extension_invocation(
                str(fake_gufo), ["install", str(ext_dir), "--yes"], root=root, windows=True
            )
            proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(recorded.read_text(encoding="utf-8")), ["extension", "install", str(ext_dir), "--yes"])

    def test_extension_job_manager_streams_logs_and_cancels(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / "gufo.exe"
            exe.touch()
            mgr = extension_manager.ExtensionJobManager()
            with patch("extension_manager.build_extension_invocation") as build_inv, \
                 patch("extension_manager.inspect_executable", return_value={"available": True, "options": []}):
                build_inv.return_value = ([sys.executable, "-u", "-c", "print('building...'); print('done')"], dict(os.environ), Path(directory))
                mgr.start(str(exe), "install", ["install", "lfm3"], target="lfm3")
                for _ in range(100):
                    snap = mgr.snapshot()
                    if snap["state"] != "running":
                        break
                    threading.Event().wait(0.05)
                self.assertEqual(snap["state"], "succeeded")
                self.assertEqual(snap["logs"], ["building...", "done"])
                self.assertEqual(snap["extensions"], {"available": True, "options": []})

                # Cancellation stops a long-running build cleanly.
                build_inv.return_value = ([sys.executable, "-u", "-c", "import time; print('working', flush=True); time.sleep(30)"], dict(os.environ), Path(directory))
                mgr.start(str(exe), "update", ["update"], target="all")
                for _ in range(50):
                    if mgr.snapshot()["logs"]:
                        break
                    threading.Event().wait(0.05)
                mgr.cancel()
                for _ in range(100):
                    snap = mgr.snapshot()
                    if snap["state"] != "running":
                        break
                    threading.Event().wait(0.05)
                self.assertEqual(snap["state"], "cancelled")

    def test_extension_management_routes_enforce_auth_trust_and_stopped_server(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "gufo.exe"
            exe.touch()
            manager = Mock(spec=ProcessManager)
            manager.snapshot.return_value = {"state": "stopped", "pid": None}
            manager.stop.return_value = {"state": "stopped"}
            ext_mgr = Mock(spec=extension_manager.ExtensionJobManager)
            ext_mgr.is_running.return_value = False
            ext_mgr.snapshot.return_value = {"state": "idle", "logs": []}
            ext_mgr.start.return_value = {"state": "running", "logs": []}
            ext_mgr.cancel.return_value = {"state": "cancelled", "logs": []}

            with patch("server.inspect_executable", return_value={"available": True, "options": [], "extensions": [], "draft_options": {}}), \
                 patch("server.list_catalog", return_value={"available": True, "extensions": [{"name": "lfm3", "newest": "0.4.0"}], "registry_error": ""}):
                app = create_app(root / "settings.json", manager, threading.Event(), extension_manager=ext_mgr)
                client = app.test_client()
                token = re.search(r'name="gufo-token" content="([^"]+)"', client.get("/").text)[1]
                headers = {"X-Gufo-Token": token}

                for method, path in (
                    ("post", "/api/extensions/catalog"),
                    ("get", "/api/extensions/job"),
                    ("post", "/api/extensions/install"),
                    ("post", "/api/extensions/update"),
                    ("post", "/api/extensions/remove"),
                    ("post", "/api/extensions/cancel"),
                ):
                    self.assertEqual(getattr(client, method)(path).status_code, 403)

                cat = client.post("/api/extensions/catalog", json={"executable": str(exe)}, headers=headers)
                self.assertEqual(cat.status_code, 200)
                self.assertEqual(cat.json["extensions"][0]["name"], "lfm3")

                # Unreviewed Git URL requires confirmed=True.
                git_src = "https://github.com/franzmoca/hy4-gufo-extension@abc1234"
                unconfirmed = client.post(
                    "/api/extensions/install",
                    json={"executable": str(exe), "source": git_src, "confirmed": False},
                    headers=headers,
                )
                self.assertEqual(unconfirmed.status_code, 400)
                self.assertIn("Confirm", unconfirmed.json["error"])

                confirmed = client.post(
                    "/api/extensions/install",
                    json={"executable": str(exe), "source": git_src, "replace_builtin": True, "confirmed": True},
                    headers=headers,
                )
                self.assertEqual(confirmed.status_code, 200)
                ext_mgr.start.assert_called_with(
                    str(exe), "install", ["install", git_src, "--replace-builtin", "--yes"], target=git_src
                )

                # Registry install does not pass --yes.
                reg = client.post(
                    "/api/extensions/install",
                    json={"executable": str(exe), "source": "lfm3"},
                    headers=headers,
                )
                self.assertEqual(reg.status_code, 200)
                ext_mgr.start.assert_called_with(str(exe), "install", ["install", "lfm3"], target="lfm3")

                # Update all (with empty body using document executable) must not deadlock.
                upd = client.post("/api/extensions/update", json={}, headers=headers)
                self.assertEqual(upd.status_code, 200)

                # Remove validates name and starts remove.
                self.assertEqual(
                    client.post("/api/extensions/remove", json={"name": "../bad"}, headers=headers).status_code, 400
                )
                rem = client.post(
                    "/api/extensions/remove", json={"executable": str(exe), "name": "hy4flash"}, headers=headers
                )
                self.assertEqual(rem.status_code, 200)
                ext_mgr.start.assert_called_with(str(exe), "remove", ["remove", "hy4flash"], target="hy4flash")

                # Active server blocks management actions.
                manager.snapshot.return_value = {"state": "ready", "pid": 42}
                blocked = client.post("/api/extensions/update", json={"executable": str(exe)}, headers=headers)
                self.assertEqual(blocked.status_code, 400)
                self.assertIn("Stop the running Gufo server", blocked.json["error"])

                # Active extension job blocks starting the Gufo server.
                manager.snapshot.return_value = {"state": "stopped", "pid": None}
                ext_mgr.is_running.return_value = True
                model = root / "model.gguf"
                model.write_bytes(b"GGUF")
                blocked_start = client.post(
                    "/api/start",
                    json={"settings": DEFAULTS | {"executable": str(exe), "model": str(model)}, "preset_id": "default"},
                    headers=headers,
                )
                self.assertEqual(blocked_start.status_code, 400)
                self.assertIn("running extension task", blocked_start.json["error"])
                manager.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
