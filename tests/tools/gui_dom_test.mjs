// npm install --prefix build/gui-test-js --no-save --package-lock=false jsdom@26.1.0
// node --experimental-vm-modules --test tests/tools/gui_dom_test.mjs
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { setup, edit, tick } from "./gui_dom_helpers.mjs";
import "./gui_runtime_dom_test.mjs";

test("English is the initial language and Chinese static UI strings have translations", async (t) => {
  const env = await setup(t, null);
  const { initLanguage, setLanguage, locale } = await env.use("i18n.js");
  const { messages } = await env.use("locales/zh-CN.js");
  for (const element of env.window.document.querySelectorAll("*")) {
    for (const attribute of element.attributes) {
      if (attribute.name === "data-i18n" || attribute.name.startsWith("data-i18n-")) {
        assert.ok(Object.hasOwn(messages, attribute.value), `Untranslated string: ${attribute.value}`);
      }
    }
  }
  initLanguage();
  assert.equal(locale(), "en");
  assert.equal(env.window.document.documentElement.lang, "en");
  assert.equal(env.$("language-select").value, "en");
  setLanguage("zh-CN");
  assert.equal(locale(), "zh-CN");
  assert.equal(env.window.document.documentElement.lang, "zh-CN");
  assert.equal(env.$("files-heading").textContent, "模型文件");
  assert.equal(env.$("model").placeholder, "选择模型文件或第一个分片");
  assert.equal(env.$("language-select").getAttribute("aria-label"), "界面语言");
  setLanguage("en");
  assert.equal(env.window.document.title, "Gufo · Local launcher");
  assert.equal(env.window.localStorage.getItem("gufo.language"), "en");
});

test("saved language is restored and invalid or blocked storage falls back to English", async (t) => {
  for (const [saved, expected] of [["zh-CN", "zh-CN"], ["en", "en"], ["invalid", "en"]]) {
    const env = await setup(t, saved);
    const { initLanguage, locale } = await env.use("i18n.js");
    initLanguage();
    assert.equal(locale(), expected);
    assert.equal(env.$("language-select").value, expected);
  }
  const env = await setup(t, null);
  Object.defineProperty(env.window, "localStorage", { get() { throw new Error("Storage blocked"); } });
  const { initLanguage, setLanguage, locale } = await env.use("i18n.js");
  initLanguage();
  assert.equal(locale(), "en");
  setLanguage("zh-CN");
  assert.equal(env.$("files-heading").textContent, "模型文件");
  setLanguage("unsupported");
  assert.equal(locale(), "zh-CN");
  setLanguage("en");
  assert.equal(env.$("files-heading").textContent, "Model files");
});

test("translations preserve placeholders and unknown source messages", async (t) => {
  const env = await setup(t, "zh-CN");
  const { messages } = await env.use("locales/zh-CN.js");
  const { t: translate } = await env.use("i18n.js");
  for (const [source, translated] of Object.entries(messages)) {
    assert.deepEqual((translated.match(/\{\w+\}/g) || []).sort(),
      (source.match(/\{\w+\}/g) || []).sort(), source);
  }
  for (const message of ["Unknown engine error", "constructor", "toString", "__proto__"])
    assert.equal(translate(message), message);
});

test("theme button labels follow both theme and language changes", async (t) => {
  const env = await setup(t);
  env.window.matchMedia = () => ({ matches: false, addEventListener() {} });
  env.window.eval(await readFile(new URL("../../tools/gui/static/theme.js", import.meta.url), "utf8"));
  env.window.document.dispatchEvent(new env.window.Event("DOMContentLoaded"));
  const { initLanguage, setLanguage } = await env.use("i18n.js");
  initLanguage();
  const toggle = env.$("theme-toggle");
  assert.equal(toggle.getAttribute("aria-label"), "Switch to the dark theme");
  setLanguage("zh-CN");
  assert.equal(toggle.getAttribute("aria-label"), "切换为深色主题");
  toggle.click();
  assert.equal(toggle.getAttribute("aria-pressed"), "true");
  assert.equal(toggle.getAttribute("aria-label"), "切换为浅色主题");
  setLanguage("en");
  assert.equal(toggle.getAttribute("aria-label"), "Switch to the light theme");
  toggle.click();
  assert.equal(toggle.getAttribute("aria-label"), "Switch to the dark theme");
});

