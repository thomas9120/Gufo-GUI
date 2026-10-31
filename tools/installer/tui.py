"""Shared terminal interface inspired by the original Gufo-Setup.cmd installer."""

from pathlib import Path
import platform
import subprocess

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, OptionList, ProgressBar, RichLog, Static
from textual.widgets.option_list import Option

from core import PHASES, REPOSITORY, Installer, Options, Runner, describe_plan, parse_event, save_options
from main import authenticate


class Confirm(ModalScreen[bool]):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def compose(self):
        with Container(id="confirm"):
            yield Static(self.message, markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Go back", id="no")
                yield Button("Continue", id="yes", variant="warning")

    @on(Button.Pressed)
    def choose(self, event):
        self.dismiss(event.button.id == "yes")

    def key_escape(self):
        self.dismiss(False)


class SetupApp(App):
    TITLE = "Gufo Setup"
    CSS_PATH = "theme.tcss"
    BINDINGS = [Binding("q", "quit", "Quit"), Binding("escape", "back", "Back"),
                Binding("ctrl+c", "quit", "Quit", priority=True), Binding("f2", "settings", "Settings")]

    def __init__(self, installer=None, options=None, initial_action=None):
        super().__init__()
        self.installer = installer or Installer()
        self.options = options or Options()
        self.initial_action = initial_action
        self.busy = False
        self.runner = None
        self.plan = None
        self.selected_action = None
        self.view = "home"
        self.quit_pending = False
        self.cancel_prompt = False
        self.lines = []
        self.completed_phases = []

    def compose(self) -> ComposeResult:
        with Container(id="frame"):
            yield Static("  .######.     G U F O  /  S E T U P\n"
                         " ###'  '''     local inference for AMD Strix Halo\n"
                         " ###  #####\n"
                         " ###.  ####    Windows / Linux\n"
                         "  '######'", id="banner", markup=False)
            yield Static("Gufo-GUI + official Gufo engine   ·   Windows / Linux", id="subtitle")
            with VerticalScroll(id="home", classes="panel"):
                yield Static("", id="facts", markup=False)
                yield OptionList(Option("Install Gufo and prepare GUI", id="install"),
                                 Option("Update official Gufo engine", id="update"),
                                 Option("Repair tools / rebuild current source", id="repair"),
                                 Option("Launch Gufo-GUI", id="launch"),
                                 Option("Update Gufo-GUI", id="update-gui"),
                                 Option("Settings / paths", id="settings"),
                                 Option("View latest installer log", id="logs"), id="menu")
            with Container(id="settings", classes="panel hidden"):
                with VerticalScroll():
                    yield Label("Engine source folder (blank uses saved location or ./gufo)")
                    yield Input(id="gufo_path")
                    yield Label("ROCm / TheRock prefix (blank detects automatically)")
                    yield Input(id="rocm")
                    yield Label("vcpkg folder (Windows only; blank uses managed dependencies)")
                    yield Input(id="vcpkg", disabled=not self.installer.windows)
                    yield Label("Parallel build jobs (1–64)")
                    yield Input(id="jobs", type="integer")
                with Horizontal(classes="buttons"):
                    yield Button("Save settings", id="save", variant="primary")
                    yield Button("Back", id="settings-back")
            with Container(id="review", classes="panel hidden"):
                with VerticalScroll():
                    yield Static("", id="plan", markup=False)
                with Horizontal(classes="buttons"):
                    yield Button("Continue", id="execute", variant="primary")
                    yield Button("Back", id="review-back")
            with Container(id="activity", classes="panel hidden"):
                yield Static("", id="phases", markup=False)
                yield ProgressBar(total=None, show_eta=False, id="progress")
                yield RichLog(id="output", markup=False, highlight=False, max_lines=1000, wrap=True)
                with Horizontal(classes="buttons"):
                    yield Button("Cancel", id="cancel", variant="warning")
                    yield Button("Back to menu", id="activity-back", disabled=True)
            yield Static("Ready. Arrow keys move; Enter selects; Tab moves between controls.", id="status", markup=False)
        yield Footer()

    def on_mount(self):
        self.refresh_facts()
        self.query_one("#menu", OptionList).focus()
        if self.initial_action:
            self.choose_action(self.initial_action)

    def on_resize(self, event):
        banners = self.query("#banner")
        if banners:
            banners.first().display = self.view == "home" and event.size.height >= 26

    def refresh_facts(self):
        source = Path(self.options.gufo_path or self.installer.root / "gufo").expanduser()
        revision = "not installed"
        if (source / ".git").exists():
            try:
                result = subprocess.run(["git", "-C", str(source), "rev-parse", "--short", "HEAD"],
                                        capture_output=True, text=True, timeout=3)
                revision = result.stdout.strip() if result.returncode == 0 else "checkout needs attention"
            except (OSError, subprocess.TimeoutExpired):
                revision = "Git unavailable"
        self.query_one("#facts", Static).update(
            f"{platform.system()} {platform.machine()}\nEngine: {source}\nRevision: {revision}\n"
            f"Source: {REPOSITORY} (main)\nBuild jobs: {self.options.jobs}\n")

    def show(self, view):
        self.view = view
        self.query_one("#banner").display = view == "home" and self.size.height >= 26
        for name in ("home", "settings", "review", "activity"):
            self.query_one(f"#{name}").set_class(name != view, "hidden")
        if view == "home":
            self.refresh_facts()
            self.query_one("#menu", OptionList).focus()

    def status(self, text):
        self.query_one("#status", Static).update(text)

    @on(OptionList.OptionSelected, "#menu")
    def menu_selected(self, event):
        self.choose_action(event.option.id)

    def choose_action(self, action):
        if self.busy:
            return
        if action == "settings":
            self.action_settings()
        elif action == "logs":
            self.show_log()
        elif action == "launch":
            self.exit("launch")
        elif action == "update-gui":
            try:
                revision = self.installer.gui_update_plan()
                self.selected_action = action
                self.query_one("#plan", Static).update(
                    f"Update Gufo-GUI main ({revision})\n\nThe TUI will close before Git fast-forwards this checkout.\n"
                    "Stop any running GUI first. Engine files, build environments and presets are preserved.\n"
                    "Run Gufo Setup again afterward to load the updated installer.")
                self.show("review")
                self.query_one("#review-back", Button).focus()
            except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                self.status(str(error))
        else:
            self.selected_action = action
            self.start_activity("Inspecting machine and dependencies…")
            self.inspect()

    def start_activity(self, message):
        self.lines = []
        self.completed_phases = []
        self.busy = True
        self.runner = Runner()
        self.query_one("#output", RichLog).clear()
        self.query_one("#phases", Static).update(message)
        self.query_one("#progress", ProgressBar).update(total=None)
        self.query_one("#cancel", Button).disabled = False
        self.query_one("#activity-back", Button).disabled = True
        self.show("activity")
        self.status(message)

    def add_line(self, line):
        self.lines.append(line)
        self.lines = self.lines[-1000:]
        event = parse_event(line)
        if event:
            phase = event["phase"]
            if phase not in self.completed_phases:
                self.completed_phases.append(phase)
            self.query_one("#phases", Static).update("\n".join(
                ("> " if item == phase else "+ ") + PHASES[item] for item in self.completed_phases))
            self.status(PHASES[phase])
        else:
            self.query_one("#output", RichLog).write(line)

    @work(thread=True, exclusive=True)
    def inspect(self):
        try:
            plan = self.installer.plan(self.selected_action, self.options, self.runner,
                                       lambda line: self.call_from_thread(self.add_line, line))
            self.call_from_thread(self.review_plan, plan)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            self.call_from_thread(self.finish, 2 if self.runner.cancelled.is_set() else 1, str(error))

    def review_plan(self, plan):
        self.busy = False
        if self.quit_pending:
            self.exit()
            return
        self.plan = plan
        self.query_one("#plan", Static).update(describe_plan(plan, self.selected_action))
        self.show("review")
        self.query_one("#review-back", Button).focus()
        self.status("Review the plan before continuing. No engine changes have been made.")

    @on(Button.Pressed, "#execute")
    def execute(self):
        if self.selected_action == "update-gui":
            self.exit("update-gui")
            return
        try:
            if self.plan.get("requiresSudo"):
                with self.suspend():
                    authenticate(self.plan)
        except (OSError, subprocess.SubprocessError) as error:
            self.status(f"Authentication failed: {error}")
            return
        self.start_activity("Starting the reviewed plan…")
        self.perform()

    @work(thread=True, exclusive=True)
    def perform(self):
        try:
            code = self.installer.execute(self.selected_action, self.options, self.runner,
                                          lambda line: self.call_from_thread(self.add_line, line))
            self.call_from_thread(self.finish, code, "")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            self.call_from_thread(self.finish, 1, str(error))

    def finish(self, code, error):
        self.busy = False
        self.query_one("#cancel", Button).disabled = True
        self.query_one("#activity-back", Button).disabled = False
        self.query_one("#activity-back", Button).focus()
        self.query_one("#progress", ProgressBar).update(total=1, progress=1 if code == 0 else 0)
        message = "Complete. Launch the GUI from the menu." if code == 0 else (
            "Cancelled. Completed downloads/build steps can be reused." if code == 2 else "Stopped. Fix the error and retry.")
        if error:
            self.add_line(error)
        self.status(message + (f" Log: {self.installer.last_log}" if self.installer.last_log else ""))
        if self.quit_pending:
            self.exit()

    def action_settings(self):
        if self.busy:
            return
        for key in ("gufo_path", "rocm", "vcpkg", "jobs"):
            self.query_one(f"#{key}", Input).value = str(getattr(self.options, key))
        self.show("settings")
        self.query_one("#gufo_path", Input).focus()

    @on(Button.Pressed, "#save")
    def save(self):
        try:
            values = {key: self.query_one(f"#{key}", Input).value.strip() for key in ("gufo_path", "rocm", "vcpkg", "jobs")}
            values["jobs"] = int(values["jobs"])
            options = Options(**values).validate(self.installer.root)
            save_options(options, self.installer.root)
            # Keep the caller's object current for the post-TUI launch handoff.
            self.options.__dict__.update(options.__dict__)
            self.show("home")
            self.status("Settings saved. Existing GUI presets are unchanged.")
        except (ValueError, OSError) as error:
            self.status(str(error))

    @on(Button.Pressed, "#settings-back")
    @on(Button.Pressed, "#review-back")
    @on(Button.Pressed, "#activity-back")
    def back_button(self):
        self.action_back()

    def action_back(self):
        if self.busy:
            self.request_cancel()
        else:
            self.show("home")

    @on(Button.Pressed, "#cancel")
    def cancel_button(self):
        self.request_cancel()

    def request_cancel(self, quit_after=False):
        if not self.busy or self.cancel_prompt:
            return
        self.cancel_prompt = True

        def confirmed(value):
            self.cancel_prompt = False
            if value and self.busy:
                self.quit_pending = quit_after
                self.query_one("#cancel", Button).disabled = True
                self.status("Stopping the installer process tree…")
                self.run_worker(self.runner.cancel, thread=True)

        self.push_screen(Confirm("Stop this operation? System packages already installed will remain.\n"
                                 "Interrupted builds can be repaired by running setup again."), confirmed)

    def action_quit(self):
        if self.busy:
            self.request_cancel(quit_after=True)
        else:
            self.exit()

    def show_log(self):
        path = self.installer.last_log
        try:
            if path is None:
                path = max((self.installer.root / "build/installer-logs").glob("*.log"),
                           key=lambda item: item.stat().st_mtime_ns, default=None)
            if path is None:
                self.status("No installer logs yet.")
                return
            # Read only the tail; compiler logs can be large.
            with path.open("rb") as file:
                file.seek(max(0, path.stat().st_size - 128 * 1024))
                lines = file.read().decode("utf-8", errors="replace").splitlines()[-1000:]
            self.query_one("#output", RichLog).clear()
            for line in lines:
                self.query_one("#output", RichLog).write(line)
            self.query_one("#phases", Static).update("Latest installer log")
            self.query_one("#cancel", Button).disabled = True
            self.query_one("#activity-back", Button).disabled = False
            self.show("activity")
            self.query_one("#output", RichLog).focus()
            self.status(str(path))
        except OSError as error:
            self.status(str(error))
