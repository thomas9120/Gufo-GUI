import assert from "node:assert/strict";
import test from "node:test";
import { setup, edit, tick } from "./gui_dom_helpers.mjs";

test("engine identity uses reported props and clears missing or stale capabilities", async (t) => {
  const env = await setup(t);
  const { createRuntime } = await env.use("runtime.js");
  const { setLanguage } = await env.use("i18n.js");
  const runtime = createRuntime(() => {});
  edit(env, "model", "C:/models/next.gguf");
  edit(env, "context", "32768");
  const ready = { state: "ready", pid: 123, logs: [], model_name: "gufo", props: {
    model_path: "C:/models/<loaded>&.gguf", build_info: "actual-revision-dirty",
    default_generation_settings: { n_ctx: 8192 }, modalities: { vision: true },
  } };
  runtime.render(ready);
  assert.equal(env.$("loaded-model-path").textContent, ready.props.model_path);
  assert.equal(env.$("loaded-model-path").children.length, 0);
  assert.equal(env.$("build-revision").textContent, "actual-revision-dirty");
  assert.equal(env.$("effective-context").textContent, "8,192");
  assert.equal(env.$("vision-chip").textContent, "Vision: on");
  assert.ok(env.$("vision-chip").classList.contains("ready"));
  setLanguage("zh-CN");
  assert.equal(env.$("vision-chip").textContent, "视觉：开启");
  assert.equal(env.$("loaded-model-path").textContent, ready.props.model_path);
  setLanguage("en");
  runtime.render({ ...ready, props: { modalities: { vision: false } } });
  assert.equal(env.$("vision-chip").textContent, "Vision: off");
  assert.equal(env.$("build-revision").textContent, "—");
  assert.equal(env.$("effective-context").textContent, "—");
  for (const props of [null, {}, { model_path: 42, build_info: {},
    default_generation_settings: { n_ctx: 0 }, modalities: { vision: "true" } }]) {
    runtime.render({ ...ready, props });
    assert.equal(env.$("loaded-model-path").textContent, "—");
    assert.equal(env.$("vision-chip").textContent, "Vision: —");
  }
  for (const state of ["loading", "stopping", "stopped", "failed"]) {
    runtime.render({ ...ready, state });
    assert.equal(env.$("build-revision").textContent, "—");
    assert.equal(env.$("vision-chip").textContent, "Vision: —");
  }
  runtime.render(ready);
  env.window.fetch = async () => { throw new Error("offline"); };
  await runtime.poll();
  assert.equal(env.$("vision-chip").textContent, "Vision: —");
  assert.equal(runtime.state.props, null);
  runtime.render(ready);
  runtime.close();
  assert.equal(env.$("loaded-model-path").textContent, "—");
});

test("busy confirmation handles queued work, escape, repeated openings, and language changes", async (t) => {
  const env = await setup(t);
  const { confirmBusyAction } = await env.use("busy-actions.js");
  const { setLanguage } = await env.use("i18n.js");
  const state = { state: "ready", metrics: { requests_processing: 1, requests_deferred: 2 } };
  const pending = confirmBusyAction(state, "stop");
  assert.equal(env.$("busy-dialog").open, true);
  assert.equal(env.$("busy-processing").textContent, "1 request is generating.");
  assert.equal(env.$("busy-queued").textContent, "2 requests are queued.");
  assert.ok(env.$("busy-dialog").querySelector('[value="cancel"]').autofocus);
  setLanguage("zh-CN");
  assert.equal(env.$("busy-processing").textContent, "1 个请求正在生成。");
  assert.equal(env.$("busy-confirm").textContent, "仍要停止");
  // Escape closes a native dialog without replacing its default returnValue.
  env.$("busy-dialog").close();
  assert.equal(await pending, false);
  setLanguage("en");
  const queued = confirmBusyAction({ ...state, metrics: { requests_processing: 0, requests_deferred: 1 } }, "exit");
  assert.equal(env.$("busy-processing").hidden, true);
  assert.equal(env.$("busy-queued").textContent, "1 request is queued.");
  assert.equal(env.$("busy-title").textContent, "Exit launcher anyway?");
  env.$("busy-dialog").close("confirm");
  assert.equal(await queued, true);
  const again = confirmBusyAction(state, "stop");
  env.$("busy-dialog").close();
  assert.equal(await again, false);
  for (const idle of [{ state: "stopped", metrics: state.metrics }, { state: "ready", metrics: null },
    { state: "ready", metrics: { requests_processing: 0, requests_deferred: 0 } },
    { state: "ready", metrics: { prefill_tps: 800 } }]) {
    assert.equal(await confirmBusyAction(idle, "stop"), true);
    assert.equal(env.$("busy-dialog").open, false);
  }
});

