import { text } from "./i18n.js";

export const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="gufo-token"]').content;

export async function api(path, body) {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Gufo-Token": token, "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}

export function notice(message, success = false, values = {}) {
  text($("notice"), message, values);
  $("notice").className = `notice${success ? " success" : ""}`;
  $("notice").hidden = !message;
}
