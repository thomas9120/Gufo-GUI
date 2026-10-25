"use strict";

// Appearance belongs to the browser, not to the launch settings shared with the
// engine, so it lives in local storage. This script is loaded without defer so
// the stored theme is applied before the first paint.
const THEME_KEY = "gufo.theme";
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");

function storedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === "light" || value === "dark" ? value : "";
  } catch {
    return "";  // Blocked storage follows the system theme.
  }
}

function rememberTheme(theme) {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // The choice still applies to this page when storage is unavailable.
  }
}

function applyTheme() {
  const theme = storedTheme() || (prefersDark.matches ? "dark" : "light");
  document.documentElement.dataset.theme = theme;
  const toggle = document.getElementById("theme-toggle");
  if (!toggle) return;
  toggle.setAttribute("aria-pressed", String(theme === "dark"));
  const label = `Switch to the ${theme === "dark" ? "light" : "dark"} theme`;
  toggle.setAttribute("data-i18n-aria-label", label);
  toggle.setAttribute("aria-label", document.documentElement.lang === "zh-CN"
    ? (theme === "dark" ? "切换为浅色主题" : "切换为深色主题") : label);
}

applyTheme();
prefersDark.addEventListener("change", applyTheme);
document.addEventListener("DOMContentLoaded", () => {
  applyTheme();
  document.getElementById("theme-toggle").addEventListener("click", () => {
    rememberTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
    applyTheme();
  });
});