test("Stop and Exit send no destructive request until confirmed and idle actions proceed directly", async (t) => {
  for (const action of ["stop", "exit"]) {
    await t.test(action, async (t) => {
      const env = await setup(t);
      const requests = [];
      const state = { state: "ready", pid: 123, logs: [],
        metrics: { requests_processing: 1, requests_deferred: 0 } };
      env.window.fetch = async (url) => {
        requests.push(url);
        const response = url === "/api/settings" ? structuredClone(env.initial)
          : url === "/api/status" ? state : url === "/api/preview" ? { command: "gufo" }
          : url === "/api/stop" ? { state: "stopped", pid: null, logs: [] }
          : url === "/api/exit" ? { stopped: true } : assert.fail(`Unexpected request ${url}`);
        return { ok: true, json: async () => response };
      };
      await env.use("app.js"); await tick();
      env.$(`${action}-button`).click(); await tick();
      env.$(`${action}-button`).click(); await tick();
      assert.equal(env.$("busy-dialog").open, true);
      assert.equal(requests.includes(`/api/${action}`), false);
      env.$("busy-dialog").close("cancel"); await tick();
      assert.equal(requests.includes(`/api/${action}`), false);
      assert.equal(env.$(`${action}-button`).disabled, false);
      env.$(`${action}-button`).click(); await tick();
      env.$("busy-dialog").close("confirm"); await tick();
      assert.equal(requests.filter((url) => url === `/api/${action}`).length, 1);
      if (action === "stop") {
        env.$("exit-button").click(); await tick();
        assert.equal(env.$("busy-dialog").open, false);
        assert.equal(requests.filter((url) => url === "/api/exit").length, 1);
      }
      assert.equal(env.$("status").textContent, "Launcher closed");
    });
  }
});

test("performance distinguishes live rates, completed speeds, legacy engines, and disconnects", async (t) => {
  const env = await setup(t);
  const { createRuntime } = await env.use("runtime.js");
  const runtime = createRuntime(() => {});
  const metrics = { prefill_tps: 800, generation_tps: 25.5, prompt_tokens_total: 100,
    generated_tokens_total: 20, requests_processing: 1, requests_deferred: 2,
    live_prefill_tps: 0, live_generation_tps: 19.5 };
  const ready = { state: "ready", logs: [], pid: 123, metrics };
  runtime.render(ready);
  assert.equal(env.$("live-prefill-speed").textContent, "0.0");
  assert.equal(env.$("live-generation-speed").textContent, "19.5");
  assert.equal(env.$("prefill-speed").textContent, "800.0");
  assert.equal(env.$("generation-speed").textContent, "25.5");
  assert.equal(env.$("prompt-total").textContent, "100");
  assert.equal(env.$("requests-processing").textContent, "1");
  assert.equal(env.$("requests-deferred").textContent, "2");
  assert.match(env.$("metrics-detail").textContent, /exclude cached tokens/);
  runtime.render({ ...ready, metrics: { ...metrics, prompt_seconds_total: 0.125 } });
  assert.match(env.$("metrics-detail").textContent, /prefill uses measured processing time/);
  assert.equal(env.$("live-prefill-speed").textContent, "0.0");
  runtime.render({ ...ready, metrics: { ...metrics, prompt_tokens_total: 0,
    generated_tokens_total: 0, requests_processing: 0, requests_deferred: 2 } });
  assert.match(env.$("metrics-note").textContent, /Live totals/);
  runtime.render({ ...ready, metrics: { ...metrics, live_prefill_tps: null, live_generation_tps: null } });
  assert.equal(env.$("live-generation-speed").textContent, "—");
  assert.equal(env.$("generation-speed").textContent, "25.5");
  runtime.render({ ...ready, metrics: { ...metrics, requests_processing: 0, requests_deferred: 0,
    live_prefill_tps: 0, live_generation_tps: 0 } });
  assert.equal(env.$("live-generation-speed").textContent, "—");
  assert.equal(env.$("live-prefill-speed").textContent, "—");
  assert.equal(env.$("generation-speed").textContent, "25.5");
  assert.equal(env.$("prompt-total").textContent, "100");
  assert.equal(env.$("requests-processing").textContent, "0");
  runtime.render({ ...ready, metrics: { prefill_tps: 800, generation_tps: 25.5,
    prompt_tokens_total: 100, generated_tokens_total: 20 } });
  assert.equal(env.$("requests-processing").textContent, "—");
  assert.equal(env.$("live-generation-speed").textContent, "—");
  assert.equal(env.$("generation-speed").textContent, "25.5");
  assert.match(env.$("metrics-note").textContent, /Update the Gufo executable/);
  assert.match(env.$("metrics-detail").textContent, /includes cached prompt tokens/);
  runtime.render({ ...ready, metrics: null });
  assert.match(env.$("metrics-note").textContent, /Retrying/);
  for (const state of ["loading", "stopped", "disconnected"]) {
    runtime.render({ ...ready, state });
    for (const id of ["live-prefill-speed", "live-generation-speed", "prefill-speed", "generation-speed",
      "prompt-total", "generated-total", "requests-processing", "requests-deferred"])
      assert.equal(env.$(id).textContent, "—");
  }
});