test("validation notices switch languages without saving or losing invalid drafts", async (t) => {
  const env = await setup(t, "zh-CN");
  const requests = [];
  env.window.fetch = async (url) => {
    requests.push(url);
    const response = url === "/api/settings" ? structuredClone(env.initial)
      : url === "/api/status" ? { state: "stopped", logs: [], pid: null }
      : url === "/api/preview" ? { command: "gufo" }
      : assert.fail(`Unexpected request ${url}`);
    return { ok: true, json: async () => response };
  };
  await env.use("app.js"); await tick();
  const { setLanguage } = await env.use("i18n.js");
  edit(env, "context", "");
  env.$("save-button").click(); await tick();
  assert.equal(env.$("notice").textContent, "上下文长度（token）：请填写此项。");
  setLanguage("en");
  assert.equal(env.$("notice").textContent, "Context tokens: enter a value.");
  assert.equal(env.$("context").value, "");
  edit(env, "context", "32768");
  edit(env, "temperature", "3");
  env.$("save-button").click(); await tick();
  assert.equal(env.$("notice").textContent, "Temperature: enter a number from 0 to 2.");
  setLanguage("zh-CN");
  assert.equal(env.$("notice").textContent, "温度（Temperature）：请输入 0 到 2 之间的数值。");
  assert.equal(env.$("temperature").value, "3");
  assert.equal(env.$("saved-state").textContent, "有未保存的更改");
  assert.ok(requests.every((url) => ["/api/settings", "/api/status", "/api/preview"].includes(url)));
});

test("language switching preserves drafts, sidecars, pending choices, and literal user names", async (t) => {
  const env = await setup(t, "zh-CN");
  const { initLanguage, setLanguage } = await env.use("i18n.js");
  const { createSettingsForm } = await env.use("settings-form.js");
  const { createPresets } = await env.use("presets.js");
  initLanguage();
  const name = '中文预设 <img src=x> {name}';
  env.initial.document.presets[0].name = name;
  env.initial.document.presets.push({ ...env.initial.document.presets[0], id: "second", name: "第二个" });
  const form = createSettingsForm(env.initial.settings, env.initial.families, env.initial.modes, () => {});
  form.apply({ ...env.initial.settings, model_family: "qwen38_27b", speculative: "dflash2",
    model: "C:\\中文模型\\主模型.gguf", dflash_model: "C:\\中文模型\\草稿.gguf", temperature: 0.42 });
  const presets = createPresets(env.initial, form, () => {}, () => {});
  presets.render();
  edit(env, "preset-select", "second");
  presets.render();
  const before = JSON.stringify(form.values());
  setLanguage("en");
  setLanguage("zh-CN");
  assert.equal(JSON.stringify(form.values()), before);
  assert.equal(presets.dirty(), true);
  assert.equal(env.$("preset-select").value, "second");
  assert.equal(env.$("loaded-preset").textContent, `当前预设：${name}`);
  assert.equal(env.$("loaded-preset").querySelector("img"), null);
  assert.equal(env.$("speculative").options[0].text, "关闭");
});

test("Chinese errors, running state, and metrics retain data across language changes", async (t) => {
  const env = await setup(t, "zh-CN");
  const { t: translate, initLanguage, setLanguage } = await env.use("i18n.js");
  const { createRuntime } = await env.use("runtime.js");
  initLanguage();
  assert.equal(translate("context: enter a whole number from 0 to 99."), "上下文长度：请输入 0 到 99 之间的整数。");
  assert.equal(translate("Port 8080 is already in use. Choose another port."), "端口 8080 已被占用，请选择其他端口。");
  assert.equal(translate("Model: select an existing GGUF file."), "主模型：请选择实际存在的 GGUF 文件。");
  assert.equal(translate("Unrecognized engine message: untouched"), "Unrecognized engine message: untouched");
  const runtime = createRuntime(() => {});
  runtime.render({ state: "ready", pid: 123, logs: ["raw engine log"], model_name: "中文-model",
    running: { preset_name: "中文预设", modified: true }, metrics: {
      prefill_tps: 100, generation_tps: 50, prompt_tokens_total: 24, generated_tokens_total: 12,
    } });
  assert.equal(env.$("running-preset").textContent, "运行中：中文预设（含未保存的更改）");
  assert.equal(env.$("status").textContent, "已就绪");
  assert.match(env.$("metrics-note").textContent, /当前引擎/);
  setLanguage("en");
  assert.equal(env.$("running-preset").textContent, "Running: 中文预设 (modified)");
  assert.equal(env.$("logs").textContent, "raw engine log");
});

