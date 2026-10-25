"""Own one Gufo child, drain its output, and report model readiness."""

from collections import deque
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request

from engine_props import fetch_props

if os.name == "nt":
    from windows_job import WindowsJob


def parse_metrics(text):
    fields = {
        "llamacpp:prompt_tokens_seconds": "prefill_tps",
        "llamacpp:predicted_tokens_seconds": "generation_tps",
        "llamacpp:prompt_tokens_total": "prompt_tokens_total",
        "llamacpp:tokens_predicted_total": "generated_tokens_total",
    }
    required = set(fields.values())
    fields.update({
        "llamacpp:prompt_seconds_total": "prompt_seconds_total",
        "llamacpp:requests_processing": "requests_processing",
        "llamacpp:requests_deferred": "requests_deferred",
    })
    metrics = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0] not in fields:
            continue
        if len(parts) < 2:
            raise ValueError("Missing metric value")
        value = float(parts[1])
        if not math.isfinite(value) or value < 0:
            raise ValueError("Invalid metric value")
        if fields[parts[0]].startswith("requests_") and not value.is_integer():
            raise ValueError("Invalid request count")
        metrics[fields[parts[0]]] = value
    if not required.issubset(metrics):
        raise ValueError("Incomplete Gufo metrics")
    return metrics


def add_live_rates(metrics, previous, elapsed):
    """Use paired engine time for prefill, retaining wall-time rates on older engines."""
    live = "requests_processing" in metrics and "requests_deferred" in metrics
    continuous = (live and previous is not None and elapsed > 0
                  and all(metrics[key] >= previous[key]
                          for key in ("prompt_tokens_total", "generated_tokens_total")))
    for total, rate in (("prompt_tokens_total", "live_prefill_tps"),
                        ("generated_tokens_total", "live_generation_tps")):
        metrics[rate] = (metrics[total] - previous[total]) / elapsed if continuous else None
    if "prompt_seconds_total" in metrics:
        metrics["live_prefill_tps"] = None
        if continuous and "prompt_seconds_total" in previous:
            prompt_seconds = metrics["prompt_seconds_total"] - previous["prompt_seconds_total"]
            prompt_tokens = metrics["prompt_tokens_total"] - previous["prompt_tokens_total"]
            if prompt_seconds > 0:
                metrics["live_prefill_tps"] = prompt_tokens / prompt_seconds
            elif prompt_seconds == 0 and prompt_tokens == 0:
                metrics["live_prefill_tps"] = 0.0
    return metrics if live else None


class ProcessManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.lifecycle_lock = threading.Lock()
        self.process = None
        self.job = None
        self.state = "stopped"
        self.error = ""
        self.exit_code = None
        self.logs = deque(maxlen=300)
        self.command = []
        self.base_url = ""
        self.model_name = ""
        self.started_at = None
        self.metrics = None
        self.props = None

    def snapshot(self):
        with self.lock:
            return {"state": self.state, "error": self.error, "exit_code": self.exit_code,
                    "metrics": self.metrics if self.state == "ready" else None,
                    "props": self.props if self.state == "ready" else None,
                    "logs": list(self.logs), "command": list(self.command),
                    "base_url": self.base_url, "model_name": self.model_name,
                    "pid": self.process.pid if self.process and self.process.poll() is None else None,
                    "elapsed_seconds": int(time.monotonic() - self.started_at) if self.started_at else 0}

    def start(self, command, port, model_name, host="127.0.0.1"):
        with self.lifecycle_lock, self.lock:
            if self.state == "stopping" or (self.process and self.process.poll() is None):
                raise ValueError("Stop the running Gufo server before starting another.")
            # Match Gufo's address reuse so TIME_WAIT does not block a restart.
            # Windows can also allow this bind beside a reusable listener, so
            # check for an accepting server before launching our child.
            connect_host = "127.0.0.1" if host == "0.0.0.0" else host
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind((host, port))
                except OSError as exc:
                    raise ValueError(f"Port {port} is unavailable or already in use.") from exc
            try:
                connection = socket.create_connection((connect_host, port), timeout=0.25)
            except OSError:
                pass
            else:
                connection.close()
                raise ValueError(f"Port {port} is already in use. Choose another port.")
            self.logs.clear()
            self.metrics = None
            self.props = None
            self.command = list(command)
            self.base_url = f"http://{connect_host}:{port}/v1"
            self.model_name = model_name
            self.error = ""
            self.exit_code = None
            self.started_at = time.monotonic()
            self.process = None  # Retire any observer from an earlier exited child.
            if self.job is not None:
                self.job.close()
                self.job = None
            child = None
            try:
                if os.name == "nt":
                    self.job = WindowsJob()
                child = subprocess.Popen(
                    command, cwd=Path(command[0]).parent, shell=False,
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if self.job is not None:
                    try:
                        self.job.assign(child)
                    except OSError:
                        # An already-exited child needs no lifetime protection.
                        if child.poll() is None:
                            raise
            except OSError as exc:
                if child is not None:
                    child.kill()
                    child.wait()
                    child.stdout.close()
                if self.job is not None:
                    self.job.close()
                    self.job = None
                self.state = "failed"
                self.error = f"Could not launch Gufo: {exc}"
                raise ValueError(self.error) from exc
            self.process = child
            self.state = "loading"
            threading.Thread(target=self._read_output, args=(child,), daemon=True).start()
            threading.Thread(target=self._watch, args=(child, connect_host, port, model_name), daemon=True).start()
        return self.snapshot()

    def _read_output(self, child):
        with child.stdout:
            while line := child.stdout.readline(4096):
                with self.lock:
                    if self.process is child:
                        self.logs.append(line.rstrip("\r\n"))

    def _watch(self, child, host, port, model_name):
        # Local probes must not inherit HTTP proxy settings from the user's shell.
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        next_metrics_poll = 0.0
        previous_metrics = None
        previous_metrics_at = 0.0
        while child.poll() is None:
            with self.lock:
                if self.process is not child:
                    return
                loading = self.state == "loading"
                ready = self.state == "ready"
            if loading:
                try:
                    with client.open(f"http://{host}:{port}/ready", timeout=0.5) as response:
                        body = json.loads(response.read(16384))
                    ready = isinstance(body, dict) and body.get("status") == "ready" and body.get("model") == model_name
                    with self.lock:
                        if ready and self.process is child and self.state == "loading" and child.poll() is None:
                            self.state = "ready"
                except (OSError, ValueError, urllib.error.URLError):
                    pass  # The model loads before Gufo starts listening.
            elif ready and time.monotonic() >= next_metrics_poll:
                try:
                    with client.open(f"http://{host}:{port}/metrics", timeout=0.5) as response:
                        metrics = parse_metrics(response.read(16384).decode("utf-8"))
                except urllib.error.HTTPError as error:
                    error.close()
                    metrics = None
                except (OSError, ValueError, urllib.error.URLError):
                    metrics = None
                sampled_at = time.monotonic()
                if metrics is not None:
                    elapsed = sampled_at - previous_metrics_at
                    previous_metrics = add_live_rates(metrics, previous_metrics, elapsed)
                    previous_metrics_at = sampled_at
                else:
                    previous_metrics = None
                props = fetch_props(client, f"http://{host}:{port}/props")
                with self.lock:
                    if self.process is child and self.state == "ready":
                        self.metrics = metrics
                        self.props = props
                next_metrics_poll = time.monotonic() + 1.0
            time.sleep(0.25)
        with self.lifecycle_lock, self.lock:
            if self.process is child:
                if self.job is not None:
                    self.job.close()
                    self.job = None
                self.exit_code = child.returncode
                if self.state == "stopping":
                    self.state = "stopped"
                elif self.state != "stopped":
                    self.state = "failed"
                    self.error = f"Gufo exited with code {child.returncode}. Check the process log below."

    def stop(self):
        # Serialize ownership changes without blocking output draining/status
        # while waiting for a child to exit.
        with self.lifecycle_lock:
            with self.lock:
                child = self.process
                self.state = "stopping"
            error = ""
            try:
                if self.job is not None:
                    self.job.terminate()
                elif child is not None and child.poll() is None:
                    child.terminate()
                if child is not None:
                    try:
                        child.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                if self.job is not None:
                    self.job.close()
                    self.job = None
            except (OSError, subprocess.TimeoutExpired) as exc:
                error = f"Gufo could not be stopped; try Stop again. {exc}"
            with self.lock:
                self.state = "failed" if error else "stopped"
                self.error = error
                self.exit_code = child.poll() if child is not None else None
            return self.snapshot()
