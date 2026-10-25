import { messages } from "./locales/zh-CN.js";

const LANGUAGE_KEY = "gufo.language";
let language = "en";
try {
  const saved = localStorage.getItem(LANGUAGE_KEY);
  language = saved === "en" || saved === "zh-CN" ? saved : "en";
} catch { /* Keep the interface usable when storage is blocked. */ }

const errorPattern = /^(\{field\}:|\{label\}:|Port |Could not launch Gufo:|Gufo exited|Gufo could not|Cannot read saved settings|Keep between|Unsupported reasoning|\{name\} does not support|Request failed)/;
const patterns = Object.entries(messages).filter(([key]) => key.includes("{") && errorPattern.test(key)).map(([key, value]) => {
  const names = [];
  const escaped = key.split(/(\{\w+\})/).map((part) => {
    if (/^\{\w+\}$/.test(part)) { names.push(part.slice(1, -1)); return "([\\s\\S]*?)"; }
    return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }).join("");
  return { pattern: new RegExp(`^${escaped}$`), names, value };
});

export function locale() { return language; }

export function t(key, values = {}) {
  let text = language === "zh-CN" && Object.hasOwn(messages, key) ? messages[key] : key;
  // Translate known launcher errors without changing the engine's raw logs.
  if (language === "zh-CN" && text === key && !Object.hasOwn(messages, key)) {
    for (const entry of patterns) {
      const match = entry.pattern.exec(key);
      if (!match) continue;
      text = entry.value;
      values = Object.fromEntries(entry.names.map((name, index) => [name, match[index + 1]]));
      break;
    }
  }
  return text.replace(/\{(\w+)\}/g, (match, name) => {
    const value = values[name];
    if (value === undefined) return match;
    // Only semantic message/field arguments are translated, never names or paths.
    return ["field", "label", "detail", "state", "modified"].includes(name) ? t(String(value)) : String(value);
  });
}

export function text(element, key, values = {}) {
  element.dataset.i18n = key;
  element.dataset.i18nValues = JSON.stringify(values);
  element.textContent = t(key, values);
  return element;
}

export function rawText(element, value) {
  delete element.dataset.i18n;
  delete element.dataset.i18nValues;
  element.textContent = value;
}

export function option(label, value) { return text(new Option(label, value), label); }

function translatePage() {
  document.documentElement.lang = language;
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n, JSON.parse(element.dataset.i18nValues || "{}"));
  });
  for (const attribute of ["aria-label", "placeholder", "title", "alt"]) {
    document.querySelectorAll(`[data-i18n-${attribute}]`).forEach((element) => {
      element.setAttribute(attribute, t(element.getAttribute(`data-i18n-${attribute}`)));
    });
  }
  const selector = document.getElementById("language-select");
  if (selector) selector.value = language;
}

export function setLanguage(value) {
  if (!["en", "zh-CN"].includes(value)) return;
  language = value;
  try { localStorage.setItem(LANGUAGE_KEY, value); } catch { /* Optional persistence. */ }
  translatePage();
  window.dispatchEvent(new Event("gufo-language-change"));
}

export function initLanguage() {
  translatePage();
  document.getElementById("language-select").addEventListener("change", (event) => setLanguage(event.target.value));
}