test("a language switch does not remove file picker entries or translate file names", async (t) => {
  const env = await setup(t, "zh-CN");
  const { initLanguage, setLanguage } = await env.use("i18n.js");
  const { initFilePicker } = await env.use("file-picker.js");
  initLanguage();
  env.window.fetch = async () => ({ ok: true, json: async () => ({ path: "C:\\模型", parent: "C:\\",
    roots: ["C:\\用户"], entries: [{ name: "中文模型.gguf", path: "C:\\模型\\中文模型.gguf", directory: false, shards: 4 }] }) });
  initFilePicker("C:\\用户");
  env.window.document.querySelector('[data-browse="model"]').click(); await tick();
  setLanguage("en");
  assert.match(env.$("picker-entries").textContent, /中文模型.gguf/);
  assert.match(env.$("picker-entries").textContent, /4 shards/);
  setLanguage("zh-CN");
  assert.match(env.$("picker-entries").textContent, /4 个分片/);
});

test("restoring a preset keeps sidecars; changing its model clears them", async (t) => {
  const env = await setup(t);
  const { createSettingsForm } = await env.use("settings-form.js");
  const { settings, families, modes } = env.initial;
  const form = createSettingsForm(settings, families, modes, () => {});
  const values = { ...settings, model_family: "qwen38_flash_next", model: "C:\\main.gguf",
    mtp_model: "C:\\draft.gguf", mmproj: "C:\\mmproj.gguf", speculative: "mtp", temperature: 0.42 };
  form.apply(values);
  assert.equal(form.values().mtp_model, values.mtp_model);
  assert.equal(form.values().mmproj, values.mmproj);
  assert.equal(env.$("mtp-options").hidden, false);
  edit(env, "model_family", "qwen38_27b");
  assert.equal(form.values().speculative, "off");
  assert.equal(form.values().temperature, 0.42);
  assert.deepEqual(Array.from(env.$("speculative").options, (option) => option.value), ["off", "dflash2"]);
  form.apply(values);
  edit(env, "model", "C:\\different.gguf");
  for (const key of ["mtp_model", "dflash_model", "mmproj"]) assert.equal(form.values()[key], "");
  assert.equal(form.values().speculative, "off");
});

test("reasoning preservation and disk caching restore independently of thinking", async (t) => {
  const env = await setup(t);
  const { createSettingsForm } = await env.use("settings-form.js");
  const { settings, families, modes } = env.initial;
  const form = createSettingsForm(settings, families, modes, () => {});
  assert.equal(env.$("preserve_thinking").checked, true);
  assert.equal(env.$("cache_disk").checked, false);
  assert.equal(env.$("disk-cache-options").disabled, true);
  edit(env, "think", "off");
  assert.equal(env.$("preserve_thinking").disabled, false);
  env.$("preserve_thinking").click();
  env.$("cache_disk").click();
  assert.equal(form.values().preserve_thinking, false);
  assert.equal(form.values().cache_disk, true);
  assert.equal(env.$("disk-cache-options").disabled, false);
  edit(env, "cache_disk_dir", "");
  assert.throws(() => form.valid());
  edit(env, "cache_disk_dir", "C:\\cache folder");
  edit(env, "cache_disk_staging_gib", "8");
  const cached = form.values();
  form.apply(settings);
  assert.equal(env.$("disk-cache-options").disabled, true);
  assert.equal(env.$("preserve_thinking").checked, true);
  form.apply(cached);
  assert.equal(form.values().cache_disk_staging_gib, 8);
  assert.equal(env.$("preserve_thinking").checked, false);
  assert.equal(env.$("disk-cache-options").disabled, false);
});

