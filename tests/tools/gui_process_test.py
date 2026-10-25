"""Exercise real child processes without loading a model or requiring a GPU."""

from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/gui"))
from launcher_process import ProcessManager, add_live_rates, parse_metrics

# Windows venv python.exe is a redirector that spawns the real interpreter.
# Exercise the same single-process ownership as gufo.exe, without that wrapper.
PYTHON = getattr(sys, "_base_executable", sys.executable)


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


FAKE_SERVER = """
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
for i in range(500):
    print('log row', i, flush=True)
print('stderr is captured', file=sys.stderr, flush=True)
time.sleep(0.6)
class Handler(BaseHTTPRequestHandler):
    metrics_requests = 0
    props_requests = 0
    def do_GET(self):
        if self.path == '/metrics':
            Handler.metrics_requests += 1
            # Exercise an unavailable scrape and automatic recovery.
            if Handler.metrics_requests == 2:
                self.send_response(503)
                self.end_headers()
                return
            speed = 25 if Handler.metrics_requests == 1 else 30
            prompt, generated = {1: (100, 20), 3: (120, 30), 4: (140, 50)}.get(Handler.metrics_requests, (0, 0))
            if Handler.metrics_requests == 4:
                time.sleep(0.2)  # Rates must include scrape latency in the interval.
            body = ('# TYPE llamacpp:prompt_tokens_seconds gauge\\n'
                    'llamacpp:prompt_tokens_seconds 800\\n'
                    f'llamacpp:predicted_tokens_seconds {speed}\\n'
                    f'llamacpp:prompt_tokens_total {prompt}\\n'
                    f'llamacpp:tokens_predicted_total {generated}\\n'
                    f'llamacpp:requests_processing {int(prompt > 0)}\\n'
                    'llamacpp:requests_deferred 2\\n').encode()
        elif self.path == '/props':
            Handler.props_requests += 1
            if Handler.props_requests == 2:
                self.send_response(503)
                self.end_headers()
                return
            body = json.dumps({'model_path': '/models/loaded.gguf', 'build_info': 'fixture-revision',
                               'default_generation_settings': {'n_ctx': 8192},
                               'modalities': {'vision': True}}).encode()
        else:
            body = json.dumps({'status': 'ready', 'model': 'fixture'}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
"""


