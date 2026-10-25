import { text } from "./i18n.js";
import { $, api, notice } from "./api.js";
import { sameSettings } from "./settings-form.js";
import { ask } from "./dialogs.js";

export function createPresets(initial, form, action, onChange) {
  let document = initial.document;
  let selectedId = document.selected_preset;
  let pendingId = selectedId;
  let hasSaved = initial.saved;
  let renderedRevision = -1;

  function selected() { return document.presets.find((preset) => preset.id === selectedId); }
  function savedValues() { return { ...selected().settings, ...document.launcher }; }
  function dirty() { return !sameSettings(form.values(), savedValues()); }

  function render() {
    if (renderedRevision !== document.revision) {
      $("preset-select").replaceChildren(...document.presets.map((preset) => new Option(preset.name, preset.id)));
      renderedRevision = document.revision;
    }
    $("preset-select").value = pendingId;
    text($("loaded-preset"), "Loaded preset: {name}", { name: selected().name });
    $("delete-preset").disabled = document.presets.length === 1;
    text($("saved-state"), dirty() ? "Unsaved changes" : hasSaved ? "Preset saved" : "Not saved yet");
  }

  async function change(request) {
    const result = await api("presets", { ...request, revision: document.revision });
    document = result.document;
    hasSaved = true;
  }

  async function save() {
    if (!form.valid()) return false;
    await change({ action: "save", id: selectedId, settings: form.values() });
    form.apply(savedValues());
    onChange();
    notice("Preset and shared launcher settings saved for your next visit.", true);
    return true;
  }

  async function mayLeave() {
    if (!dirty()) return true;
    const choice = await ask($("unsaved-dialog"));
    return choice === "discard" || (choice === "save" && await save());
  }

  for (const event of ["input", "change"]) {
    $("preset-select").addEventListener(event, () => { pendingId = $("preset-select").value; });
  }
  $("load-preset").addEventListener("click", () => {
    const next = pendingId;
    action(async () => {
      if (!await mayLeave()) return;
      selectedId = pendingId = next;
      form.apply(savedValues());
      onChange();
      notice('Preset "{name}" loaded for the next launch.', true, { name: selected().name });
    });
  });
  $("save-button").addEventListener("click", () => action(save));

  for (const [button, operation] of [["save-as-preset", "create"], ["rename-preset", "rename"]]) {
    $(button).addEventListener("click", () => action(async () => {
      if (operation === "create" && !form.valid()) return;
      text($("preset-name-title"), operation === "create" ? "Save as a new preset" : "Rename preset");
      $("preset-name").value = operation === "create" ? "" : selected().name;
      if (await ask($("preset-name-dialog")) !== "save") return;
      await change({ action: operation, id: selectedId, name: $("preset-name").value,
                     ...(operation === "create" ? { settings: form.values() } : {}) });
      if (operation === "create") {
        selectedId = pendingId = document.selected_preset;
        form.apply(savedValues());
      }
      onChange();
      notice(operation === "create" ? "New preset saved." : "Preset renamed. Unsaved form edits are unchanged.", true);
    }));
  }

  $("delete-preset").addEventListener("click", () => action(async () => {
    if (!await mayLeave()) return;
    $("delete-preset-name").textContent = selected().name;
    if (await ask($("delete-dialog")) !== "delete") return;
    await change({ action: "delete", id: selectedId });
    selectedId = pendingId = document.selected_preset;
    form.apply(savedValues());
    onChange();
    notice("Preset deleted. Model files and the running server are unchanged.", true);
  }));

  $("export-presets").addEventListener("click", () => action(async () => {
    const backup = await api("presets/export");
    const link = Object.assign(window.document.createElement("a"), {
      href: URL.createObjectURL(new Blob([`${JSON.stringify(backup, null, 2)}
`], { type: "application/json" })),
      download: `gufo-presets-${new Date().toISOString().slice(0, 10)}.json`,
    });
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    notice("Presets backed up: {count}. Unsaved form edits are not included.", true, { count: backup.presets.length });
  }));

  $("import-presets").addEventListener("click", () => $("import-file").click());
  $("import-file").addEventListener("change", () => action(async () => {
    const [file] = $("import-file").files;
    $("import-file").value = "";
    if (!file) return;
    let data;
    try { data = JSON.parse(await file.text()); }
    catch { throw new Error("This is not a Gufo preset backup file."); }
    const result = await api("presets/import", { data, revision: document.revision });
    document = result.document;
    onChange();
    notice("Presets imported: {count}. Existing presets were not changed.", true, { count: result.imported });
  }));

  return { get id() { return selectedId; }, dirty, render };
}
