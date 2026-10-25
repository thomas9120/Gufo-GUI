"""Local browser launcher. Run with python tools/gui/server.py."""

import argparse
import hmac
import os
from pathlib import Path
import secrets
import shlex
import signal
import subprocess
import threading
import webbrowser

from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException

from command import build_command
from files import browse_directory
from launcher_process import ProcessManager
from models import MODEL_FAMILIES, SPECULATIVE_MODES
from presets import (change_preset, export_presets, find_preset, import_presets, load_document,
                     new_document, resolved_settings, save_document)
from settings import ROOT, settings_path, validate_settings


def create_app(config_path, manager, exit_event, ui_port=8090):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=32768, TRUSTED_HOSTS=["127.0.0.1", "localhost"])
    token = secrets.token_urlsafe(32)
    action_lock = threading.Lock()
    shutting_down = False
    running = None
    try:
        document = load_document(config_path)
        load_error = ""
    except (ValueError, OSError) as exc:
        document, load_error = new_document(), str(exc)

    @app.before_request
    def local_requests_only():
        origin = request.headers.get("Origin")
        if origin and origin != request.host_url.rstrip("/"):
            abort(403, "Open the launcher directly on localhost.")
        if request.path.startswith("/api/"):
            if not hmac.compare_digest(request.headers.get("X-Gufo-Token", ""), token):
                abort(403, "Reload the launcher page to reconnect.")
            if shutting_down or exit_event.is_set():
                abort(503, "The launcher is shutting down.")

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        return response

    @app.errorhandler(ValueError)
    @app.errorhandler(OSError)
    def invalid_input(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.get("/")
    def index():
        return render_template("index.html", token=token)

    @app.get("/logo.jpg")
    def logo():
        return send_file(ROOT / "assets/gufo-logo.jpg")

    @app.get("/api/settings")
    def settings():
        with action_lock:
            return jsonify(document=document, settings=resolved_settings(document),
                           families=MODEL_FAMILIES, modes=SPECULATIVE_MODES,
                           path=str(config_path), warning=load_error,
                           saved=config_path.exists() and not load_error, home=str(Path.home()))

    @app.post("/api/presets")
    def save():
        nonlocal document, load_error
        with action_lock:
            document = save_document(config_path, change_preset(document, request.get_json()))
            load_error = ""
            return jsonify(document=document)

    @app.get("/api/presets/export")
    def export():
        with action_lock:
            return jsonify(export_presets(document))

    @app.post("/api/presets/import")
    def import_backup():
        nonlocal document, load_error
        # A backup of 100 presets exceeds the small default request limit.
        request.max_content_length = 1024 * 1024
        with action_lock:
            added = import_presets(document, request.get_json())
            count = len(added["presets"]) - len(document["presets"])
            document = save_document(config_path, added)
            load_error = ""
            return jsonify(document=document, imported=count)

    @app.get("/api/browse")
    def browse():
        return jsonify(browse_directory(request.args.get("path", ""), request.args.get("kind", "gguf")))

    @app.post("/api/preview")
    def preview():
        command = build_command(request.get_json())
        display = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
        return jsonify(command=display)

    @app.get("/api/status")
    def status():
        with action_lock:
            return jsonify(manager.snapshot() | {"running": running})

    @app.post("/api/start")
    def start():
        nonlocal running
        with action_lock:
            if shutting_down or exit_event.is_set():
                abort(503, "The launcher is shutting down.")
            payload = request.get_json()
            if not isinstance(payload, dict) or set(payload) != {"settings", "preset_id"}:
                raise ValueError("Provide launch settings and the selected preset.")
            preset = find_preset(document, payload["preset_id"])
            values = validate_settings(payload["settings"])
            if values["port"] == ui_port:
                raise ValueError("The Gufo API and launcher need different ports (defaults: 8080 and 8090).")
            command = build_command(values, check_files=True)
            state = manager.start(command, values["port"], values["served_model_name"], host=values["host"])
            running = {"preset_id": preset["id"], "preset_name": preset["name"],
                       "modified": values != resolved_settings(document, preset["id"]),
                       "settings": values}
            return jsonify(state | {"running": running})

    @app.post("/api/stop")
    def stop():
        with action_lock:
            return jsonify(manager.stop() | {"running": running})

    @app.post("/api/exit")
    def exit_launcher():
        nonlocal shutting_down
        with action_lock:
            stopped = manager.stop()
            if stopped["state"] != "stopped":
                abort(503, stopped.get("error") or "Gufo is still running; try Stop again.")
            shutting_down = True
            # Allow the acknowledgement to reach the browser before closing HTTP.
            threading.Timer(0.3, exit_event.set).start()
            return jsonify(stopped=True)

    return app


def main():
    from waitress import create_server

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8090, help="Launcher port (Gufo defaults to 8080)")
    parser.add_argument("--config", type=Path, default=settings_path(), help="Saved launcher settings file")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be from 1 to 65535")
    manager, exiting = ProcessManager(), threading.Event()
    app = create_app(args.config, manager, exiting, args.port)
    try:
        server = create_server(app, host="127.0.0.1", port=args.port, threads=4,
                               max_request_body_size=32768, clear_untrusted_proxy_headers=True)
    except OSError as exc:
        parser.exit(1, f"Cannot open launcher port {args.port}: {exc}\n")
    signal.signal(signal.SIGINT, lambda *_: exiting.set())
    signal.signal(signal.SIGTERM, lambda *_: exiting.set())
    url = f"http://127.0.0.1:{args.port}"
    print(f"Gufo launcher: {url}\nSettings: {args.config}\nCtrl+C stops the launcher and its Gufo server.", flush=True)
    worker = threading.Thread(target=server.run, daemon=True)
    worker.start()
    try:
        if not args.no_browser:
            webbrowser.open(url)
        while worker.is_alive() and not exiting.wait(0.5):
            pass
    finally:
        exiting.set()
        manager.stop()
        server.task_dispatcher.shutdown()
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
