import { text, rawText, initLanguage } from "./i18n.js";
import { $, api, notice } from "./api.js";
import { createSettingsForm, sameSettings } from "./settings-form.js";
import { createPresets } from "./presets.js";
import { initFilePicker } from "./file-picker.js";
import { createRuntime } from "./runtime.js";
import { confirmBusyAction } from "./busy-actions.js";

initLanguage();

let form, presets, busy = false, closed = false;
let previewTimer, previewVersion = 0;
const runtime = createRuntime(updateControls);

function updateControls() {
  const state = runtime.state;
  const active = state.pid != null || ["loading", "ready", "stopping"].includes(state.state);
  $("settings-form").inert = !form || busy || closed;
  $("start-button").disabled = !form || busy || active || closed;
  $("stop-button").disabled = busy || !active || state.state === "stopping" || closed;
  $("exit-button").disabled = busy || closed;
  presets?.render();
  const different = active && state.running && form && !sameSettings(form.values(), state.running.settings);
  text($("next-launch-note"), different
    ? "These settings differ from the running server. Changes apply to the next launch."
    : "Changes apply to the next launch.");
}

async function preview(version) {
  try {
    const result = await api("preview", form.values());
    if (version === previewVersion) rawText($("command"), result.command);
  } catch (error) {
    if (version === previewVersion) text($("command"), error.message);
  }
}

function edited() {
  updateControls();
  clearTimeout(previewTimer);
  const version = ++previewVersion;
  previewTimer = setTimeout(() => preview(version), 250);
}

async function action(callback) {
  if (busy || closed) return;
  busy = true; updateControls(); notice("");
  try { return await callback(); }
  catch (error) { notice(error.message, false, error.i18nValues); }
  finally { busy = false; updateControls(); }
}

$("settings-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => runtime.render(await api("start", { settings: form.values(), preset_id: presets.id })));
});
$("stop-button").addEventListener("click", () => action(async () => {
  if (await confirmBusyAction(runtime.state, "stop")) runtime.render(await api("stop", {}));
}));
$("exit-button").addEventListener("click", () => action(async () => {
  if (!await confirmBusyAction(runtime.state, "exit")) return;
  await api("exit", {});
  closed = true;
  runtime.close();
  notice("Launcher closed. Saved presets will be restored next time.", true);
}));
$("copy-url").addEventListener("click", () => action(async () => {
  await navigator.clipboard.writeText($("api-url").textContent);
  notice("API address copied.", true);
}));
window.addEventListener("beforeunload", (event) => {
  if (!closed && presets?.dirty()) { event.preventDefault(); event.returnValue = ""; }
});

updateControls();
(async () => {
  try {
    const result = await api("settings");
    form = createSettingsForm(result.settings, result.families, result.modes, edited);
    presets = createPresets(result, form, action, edited);
    initFilePicker(result.home);
    text($("settings-location"), "Settings · {path}", { path: result.path });
    edited();
    if (result.warning) notice("{detail} Defaults are shown; your saved file has not been changed.", false, { detail: result.warning });
    runtime.poll();
  } catch (error) { notice("Could not load settings. {detail}", false, { detail: error.message }); }
})();
