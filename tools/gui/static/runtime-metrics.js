import { text, locale } from "./i18n.js";
import { $ } from "./api.js";

export function renderMetrics(state) {
  const metrics = state.state === "ready" ? state.metrics : null;
  const idle = metrics?.requests_processing === 0 && metrics?.requests_deferred === 0;
  for (const [id, key, decimals, nonzero] of [
    ["live-prefill-speed", "live_prefill_tps", 1], ["live-generation-speed", "live_generation_tps", 1],
    ["prefill-speed", "prefill_tps", 1, true], ["generation-speed", "generation_tps", 1, true],
    ["prompt-total", "prompt_tokens_total", 0], ["generated-total", "generated_tokens_total", 0],
    ["requests-processing", "requests_processing", 0], ["requests-deferred", "requests_deferred", 0],
  ]) {
    const value = idle && key.startsWith("live_") ? null : metrics?.[key];
    $(id).textContent = Number.isFinite(value) && (!nonzero || value > 0)
      ? value.toLocaleString(locale(), { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : "—";
  }
  const live = Number.isFinite(metrics?.requests_processing) && Number.isFinite(metrics?.requests_deferred);
  text($("metrics-note"), state.state === "ready"
    ? !metrics ? "Performance unavailable. Retrying…"
      : !live ? "Update the Gufo executable to enable live rates and request counts."
      : metrics.prompt_tokens_total === 0 && metrics.generated_tokens_total === 0
        && metrics.requests_processing === 0 && metrics.requests_deferred === 0
        ? "Waiting for requests."
        : "Live totals and request counts update about once per second."
    : ({ loading: "Performance will appear when the model is ready.",
         stopping: "Stopping Gufo…", failed: "Performance unavailable while Gufo is stopped.",
         disconnected: "Performance unavailable. Launcher disconnected." }[state.state] || "Start Gufo to see performance."));
  text($("metrics-detail"), metrics && !live
    ? "This executable reports totals after requests finish and includes cached prompt tokens. Completed speeds retain the latest nonzero measurement."
    : Number.isFinite(metrics?.prompt_seconds_total)
      ? "Live prefill uses measured processing time; generation uses wall time between polls. Cached prompt tokens are excluded. Completed speeds retain the latest nonzero measurement."
      : "Live rates cover all requests between polls. Prompt totals and live prefill exclude cached tokens. Completed speeds retain the latest nonzero measurement.");
}
