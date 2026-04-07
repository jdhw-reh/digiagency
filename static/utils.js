"use strict";

function renderMarkdown(text) {
  if (!text) return "";
  return marked.parse(text);
}

function showNotionConfigPrompt() {
  if (sessionStorage.getItem("notion_prompt_seen")) return;
  const el = document.getElementById("notion-config-prompt");
  if (!el) return;
  el.classList.add("visible");

  const dismiss = () => {
    el.classList.remove("visible");
    sessionStorage.setItem("notion_prompt_seen", "1");
  };

  el.querySelector(".notion-prompt__yes").onclick = () => {
    dismiss();
    if (window.showSettings) window.showSettings();
  };
  el.querySelector(".notion-prompt__no").onclick = dismiss;
}
