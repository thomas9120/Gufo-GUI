# Local Gufo launcher

This browser control panel manages one official Gufo `serve llm` process. Run
[setup-windows.bat](../../setup-windows.bat) to build the engine, then use
[launch-gui.bat](../../launch-gui.bat). See the [main README](../../README.md)
for prerequisites, custom engine folders, updates, and command-line options.

## Using the GUI

1. Choose a models folder and select a main GGUF. Browse subfolders or paste
   an absolute path. For split models, select the first shard.
2. Choose a model family and speculative mode: Off, MTP for Flash-Next, or
   DFlash2 for Qwen3.8-27B. Select the matching MTP sidecar or DFlash2 draft.
   The family describes GUI choices; the engine checks actual compatibility.
3. Optionally select a vision projector. A blank path leaves auto-discovery
   to the engine. An incompatible projector can fail during model loading.
4. Check the executable. New presets default to the official checkout's
   `build/windows-release/gufo.exe`. Saved selections are preserved.
   Keep the executable beside its runtime libraries.
5. Adjust settings, Save preset (or Save as for a new name), then Start Gufo.
   Wait for Ready before connecting your API client.

The GUI defaults to 32K context, one session, a 2,048-token output limit,
temperature 1, top-p 0.95, top-k 20, and min-p 0. Choose settings appropriate
for your model and available memory. Thinking and reasoning controls set
server defaults; clients can override generation defaults per request.

The API defaults to `http://127.0.0.1:8080/v1` with model name `gufo`.
The launcher listens only on localhost at port 8090. Changing the engine's
API bind address to `0.0.0.0` permits LAN access; clients use the PC's LAN
address and Windows Firewall must allow the API port. This GUI does not
configure API authentication. See the upstream
[server documentation](https://github.com/gufo-org/gufo/blob/main/docs/SERVER.md).
Use different ports for the engine and GUI.

Settings and named presets are saved explicitly in
`%LOCALAPPDATA%\Gufo\launcher.json`. Start uses the current form without saving.
Load preset restores a saved configuration. Export and Import provide JSON
backups. The GUI shares the original Windows launcher's settings location;
select and save the official executable when migrating existing presets.

Stop unloads the owned engine. Exit closes both processes. Closing the terminal
also stops the engine on Windows through its job object. A selected model is
not loaded until Start is clicked. Runtime identity, capabilities and metrics
come from the running engine; unavailable observations appear as dashes.

Live prefill and generation show token-counter changes divided by wall time
between polls, across all requests and excluding cached prompt tokens. Counters
advance after processing chunks return, so short prefills may fall between polls.
The live cards show a dash while idle. Completed prefill and generation retain
the engine's latest nonzero measured processing speeds. Upstream's cumulative
prefill-time counter updates at request completion and cannot measure live
processing speed while a request is still running.

More options exposes sessions, penalties, continuation cache settings and MTP
draft limits. Optional controls depend on engine support. Disk caching is off
by default. Start checks filesystem paths, GGUF magic, split-file presence
and numeric inputs; it cannot guarantee model compatibility or available VRAM.
The command preview shows the native argument list. Logs retain 300 lines.

## Development

The launcher requires 64-bit Python 3.10+ and the packages in requirements.txt.
`tools/windows/gui.ps1 -PrepareOnly` creates the isolated `build/gui-env`.
To run directly, install the requirements in your environment and use
`python tools/gui/server.py`. The backend also supports POSIX paths.

```powershell
.\build\gui-env\Scripts\python.exe -m unittest discover -s tests/tools -p "*_test.py"
npm install --prefix build/gui-test-js --no-save --package-lock=false jsdom@26.1.0
node --experimental-vm-modules --test tests/tools/gui_dom_test.mjs tests/tools/gui_runtime_dom_test.mjs
```

The Python tests cover persistence, command validation, filesystem selection,
real child processes, local HTTP controls, default executable discovery and
the Windows source/build scripts. Windows script tests use temporary checkouts
and simulated builds; they do not install prerequisites or load models.
DOM tests use Flask-rendered templates. Set `GUI_TEST_PYTHON` if the test Python
is outside `build/gui-env`. DOM tests verify interactions, not browser layout.

The GUI was extracted from thomas9120/gufo-windows at commit
`134ccfa0a05645be6fd1d5b6b6e4a871c17d49d8`, under the MIT license.
Backend modules keep settings, presets, command construction, filesystem access,
HTTP controls and process lifetime separate. Browser modules cover form editing,
presets, file picking, runtime display, themes and English/Chinese localization.
