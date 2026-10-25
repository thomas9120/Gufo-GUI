import { $ } from "./api.js";
import { text, rawText, locale } from "./i18n.js";

export function renderIdentity(state) {
  const props = state.state === "ready" ? state.props : null;
  for (const [id, value] of [["loaded-model-path", props?.model_path], ["build-revision", props?.build_info]]) {
    rawText($(id), typeof value === "string" && value ? value : "—");
  }
  const context = props?.default_generation_settings?.n_ctx;
  rawText($("effective-context"), Number.isInteger(context) && context > 0 ? context.toLocaleString(locale()) : "—");
  const vision = props?.modalities?.vision;
  text($("vision-chip"), vision === true ? "Vision: on" : vision === false ? "Vision: off" : "Vision: —");
  $("vision-chip").className = `status${vision === true ? " ready" : ""}`;
}
