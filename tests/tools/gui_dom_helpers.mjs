import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const root = fileURLToPath(new URL("../../", import.meta.url));
const require = createRequire(path.join(root, "build/gui-test-js/package.json"));
const { JSDOM } = require("jsdom");
const python = process.env.GUI_TEST_PYTHON || path.join(root, process.platform === "win32"
  ? "build/gui-env/Scripts/python.exe" : "build/gui-env/bin/python");
const fixture = JSON.parse(execFileSync(python, ["-c", `
import json, re, sys, tempfile, threading
from pathlib import Path
sys.path.insert(0, 'tools/gui')
from server import create_app
from launcher_process import ProcessManager
with tempfile.TemporaryDirectory() as directory:
    app = create_app(Path(directory) / 'settings.json', ProcessManager(), threading.Event())
    client = app.test_client()
    html = client.get('/').text
    token = re.search('name="gufo-token" content="([^"]+)"', html)[1]
    initial = client.get('/api/settings', headers={'X-Gufo-Token': token}).json
    print(json.dumps({'html': html, 'initial': initial}))
`], { cwd: root, encoding: "utf8" }));

export async function setup(t, language = "en") {
  const dom = new JSDOM(fixture.html, { url: "http://localhost/", runScripts: "outside-only" });
  t.after(() => dom.window.close());
  const { window } = dom;
  if (language) window.localStorage.setItem("gufo.language", language);
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function (value = this.returnValue) {
    this.returnValue = value; this.open = false; this.dispatchEvent(new window.Event("close"));
  };
  const modules = new Map();
  async function load(name) {
    if (modules.has(name)) return modules.get(name);
    const module = readFile(path.join(root, "tools/gui/static", name), "utf8").then((code) =>
      new vm.SourceTextModule(code, { context: dom.getInternalVMContext(), identifier: name }));
    modules.set(name, module);
    return module;
  }
  async function use(name) {
    const module = await load(name);
    if (module.status === "unlinked") await module.link((specifier) => load(specifier.replace(/^\.\//, "")));
    if (module.status !== "evaluated") await module.evaluate();
    return module.namespace;
  }
  return { window, use, $: (id) => window.document.getElementById(id),
           initial: structuredClone(fixture.initial) };
}

export function edit(env, id, value) {
  env.$(id).value = value;
  env.$(id).dispatchEvent(new env.window.Event("input", { bubbles: true }));
  env.$(id).dispatchEvent(new env.window.Event("change", { bubbles: true }));
}
export const tick = () => new Promise((resolve) => setImmediate(resolve));

