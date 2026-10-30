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

### Windows

1. Download or clone this repository into a writable folder.
2. Double-click **setup-windows.bat**. Review its plan and accept to install missing
   tools, clone **gufo-org/gufo, branch main**, build the engine, verify GPU startup,
   and prepare the GUI environment. Setup opens the launcher when complete.
3. Select your GGUF model and optional projector/draft files, save a preset, and
   click **Start Gufo**. Connect your client to `http://127.0.0.1:8080/v1`
   with model name `gufo` by default.

On later runs, double-click **launch-gui.bat**. The GUI opens at
`http://127.0.0.1:8090`; opening it does not load a model. Keep the terminal open.
**Stop** unloads the engine; **Exit** closes both the launcher and its engine.

Setup installs missing Git, Visual Studio C++ Build Tools/Windows SDK, CMake,
Ninja and 64-bit Python using WinGet. It reuses suitable existing tools. The first
run also downloads the verified TheRock 10.0.0 SDK and prepares a full vcpkg clone.
Downloads and completed build steps are reused when setup is rerun.
The SDK comes from the mirror documented by upstream because AMD's index no
longer serves this version. Setup verifies its pinned SHA-256 before extracting it.
See [official Windows prerequisites and build instructions](https://github.com/gufo-org/gufo/blob/main/BUILD-WINDOWS.md).

## Folders and existing installations

The GUI and engine have separate checkouts:

```text
Gufo-GUI/
  launch-gui.bat
  setup-windows.bat
  update-windows.bat
  launch-gui.sh
  setup-linux.sh
  update-linux.sh
  tools/gui/                         GUI code and assets
  gufo/                              official Gufo source (created by setup)
    build/windows-release/gufo.exe   engine and staged runtime libraries
    build/release/gufo              Linux engine
  build/gui-env/                     isolated Python environment
  build/windows-setup.json           saved tool and engine paths
  build/linux-setup.json             saved Linux tool and engine paths
  build/setup-*.log                  setup logs
```

You can choose another folder, including an existing clean checkout of official
Gufo on `main`. Run from PowerShell:

```powershell
.\setup-windows.bat -GufoPath "D:\AI\Gufo" -Jobs 4
```

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

On Linux, follow [Updating on Linux](#updating-on-linux). The Windows engine
update steps are below; the GUI update instructions apply to both platforms.

Stop the engine, then run **update-windows.bat**. It fast-forwards the separate
official checkout from `gufo-org/gufo` `main`, reapplies upstream's idempotent SDK
header patch, builds with the `windows-release` preset, and checks GPU startup.
Local changes, untracked files, a different branch, or a divergent history stop
the update. Resolve them in the engine checkout before retrying.
If compilation fails after pulling, the source update is retained; fix the error
and rerun the updater.

To update the GUI itself, pull this repository or replace it with a newer download,
preserving the `gufo` and `build` folders. Launcher dependencies refresh when
`requirements.txt` changes. Updating the engine leaves GUI code and presets intact.

## Options

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

The Linux scripts mirror the Windows ones and target **x86-64 Linux on AMD Strix
Halo / gfx1151**. Install ROCm first using
[AMD's Linux instructions](https://rocm.docs.amd.com/projects/install-on-linux/en/latest/)
(upstream qualifies ROCm 7.2.3), including the hipBLAS, hipBLASLt, rocBLAS, hipCUB,
rocPRIM and rocWMMA development packages. Add your user to the `render` and
`video` groups, then log out and back in.

### First-time setup on Linux

1. Download and extract the repository's source ZIP, or clone this repository,
   into a writable folder.
2. Open a terminal in the `Gufo-GUI` folder and run:

   ```sh
   bash setup-linux.sh
   ```

3. Review the setup plan and accept it. Setup installs missing build tools,
   clones the official `gufo-org/gufo` `main` branch, builds the engine, verifies
   GPU startup, and prepares the GUI's Python environment. The first build can
   take a while. Setup opens the GUI when it completes.
4. In the GUI, select your GGUF model and any optional projector or draft model,
   save a preset, and click **Start Gufo**. Connect your client to
   `http://127.0.0.1:8080/v1` with model name `gufo` by default.

Setup reviews the plan before changing anything. With apt, dnf or pacman it offers
to install missing build tools and libraries through `sudo`; it does not install
ROCm or change GPU drivers. It builds upstream's `release` preset, so the engine
is `gufo/build/release/gufo`. The chosen folders and tools are saved in
`build/linux-setup.json`, and presets are saved in `~/.config/Gufo/launcher.json`.
Setup logs are written to `build/setup-*.log`. If setup fails, read the error,
fix the missing prerequisite, and rerun the same command.

The commands here use `bash` so they also work when a downloaded ZIP has not
preserved executable permissions. Run them from the repository folder.

### Launching on Linux

On later runs, open a terminal in the repository folder and run:

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

Stop the engine in the GUI, then run:

```sh
bash update-linux.sh
```

The updater fast-forwards the separate official engine checkout from `main`,
rebuilds it with the `release` preset, and verifies GPU startup. It reuses the
paths saved by setup and preserves your presets. Local changes, untracked files,
another branch, or divergent history in the engine checkout stop the update;
resolve them before retrying. If a build fails after pulling, the source update
is retained; fix the error and rerun the updater.

After updating, run `bash launch-gui.sh` again. To update the GUI itself, pull
this repository or replace it with a newer source download, preserving the
`gufo` and `build` folders. The launcher refreshes its Python dependencies when
`requirements.txt` changes.

### Linux options

```sh
bash setup-linux.sh --check-only                  # show plan without installing
bash setup-linux.sh --yes --no-launch --jobs 8
bash setup-linux.sh --gufo-path ~/AI/gufo --rocm /opt/rocm
bash update-linux.sh --jobs 8
bash launch-gui.sh --port 8091 --no-browser
bash launch-gui.sh --config ~/AI/launcher.json
```

Use `--help` with any of the three scripts to see its available options.
