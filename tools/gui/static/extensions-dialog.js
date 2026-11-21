import { text, rawText } from "./i18n.js";
import { $, api } from "./api.js";
import { ask } from "./dialogs.js";

const REGISTRY_SPEC = /^[a-z][a-z0-9_]*(@[0-9]+\.[0-9]+\.[0-9]+)?$/;

export function isRegistrySource(source) {
  return REGISTRY_SPEC.test(String(source || "").trim());
}

export function createExtensionsDialog({ getExecutable, isServerActive, onExtensionsUpdated }) {
  let pollTimer = null;
  let catalogVersion = 0;
  let jobState = { state: "idle", logs: [] };
  let lastNotifiedKey = "";

  function runningJob() {
    return jobState.state === "running";
  }

  function updateButtons() {
    const blocked = isServerActive() || runningJob();
    $("ext-server-warning").hidden = !isServerActive();
    $("ext-update-all").disabled = blocked;
    $("ext-install-button").disabled = blocked;
    $("ext-cancel-job").disabled = !runningJob();
    for (const button of $("ext-catalog-list").querySelectorAll("button[data-ext-action]")) {
      button.disabled = blocked;
    }
  }

  function renderJob(snapshot) {
    jobState = snapshot || { state: "idle", logs: [] };
    const statusMap = {
      idle: ["Idle", "status"],
      running: ["Running", "status loading"],
      succeeded: ["Complete", "status ready"],
      failed: ["Failed", "status failed"],
      cancelled: ["Cancelled", "status"],
    };
    const [label, cls] = statusMap[jobState.state] || statusMap.idle;
    text($("ext-job-status"), label);
    $("ext-job-status").className = cls;
    if (jobState.logs?.length) {
      rawText($("ext-job-logs"), jobState.logs.join("\n"));
      $("ext-job-logs").scrollTop = $("ext-job-logs").scrollHeight;
    } else if (jobState.state === "idle") {
      text($("ext-job-logs"), "No extension task running.");
    }
    if (jobState.error) text($("ext-dialog-error"), jobState.error);
    updateButtons();

    if (jobState.state === "running") {
      schedulePoll();
    } else {
      clearTimeout(pollTimer);
      pollTimer = null;
      const key = `${jobState.state}:${jobState.operation}:${jobState.target}:${jobState.exit_code}`;
      if (jobState.state === "succeeded" && key !== lastNotifiedKey) {
        lastNotifiedKey = key;
        if (jobState.extensions) onExtensionsUpdated(jobState.extensions);
        loadCatalog();
      }
    }
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      try {
        renderJob(await api("extensions/job"));
      } catch (error) {
        text($("ext-dialog-error"), error.message);
      }
    }, 800);
  }

  function renderCatalog(catalog) {
    const list = $("ext-catalog-list");
    delete list.dataset.i18n;
    const regWarn = $("ext-registry-warning");
    if (!catalog.available) {
      regWarn.hidden = true;
      text(list, catalog.error || "No extensions reported.");
      updateButtons();
      return;
    }
    if (catalog.registry_error) {
      text(regWarn, "Registry index unavailable: {detail}", { detail: catalog.registry_error });
      regWarn.hidden = false;
    } else {
      regWarn.hidden = true;
    }
    const items = catalog.extensions || [];
    if (!items.length) {
      text(list, "No extensions reported.");
      updateButtons();
      return;
    }
    const nodes = items.map((item) => {
      const row = document.createElement("div");
      row.className = "ext-catalog-row";

      const meta = document.createElement("div");
      meta.className = "ext-catalog-meta";
      const title = document.createElement("div");
      title.className = "ext-catalog-title";
      const name = document.createElement("strong");
      name.textContent = item.name;
      title.append(name);
      const version = item.version || item.newest;
      if (version) {
        const ver = document.createElement("span");
        ver.className = "hint";
        ver.textContent = ` ${version}`;
        title.append(ver);
      }
      const badge = document.createElement("span");
      badge.className = "tag";
      if (item.installed) {
        if (item.status === "needs update") {
          badge.classList.add("ext-unknown-tag");
          text(badge, "Needs update");
        } else {
          text(badge, "Ready");
        }
      } else if (item.builtin) {
        text(badge, "Built-in");
      } else {
        text(badge, "Registry");
      }
      title.append(badge);
      meta.append(title);

      if (item.description) {
        const desc = document.createElement("p");
        desc.className = "hint";
        rawText(desc, item.description);
        meta.append(desc);
      } else if (item.source && item.sourceKind && item.sourceKind !== "registry") {
        const src = document.createElement("p");
        src.className = "hint";
        rawText(src, item.revision ? `${item.source}@${item.revision}` : item.source);
        meta.append(src);
      }

      const actions = document.createElement("div");
      actions.className = "ext-catalog-actions";
      if (!item.installed && !item.builtin && item.newest) {
        const installBtn = document.createElement("button");
        installBtn.type = "button";
        installBtn.dataset.extAction = "install";
        text(installBtn, "Install");
        installBtn.addEventListener("click", () => startInstall(item.name, false));
        actions.append(installBtn);
      }
      if (item.installed && (item.status === "needs update" || (item.newest && item.newest !== item.version))) {
        const updateBtn = document.createElement("button");
        updateBtn.type = "button";
        updateBtn.dataset.extAction = "update";
        text(updateBtn, "Update");
        updateBtn.addEventListener("click", () => startUpdate(item.name));
        actions.append(updateBtn);
      }
      if (item.installed) {
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "stop";
        removeBtn.dataset.extAction = "remove";
        text(removeBtn, "Remove");
        removeBtn.addEventListener("click", () => startRemove(item.name));
        actions.append(removeBtn);
      }

      row.append(meta, actions);
      return row;
    });
    list.replaceChildren(...nodes);
    updateButtons();
  }

  async function loadCatalog() {
    const version = ++catalogVersion;
    text($("ext-dialog-error"), "");
    text($("ext-catalog-list"), "Loading extension catalog…");
    try {
      const catalog = await api("extensions/catalog", { executable: getExecutable() });
      if (version === catalogVersion) renderCatalog(catalog);
    } catch (error) {
      if (version === catalogVersion) {
        text($("ext-dialog-error"), "Could not load extension catalog. {detail}", { detail: error.message });
        text($("ext-catalog-list"), "No extensions reported.");
      }
    }
  }

  async function startInstall(source, replaceBuiltin) {
    text($("ext-dialog-error"), "");
    const trimmed = String(source || "").trim();
    if (!trimmed) {
      text($("ext-dialog-error"), "Extension source: enter a registry name, pinned Git URL, or local folder.");
      return;
    }
    let confirmed = false;
    if (!isRegistrySource(trimmed)) {
      rawText($("extension-trust-source"), trimmed);
      const choice = await ask($("extension-trust-dialog"));
      if (choice !== "confirm") return;
      confirmed = true;
    }
    try {
      lastNotifiedKey = "";
      const snap = await api("extensions/install", {
        executable: getExecutable(),
        source: trimmed,
        replace_builtin: Boolean(replaceBuiltin),
        confirmed,
      });
      renderJob(snap);
    } catch (error) {
      text($("ext-dialog-error"), error.message);
    }
  }

  async function startUpdate(name = "") {
    text($("ext-dialog-error"), "");
    try {
      lastNotifiedKey = "";
      const payload = { executable: getExecutable() };
      if (name) payload.name = name;
      renderJob(await api("extensions/update", payload));
    } catch (error) {
      text($("ext-dialog-error"), error.message);
    }
  }

  async function startRemove(name) {
    text($("ext-dialog-error"), "");
    try {
      lastNotifiedKey = "";
      renderJob(await api("extensions/remove", { executable: getExecutable(), name }));
    } catch (error) {
      text($("ext-dialog-error"), error.message);
    }
  }

  async function open() {
    $("extensions-dialog").showModal();
    updateButtons();
    await loadCatalog();
    try {
      renderJob(await api("extensions/job"));
    } catch { /* Ignore initial job check errors. */ }
  }

  $("manage-extensions")?.addEventListener("click", open);
  $("close-extensions-dialog")?.addEventListener("click", () => $("extensions-dialog").close());
  $("extensions-dialog")?.addEventListener("close", () => {
    clearTimeout(pollTimer);
    pollTimer = null;
  });
  $("ext-catalog-refresh")?.addEventListener("click", loadCatalog);
  $("ext-update-all")?.addEventListener("click", () => startUpdate(""));
  $("ext-install-button")?.addEventListener("click", () => {
    startInstall($("ext-source-input").value, $("ext-replace-builtin").checked);
  });
  $("ext-cancel-job")?.addEventListener("click", async () => {
    text($("ext-dialog-error"), "");
    try {
      renderJob(await api("extensions/cancel", {}));
    } catch (error) {
      text($("ext-dialog-error"), error.message);
    }
  });

  return { open, syncServerState: updateButtons };
}
