"""Gufo Setup entry point. --plain never imports Textual."""

import argparse
import json
import os
import subprocess
import sys

from core import Installer, Options, Runner, describe_plan, load_options, parse_event


def parser():
    result = argparse.ArgumentParser(description="Gufo-GUI setup and official Gufo engine manager")
    result.add_argument("--plain", action="store_true", help="Use a plain terminal, without TUI dependencies")
    result.add_argument("--action", choices=("install", "update", "repair", "launch", "update-gui"))
    result.add_argument("--gufo-path", help="Separate official engine checkout")
    result.add_argument("--rocm", help="ROCm/TheRock installation prefix")
    result.add_argument("--vcpkg", help="Windows vcpkg checkout")
    result.add_argument("--jobs", type=int, help="Parallel build jobs, 1-64")
    result.add_argument("--check-only", action="store_true", help="Inspect the selected action without installing")
    result.add_argument("--yes", action="store_true", help="Accept the plain-mode plan")
    return result


def authenticate(plan):
    if plan.get("requiresSudo") and os.name != "nt" and os.geteuid() != 0:
        print("Gufo Setup needs permission to install the system packages in your plan.", flush=True)
        subprocess.run(["sudo", "-v"], check=True)


def plain(installer, options, args):
    action = args.action
    if not action:
        if not sys.stdin.isatty():
            raise ValueError("Use --action with --plain when input is redirected.")
        print("Gufo Setup\n  1 Install\n  2 Update engine\n  3 Repair\n  4 Launch GUI\n  5 Update GUI")
        action = {"1": "install", "2": "update", "3": "repair", "4": "launch", "5": "update-gui"}.get(input("> ").strip())
        if not action:
            return 2
    if action == "launch":
        if args.check_only:
            print("Launch command: " + json.dumps(installer.command("launch", options)))
            return 0
        return subprocess.call(installer.command("launch", options), cwd=installer.root)
    if action == "update-gui":
        revision = installer.gui_update_plan()
        print(f"Fast-forward Gufo-GUI main from {revision}. Stop the GUI first. Engine and presets are preserved.")
        if args.check_only:
            return 0
        if not args.yes and (not sys.stdin.isatty() or input("Continue? [y/N] ").lower() not in ("y", "yes")):
            return 2
        installer.update_gui()
        return 0

    def output(line):
        event = parse_event(line)
        print(f"-- {event['phase']} --" if event else line, flush=True)

    runner = Runner()
    try:
        plan = installer.plan(action, options, runner, output)
        print(describe_plan(plan, action))
        if args.check_only:
            return 0
        if not args.yes and (not sys.stdin.isatty() or input("Continue? [y/N] ").lower() not in ("y", "yes")):
            return 2
        authenticate(plan)
        runner = Runner()
        code = installer.execute(action, options, runner, output)
        print(f"{'Complete' if code == 0 else 'Stopped'}. Log: {installer.last_log}")
        return code
    finally:
        runner.cancel()


def main():
    args = parser().parse_args()
    installer = Installer()
    options = load_options()
    for key in ("gufo_path", "rocm", "vcpkg", "jobs"):
        if getattr(args, key) is not None:
            setattr(options, key, getattr(args, key))
    options.validate()
    if args.plain or args.check_only or not (sys.stdin.isatty() and sys.stdout.isatty()):
        return plain(installer, options, args)
    from tui import SetupApp
    result = SetupApp(installer, options, initial_action=args.action).run()
    if result == "launch":
        return subprocess.call(installer.command("launch", options), cwd=installer.root)
    if result == "update-gui":
        installer.update_gui()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled. Completed downloads/build steps can be reused.")
        sys.exit(2)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Gufo Setup: {error}", file=sys.stderr)
        sys.exit(1)
