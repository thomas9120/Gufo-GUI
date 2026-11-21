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
from extension_manager import ExtensionJobManager, list_catalog, parse_extension_source, validate_extension_name
from extensions import inspect_executable
from files import browse_directory
from launcher_process import ProcessManager
from models import MODEL_FAMILIES, SPECULATIVE_MODES
from presets import (change_preset, export_presets, find_preset, import_presets, load_document,
                     new_document, resolved_settings, save_document)
from settings import ROOT, settings_path, validate_settings


# A backup of 100 presets exceeds the small default request limit.
IMPORT_MAX_BYTES = 1024 * 1024


def create_app(config_path, manager, exit_event, ui_port=8090, extension_manager=None):
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=32768, TRUSTED_HOSTS=["127.0.0.1", "localhost"])
    token = secrets.token_urlsafe(32)
    action_lock = threading.Lock()
    # Pairs each snapshot with its launch record; Stop does not hold it, so
    # status keeps reporting "stopping" while the engine releases GPU memory.
    status_lock = threading.Lock()
    shutting_down = False
    running = None
    ext_manager = extension_manager if extension_manager is not None else ExtensionJobManager()
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
        # A small copy: the 2048px source is 2.4 MB, and responses are not cached.
        return send_file(ROOT / "assets/gufo-logo-192.jpg")

    @app.get("/api/settings")
    def settings():
        with action_lock:
            current = resolved_settings(document)
            return jsonify(document=document, settings=current,
                           families=MODEL_FAMILIES, modes=SPECULATIVE_MODES,
                           extensions=inspect_executable(current["executable"]),
                           path=str(config_path), warning=load_error,
                           saved=config_path.exists() and not load_error, home=str(Path.home()))

    def _resolve_extension_executable(payload, *, locked=False):
        if "executable" in payload:
            executable = payload["executable"]
            if not isinstance(executable, str) or any(ord(c) < 32 for c in executable):
                raise ValueError("executable: enter a single line of text.")
            executable = executable.strip()
            if executable and not Path(executable).expanduser().is_absolute():
                raise ValueError("executable: use a full filesystem path.")
            return executable
        if locked:
            return resolved_settings(document)["executable"]
        with action_lock:
            return resolved_settings(document)["executable"]

    def _assert_server_stopped_for_extensions():
        snap = manager.snapshot()
        if snap.get("pid") is not None or snap.get("state") in ("loading", "ready", "stopping"):
            raise ValueError("Stop the running Gufo server before managing extensions.")

    @app.post("/api/extensions")
    def extensions():
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict) or set(payload) - {"executable", "refresh"}:
            raise ValueError("Invalid extension inspection request.")
        refresh = payload.get("refresh", False)
        if type(refresh) is not bool:
            raise ValueError("refresh: expected a checkbox value.")
        executable = _resolve_extension_executable(payload)
        return jsonify(inspect_executable(executable, refresh=refresh))

    @app.post("/api/extensions/catalog")
    def extensions_catalog():
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {}
        if not isinstance(payload, dict) or set(payload) - {"executable"}:
            raise ValueError("Invalid extension catalog request.")
        executable = _resolve_extension_executable(payload)
        return jsonify(list_catalog(executable))

    @app.get("/api/extensions/job")
    def extensions_job():
        return jsonify(ext_manager.snapshot())

    @app.post("/api/extensions/install")
    def extensions_install():
        with action_lock:
            _assert_server_stopped_for_extensions()
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or set(payload) - {"executable", "source", "replace_builtin", "confirmed"}:
                raise ValueError("Invalid extension install request.")
            parsed = parse_extension_source(payload.get("source"))
            replace_builtin = payload.get("replace_builtin", False)
            confirmed = payload.get("confirmed", False)
            if type(replace_builtin) is not bool or type(confirmed) is not bool:
                raise ValueError("Expected a checkbox value.")
            if not parsed["trusted"] and not confirmed:
                raise ValueError("Confirm that you trust this unreviewed extension source before installing.")
            executable = _resolve_extension_executable(payload, locked=True)
            args = ["install", parsed["source"]]
            if replace_builtin:
                args.append("--replace-builtin")
            if not parsed["trusted"]:
                args.append("--yes")
            return jsonify(ext_manager.start(executable, "install", args, target=parsed["source"]))

    @app.post("/api/extensions/update")
    def extensions_update():
        with action_lock:
            _assert_server_stopped_for_extensions()
            payload = request.get_json(silent=True)
            if payload is None:
                payload = {}
            if not isinstance(payload, dict) or set(payload) - {"executable", "name"}:
                raise ValueError("Invalid extension update request.")
            executable = _resolve_extension_executable(payload, locked=True)
            name = payload.get("name")
            args = ["update"]
            target = "all"
            if name is not None and name != "":
                target = validate_extension_name(name)
                args.append(target)
            return jsonify(ext_manager.start(executable, "update", args, target=target))

    @app.post("/api/extensions/remove")
    def extensions_remove():
        with action_lock:
            _assert_server_stopped_for_extensions()
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict) or set(payload) - {"executable", "name"}:
                raise ValueError("Invalid extension remove request.")
            name = validate_extension_name(payload.get("name"))
            executable = _resolve_extension_executable(payload, locked=True)
            return jsonify(ext_manager.start(executable, "remove", ["remove", name], target=name))

    @app.post("/api/extensions/cancel")
    def extensions_cancel():
        return jsonify(ext_manager.cancel())

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
        request.max_content_length = IMPORT_MAX_BYTES
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
        payload = request.get_json()
        values = validate_settings(payload)
        command = build_command(values, extension_info=inspect_executable(values["executable"]))
        display = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
        return jsonify(command=display)

    @app.get("/api/status")
    def status():
        with status_lock:
            return jsonify(manager.snapshot() | {"running": running})

    @app.post("/api/start")
    def start():
        nonlocal running
        with action_lock:
            if shutting_down or exit_event.is_set():
                abort(503, "The launcher is shutting down.")
            if ext_manager.is_running():
                raise ValueError("Wait for the running extension task to finish or cancel it before starting Gufo.")
            payload = request.get_json()
            if not isinstance(payload, dict) or set(payload) != {"settings", "preset_id"}:
                raise ValueError("Provide launch settings and the selected preset.")
            preset = find_preset(document, payload["preset_id"])
            values = validate_settings(payload["settings"])
            if values["port"] == ui_port:
                raise ValueError("The Gufo API and launcher need different ports (defaults: 8080 and 8090).")
            command = build_command(values, check_files=True,
                                    extension_info=inspect_executable(values["executable"]))
            launch = {"preset_id": preset["id"], "preset_name": preset["name"],
                      "modified": values != resolved_settings(document, preset["id"]),
                      "settings": values}
            with status_lock:
                state = manager.start(command, values["port"], values["served_model_name"], host=values["host"])
                running = launch
            return jsonify(state | {"running": running})

    @app.post("/api/stop")
    def stop():
        with action_lock:
            return jsonify(manager.stop() | {"running": running})

    @app.post("/api/exit")
    def exit_launcher():
        nonlocal shutting_down
        with action_lock:
            ext_manager.cancel()
            stopped = manager.stop()
            if stopped["state"] != "stopped":
                abort(503, stopped.get("error") or "Gufo is still running; try Stop again.")
            shutting_down = True
            # Allow the acknowledgement to reach the browser before closing HTTP.
            threading.Timer(0.3, exit_event.set).start()
            return jsonify(stopped=True)

    return app


def create_http_server(app, port):
    from waitress import create_server

    return create_server(app, host="127.0.0.1", port=port, threads=4,
                         max_request_body_size=IMPORT_MAX_BYTES, clear_untrusted_proxy_headers=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8090, help="Launcher port (Gufo defaults to 8080)")
    parser.add_argument("--config", type=Path, default=settings_path(), help="Saved launcher settings file")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be from 1 to 65535")
    manager, ext_manager, exiting = ProcessManager(), ExtensionJobManager(), threading.Event()
    app = create_app(args.config, manager, exiting, args.port, extension_manager=ext_manager)
    try:
        server = create_http_server(app, args.port)
    except OSError as exc:
        parser.exit(1, f"Cannot open launcher port {args.port}: {exc}\n")
    signal.signal(signal.SIGINT, lambda *_: exiting.set())
    signal.signal(signal.SIGTERM, lambda *_: exiting.set())
    if hasattr(signal, "SIGHUP"):
        # Closing the terminal must still stop the owned engine on POSIX.
        signal.signal(signal.SIGHUP, lambda *_: exiting.set())
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
        ext_manager.cancel()
        manager.stop()
        server.task_dispatcher.shutdown()
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