test("preset switching supports cancel, discard, and save without starting the server", async (t) => {
  const env = await setup(t);
  const { createSettingsForm } = await env.use("settings-form.js");
  const { createPresets } = await env.use("presets.js");
  const { settings, families, modes } = env.initial;
  const document = env.initial.document;
  document.presets.push({ id: "second", name: "Second", settings: {
    ...document.presets[0].settings, context: 65536, model: "C:\\second.gguf",
    speculative: "mtp", mtp_model: "C:\\sidecar.gguf", mmproj: "C:\\projector.gguf",
  } });
  let presets;
  const form = createSettingsForm(settings, families, modes, () => presets?.render());
  const requests = [];
  env.window.fetch = async (url, options) => {
    requests.push([url, JSON.parse(options.body)]);
    const body = requests.at(-1)[1];
    assert.equal(url, "/api/presets");
    assert.equal(body.action, "save");
    document.presets[0].settings = { ...document.presets[0].settings, context: body.settings.context };
    document.revision++;
    return { ok: true, json: async () => ({ document: structuredClone(document) }) };
  };
  const errors = [];
  const action = async (fn) => { try { await fn(); } catch (error) { errors.push(error); } };
  presets = createPresets(env.initial, form, action, () => presets.render());
  presets.render();
  edit(env, "context", "8192");
  edit(env, "preset-select", "second");
  presets.render(); // Runtime refreshes must preserve the pending choice.
  assert.equal(env.$("preset-select").value, "second");
  assert.equal(presets.id, "default");
  assert.equal(form.values().context, 8192);
  assert.equal(env.$("unsaved-dialog").open, false);
  env.$("load-preset").click();
  assert.equal(env.$("unsaved-dialog").open, true);
  env.$("unsaved-dialog").close("cancel"); await tick();
  assert.equal(presets.id, "default");
  assert.equal(form.values().context, 8192);
  assert.equal(env.$("preset-select").value, "second");
  env.$("load-preset").click();
  env.$("unsaved-dialog").close("discard"); await tick();
  assert.equal(presets.id, "second");
  assert.equal(env.$("loaded-preset").textContent, "Loaded preset: Second");
  assert.equal(form.values().mtp_model, "C:\\sidecar.gguf");
  assert.equal(form.values().mmproj, "C:\\projector.gguf");
  assert.equal(presets.dirty(), false);
  edit(env, "preset-select", "default");
  env.$("load-preset").click(); await tick();
  edit(env, "context", "16384");
  edit(env, "preset-select", "second");
  env.$("load-preset").click();
  env.$("unsaved-dialog").close("save"); await tick();
  assert.equal(presets.id, "second");
  assert.equal(requests.length, 1);
  assert.equal(requests[0][1].id, "default");
  assert.equal(requests[0][1].settings.context, 16384);
  assert.equal(env.$("preset-select").value, "second");
  assert.deepEqual(errors, []);
});

test("file picker selection follows the same model-change rules", async (t) => {
  const env = await setup(t);
  const { createSettingsForm } = await env.use("settings-form.js");
  const { initFilePicker } = await env.use("file-picker.js");
  const form = createSettingsForm(env.initial.settings, env.initial.families, env.initial.modes, () => {});
  form.apply({ ...env.initial.settings, model: "C:\\old.gguf", mtp_model: "C:\\old-mtp.gguf", speculative: "mtp" });
  env.window.fetch = async () => ({ ok: true, json: async () => ({ path: "C:\\", parent: "C:\\", roots: ["C:\\"],
    entries: [{ name: "new.gguf", path: "C:\\new.gguf", directory: false, shards: 1 }] }) });
  initFilePicker("C:\\");
  env.window.document.querySelector('[data-browse="model"]').click(); await tick();
  env.$("picker-entries").querySelector("button").click();
  assert.equal(form.values().model, "C:\\new.gguf");
  assert.equal(form.values().mtp_model, "");
  assert.equal(form.values().speculative, "off");
  assert.equal(env.$("file-dialog").open, false);
});

test("runtime display reports the launch snapshot independently of form edits", async (t) => {
  const env = await setup(t);
  const { createRuntime } = await env.use("runtime.js");
  const runtime = createRuntime(() => {});
  edit(env, "host", "192.168.1.10");
  runtime.render({ state: "stopped", logs: [] });
  assert.equal(env.$("api-url").textContent, "http://192.168.1.10:8080/v1");
  edit(env, "host", "0.0.0.0");
  runtime.render({ state: "stopped", logs: [] });
  assert.equal(env.$("api-url").textContent, "http://127.0.0.1:8080/v1");
  const state = { state: "ready", pid: 123, logs: [], base_url: "http://127.0.0.1:8080/v1", model_name: "gufo",
    running: { preset_name: "Flash 32K", modified: true, settings: env.initial.settings } };
  runtime.render(state);
  edit(env, "host", "192.168.1.20");
  runtime.render(state);
  assert.equal(env.$("api-url").textContent, state.base_url);
  edit(env, "context", "65536");
  assert.equal(env.$("running-preset").textContent, "Running: Flash 32K (modified)");
  runtime.render({ ...state, state: "stopped", pid: null });
  assert.equal(env.$("running-preset").textContent, "Last launch: Flash 32K (modified)");
});

