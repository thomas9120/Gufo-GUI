"""Local control routes enforce origin/token checks and validate launches."""

from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gui"))
from settings import DEFAULTS
from launcher_process import ProcessManager
from presets import load_document
from server import create_app


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "settings.json"
        self.manager = Mock(spec=ProcessManager)
        self.manager.snapshot.return_value = {"state": "stopped"}
        self.manager.start.return_value = {"state": "loading"}
        self.manager.stop.return_value = {"state": "stopped"}
        self.exiting = threading.Event()
        self.app = create_app(self.config, self.manager, self.exiting)
        self.client = self.app.test_client()
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        token = re.search(r'name="gufo-token" content="([^"]+)"', page.text)[1]
        self.headers = {"X-Gufo-Token": token}

    def save(self, settings):
        document = self.client.get("/api/settings", headers=self.headers).json["document"]
        return self.client.post("/api/presets", json={"action": "save", "id": "default",
                                "settings": settings, "revision": document["revision"]}, headers=self.headers)

    def start(self, settings):
        return self.client.post("/api/start", json={"settings": settings, "preset_id": "default"}, headers=self.headers)

    def test_control_and_file_routes_require_same_origin_and_runtime_token(self):
        for method, path in (("get", "/api/browse"), ("get", "/api/settings"), ("get", "/api/status"),
                             ("post", "/api/presets"), ("post", "/api/start"), ("post", "/api/stop"), ("post", "/api/exit")):
            for headers in ({}, self.headers | {"Origin": "https://example.com"},
                            {"X-Gufo-Token": "stale token"}):
                with self.subTest(path=path, headers=headers):
                    response = getattr(self.client, method)(path, headers=headers)
                    self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/", headers={"Host": "attacker.example"}).status_code, 400)
        self.assertIn("frame-ancestors 'none'", self.client.get("/").headers["Content-Security-Policy"])
        self.manager.start.assert_not_called()
        self.manager.stop.assert_not_called()

    def test_status_proxies_engine_identity_under_same_origin_policy(self):
        props = {"build_info": "actual-revision", "model_path": "C:/models/actual.gguf",
                 "default_generation_settings": {"n_ctx": 8192}, "modalities": {"vision": True}}
        self.manager.snapshot.return_value = {"state": "ready", "props": props}
        response = self.client.get("/api/status", headers=self.headers)
        self.assertEqual(response.json["props"], props)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("connect-src 'self'", response.headers["Content-Security-Policy"])

    def test_save_restore_preview_and_browse(self):
        settings = DEFAULTS | {"context": 8192, "models_dir": str(self.root)}
        saved = self.save(settings)
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(self.config.is_file())
        app = create_app(self.config, self.manager, self.exiting)
        client = app.test_client()
        token = re.search(r'name="gufo-token" content="([^"]+)"', client.get("/").text)[1]
        self.assertEqual(client.get("/api/settings", headers={"X-Gufo-Token": token}).json["settings"], settings)
        preview = self.client.post("/api/preview", json=settings, headers=self.headers)
        self.assertIn("--context 8192", preview.json["command"])
        (self.root / "model.gguf").touch()
        files = self.client.get("/api/browse", query_string={"path": str(self.root)}, headers=self.headers)
        self.assertEqual(files.json["entries"][0]["name"], "model.gguf")
        invalid = self.save(settings | {"temperature": None})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.post("/api/presets", data="x" * 40000,
                                         content_type="application/json", headers=self.headers).status_code, 413)

    def test_launch_uses_explicit_argv_and_does_not_overwrite_saved_settings(self):
        exe, model, mtp = [self.root / name for name in ("gufo.exe", "main & model.gguf", "mtp.gguf")]
        exe.touch()
        model.write_bytes(b"GGUF")
        mtp.write_bytes(b"GGUF")
        settings = DEFAULTS | {"executable": str(exe), "model": str(model),
                               "speculative": "mtp", "mtp_model": str(mtp),
                               "host": "192.168.1.10"}
        started = self.start(settings)
        self.assertEqual(started.status_code, 200)
        command, port, name = self.manager.start.call_args.args
        self.assertEqual(command[command.index("--model") + 1], str(model))
        self.assertEqual(command[command.index("--host") + 1], "192.168.1.10")
        self.assertEqual(self.manager.start.call_args.kwargs, {"host": "192.168.1.10"})
        self.assertNotIn("--prompt-lookup", command)
        self.assertEqual((port, name), (8080, "gufo"))
        self.assertFalse(self.config.exists())
        invalid = self.start(settings | {"port": 8090})
        self.assertEqual(invalid.status_code, 400)
        model.unlink()
        invalid = self.start(settings)
        self.assertEqual(invalid.status_code, 400)
        self.client.post("/api/stop", headers=self.headers)
        self.manager.stop.assert_called_once()

    def test_corrupt_settings_are_reported_and_preserved_until_explicit_save(self):
        self.config.write_text("broken")
        app = create_app(self.config, self.manager, self.exiting)
        client = app.test_client()
        token = re.search(r'name="gufo-token" content="([^"]+)"', client.get("/").text)[1]
        response = client.get("/api/settings", headers={"X-Gufo-Token": token})
        self.assertIn("Cannot read saved settings", response.json["warning"])
        self.assertEqual(self.config.read_text(), "broken")

    def test_dflash_launch_uses_draft_flag_and_leaves_saved_mtp_settings_alone(self):
        exe, model, draft = [self.root / name for name in ("gufo.exe", "main.gguf", "DFlash2.gguf")]
        exe.touch()
        model.write_bytes(b"GGUF")
        draft.write_bytes(b"GGUF")
        saved = DEFAULTS | {"speculative": "mtp", "context": 200000}
        self.save(saved)
        before = self.config.read_bytes()
        settings = saved | {"executable": str(exe), "model": str(model),
                            "speculative": "dflash2", "dflash_model": str(draft)}
        started = self.start(settings)
        self.assertEqual(started.status_code, 200)
        command = self.manager.start.call_args.args[0]
        self.assertEqual(command[command.index("--speculative") + 1], "dflash2")
        self.assertEqual(command[command.index("--dflash-model") + 1], str(draft))
        self.assertNotIn("--mtp-model", command)
        self.assertNotIn("--prompt-lookup", command)
        self.assertEqual(self.config.read_bytes(), before)

    def test_exit_stops_owned_process_and_rejects_a_racing_start(self):
        response = self.client.post("/api/exit", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.manager.stop.assert_called_once()
        self.assertEqual(self.client.post("/api/start", json=DEFAULTS, headers=self.headers).status_code, 503)
        self.assertTrue(self.exiting.wait(1))

    def test_exit_failure_leaves_launcher_available_for_retry(self):
        self.manager.stop.return_value = {"state": "failed", "pid": 123,
                                          "error": "Gufo could not be stopped; try Stop again."}
        response = self.client.post("/api/exit", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertIn("try Stop again", response.json["error"])
        self.assertFalse(self.exiting.is_set())
        self.assertEqual(self.client.get("/api/status", headers=self.headers).status_code, 200)
        self.manager.stop.return_value = {"state": "stopped"}
        self.assertEqual(self.client.post("/api/exit", headers=self.headers).status_code, 200)
        self.assertTrue(self.exiting.wait(1))

    def test_preset_edits_do_not_change_running_snapshot(self):
        exe, model = self.root / "gufo.exe", self.root / "main.gguf"
        exe.touch()
        model.write_bytes(b"GGUF")
        settings = DEFAULTS | {"executable": str(exe), "model": str(model)}
        self.save(settings)
        running = self.start(settings | {"context": 8192}).json["running"]
        self.assertTrue(running["modified"])
        self.assertEqual(running["preset_name"], "Default")
        self.save(settings | {"context": 65536})
        state = self.client.get("/api/status", headers=self.headers).json
        self.assertEqual(state["running"], running)
        self.manager.start.assert_called_once()
        self.manager.stop.assert_not_called()

    def test_failed_save_does_not_replace_memory_and_stale_tabs_cannot_save(self):
        self.save(DEFAULTS)
        before = self.client.get("/api/settings", headers=self.headers).json["document"]
        with patch("presets.os.replace", side_effect=OSError("disk full")):
            self.assertEqual(self.save(DEFAULTS | {"context": 8192}).status_code, 400)
        self.assertEqual(self.client.get("/api/settings", headers=self.headers).json["document"], before)
        stale = self.client.post("/api/presets", json={"action": "delete", "id": "default", "revision": 0},
                                 headers=self.headers)
        self.assertEqual(stale.status_code, 400)
        self.assertIn("another tab", stale.json["error"])

    def test_export_and_import_presets_over_http(self):
        self.save(DEFAULTS | {"context": 8192})
        backup = self.client.get("/api/presets/export", headers=self.headers)
        self.assertEqual(backup.status_code, 200)
        revision = self.client.get("/api/settings", headers=self.headers).json["document"]["revision"]
        imported = self.client.post("/api/presets/import", json={"revision": revision, "data": backup.json},
                                    headers=self.headers)
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.json["imported"], 1)
        self.assertEqual([p["name"] for p in imported.json["document"]["presets"]], ["Default", "Default (2)"])
        self.assertEqual(load_document(self.config), imported.json["document"])
        # Larger than the default 32 KiB request limit, so this proves the import route accepts big backups.
        padded = backup.json | {"padding": "x" * 40000}
        rejected = self.client.post("/api/presets/import", json={"revision": revision + 1, "data": padded},
                                    headers=self.headers)
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("not a Gufo preset backup", rejected.json["error"])
        for method, path in (("get", "/api/presets/export"), ("post", "/api/presets/import")):
            self.assertEqual(getattr(self.client, method)(path).status_code, 403)


if __name__ == "__main__":
    unittest.main()
