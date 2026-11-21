import { text } from "./i18n.js";
import { $, api } from "./api.js";

export function initFilePicker(homeFolder) {
  let pickerTarget, pickerKind, listing, browseVersion = 0;

  async function browse(path, fallback = "") {
    const version = ++browseVersion;
    text($("picker-error"), "");
    text($("picker-entries"), "Loading folder…");
    $("select-folder").disabled = true;
    try {
      const result = await api(`browse?${new URLSearchParams({ path, kind: pickerKind })}`);
      if (version !== browseVersion) return;
      listing = result;
      $("picker-path").value = listing.path;
      $("picker-filter").value = "";
      $("picker-roots").replaceChildren(...listing.roots.map((root, index) => {
        const button = document.createElement("button");
        button.type = "button"; if (index === 0) text(button, "Home"); else button.textContent = root;
        button.addEventListener("click", () => browse(root));
        return button;
      }));
      $("select-folder").disabled = false;
      renderFiles();
    } catch (error) {
      if (version !== browseVersion) return;
      if (fallback && fallback !== path) return browse(fallback);
      listing = null;
      text($("picker-entries"), "");
      text($("picker-error"), error.message);
    }
  }

  function choose(path) {
    const target = $(pickerTarget);
    if (!target) return $("file-dialog").close();
    target.value = path;
    target.dispatchEvent(new Event("change", { bubbles: true }));
    $("file-dialog").close();
  }

  function renderFiles() {
    const filter = $("picker-filter").value.toLocaleLowerCase();
    const entries = listing?.entries.filter((entry) => entry.name.toLocaleLowerCase().includes(filter)) || [];
    delete $("picker-entries").dataset.i18n;
    $("picker-entries").replaceChildren(...entries.map((entry) => {
      const button = document.createElement("button"); button.type = "button";
      const icon = document.createElement("span"); icon.className = "file-icon";
      text(icon, entry.directory ? "DIR" : pickerKind === "gguf" ? "GGUF" : pickerKind === "executable" ? "EXE" : "FILE");
      const name = document.createElement("span"); name.textContent = entry.name;
      button.append(icon, name);
      if (!entry.directory && entry.shards > 1) {
        const shards = document.createElement("small"); text(shards, "{count} shards", { count: entry.shards });
        button.append(shards);
      }
      button.addEventListener("click", () => entry.directory ? browse(entry.path) : choose(entry.path));
      return button;
    }));
    if (!entries.length) text($("picker-entries"), "No matching files or folders.");
  }

  document.addEventListener("click", (event) => {
    const button = event.target?.closest?.("[data-browse]");
    if (!button) return;
    pickerTarget = button.dataset.browse; pickerKind = button.dataset.kind;
    const defaultTitle = pickerKind === "folder" ? "Choose a folder"
      : pickerKind === "path" ? "Choose a file or folder" : "Choose a file";
    text($("picker-title"), button.getAttribute("data-i18n-aria-label") || button.getAttribute("aria-label") || defaultTitle);
    $("select-folder").hidden = pickerKind !== "folder" && pickerKind !== "path";
    $("picker-roots").replaceChildren();
    const homeButton = document.createElement("button");
    homeButton.type = "button"; text(homeButton, "Home");
    homeButton.addEventListener("click", () => browse(homeFolder));
    $("picker-roots").append(homeButton);
    $("file-dialog").showModal();
    const current = $(pickerTarget)?.value || "";
    let parent = current.replace(/[\\/][^\\/]*$/, "");
    if (/^[a-z]:$/i.test(parent)) parent += "\\";
    const modelsDir = $("models_dir").value;
    if (pickerKind === "folder") {
      browse(current || modelsDir);
    } else if (pickerKind === "path") {
      const fallback = current && parent !== current ? parent : modelsDir;
      browse(current || modelsDir, fallback);
    } else {
      const path = current && parent !== current ? parent : modelsDir;
      browse(path);
    }
  });
  $("close-picker").addEventListener("click", () => $("file-dialog").close());
  $("file-dialog").addEventListener("close", () => { ++browseVersion; });
  $("picker-filter").addEventListener("input", renderFiles);
  $("picker-up").addEventListener("click", () => { if (listing) browse(listing.parent); });
  $("picker-go").addEventListener("click", () => browse($("picker-path").value));
  $("picker-path").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); browse(event.target.value); } });
  $("select-folder").addEventListener("click", () => { if (listing) choose(listing.path); });

}