test("save as, rename, failed save, and delete keep the correct draft", async (t) => {
  const env = await setup(t);
  const { createSettingsForm } = await env.use("settings-form.js");
  const { createPresets } = await env.use("presets.js");
  const { settings, families, modes } = env.initial;
  let document = structuredClone(env.initial.document);
  let failSave = false, presets;
  const form = createSettingsForm(settings, families, modes, () => presets?.render());
  const errors = [];
  const action = async (fn) => { try { await fn(); } catch (error) { errors.push(error.message); } };
  env.window.fetch = async (url, options) => {
    assert.equal(url, "/api/presets");
    const body = JSON.parse(options.body);
    if (failSave) return { ok: false, json: async () => ({ error: "disk full" }) };
    if (body.action === "create") {
      const values = { ...body.settings };
      for (const key of ["executable", "models_dir", "port"]) delete values[key];
      document.presets.push({ id: "copy", name: body.name, settings: values });
      document.selected_preset = "copy";
    } else if (body.action === "rename") {
      document.presets[1].name = body.name;
    } else if (body.action === "delete") {
      document.presets.pop(); document.selected_preset = "default";
    } else assert.fail(`Unexpected action ${body.action}`);
    document.revision++;
    return { ok: true, json: async () => ({ document: structuredClone(document) }) };
  };
  presets = createPresets(env.initial, form, action, () => presets.render());
  presets.render();
  edit(env, "context", "8192");
  env.$("save-as-preset").click();
  env.$("preset-name").value = "Copy";
  env.$("preset-name-dialog").close("save"); await tick();
  assert.equal(presets.id, "copy");
  assert.equal(presets.dirty(), false);
  edit(env, "context", "16384");
  env.$("rename-preset").click();
  env.$("preset-name").value = "Renamed";
  env.$("preset-name-dialog").close("save"); await tick();
  assert.equal(form.values().context, 16384);
  assert.equal(presets.dirty(), true);
  assert.equal(env.$("preset-select").selectedOptions[0].textContent, "Renamed");
  failSave = true;
  env.$("save-button").click(); await tick();
  assert.equal(presets.dirty(), true);
  assert.equal(form.values().context, 16384);
  assert.deepEqual(errors, ["disk full"]);
  failSave = false;
  env.$("delete-preset").click();
  env.$("unsaved-dialog").close("discard"); await tick();
  env.$("delete-dialog").close("delete"); await tick();
  assert.equal(presets.id, "default");
  assert.equal(env.$("delete-preset").disabled, true);
  assert.equal(form.values().context, settings.context);
});


test("application initializes and previews edits without launching or saving", async (t) => {
  const env = await setup(t);
  env.initial.document.presets.push({ id: "second", name: "Second", settings: {
    ...env.initial.document.presets[0].settings, context: 65536,
  } });
  const requests = [];
  env.window.fetch = async (url, options) => {
    requests.push(url);
    const response = url === "/api/settings" ? structuredClone(env.initial)
      : url === "/api/status" ? { state: "stopped", logs: [], pid: null }
      : url === "/api/preview" ? { command: `gufo --context ${JSON.parse(options.body).context}` }
      : assert.fail(`Unexpected request ${url}`);
    return { ok: true, json: async () => response };
  };
  await env.use("app.js"); await tick();
  assert.equal(env.$("notice").textContent, "");
  assert.equal(env.$("settings-form").inert, false);
  assert.equal(env.$("start-button").disabled, false);
  assert.equal(env.$("preset-select").selectedOptions[0].textContent, "Default");
  edit(env, "context", "8192");
  edit(env, "preset-select", "second");
  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.equal(env.$("preset-select").value, "second");
  assert.equal(env.$("loaded-preset").textContent, "Loaded preset: Default");
  assert.equal(env.$("command").textContent, "gufo --context 8192");
  assert.equal(env.$("saved-state").textContent, "Unsaved changes");
  env.$("load-preset").click();
  assert.equal(env.$("unsaved-dialog").open, true);
  env.$("unsaved-dialog").close("discard"); await tick();
  assert.equal(env.$("settings-form").inert, false);
  assert.equal(env.$("preset-select").value, "second");
  assert.equal(env.$("loaded-preset").textContent, "Loaded preset: Second");
  assert.equal(env.$("context").value, "65536");
  await new Promise((resolve) => setTimeout(resolve, 300));
  assert.equal(env.$("command").textContent, "gufo --context 65536");
  assert.deepEqual([...new Set(requests)].sort(), ["/api/preview", "/api/settings", "/api/status"]);
});


test("RAM snapshot cap stays editable without disk caching and follows form settings", async (t) => {
  const env = await setup(t);
  const { createSettingsForm } = await env.use("settings-form.js");
  const form = createSettingsForm(env.initial.settings, env.initial.families, env.initial.modes, () => {});
  assert.equal(env.$("disk-cache-options").disabled, true);
  assert.equal(env.$("cache_ram_gib").matches(":disabled"), false);
  edit(env, "cache_ram_gib", "2");
  assert.equal(form.values().cache_ram_gib, 2);
  assert.equal(form.valid(), true);
  form.apply({ ...env.initial.settings, cache_ram_gib: 4 });
  assert.equal(env.$("cache_ram_gib").value, "4");
  edit(env, "cache_ram_gib", "-1");
  assert.throws(() => form.valid());
});
