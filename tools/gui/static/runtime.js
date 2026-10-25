import { text, rawText } from "./i18n.js";
import { $, api } from "./api.js";
import { renderMetrics } from "./runtime-metrics.js";
import { renderIdentity } from "./runtime-identity.js";

export function createRuntime(onChange) {
  let runtime = { state: "stopped" }, closed = false;

  function renderStatus(state) {
    runtime = state;
    renderMetrics(state);
    renderIdentity(state);
    const active = state.pid != null || ["loading", "ready", "stopping"].includes(state.state);
    const launch = state.running;
    text($("running-preset"), launch ? "{state}: {name}{modified}" : "", launch ? {
      state: active ? "Running" : "Last launch", name: launch.preset_name,
      modified: launch.modified ? " (modified)" : "",
    } : {});
    const title = state.state[0].toUpperCase() + state.state.slice(1);
    text($("status"), state.state === "loading" ? "{state} · {seconds}s" : title,
      { state: title, seconds: state.elapsed_seconds });
    $("status").className = `status ${state.state}`;
    const host = $("host").value.trim() || "127.0.0.1";
    $("api-url").textContent = state.base_url || `http://${host === "0.0.0.0" ? "127.0.0.1" : host}:${$("port").value || 8080}/v1`;
    text($("active-model"), state.model_name ? "Model: {name}" : "", { name: state.model_name });
    text($("runtime-note"), state.error || ({
      stopped: "Start Gufo to connect your OpenAI-compatible client.",
      loading: "Loading weights. This can take a few minutes; the process log shows progress.",
      ready: "Ready for requests · PID {pid}. Closing this tab keeps Gufo running.",
      stopping: "Stopping Gufo and releasing its GPU memory…",
    }[state.state] || "Check the process log."), { pid: state.pid });
    if (state.state === "failed") $("logs-details").open = true;
    const output = state.logs.join("\n") || "No process output yet.";
    if ($("logs").textContent !== output) {
      const atBottom = $("logs").scrollTop + $("logs").clientHeight >= $("logs").scrollHeight - 30;
      if (state.logs.length) rawText($("logs"), output); else text($("logs"), output);
      if (atBottom) $("logs").scrollTop = $("logs").scrollHeight;
    }
    onChange(state);
  }

  async function poll() {
    if (closed) return;
    try {
      const state = await api("status");
      if (!closed) renderStatus(state);
    } catch (error) {
      if (closed) return;
      text($("status"), "Disconnected");
      runtime = { ...runtime, state: "disconnected", metrics: null, props: null };
      renderMetrics(runtime);
      renderIdentity(runtime);
      $("status").className = "status failed";
      text($("runtime-note"), "Cannot reach the launcher. {detail}", { detail: error.message });
    }
    if (!closed) setTimeout(poll, 1000);
  }

  return {
    get state() { return runtime; },
    render: renderStatus,
    poll,
    close() {
      closed = true;
      renderMetrics({ state: "stopped" });
      renderIdentity({ state: "stopped" });
      text($("status"), "Launcher closed");
      $("status").className = "status stopped";
      text($("runtime-note"), "Gufo has stopped. You can close this tab.");
      text($("running-preset"), "");
    },
  };
}
