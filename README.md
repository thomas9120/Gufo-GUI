# Gufo GUI for Windows

A standalone browser launcher for the official [Gufo inference engine](https://github.com/gufo-org/gufo).
Adapted from the GUI and Windows setup scripts in [thomas9120/gufo-windows](https://github.com/thomas9120/gufo-windows).
The launcher manages one text inference server, with model selection, named presets,
sampling and reasoning controls, speculative decoding, live status, and Start/Stop/Exit.

## Getting started

This setup targets **Windows 11 x64 on AMD Strix Halo / gfx1151**. Install the AMD
graphics driver first. Models are downloaded separately; keep enough disk and GPU
memory for your model and context size.

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
  tools/gui/                         GUI code and assets
  gufo/                              official Gufo source (created by setup)
    build/windows-release/gufo.exe   engine and staged runtime libraries
  build/gui-env/                     isolated Python environment
  build/windows-setup.json           saved tool and engine paths
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
