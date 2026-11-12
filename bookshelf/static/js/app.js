/* Bookshelf – small progressive enhancements:
   uploads (picker + drag & drop), dialogs, confirmations and copy buttons. */
(() => {
  "use strict";

  const UPLOAD_URL = "/api/books";
  const PARALLEL_UPLOADS = 2;
  const AUTO_HIDE_MS = 4000;

  const $ = (selector, root = document) => root.querySelector(selector);

  /* ---------- Dialogs, copy buttons, upload trigger ---------- */

  // A dialog re-rendered with a validation error opens again by itself.
  document.querySelectorAll("dialog[data-open]").forEach((dialog) => dialog.showModal());

  document.addEventListener("click", (event) => {
    const target = event.target;

    // Clicking the backdrop of a modal dialog closes it.
    if (target instanceof HTMLDialogElement) {
      target.close();
      return;
    }
    const opener = target.closest("[data-dialog-open]");
    if (opener) {
      document.getElementById(opener.dataset.dialogOpen)?.showModal();
      return;
    }
    if (target.closest("[data-dialog-close]")) {
      target.closest("dialog")?.close();
      return;
    }
    const copyButton = target.closest("[data-copy]");
    if (copyButton) {
      copyText(copyButton.dataset.copy).then(() => flashCopied(copyButton));
      return;
    }
    if (target.closest("[data-upload-trigger]")) {
      $("#upload-input")?.click();
      return;
    }
    const scanButton = target.closest("[data-scan-trigger]");
    if (scanButton) scanLibrary(scanButton);
  });

  /* ---------- Library scan (files added to or removed from the library folder) ---------- */

  const SCAN_URL = "/api/library/scan";

  async function scanLibrary(button) {
    if (button.classList.contains("is-busy")) return;
    button.classList.add("is-busy");
    button.disabled = true;
    try {
      let status = await (await fetch(SCAN_URL, { method: "POST" })).json();
      if (status.error && status.started === undefined) throw new Error(status.error);
      while (status.running || status.started === false) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        status = await (await fetch(SCAN_URL)).json();
        if (!status.running) break;
      }
      if (status.error) throw new Error(status.error);
      const changes = [];
      if (status.imported) changes.push(`${status.imported} added`);
      if (status.removed) changes.push(`${status.removed} removed`);
      toast(changes.length ? `Scan finished: ${changes.join(", ")}.` : "Scan finished: no changes.");
      if ((status.imported || status.removed) && document.getElementById("library") && window.htmx) {
        window.htmx.ajax("GET", location.pathname + location.search, {
          target: "#library",
          swap: "outerHTML",
        });
      }
    } catch (error) {
      toast(`Scan failed: ${error.message}`, true);
    } finally {
      button.classList.remove("is-busy");
      button.disabled = false;
    }
  }

  function toast(message, isError = false) {
    const element = document.createElement("div");
    element.className = isError ? "toast toast-error" : "toast";
    element.setAttribute("role", "status");
    element.textContent = message;
    document.body.append(element);
    setTimeout(() => element.remove(), 4000);
  }

  // Horizontally scrolling areas that should start at their end (e.g. the reading calendar).
  document.querySelectorAll("[data-scroll-end]").forEach((element) => {
    element.scrollLeft = element.scrollWidth;
  });

  // Rows that scroll sideways (Continue reading): page dots next to the title (one per
  // screenful, click to jump) and dragging with the mouse. Touch keeps native swiping.
  // Rebuilt after htmx swaps the library.
  function hscrollPages(track) {
    const max = track.scrollWidth - track.clientWidth;
    return max > 2 ? Math.ceil(track.scrollWidth / track.clientWidth - 0.05) : 1;
  }
  function updateHscroll(box) {
    const track = box.querySelector("[data-hscroll-track]");
    const dots = box.querySelector("[data-hscroll-dots]");
    if (!track || !dots) return;
    const pages = hscrollPages(track);
    track.classList.toggle("can-drag", pages > 1);
    dots.hidden = pages < 2;
    if (dots.children.length !== (pages > 1 ? pages : 0)) {
      dots.replaceChildren(
        ...Array.from({ length: pages > 1 ? pages : 0 }, (_, page) => {
          const dot = document.createElement("button");
          dot.type = "button";
          dot.className = "hscroll-dot";
          dot.dataset.hscrollPage = page;
          dot.setAttribute("aria-label", `Page ${page + 1} of ${pages}`);
          return dot;
        }),
      );
    }
    const max = track.scrollWidth - track.clientWidth;
    const current = max > 0 ? Math.round((track.scrollLeft / max) * (pages - 1)) : 0;
    [...dots.children].forEach((dot, page) => dot.setAttribute("aria-current", String(page === current)));
  }
  const updateAllHscroll = () => document.querySelectorAll("[data-hscroll]").forEach(updateHscroll);
  updateAllHscroll();
  window.addEventListener("resize", updateAllHscroll);
  document.body.addEventListener("htmx:afterSettle", updateAllHscroll);
  document.addEventListener(
    "scroll",
    (event) => {
      const box = event.target.closest?.("[data-hscroll]");
      if (box) updateHscroll(box);
    },
    true,
  );
  document.addEventListener("click", (event) => {
    const dot = event.target.closest("[data-hscroll-page]");
    if (!dot) return;
    const track = dot.closest("[data-hscroll]").querySelector("[data-hscroll-track]");
    const pages = hscrollPages(track);
    const max = track.scrollWidth - track.clientWidth;
    track.scrollTo({ left: (max * Number(dot.dataset.hscrollPage)) / (pages - 1), behavior: "smooth" });
  });

  let drag = null;
  document.addEventListener("pointerdown", (event) => {
    const track = event.target.closest?.("[data-hscroll-track].can-drag");
    if (!track || event.pointerType !== "mouse" || event.button !== 0) return;
    drag = { track, x: event.clientX, left: track.scrollLeft, moved: false };
  });
  document.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) < 6) return; // a click, not a drag
    drag.moved = true;
    drag.track.classList.add("is-dragging");
    drag.track.scrollLeft = drag.left - dx;
  });
  const endDrag = () => {
    if (!drag) return;
    const { track, moved } = drag;
    drag = null;
    if (!moved) return;
    // Let the click that ends a drag pass without opening the card under the mouse.
    setTimeout(() => track.classList.remove("is-dragging"), 0);
  };
  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);
  // Covers and links would otherwise start a native image/link drag.
  document.addEventListener("dragstart", (event) => {
    if (event.target.closest?.("[data-hscroll-track].can-drag")) event.preventDefault();
  });

  document.addEventListener("submit", (event) => {
    const message = event.target.dataset.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });

  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    // Fallback for plain-HTTP origins (typical for LAN servers).
    const area = Object.assign(document.createElement("textarea"), { value: text });
    area.style.cssText = "position:fixed;opacity:0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }

  function flashCopied(button) {
    const label = button.querySelector("span");
    const original = label?.textContent;
    button.classList.add("is-copied");
    if (label) label.textContent = "Copied";
    setTimeout(() => {
      button.classList.remove("is-copied");
      if (label) label.textContent = original;
    }, 1600);
  }

  /* ---------- Uploads ---------- */

  const input = $("#upload-input");
  const panel = $(".upload-panel");
  const overlay = $(".drop-overlay");
  if (!input || !panel || !overlay) return;

  const list = $(".upload-list", panel);
  const title = $(".upload-title", panel);
  const queue = [];
  const stats = { total: 0, finished: 0, added: 0, failed: 0 };
  let active = 0;
  let hideTimer = null;

  input.addEventListener("change", () => {
    enqueue(input.files);
    input.value = "";
  });

  $(".upload-close", panel).addEventListener("click", () => {
    if (active || queue.length) panel.hidden = true;
    else resetPanel();
  });

  function enqueue(files) {
    if (!files || !files.length) return;
    clearTimeout(hideTimer);
    panel.hidden = false;
    for (const file of files) {
      queue.push({ file, row: addRow(file) });
      stats.total += 1;
    }
    updateTitle();
    pump();
  }

  function addRow(file) {
    const row = document.createElement("li");
    row.className = "upload-item";
    row.innerHTML =
      '<div class="upload-row"><span class="upload-name"></span>' +
      '<span class="upload-state">Waiting…</span></div>' +
      '<div class="progress"><span style="width:0%"></span></div>';
    $(".upload-name", row).textContent = file.name;
    list.append(row);
    return row;
  }

  function pump() {
    while (active < PARALLEL_UPLOADS && queue.length) {
      const job = queue.shift();
      active += 1;
      upload(job).then(() => {
        active -= 1;
        stats.finished += 1;
        updateTitle();
        if (active === 0 && queue.length === 0) allDone();
        else pump();
      });
    }
  }

  function upload({ file, row }) {
    return new Promise((resolve) => {
      const bar = $(".progress span", row);
      const state = $(".upload-state", row);
      const xhr = new XMLHttpRequest();
      const form = new FormData();
      form.append("file", file);

      xhr.upload.addEventListener("progress", (event) => {
        if (!event.lengthComputable) return;
        const percent = Math.round((event.loaded / event.total) * 100);
        bar.style.width = `${percent}%`;
        state.textContent = percent < 100 ? `${percent}%` : "Processing…";
      });
      xhr.addEventListener("load", () => {
        let data = {};
        try {
          data = JSON.parse(xhr.responseText);
        } catch {
          /* non-JSON error page */
        }
        if (xhr.status === 201) {
          stats.added += 1;
          finishRow(row, "done", "Added");
        } else if (xhr.status === 409) {
          finishRow(row, "skipped", "Already in library");
        } else {
          stats.failed += 1;
          finishRow(row, "error", data.error || `Failed (${xhr.status})`);
        }
        resolve();
      });
      xhr.addEventListener("error", () => {
        stats.failed += 1;
        finishRow(row, "error", "Network error");
        resolve();
      });

      state.textContent = "0%";
      xhr.open("POST", UPLOAD_URL);
      xhr.setRequestHeader("Accept", "application/json");
      xhr.send(form);
    });
  }

  function finishRow(row, kind, text) {
    row.classList.add(`is-${kind}`);
    $(".upload-state", row).textContent = text;
    $(".progress span", row).style.width = "100%";
  }

  function updateTitle() {
    const running = active > 0 || queue.length > 0;
    title.textContent = running
      ? `Uploading… ${stats.finished} of ${stats.total} done`
      : `${stats.added} of ${stats.total} added`;
  }

  function allDone() {
    refreshLibrary();
    if (stats.failed === 0) hideTimer = setTimeout(resetPanel, AUTO_HIDE_MS);
  }

  function resetPanel() {
    panel.hidden = true;
    list.replaceChildren();
    Object.assign(stats, { total: 0, finished: 0, added: 0, failed: 0 });
  }

  function refreshLibrary() {
    if (!document.getElementById("library") || !window.htmx || stats.added === 0) return;
    window.htmx.ajax("GET", location.pathname + location.search, {
      target: "#library",
      swap: "outerHTML",
    });
  }

  /* ---------- Drag & drop anywhere on the page ---------- */

  let dragDepth = 0;
  const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes("Files");

  window.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragDepth += 1;
    overlay.hidden = false;
  });
  window.addEventListener("dragover", (event) => {
    if (hasFiles(event)) event.preventDefault();
  });
  window.addEventListener("dragleave", (event) => {
    if (!hasFiles(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) overlay.hidden = true;
  });
  window.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragDepth = 0;
    overlay.hidden = true;
    collectDropped(event.dataTransfer).then(enqueue);
  });

  /* A dropped folder shows up as a zero-byte "file" that never uploads, so walk folders and
     pick out the books inside. Entries must be read synchronously, before the first await. */
  const BOOK_EXTENSIONS = new Set([
    "epub", "pdf", "mobi", "azw3", "fb2", "cbz", "cbr", "djvu", "txt", "rtf", "html", "docx", "chm",
  ]);
  const isBook = (file) => BOOK_EXTENSIONS.has(file.name.split(".").pop().toLowerCase());

  async function collectDropped(dataTransfer) {
    const entries = Array.from(dataTransfer.items || [])
      .map((item) => item.webkitGetAsEntry?.())
      .filter(Boolean);
    if (!entries.length) return Array.from(dataTransfer.files);
    const files = [];
    const walk = async (entry) => {
      if (entry.isFile) {
        const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
        if (isBook(file)) files.push(file);
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        let batch;
        do {
          batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
          for (const child of batch) await walk(child);
        } while (batch.length);
      }
    };
    for (const entry of entries) await walk(entry);
    return files;
  }
})();
