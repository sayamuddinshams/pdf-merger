/* ============================================================
   PDF Weave — frontend logic
   Drag & drop, file list management (with per-file page ranges),
   and the authenticated merge request.
   ============================================================ */

(function () {
  "use strict";

  // Injected by base.html — lets the UI react to the session state.
  const AUTHENTICATED = window.USER_AUTHENTICATED === true;
  // Injected by base.html — required on every state-changing request.
  const CSRF_TOKEN = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  const $ = (id) => document.getElementById(id);

  const dropzone = $("dropzone");
  const fileInput = $("fileInput");
  const fileList = $("fileList");
  const clearBtn = $("clearBtn");
  const mergeBtn = $("mergeBtn");
  const fileSummary = $("fileSummary");

  const MAX_FILES = 10;

  /** @type {File[]} — the user's PDFs, kept in merge order. */
  let files = [];
  /** @type {string[]} — page-range spec per file ("", "all", "2-5", "1,3"). */
  let pageSpecs = [];

  /* ---------------- Helpers ---------------- */

  const ICONS = {
    up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 15-6-6-6 6"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>',
  };

  function formatBytes(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    const value = bytes / Math.pow(1024, i);
    return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)} ${units[i]}`;
  }

  function isPdf(file) {
    return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  }

  function showToast(message, type = "") {
    const toast = $("toast");
    toast.textContent = message;
    toast.className = `toast show ${type}`;
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => toast.classList.remove("show"), 4000);
  }

  /* ---------------- File management ---------------- */

  function addFiles(incoming) {
    let added = 0;
    let skipped = 0;

    for (const file of incoming) {
      if (!isPdf(file)) { skipped++; continue; }
      if (files.some((f) => f.name === file.name && f.size === file.size)) { skipped++; continue; }
      if (files.length >= MAX_FILES) {
        showToast(`You can add up to ${MAX_FILES} files at once.`, "error");
        break;
      }
      files.push(file);
      pageSpecs.push("all");
      added++;
    }

    if (added > 0) {
      render();
      showToast(added === 1 ? "1 PDF added" : `${added} PDFs added`, "success");
    }
    if (skipped > 0) {
      showToast(`${skipped} non-PDF file${skipped === 1 ? "" : "s"} skipped.`, "error");
    }
  }

  function removeFileAt(index) {
    files.splice(index, 1);
    pageSpecs.splice(index, 1);
    render();
  }

  function moveFile(index, dir) {
    const target = index + dir;
    if (target < 0 || target >= files.length) return;
    [files[index], files[target]] = [files[target], files[index]];
    [pageSpecs[index], pageSpecs[target]] = [pageSpecs[target], pageSpecs[index]];
    render();
  }

  function clearAll() {
    files = [];
    pageSpecs = [];
    render();
  }

  function updateSummary() {
    const total = files.reduce((sum, f) => sum + f.size, 0);
    fileSummary.textContent =
      files.length === 0
        ? "No files selected"
        : `${files.length} file${files.length > 1 ? "s" : ""} · ${formatBytes(total)}`;
    mergeBtn.disabled = files.length < 2;
  }

  function onRangeInput(i) {
    return (e) => {
      pageSpecs[i] = (e.target.value || "").trim() || "all";
    };
  }

  function render() {
    fileList.innerHTML = "";
    updateSummary();

    if (files.length === 0) {
      fileList.hidden = true;
      return;
    }

    fileList.hidden = false;
    const fragment = document.createDocumentFragment();

    files.forEach((file, i) => {
      const row = document.createElement("div");
      row.className = "file-row";

      const chip = document.createElement("span");
      chip.className = "pdf-chip";
      chip.textContent = "PDF";

      const meta = document.createElement("div");
      meta.className = "file-meta";

      const name = document.createElement("span");
      name.className = "file-name";
      name.textContent = file.name;
      name.title = file.name;

      const bottom = document.createElement("span");
      bottom.className = "file-meta__bottom";

      const size = document.createElement("span");
      size.className = "file-size";
      size.textContent = formatBytes(file.size);

      const rangeField = document.createElement("label");
      rangeField.className = "range-field";

      const rangeLabel = document.createElement("span");
      rangeLabel.className = "range-field__label";
      rangeLabel.textContent = "Pages";

      const rangeInput = document.createElement("input");
      rangeInput.className = "range-input";
      rangeInput.type = "text";
      rangeInput.inputMode = "numeric";
      rangeInput.placeholder = "all";
      rangeInput.value = pageSpecs[i] === "all" ? "" : pageSpecs[i];
      rangeInput.title = 'Page range, e.g. "2-5" or "1,3,8". Leave empty for all pages.';
      rangeInput.setAttribute("aria-label", `Pages to include from ${file.name}`);
      rangeInput.addEventListener("input", onRangeInput(i));

      rangeField.append(rangeLabel, rangeInput);
      bottom.append(size, rangeField);
      meta.append(name, bottom);

      const actions = document.createElement("div");
      actions.className = "file-actions";

      actions.appendChild(makeIconBtn(ICONS.up, "Move up", "up", i, i === 0));
      actions.appendChild(makeIconBtn(ICONS.down, "Move down", "down", i, i === files.length - 1));
      actions.appendChild(makeIconBtn(ICONS.trash, "Remove file", "remove", i, false, true));

      row.append(chip, meta, actions);
      fragment.appendChild(row);
    });

    fileList.appendChild(fragment);
  }

  function makeIconBtn(svg, label, action, index, disabled = false, danger = false) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `icon-btn${danger ? " icon-btn--danger" : ""}`;
    btn.innerHTML = svg;
    btn.setAttribute("aria-label", label);
    btn.disabled = disabled;
    btn.addEventListener("click", () => {
      if (action === "up") moveFile(index, -1);
      if (action === "down") moveFile(index, 1);
      if (action === "remove") removeFileAt(index);
    });
    return btn;
  }

  /* ---------------- Drop zone ---------------- */

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    addFiles([...fileInput.files]);
    fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag");
    })
  );

  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag");
    })
  );

  dropzone.addEventListener("drop", (e) => addFiles([...e.dataTransfer.files]));

  // Stop the browser from opening files dropped anywhere else on the page.
  ["dragover", "drop"].forEach((evt) =>
    window.addEventListener(evt, (e) => e.preventDefault())
  );

  clearBtn.addEventListener("click", clearAll);

  /* ---------------- Merge ---------------- */

  mergeBtn.addEventListener("click", merge);

  /** Send the files to the Flask backend and follow to the thank-you page. */
  async function merge() {
    if (!AUTHENTICATED) {
      showToast("Please log in to merge your PDFs.", "error");
      setTimeout(() => window.location.assign("/login"), 1100);
      return;
    }

    if (files.length < 2) {
      showToast("Add at least two PDFs to merge.", "error");
      return;
    }

    mergeBtn.disabled = true;
    const originalLabel = mergeBtn.textContent;
    mergeBtn.textContent = "Merging…";

    const body = new FormData();
    files.forEach((f, i) => {
      body.append("files", f, f.name);
      body.append("pages", (pageSpecs[i] || "all").trim() || "all");
    });

    try {
      const res = await fetch("/api/merge", {
        method: "POST",
        headers: { "X-CSRFToken": CSRF_TOKEN },
        body,
      });

      if (res.status === 401) {
        showToast("Please log in to merge your PDFs.", "error");
        setTimeout(() => window.location.assign("/login"), 1100);
        return;
      }

      let data = {};
      try { data = await res.json(); } catch (_) { /* non-JSON reply */ }

      // Success: take the user to the thank-you page, where the merged PDF
      // is previewed and a Download button saves it to their device.
      if (data.ok && data.thankyouUrl) {
        showToast("PDFs merged! Taking you to your download…", "success");
        setTimeout(() => window.location.assign(data.thankyouUrl), 500);
        return;
      }

      showToast(data.error || "Merge failed — please try again.", "error");
    } catch (_) {
      showToast("Could not reach the server. Is it running?", "error");
    } finally {
      mergeBtn.disabled = files.length < 2;
      mergeBtn.textContent = originalLabel;
    }
  }
})();