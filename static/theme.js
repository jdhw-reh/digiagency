"use strict";

const _THEME_KEY = "digi_agency_theme";

function _applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const icon  = document.getElementById("theme-icon");
  const label = document.getElementById("theme-label");
  if (!icon || !label) return;
  if (theme === "dark") {
    icon.textContent  = "☀️";
    label.textContent = "Light mode";
  } else {
    icon.textContent  = "🌙";
    label.textContent = "Dark mode";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  // Sync button label with whatever the inline script applied
  _applyTheme(document.documentElement.dataset.theme || "light");

  document.getElementById("theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem(_THEME_KEY, next);
    _applyTheme(next);
  });
});