class ProcessTest(unittest.TestCase):
    def test_selected_bind_address_is_used_for_preflight_and_probes(self):
        for host in ("0.0.0.0", "127.0.0.2"):
            with self.subTest(host=host):
                port = unused_port()
                server = FAKE_SERVER.replace("HTTPServer(('127.0.0.1',", f"HTTPServer(('{host}',")
                self.manager.start([PYTHON, "-u", "-c", server, str(port)], port, "fixture", host=host)
                ready = self.wait_for("ready")
                connect_host = "127.0.0.1" if host == "0.0.0.0" else host
                self.assertEqual(ready["base_url"], f"http://{connect_host}:{port}/v1")
                deadline = time.monotonic() + 8
                while self.manager.snapshot()["metrics"] is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertIsNotNone(self.manager.snapshot()["metrics"])
                self.manager.stop()
                with socket.socket() as listener:
                    listener.bind((host, port))
                    listener.listen()
                    with self.assertRaisesRegex(ValueError, "already in use"):
                        self.manager.start([PYTHON], port, "fixture", host=host)

    def setUp(self):
        self.manager = ProcessManager()
        self.addCleanup(self.manager.stop)

    def wait_for(self, state):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            snapshot = self.manager.snapshot()
            if snapshot["state"] == state:
                return snapshot
            time.sleep(0.05)
        self.fail(f"Expected {state}, got {self.manager.snapshot()}")

    def test_loading_ready_logs_duplicate_start_stop_and_relaunch(self):
        port = unused_port()
        argv = [PYTHON, "-u", "-c", FAKE_SERVER, str(port)]
        self.assertEqual(self.manager.start(argv, port, "fixture")["state"], "loading")
        with self.assertRaisesRegex(ValueError, "Stop the running"):
            self.manager.start(argv, port, "fixture")
        ready = self.wait_for("ready")
        self.assertEqual(ready["model_name"], "fixture")
        self.assertEqual(len(ready["logs"]), 300)
        self.assertIn("stderr is captured", ready["logs"])
        child = self.manager.process
        self.assertEqual(self.manager.stop()["state"], "stopped")
        self.assertIsNotNone(child.poll())
        self.manager.start(argv, port, "fixture")
        self.wait_for("ready")

    def test_start_failure_and_early_exit_are_visible(self):
        with self.assertRaisesRegex(ValueError, "Could not launch"):
            self.manager.start([str(Path.cwd() / "missing-gufo-executable")], unused_port(), "fixture")
        self.assertEqual(self.manager.snapshot()["state"], "failed")
        self.manager.start([PYTHON, "-c", "import sys; print('bad model', flush=True); sys.exit(7)"],
                           unused_port(), "fixture")
        failed = self.wait_for("failed")
        self.assertEqual(failed["exit_code"], 7)
        self.assertIn("code 7", failed["error"])

    def test_metrics_poll_failure_recovery_and_restart(self):
        port = unused_port()
        argv = [PYTHON, "-u", "-c", FAKE_SERVER, str(port)]
        self.assertIsNone(self.manager.start(argv, port, "fixture")["metrics"])
        self.wait_for("ready")
        previous_seen_at = None
        for expected_speed, expected_prompt, expected_live in ((25, 100, None), (None, None, None),
                                                             (30, 120, None), (30, 140, True),
                                                             (30, 0, None), (30, 0, 0)):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                snapshot = self.manager.snapshot()
                metrics = snapshot["metrics"]
                if metrics is None and expected_speed is None:
                    break
                if metrics and metrics["generation_tps"] == expected_speed and metrics["prompt_tokens_total"] == expected_prompt:
                    rate = metrics["live_generation_tps"]
                    if (expected_live is True and rate is not None and rate > 0
                            or expected_live is None and rate is None
                            or expected_live == 0 and rate == 0):
                        break
                time.sleep(0.05)
            else:
                self.fail(f"Expected speed {expected_speed}, got {metrics}")
            seen_at = time.monotonic()
            self.assertEqual(snapshot["state"], "ready")
            if metrics:
                self.assertEqual(metrics["prefill_tps"], 800)
                self.assertEqual(metrics["prompt_tokens_total"], expected_prompt)
                self.assertEqual(metrics["requests_processing"], int(expected_prompt > 0))
                self.assertEqual(metrics["requests_deferred"], 2)
                if expected_live is True:
                    self.assertAlmostEqual(metrics["live_prefill_tps"], metrics["live_generation_tps"])
                    self.assertGreater(metrics["live_generation_tps"], 0)
                    self.assertLess(metrics["live_generation_tps"], 40)
                    self.assertAlmostEqual(metrics["live_generation_tps"],
                                           20 / (seen_at - previous_seen_at), delta=1)
                else:
                    self.assertEqual(metrics["live_prefill_tps"], expected_live)
            previous_seen_at = seen_at if metrics is not None else None
        self.assertIsNone(self.manager.stop()["metrics"])
        self.assertIsNone(self.manager.start(argv, port, "fixture")["metrics"])
        self.wait_for("ready")
        deadline = time.monotonic() + 8
        while self.manager.snapshot()["metrics"] is None and time.monotonic() < deadline:
            time.sleep(0.05)
        restarted = self.manager.snapshot()["metrics"]
        self.assertIsNotNone(restarted)
        self.assertIsNone(restarted["live_prefill_tps"])
        self.assertIsNone(restarted["live_generation_tps"])

    def test_props_poll_failure_recovery_stop_and_restart(self):
        port = unused_port()
        server = FAKE_SERVER.replace("if Handler.metrics_requests == 2:", "if Handler.metrics_requests == -1:")
        argv = [PYTHON, "-u", "-c", server, str(port)]
        self.assertIsNone(self.manager.start(argv, port, "fixture")["props"])
        self.wait_for("ready")
        for expected in (True, False, True):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                snapshot = self.manager.snapshot()
                props = snapshot["props"]
                if (props is not None) == expected:
                    break
                time.sleep(0.05)
            else:
                self.fail(f"Expected props available={expected}, got {props}")
            self.assertIsNotNone(snapshot["metrics"])
            if expected:
                self.assertEqual(props["build_info"], "fixture-revision")
                self.assertEqual(props["model_path"], "/models/loaded.gguf")
                self.assertEqual(props["default_generation_settings"]["n_ctx"], 8192)
                self.assertTrue(props["modalities"]["vision"])
        self.assertIsNone(self.manager.stop()["props"])
        argv[3] = FAKE_SERVER.replace("fixture-revision", "rebuilt-revision")
        self.assertIsNone(self.manager.start(argv, port, "fixture")["props"])
        self.wait_for("ready")
        deadline = time.monotonic() + 8
        while self.manager.snapshot()["props"] is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.manager.snapshot()["props"]["build_info"], "rebuilt-revision")

    def test_metrics_parser_rejects_missing_and_nonfinite_values(self):
        text = ("# HELP ignored comment\n"
                "llamacpp:prompt_tokens_seconds 8e2\n"
                "llamacpp:predicted_tokens_seconds 25.5\n"
                "llamacpp:prompt_tokens_total 100\n"
                "llamacpp:tokens_predicted_total 0\n"
                "llamacpp:kv_cache_usage_ratio 0.0\n")
        self.assertEqual(parse_metrics(text), {"prefill_tps": 800, "generation_tps": 25.5,
                                             "prompt_tokens_total": 100, "generated_tokens_total": 0})
        for invalid in ("", "{}", text.replace("25.5", ""),
                        *(text.replace("25.5", value) for value in ("NaN", "+Inf", "-1", "bad"))):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_metrics(invalid)

    def test_metrics_parser_accepts_optional_request_gauges(self):
        text = ("llamacpp:prompt_tokens_seconds 800\n"
                "llamacpp:predicted_tokens_seconds 25\n"
                "llamacpp:prompt_tokens_total 100\n"
                "llamacpp:tokens_predicted_total 20\n"
                "llamacpp:requests_processing 1\n"
                "llamacpp:requests_deferred 0\n")
        metrics = parse_metrics(text)
        self.assertEqual(metrics["requests_processing"], 1)
        self.assertEqual(metrics["requests_deferred"], 0)
        for value in ("NaN", "Inf", "-1", "0.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_metrics(text.replace("requests_processing 1", f"requests_processing {value}"))

    def test_prefill_rate_uses_processing_time_and_handles_counter_transitions(self):
        previous = {"prompt_tokens_total": 100, "prompt_seconds_total": 0.25,
                    "generated_tokens_total": 20, "requests_processing": 1, "requests_deferred": 0}
        for elapsed in (1, 10):
            current = {**previous, "prompt_tokens_total": 1100, "prompt_seconds_total": 0.5,
                       "generated_tokens_total": 40}
            self.assertIs(add_live_rates(current, previous, elapsed), current)
            self.assertEqual(current["live_prefill_tps"], 4000)
            self.assertEqual(current["live_generation_tps"], 20 / elapsed)
        idle = dict(previous)
        add_live_rates(idle, previous, 10)
        self.assertEqual(idle["live_prefill_tps"], 0)
        for changes, baseline, elapsed in (
                ({}, None, 1), ({}, previous, 0),
                ({"prompt_seconds_total": 0.1}, previous, 1),
                ({"prompt_tokens_total": 0}, previous, 1),
                ({"generated_tokens_total": 0}, previous, 1),
                ({"prompt_tokens_total": 200}, previous, 1),
                ({}, {key: value for key, value in previous.items() if key != "prompt_seconds_total"}, 1)):
            with self.subTest(changes=changes, baseline=baseline, elapsed=elapsed):
                current = {**previous, **changes}
                add_live_rates(current, baseline, elapsed)
                self.assertIsNone(current["live_prefill_tps"])

    def test_metrics_parser_accepts_and_validates_optional_prefill_time(self):
        text = ("llamacpp:prompt_tokens_seconds 800\n"
                "llamacpp:predicted_tokens_seconds 25\n"
                "llamacpp:prompt_tokens_total 100\n"
                "llamacpp:tokens_predicted_total 20\n"
                "llamacpp:prompt_seconds_total 1.25e-1\n")
        self.assertEqual(parse_metrics(text)["prompt_seconds_total"], 0.125)
        for value in ("NaN", "Inf", "-1", "bad", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_metrics(text.replace("1.25e-1", value))

    def test_occupied_port_is_not_mistaken_for_our_server(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with self.assertRaisesRegex(ValueError, "already in use"):
                self.manager.start([PYTHON], listener.getsockname()[1], "fixture")
            self.assertIsNone(self.manager.process)

    def test_stop_while_model_is_loading(self):
        self.manager.start([PYTHON, "-c", "import time; time.sleep(30)"], unused_port(), "fixture")
        self.assertEqual(self.manager.stop()["state"], "stopped")
        self.assertIsNotNone(self.manager.process.poll())

    def test_failed_stop_keeps_child_owned_and_can_be_retried(self):
        self.manager.start([PYTHON, "-c", "import time; time.sleep(30)"], unused_port(), "fixture")
        child = self.manager.process
        target = self.manager.job if os.name == "nt" else child
        with patch.object(target, "terminate", side_effect=OSError("fixture termination failure")):
            failed = self.manager.stop()
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["pid"], child.pid)
        self.assertIn("try Stop again", failed["error"])
        self.assertEqual(self.manager.stop()["state"], "stopped")
        self.assertIsNotNone(child.poll())

    @unittest.skipUnless(os.name == "nt", "Windows Job Object lifetime")
    def test_failed_job_assignment_does_not_leave_a_child_running(self):
        from windows_job import WindowsJob
        children = []

        def fail_assignment(job, child):
            children.append(child)
            raise OSError("fixture job assignment failure")

        with patch.object(WindowsJob, "assign", fail_assignment):
            with self.assertRaisesRegex(ValueError, "Could not launch"):
                self.manager.start([PYTHON, "-c", "import time; time.sleep(30)"], unused_port(), "fixture")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertIsNone(self.manager.job)
        self.assertEqual(self.manager.snapshot()["state"], "failed")

    @unittest.skipUnless(os.name == "nt", "Windows Job Object lifetime")
    def test_owned_tree_exits_on_stop_and_abrupt_launcher_exit(self):
        import ctypes
        from ctypes import wintypes
        from windows_job import kernel32

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL

        def close_process(handle):
            if kernel32.WaitForSingleObject(handle, 0) == 258:
                kernel32.TerminateProcess(handle, 1)
                kernel32.WaitForSingleObject(handle, 5000)
            kernel32.CloseHandle(handle)

        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "tree.json"
            # Wait for assignment before creating descendants: simulate Gufo
            # starting helper processes after its model has begun loading.
            gate = Path(directory) / "assigned"
            child_code = (
                "import json, os, pathlib, subprocess, sys, time\n"
                f"while not pathlib.Path({str(gate)!r}).exists(): time.sleep(0.02)\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                f"pathlib.Path({str(marker)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n"
                "time.sleep(60)\n"
            )
            for abrupt in (False, True):
                with self.subTest(abrupt=abrupt):
                    marker.unlink(missing_ok=True)
                    gate.unlink(missing_ok=True)
                    helper = None
                    try:
                        if abrupt:
                            helper_code = (
                                f"import pathlib, sys, time; sys.path.insert(0, {str(Path(__file__).resolve().parents[2] / 'tools/gui')!r})\n"
                                "from launcher_process import ProcessManager\n"
                                "manager = ProcessManager()\n"
                                f"manager.start({[PYTHON, '-c', child_code]!r}, {unused_port()}, 'fixture')\n"
                                f"pathlib.Path({str(gate)!r}).touch()\n"
                                "time.sleep(60)\n"
                            )
                            helper = subprocess.Popen([PYTHON, "-c", helper_code],
                                                      creationflags=subprocess.CREATE_NO_WINDOW)
                        else:
                            self.manager.start([PYTHON, "-c", child_code], unused_port(), "fixture")
                            gate.touch()
                        deadline = time.monotonic() + 8
                        while not marker.exists() and time.monotonic() < deadline:
                            time.sleep(0.05)
                        pids = json.loads(marker.read_text())
                        handles = []
                        for pid in pids:
                            handle = kernel32.OpenProcess(0x100001, False, pid)  # SYNCHRONIZE | TERMINATE
                            self.assertTrue(handle, str(ctypes.WinError()))
                            self.addCleanup(close_process, handle)
                            handles.append(handle)
                        if abrupt:
                            helper.kill()  # No finally, signal handler or manager.stop().
                            helper.wait(timeout=5)
                        else:
                            self.assertEqual(self.manager.stop()["state"], "stopped")
                        for handle in handles:
                            self.assertEqual(kernel32.WaitForSingleObject(handle, 5000), 0,
                                             "Owned child survived launcher shutdown")
                    finally:
                        if helper is not None and helper.poll() is None:
                            helper.kill()
                            helper.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
