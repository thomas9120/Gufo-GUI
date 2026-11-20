# TODO

## Gufo Extensions Support

### Phase 1: Launch & Discovery Support
- [x] **Backend extension & option discovery (`tools/gui/extensions.py`)**
  - [x] Inspect the selected Gufo executable locally (no network calls on load): run `gufo diagnose --section extensions --json` and `gufo serve llm --help` to discover built-in/loaded extensions, excluded extensions, providers, and `Provider options` (`path`, `integer`, `number`, `string`, `boolean`).
  - [x] Enrich installed module metadata from the local extension store (`$GUFO_EXTENSIONS_DIR` or platform user data `gufo/extensions/installed.json` and `<name>/source/extension.json`) when available, including `serving.draft_options` and `needs update` detection against `<exe>` build ID.
  - [x] Cache discovery results per `(executable path, mtime, store state)` and degrade gracefully for older/missing executables.
- [x] **Settings, presets & command generation (`tools/gui/settings.py`, `tools/gui/presets.py`, `tools/gui/command.py`)**
  - [x] Add `provider_options: {}` to `DEFAULTS` (stored per preset, preserved across Export/Import and older preset loads without rewriting saved files).
  - [x] Strictly validate `provider_options` flag names (`^--[a-z0-9][a-z0-9-]*$`, rejecting core-owned flags and control characters) and value types (`str`, `int`, `float`, `bool`) while preserving unknown saved flags for presets whose extension is currently absent.
  - [x] Emit active `provider_options` in `build_command` using Gufo's `ProviderOptions` syntax (`--flag=value`, bare `--flag` for `True`, omitted when empty/`False`), and validate `path` options on launch (`check_files=True`) allowing either an existing file or directory (e.g. Hy4 `--dfly-model` `.safetensors` file or checkpoint directory).
  - [x] Guard against combining core `--speculative` != `off` with an extension-owned draft option (from `serving.draft_options`).
- [x] **File picker support for non-GGUF / directory-or-file paths (`tools/gui/files.py`, `tools/gui/static/file-picker.js`)**
  - [x] Add `kind="path"` in `browse_directory` showing all files and folders while enabling the **Use this folder** action in the picker dialog.
- [x] **API & Frontend UI (`tools/gui/server.py`, `tools/gui/templates/index.html`, `tools/gui/static/`)**
  - [x] Include initial `extensions` discovery payload in `GET /api/settings` and expose `POST /api/extensions` (with token/origin checks) to refresh or inspect a newly selected executable.
  - [x] Render a dynamic **Extension options** section in the form from discovered `serve` provider options (with `path` browse buttons, numeric/text/checkbox inputs, help text, and warning badges for saved options whose extension is not currently loaded), plus an **Installed extensions** summary/refresh control.
  - [x] Keep `sameSettings`, dirty tracking, preset load/save/export/import, and `zh-CN` i18n translations (`tools/gui/static/locales/zh-CN.js`) aligned with `provider_options`.
- [x] **Automated tests**
  - [x] Python unit tests (`tests/tools/gui_extensions_test.py` + updates to `gui_config_test.py` / `gui_server_test.py`) covering discovery parsing (including Hy4 Flash `--dfly-model` / `--dfly-draft-tokens`), validation, preset round-trips, `path` file picker, and HTTP routes.
  - [x] DOM & i18n tests (`tests/tools/gui_dom_test.mjs`) covering dynamic extension option rendering, editing, preset restore, dirty state, file picker `path` mode, and `zh-CN` translations.

### Phase 2: Extension Management & Build Integration
- [x] Expose `gufo extension install / update / remove` via async background runner with streamed logs and cancellation (in Web GUI **Manage extensions** dialog when server is stopped).
- [x] Add registry browsing (`gufo extension list --json`) alongside explicit security confirmation + pinned revision enforcement for non-registry Git URLs and local paths (`--yes`).
- [x] Rebuild `needs update` modules via `gufo extension update` after **Update official Gufo engine** (Linux `tools/linux/update.sh` and Windows `tools/windows/update.ps1`).
- [x] Wrap `gufo extension install/update` on Windows with the saved Visual Studio (`vcvars64.bat`), ROCm, and vcpkg toolchain environment from `build/windows-setup.json` (`tools/windows/run-extension.cmd`).
- [x] Add `extension_dirs` (`-DGUFO_EXTENSION_DIRS`) support to `tools/installer/core.py`, `tools/installer/main.py`, `tools/installer/tui.py`, `tools/linux/common.sh` / `setup.sh` / `update.sh`, and `tools/windows/build.ps1` / `build-upstream.cmd` / `setup.ps1` / `update.ps1` for compiled-in source extensions.

## Advanced engine controls

- [ ] Expose queue limits: `--max-pending` and `--max-pending-per-client`, including zero to disable queuing.
- [ ] Expose request timeout: `--request-timeout-ms` (waiting time included).
- [ ] Expose stall timeout: `--stall-timeout-ms` (off by default; minimum 60000 ms when enabled). Explain that it exits the engine when generation stalls.
- [ ] Expose connection limits: `--max-connections`.
- [ ] Consider request-body and response-size limits: `--max-request-bytes` and `--max-output-bytes`.

Keep these in More options, validate against upstream limits, preserve existing preset behavior, and cover command generation and form restoration.

## Future scope

- [ ] Evaluate launch support for other Gufo modalities separately from the text-server GUI.
