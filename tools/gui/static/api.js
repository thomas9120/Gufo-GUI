import { text } from "./i18n.js";

export const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="gufo-token"]').content;

export async function api(path, body) {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Gufo-Token": token, "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  // Errors from the HTTP server itself, such as an oversized body, are plain text.
  const result = await response.json().catch(() => null);
  if (!response.ok || !result) throw new Error(result?.error || `Request failed (${response.status})`);
  return result;
}

export function notice(message, success = false, values = {}) {
  text($("notice"), message, values);
  $("notice").className = `notice${success ? " success" : ""}`;
  $("notice").hidden = !message;
  // Start and Stop sit below the fold; errors must not appear off-screen.
  if (message && !success) $("notice").scrollIntoView?.({ block: "nearest" });
}
