# Gufo Setup

A shared Windows/Linux terminal installer inspired by the original
`older-gui/Gufo-Setup.cmd` and its PowerShell interface. It manages the official
Gufo engine in a separate checkout and prepares this repository's web GUI.

From a complete source checkout or extracted source archive:

```powershell
.\Gufo-Setup.cmd
```

```sh
bash gufo-setup.sh
```

Windows can install missing Python through WinGet after asking. Linux requires
64-bit Python 3.10+ with venv support (`python3-venv` on Debian/Ubuntu).
The bootstrap installs the pinned Textual dependency into `build/installer-env`.
It does not install anything into system Python. These launchers require the
repository files beside them; they are not standalone release downloaders.

Use arrow keys and Enter in the menu, Tab between controls, F2 for settings,
Escape to go back, and Q or Ctrl+C to quit. Review defaults to the Back button;
installation starts only after choosing Continue. Small terminals can scroll.
The green, amber, and cream theme follows the older installer.

## Actions

- **Install:** inspect hardware/tools, review missing packages and paths, clone
  official `gufo-org/gufo` main if absent, build, verify GPU startup, prepare GUI.
- **Update engine:** validate the official clean main checkout and prerequisites,
  review, fast-forward main, rebuild, and verify. Forks and dirty checkouts stop
  the operation; they are never converted or reset.
- **Repair:** rerun setup against the existing revision, reusing downloads and
  build outputs. Missing GUI environments are recreated. It does not pull source
  or delete models/presets; it does not clean local changes automatically.
- **Launch GUI:** close the TUI and run the existing web launcher in the terminal.
- **Update GUI:** stop the web GUI first. A clean main checkout with the official
  GUI origin is required. After review, the TUI closes and external Git performs
  a fast-forward update. Run Setup again to load updated dependencies and code.
  Source archives and development branches must be updated manually.
- **Settings / logs:** customize engine and tool paths and build jobs; read the
  tail of the most recent installer log. Full logs live in `build/installer-logs`.

Linux authenticates sudo in the terminal before package installation, then uses
`sudo -n` in the worker so a hidden password prompt cannot hang the TUI. If sudo
credentials expire during a long run, authenticate and retry. ROCm and graphics
drivers must be installed separately on Linux. Continuing a Windows package plan
accepts WinGet source and package agreements; installers may display UAC dialogs.

Cancellation terminates the owned subprocess tree (Windows Job / POSIX process
group). Packages already installed remain. A lock prevents two new installers
from executing in the same GUI folder. Do not run the older direct setup/update
scripts concurrently or point two GUI installations at one engine concurrently.

## Plain mode and automation

Plain mode uses only the Python standard library and existing OS scripts:

```powershell
.\Gufo-Setup.cmd --plain --action install --check-only
.\Gufo-Setup.cmd --plain --action install --yes --gufo-path "D:\AI\gufo" --jobs 8
.\Gufo-Setup.cmd --plain --action update
```

```sh
bash gufo-setup.sh --plain --action install --check-only
bash gufo-setup.sh --plain --action install --yes --gufo-path "$HOME/AI/gufo" --jobs 8
bash gufo-setup.sh --plain --action update
```

`--check-only` skips TUI bootstrapping and changes no engine files or setup state.
Redirected input/output uses plain mode; supply `--action` explicitly. Without
`--yes`, redirected input never accepts installation automatically. `--yes` does
not bypass initial Python-install permission or OS elevation requirements.

## Update and recovery limits

The engine tracks upstream main, using the tool versions already pinned by the
platform scripts. This is not a promise that every future main revision will
build with those versions. Upstream owns CMake presets, build dependencies, and
SDK compatibility. Build errors remain visible with a full log for diagnosis.

Builds currently run in place. A failure after pulling retains the new source;
the previous executable may have been replaced before GPU verification fails.
There is no automatic runtime rollback. Fix the reported issue and use Repair,
or restore a known working engine revision manually. GUI updates are Git
fast-forwards, not staged application deployments. Models and saved presets
remain outside the updater's operations. This version deliberately offers no
uninstall action that could remove user files.

## Development

`core.py` has no UI dependencies. `main.py` provides the plain CLI and post-TUI
handoff; `tui.py` / `theme.tcss` implement the interface. Platform scripts retain
ownership of package managers and builds. They export schema-1 plans with
`-CheckOnly -PlanJson PATH` (Windows) / `--check-only --plan-json PATH` (Linux).
When `GUFO_INSTALLER_EVENTS=1`, they emit `GUFO_EVENT ` followed by a JSON object
with `schema: 1` and `phase`. Ordinary command output remains log text.

```sh
python -m pip install -r tools/installer/requirements.txt
python -m unittest discover -s tests/tools -p installer_test.py -v
python -m unittest discover -s tests/tools -p '*launcher_test.py' -v
```

Tests use temporary Git repos and simulated builds; no GPU build, system package
installation, or live engine update occurs. Real Strix Halo smoke tests remain
necessary to qualify a toolchain/upstream combination.
