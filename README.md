# Gufo GUI for Windows and Linux


A standalone browser launcher for the official [Gufo inference engine](https://github.com/gufo-org/gufo).
The launcher manages one text inference server, with model selection, named presets,
sampling and reasoning controls, speculative decoding, live status, and Start/Stop/Exit.

Simplified Chinese language support by @jerrydong1988



## Getting started

Follow the [Windows instructions](#windows) below or jump to the
[Linux instructions](#linux) for setup, launching, and updating.

This setup targets **Windows 11 x64 and Linux on AMD Strix Halo / gfx1151**. Install the AMD
graphics driver first. Models are downloaded separately; keep enough disk and GPU
memory for your model and context size.

**Gufo Setup is the recommended way to install and manage Gufo-GUI and the
official Gufo engine.** Run **Gufo-Setup.cmd** on Windows or `bash gufo-setup.sh`
on Linux. The TUI provides install, engine update, repair, GUI launch/update,
settings, and logs in one menu.

The older `setup-windows.bat`, `update-windows.bat`, `setup-linux.sh`, and
`update-linux.sh` remain available as legacy/fallback entry points. They use
the same platform setup/build operations underneath the TUI.

### Windows

1. Download or clone this repository into a writable folder.
2. Double-click **Gufo-Setup.cmd**. If Python is missing, accept the prompt to
   install it. The bootstrap prepares an isolated environment for the TUI.
3. Choose **Install Gufo and prepare GUI**, review the plan, and choose
   **Continue**. Setup installs missing tools, clones **gufo-org/gufo, branch
   main**, builds the engine, verifies GPU startup, and prepares the GUI.
4. Return to the menu and choose **Launch Gufo-GUI**. Select your GGUF model
   and optional projector/draft files, save a preset, and
   click **Start Gufo**. Connect your client to `http://127.0.0.1:8080/v1`
   with model name `gufo` by default.

On later runs, choose **Launch Gufo-GUI** in Setup or double-click
**launch-gui.bat** for direct access. The GUI opens at
`http://127.0.0.1:8090`; opening it does not load a model. Keep the terminal open.
**Stop** unloads the engine; **Exit** closes both the launcher and its engine.

Setup installs missing Git, Visual Studio C++ Build Tools/Windows SDK, CMake,
Ninja, Rust (via rustup), and 64-bit Python using WinGet. It reuses suitable existing tools. The first
run also downloads the verified TheRock 10.0.0 and XRT 2.21.75 SDKs and prepares a full vcpkg clone.
Rustup selects Gufo's pinned Rust toolchain during the build. The XRT SDK supplies
build headers and libraries; the NPU runtime comes from AMD's driver.
Downloads and completed build steps are reused when setup is rerun.
The SDK comes from the mirror documented by upstream because AMD's index no
longer serves this version. Setup verifies its pinned SHA-256 before extracting it.
See [official Windows prerequisites and build instructions](https://github.com/gufo-org/gufo/blob/main/BUILD-WINDOWS.md).

### Using the setup menu

Use arrow keys and **Enter** to select a menu item, **Tab** to move between
controls, **F2** for settings, **Escape** to go back, and **Q** or **Ctrl+C** to
quit. Installation starts only after choosing **Continue** on the review screen.

- **Settings / paths:** choose the engine folder, ROCm/TheRock and vcpkg paths,
  and parallel build jobs before installing or updating.
- **Repair tools / rebuild current source:** rerun setup against the current
  engine revision, reusing completed downloads and build steps.
- **View latest installer log:** inspect output after a failure; full logs are
  saved under `build/installer-logs/`.

For a plain terminal without the full-screen interface, use `--plain`:

```powershell
.\Gufo-Setup.cmd --plain --action install --check-only
.\Gufo-Setup.cmd --plain --action install --gufo-path "D:\AI\Gufo" --jobs 8
```

```sh
bash gufo-setup.sh --plain --action install --check-only
bash gufo-setup.sh --plain --action install --gufo-path "$HOME/AI/gufo" --jobs 8
```

See the [Gufo Setup guide](tools/installer/README.md) for all actions, automation,
cancellation, and recovery details. Keep the entry point beside the rest of the
repository files; it is not a standalone installer download.

## Folders and existing installations

The GUI and engine have separate checkouts:

```text
Gufo-GUI/
  Gufo-Setup.cmd                     recommended Windows setup menu
  gufo-setup.sh                      recommended Linux setup menu
  launch-gui.bat
  setup-windows.bat                  legacy/fallback Windows setup
  update-windows.bat                 legacy/fallback Windows engine update
  launch-gui.sh
  setup-linux.sh                     legacy/fallback Linux setup
  update-linux.sh                    legacy/fallback Linux engine update
  tools/gui/                         GUI code and assets
  tools/installer/                   shared TUI and plain CLI
  gufo/                              official Gufo source (created by setup)
    build/windows-release/gufo.exe   engine and staged runtime libraries
    build/release/gufo              Linux engine
  build/gui-env/                     isolated GUI Python environment
  build/installer-env/               isolated TUI Python environment
  build/installer-logs/              TUI/plain-mode operation logs
  build/windows-setup.json           saved tool and engine paths
  build/linux-setup.json             saved Linux tool and engine paths
  build/setup-*.log                  setup logs
```

You can choose another folder, including an existing clean checkout of official
Gufo on `main`. Open **Settings / paths** in the TUI and set the engine source
folder before choosing Install. The plain-mode examples above provide the same
choice from the command line.

The folder is remembered for later setup, update, and default executable discovery.
Setup refuses a fork or modified checkout; it does not convert your existing
Windows port. To use an already built engine without setup, install 64-bit
Python 3.10+, run `launch-gui.bat`, and select its executable in the GUI. Keep
`gufo.exe` beside its runtime DLLs and `rocblas`/`hipblaslt` folders.

Saved presets remain at `%LOCALAPPDATA%\Gufo\launcher.json`, shared with the
original launcher. Existing executable selections are preserved: if migrating
from the Windows port, select the new official `gufo.exe` and save each preset
you want to migrate. Back up presets using the GUI's Export function.

## Updating

On either platform, open **Gufo-Setup.cmd** / `bash gufo-setup.sh`:

- **Engine:** stop Gufo in the GUI, choose **Update official Gufo engine**, review
  the plan, and choose **Continue**. Setup fast-forwards the separate official
  engine checkout from `main`, rebuilds, and verifies GPU startup.
- **GUI:** close the web GUI and engine, then choose **Update Gufo-GUI**. This
  requires a clean GUI checkout on `main` with the official GUI origin. The TUI
  closes before Git updates the repository. Run Setup again afterward to load
  the updated installer. Source archives and development branches must be
  updated manually; preserve the `gufo` and `build` folders when replacing a
  source download.

For engine updates, local changes, untracked files, a different branch, or a
divergent history stop the update. Resolve them in the engine checkout before
retrying.
Engine updates build in place: if compilation or verification fails after
pulling, the source update is retained and the old runtime may have been
replaced. Fix the error and use **Repair**; there is no automatic runtime rollback.

Launcher dependencies refresh when `requirements.txt` changes. Updating the
engine leaves GUI code and presets intact.

### Legacy/fallback Windows scripts

If you prefer the original direct scripts or need a fallback, run
**setup-windows.bat** for setup or **update-windows.bat** for engine updates.
Stop the engine before updating. The updater reapplies upstream's idempotent
SDK header patch, builds the `windows-release` preset, and checks GPU startup.

These examples use the older scripts' PowerShell-style options. The new Setup
entry point uses the `--plain`, `--action`, and other options shown above.

```powershell
.\setup-windows.bat -CheckOnly                      # show plan without installing
.\setup-windows.bat -CheckOnly -PlanJson plan.json  # also export the plan
.\setup-windows.bat -Yes -NoLaunch -Jobs 8
.\setup-windows.bat -Rocm "C:\TheRock\build" -Vcpkg "C:\vcpkg"
.\update-windows.bat -Jobs 8
.\launch-gui.bat -Port 8091 -NoBrowser
.\launch-gui.bat -Config "D:\AI\launcher.json"
```

Setup can request Windows elevation and license acceptance for missing tools.
It does not change your AMD driver or graphics memory allocation.
Dependencies installed by setup are kept under `%LOCALAPPDATA%\Gufo\dependencies`.
For GUI controls and development checks, see [tools/gui/README.md](tools/gui/README.md).

## Linux

Gufo Setup targets **x86-64 Linux on AMD Strix Halo / gfx1151**. Install 64-bit
Python 3.10+ with venv support (`python3-venv` on Debian/Ubuntu), then install
ROCm using
[AMD's Linux instructions](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/)
(upstream qualifies ROCm 7.2.3), including the hipBLAS, hipBLASLt, rocBLAS, hipCUB,
rocPRIM and rocWMMA development packages. Add your user to the `render` and
`video` groups, then log out and back in.

Install **Rust/Cargo 1.88+ through [rustup](https://rustup.rs)** and **XRT with
the amdxdna plugin** before setup or engine updates. Follow the
[upstream Linux prerequisites](https://github.com/gufo-org/gufo/blob/main/docs/install.md)
for XRT installation. Setup checks its CMake configuration under
`/opt/xilinx/xrt/share/cmake/XRT`, `$XILINX_XRT/share/cmake/XRT`, or `$XRT_DIR`.
For a custom installation, export `XRT_DIR` before launching Setup.
Linux setup installs libopus development files with the other system dependencies;
libsndfile and soxr are no longer required. Rust and XRT must be installed separately.

### First-time setup on Linux

1. Download and extract the repository's source ZIP, or clone this repository,
   into a writable folder.
2. Open a terminal in the `Gufo-GUI` folder and run:

   ```sh
   bash gufo-setup.sh
   ```

3. Choose **Install Gufo and prepare GUI**, review the plan, and choose
   **Continue**. Setup installs missing build tools,
   clones the official `gufo-org/gufo` `main` branch, builds the engine, verifies
   GPU startup, and prepares the GUI's Python environment. The first build can
   take a while. If system packages are needed, authenticate `sudo` in the
   terminal when prompted before installation starts.
4. Return to the menu and choose **Launch Gufo-GUI**. In the GUI, select your
   GGUF model and any optional projector or draft model,
   save a preset, and click **Start Gufo**. Connect your client to
   `http://127.0.0.1:8080/v1` with model name `gufo` by default.

Setup reviews the plan before changing anything. With apt, dnf or pacman it offers
to install missing build tools and libraries through `sudo`; it does not install
ROCm or change GPU drivers. It builds upstream's `release` preset, so the engine
is `gufo/build/release/gufo`. The chosen folders and tools are saved in
`build/linux-setup.json`, and presets are saved in `~/.config/Gufo/launcher.json`.
Full operation logs are written to `build/installer-logs/`; the platform setup
also writes `build/setup-*.log`. If setup fails, read the error, fix the missing
prerequisite, and use **Repair tools / rebuild current source**.

The commands here use `bash` so they also work when a downloaded ZIP has not
preserved executable permissions. Run them from the repository folder.

### Launching on Linux

On later runs, choose **Launch Gufo-GUI** in Setup. For direct access, open a
terminal in the repository folder and run:

```sh
bash launch-gui.sh
```

The GUI opens at `http://127.0.0.1:8090`. Opening it does not load a model;
select a preset and click **Start Gufo** when ready. Keep the terminal open.
**Stop** unloads the engine; **Exit** closes the launcher and its engine.
Closing the terminal also stops both.

To use an engine you have already built, install 64-bit Python 3.10+ with venv
support, run the launcher, and select your `gufo` executable in the GUI. The
launcher creates `build/gui-env` and installs its Python dependencies on first
use. On Debian/Ubuntu, install `python3-venv` if environment creation fails.

### Updating on Linux

Stop the engine in the GUI, run `bash gufo-setup.sh`, and choose **Update
official Gufo engine**. Review the plan and choose **Continue**. It reuses the
paths saved by setup and preserves your presets. See [Updating](#updating) for
checkout requirements, GUI updates, and recovery limits.

### Legacy/fallback Linux scripts

The original direct scripts remain available for setup and engine updates:

```sh
bash setup-linux.sh
bash update-linux.sh
```

Stop the engine before running the updater. It fast-forwards official `main`,
builds the `release` preset, and verifies GPU startup. The direct setup script
opens the GUI when it finishes. Optional arguments for these legacy scripts:

```sh
bash setup-linux.sh --check-only                  # show plan without installing
bash setup-linux.sh --yes --no-launch --jobs 8
bash setup-linux.sh --gufo-path ~/AI/gufo --rocm /opt/rocm
bash update-linux.sh --jobs 8
bash launch-gui.sh --port 8091 --no-browser
bash launch-gui.sh --config ~/AI/launcher.json
```

Use `--help` with any of the three scripts to see its available options.
