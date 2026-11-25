import { text, rawText, option } from "./i18n.js";
import { $ } from "./api.js";

function sameValue(left, right) {
  if (left === right) return true;
  if (!left || !right || typeof left !== "object" || typeof right !== "object"
      || Array.isArray(left) || Array.isArray(right)) return false;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => left[key] === right[key]);
}

export function sameSettings(left, right) {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => sameValue(left[key], right[key]));
}

export function createSettingsForm(initial, families, modes, onEdit, initialExtensions = null) {
  const element = $("settings-form");
  const scalarKeys = Object.keys(initial).filter((key) => key !== "provider_options");
  let previousModel = initial.model;
  let previousFamily = initial.model_family;
  let extensionInfo = initialExtensions || {
    available: false, error: "", extensions: [], excluded: [], providers: [], options: [], draft_options: {},
  };
  let providerValues = { ...(initial.provider_options || {}) };

  $("model_family").replaceChildren(...Object.entries(families).map(([id, family]) => option(family.label, id)));

  function readProviderOptions() {
    const result = {};
    const container = $("extension-options-list");
    if (!container) return { ...providerValues };
    const inputs = container.querySelectorAll("[data-provider-option]");
    for (const input of inputs) {
      const flag = input.dataset.providerOption;
      const kind = input.dataset.providerType;
      if (kind === "boolean") {
        if (input.checked) result[flag] = true;
      } else if (kind === "integer" || kind === "number") {
        const raw = input.value.trim();
        if (raw === "") continue;
        const parsed = input.valueAsNumber;
        if (Number.isFinite(parsed)) result[flag] = kind === "integer" && Number.isInteger(parsed) ? parsed : parsed;
        else result[flag] = raw;
      } else {
        const raw = input.value.trim();
        if (raw !== "") result[flag] = raw;
      }
    }
    return Object.fromEntries(Object.keys(result).sort().map((key) => [key, result[key]]));
  }

  function values() {
    const data = Object.fromEntries(scalarKeys.map((key) => {
      const input = $(key);
      return [key, input.type === "checkbox" ? input.checked : input.type === "number" ? input.valueAsNumber : input.value];
    }));
    data.provider_options = readProviderOptions();
    return data;
  }

  function choices(id, entries, value) {
    $(id).replaceChildren(...entries.map(([key, label]) => option(label, key)));
    $(id).value = value;
  }

  function renderExtensionSummary() {
    const summary = $("extensions-summary");
    const warning = $("extensions-warning");
    if (!summary || !warning) return;
    if (!extensionInfo || !extensionInfo.available) {
      text(summary, "Extensions: unavailable");
      summary.title = extensionInfo?.error || "";
      warning.hidden = true;
      return;
    }
    const all = extensionInfo.extensions || [];
    const loaded = all.filter((item) => item.status === "ready");
    const extra = loaded.filter((item) => item.installed || !item.builtin).map((item) => item.name);
    if (extra.length) {
      text(summary, "Extensions: {count} loaded ({names})", { count: loaded.length, names: extra.join(", ") });
    } else {
      text(summary, "Extensions: {count} loaded", { count: loaded.length });
    }
    summary.title = loaded.map((item) => `${item.name}${item.version ? ` ${item.version}` : ""}`).join(", ");
    const outdated = all.filter((item) => item.status === "needs update").map((item) => item.name);
    if (outdated.length) {
      text(warning, "Extension modules need update after rebuilding Gufo: {names}. Run gufo extension update.", {
        names: outdated.join(", "),
      });
      warning.hidden = false;
    } else {
      warning.hidden = true;
    }
  }

  function renderProviderOptions() {
    const section = $("extension-options-section");
    const list = $("extension-options-list");
    if (!section || !list) return;
    const known = extensionInfo?.options || [];
    const knownFlags = new Set(known.map((opt) => opt.name));
    const unknownFlags = Object.keys(providerValues).filter((flag) => !knownFlags.has(flag)).sort();
    const items = [
      ...known.map((opt) => ({ ...opt, unknown: false })),
      ...unknownFlags.map((flag) => ({
        name: flag,
        type: typeof providerValues[flag] === "boolean" ? "boolean"
          : typeof providerValues[flag] === "number"
            ? (Number.isInteger(providerValues[flag]) ? "integer" : "number") : "string",
        help: "",
        providers: [],
        extensions: [],
        draft_mode: "",
        unknown: true,
      })),
    ];

    section.hidden = items.length === 0;
    const nodes = items.map((opt, index) => {
      const row = document.createElement("div");
      row.className = "ext-option";
      const inputId = `provider-opt-${index}`;
      const saved = providerValues[opt.name];

      if (opt.type === "boolean") {
        const label = document.createElement("label");
        label.className = "check-label";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.id = inputId;
        input.dataset.providerOption = opt.name;
        input.dataset.providerType = "boolean";
        input.checked = saved === true;
        const code = document.createElement("code");
        code.textContent = opt.name;
        label.append(input, code);
        appendOptionBadges(label, opt);
        row.append(label);
      } else {
        const head = document.createElement("div");
        head.className = "ext-option-head";
        const label = document.createElement("label");
        label.htmlFor = inputId;
        const code = document.createElement("code");
        code.textContent = opt.name;
        label.append(code);
        appendOptionBadges(label, opt);
        head.append(label);
        if (opt.unknown) {
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "quiet ext-remove";
          text(remove, "Remove");
          remove.addEventListener("click", () => {
            delete providerValues[opt.name];
            renderProviderOptions();
            update();
            onEdit();
          });
          head.append(remove);
        }
        row.append(head);

        const input = document.createElement("input");
        input.id = inputId;
        input.dataset.providerOption = opt.name;
        input.dataset.providerType = opt.type;
        if (opt.type === "integer" || opt.type === "number") {
          input.type = "number";
          input.step = opt.type === "integer" ? "1" : "any";
          input.value = saved === undefined || saved === null ? "" : String(saved);
        } else {
          input.type = "text";
          input.spellcheck = false;
          input.value = saved === undefined || saved === null ? "" : String(saved);
        }

        if (opt.type === "path") {
          const pathRow = document.createElement("div");
          pathRow.className = "path-row";
          const browse = document.createElement("button");
          browse.type = "button";
          browse.dataset.browse = inputId;
          browse.dataset.kind = "path";
          browse.setAttribute("aria-label", opt.name);
          text(browse, "Choose");
          pathRow.append(input, browse);
          row.append(pathRow);
          const preview = document.createElement("p");
          preview.id = `${inputId}-filename`;
          preview.className = "selected-file";
          row.append(preview);
        } else {
          row.append(input);
        }
      }

      if (opt.help) {
        const hint = document.createElement("p");
        hint.className = "hint";
        rawText(hint, opt.help);
        row.append(hint);
      } else if (opt.unknown) {
        const hint = document.createElement("p");
        hint.className = "hint";
        text(hint, "Saved on this preset, but not reported by the selected Gufo executable.");
        row.append(hint);
      }
      return row;
    });
    list.replaceChildren(...nodes);
  }

  function appendOptionBadges(container, opt) {
    const owners = opt.extensions?.length ? opt.extensions : opt.providers;
    if (owners?.length) {
      const badge = document.createElement("span");
      badge.className = "tag ext-provider-tag";
      badge.textContent = owners.join(", ");
      container.append(badge);
    }
    if (opt.unknown) {
      const badge = document.createElement("span");
      badge.className = "tag ext-unknown-tag";
      text(badge, "Unavailable");
      container.append(badge);
    }
  }

  function update() {
    const family = families[$("model_family").value];
    const mode = $("speculative").value;
    for (const [id, spec] of Object.entries(modes)) {
      if (spec.file_field) document.querySelector(`[data-speculative-file="${spec.file_field}"]`).hidden = mode !== id;
      if (spec.options_id) {
        $(spec.options_id).hidden = mode !== id;
        $(spec.options_id).disabled = mode !== id;
      }
    }
    $("reasoning_effort").disabled = $("think").value === "off";
    $("reasoning_budget").disabled = $("think").value === "off";
    $("cache_ram_gib").disabled = $("cache_ram_off").checked;
    $("disk-cache-options").disabled = !$("cache_disk").checked;
    text($("family-hint"), family.hint);
    text($("mmproj-hint"), family.projector_hint || "Leave blank for Gufo to auto-detect a compatible projector.");
    text($("think").querySelector('[value="off"]'), family.thinking_off_label || "Off");
    text($("thinking-hint"), family.thinking_hint || "Auto uses the model default. Clients can override the level per request. The level is ignored while Thinking is Off.");
    $("family-defaults").hidden = !Object.keys(family.defaults).length;
    for (const key of ["model", "mtp_model", "dflash_model", "dspark_model", "mmproj"]) {
      $(key).title = $(key).value;
      $(`${key}-filename`).textContent = $(key).value.split(/[\\/]/).pop();
    }
    for (const input of element.querySelectorAll('[data-provider-type="path"]')) {
      input.title = input.value;
      const preview = $(`${input.id}-filename`);
      if (preview) preview.textContent = input.value.split(/[\\/]/).pop();
    }
  }

  function apply(settings) {
    const family = families[settings.model_family];
    choices("speculative", family.speculative.map((id) => [id, modes[id].label]), settings.speculative);
    choices("reasoning_effort", family.reasoning_effort.map((id) => [id, id === "auto" ? "Auto (model default)" : id]), settings.reasoning_effort);
    for (const key of scalarKeys) {
      if ($(key).type === "checkbox") $(key).checked = settings[key];
      else $(key).value = settings[key];
    }
    providerValues = { ...(settings.provider_options || {}) };
    renderProviderOptions();
    previousModel = settings.model;
    previousFamily = settings.model_family;
    update();
  }

  function setExtensions(info) {
    providerValues = readProviderOptions();
    extensionInfo = info || {
      available: false, error: "", extensions: [], excluded: [], providers: [], options: [], draft_options: {},
    };
    renderExtensionSummary();
    renderProviderOptions();
    update();
  }

  function edited() {
    if ($("model").value !== previousModel) {
      for (const key of ["mtp_model", "dflash_model", "dspark_model", "mmproj"]) $(key).value = "";
      $("speculative").value = "off";
      const draftFlags = Object.keys(extensionInfo?.draft_options || {});
      for (const flag of draftFlags) {
        const input = element.querySelector(`[data-provider-option="${flag}"]`);
        if (input) {
          if (input.type === "checkbox") input.checked = false;
          else input.value = "";
        }
      }
      previousModel = $("model").value;
    }
    providerValues = readProviderOptions();
    if ($("model_family").value !== previousFamily) {
      const settings = values();
      const family = families[settings.model_family];
      if (!family.speculative.includes(settings.speculative)) settings.speculative = "off";
      if (!family.reasoning_effort.includes(settings.reasoning_effort)) settings.reasoning_effort = "auto";
      apply(settings);
    }
    update();
    onEdit();
  }

  element.addEventListener("input", edited);
  element.addEventListener("change", edited);
  $("family-defaults").addEventListener("click", () => {
    apply({ ...values(), ...families[$("model_family").value].defaults });
    onEdit();
  });
  renderExtensionSummary();
  apply(initial);
  return { values, apply, setExtensions, valid() {
    if (element.checkValidity()) return true;
    const input = element.querySelector("input:invalid, select:invalid");
    const label = input.labels?.[0];
    const field = input.dataset.providerOption
      || label?.dataset.i18n || label?.querySelector("[data-i18n]")?.dataset.i18n || input.id;
    const message = input.validity.valueMissing ? "{field}: enter a value."
      : input.validity.rangeUnderflow || input.validity.rangeOverflow
        ? "{field}: enter a number from {low} to {high}."
        : "{field}: enter a valid value.";
    // Keep the source message so an existing notice follows language changes.
    throw Object.assign(new Error(message), { i18nValues: { field, low: input.min, high: input.max } });
  } };
}
