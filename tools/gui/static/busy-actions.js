import { $ } from "./api.js";
import { text } from "./i18n.js";
import { ask } from "./dialogs.js";

export async function confirmBusyAction(state, action) {
  const metrics = state.state === "ready" ? state.metrics : null;
  const processing = metrics?.requests_processing;
  const queued = metrics?.requests_deferred;
  const generating = Number.isFinite(processing) && processing > 0 ? processing : 0;
  const waiting = Number.isFinite(queued) && queued > 0 ? queued : 0;
  if (generating + waiting === 0) return true;

  text($("busy-title"), action === "exit" ? "Exit launcher anyway?" : "Stop Gufo anyway?");
  text($("busy-processing"), generating === 1 ? "1 request is generating." : "{count} requests are generating.",
    { count: generating });
  $("busy-processing").hidden = generating === 0;
  text($("busy-queued"), waiting === 1 ? "1 request is queued." : "{count} requests are queued.",
    { count: waiting });
  $("busy-queued").hidden = waiting === 0;
  text($("busy-confirm"), action === "exit" ? "Exit anyway" : "Stop anyway");
  return await ask($("busy-dialog")) === "confirm";
}
