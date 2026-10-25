import { text, option } from "./i18n.js";
import { $ } from "./api.js";

export function sameSettings(left, right) {
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => left[key] === right[key]);
}

export function createSettingsForm(initial, families, modes, onEdit) {
  const element = $("settings-form");
  const keys = Object.keys(initial);
  let previousModel = initial.model;
  let previousFamily = initial.model_family;
  $("model_family").replaceChildren(...Object.entries(families).map(([id, family]) => option(family.label, id)));

  function values() {
    return Object.fromEntries(keys.map((key) => {
      const input = $(key);
      return [key, input.type === "checkbox" ? input.checked : input.type === "number" ? input.valueAsNumber : input.value];
    }));
  }

  function choices(id, entries, value) {
    $(id).replaceChildren(...entries.map(([key, label]) => option(label, key)));
    $(id).value = value;
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
    $("disk-cache-options").disabled = !$("cache_disk").checked;
    text($("family-hint"), family.hint);
    $("family-defaults").hidden = !Object.keys(family.defaults).length;
    for (const key of ["model", "mtp_model", "dflash_model", "mmproj"]) {
      $(key).title = $(key).value;
      $(`${key}-filename`).textContent = $(key).value.split(/[\\/]/).pop();
    }
  }

  function apply(settings) {
    const family = families[settings.model_family];
    choices("speculative", family.speculative.map((id) => [id, modes[id].label]), settings.speculative);
    choices("reasoning_effort", family.reasoning_effort.map((id) => [id, id === "auto" ? "Auto (model default)" : id]), settings.reasoning_effort);
    for (const key of keys) {
      if ($(key).type === "checkbox") $(key).checked = settings[key];
      else $(key).value = settings[key];
    }
    previousModel = settings.model;
    previousFamily = settings.model_family;
    update();
  }

  function edited() {
    if ($("model").value !== previousModel) {
      for (const key of ["mtp_model", "dflash_model", "mmproj"]) $(key).value = "";
      $("speculative").value = "off";
      previousModel = $("model").value;
    }
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
  apply(initial);
  return { values, apply, valid() {
    if (element.checkValidity()) return true;
    const input = element.querySelector("input:invalid, select:invalid");
    const label = input.labels?.[0];
    const field = label?.dataset.i18n || label?.querySelector("[data-i18n]")?.dataset.i18n || input.id;
    const message = input.validity.valueMissing ? "{field}: enter a value."
      : input.validity.rangeUnderflow || input.validity.rangeOverflow
        ? "{field}: enter a number from {low} to {high}."
        : "{field}: enter a valid value.";
    // Keep the source message so an existing notice follows language changes.
    throw Object.assign(new Error(message), { i18nValues: { field, low: input.min, high: input.max } });
  } };
}
