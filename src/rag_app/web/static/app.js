// Dafira UI behaviour: small, dependency-free enhancements on top of htmx.
// No inline handlers anywhere, so the Content-Security-Policy can forbid inline script.
"use strict";

(() => {
  const ALLOWED = /\.(pdf|md|markdown)$/i;

  // ---------------------------------------------------------------- alerts
  document.addEventListener("click", (event) => {
    const close = event.target.closest("[data-dismiss]");
    if (close) close.closest(".alert")?.remove();
  });

  // ---------------------------------------------------------------- confirm dialog
  // Replaces window.confirm for every hx-confirm with an accessible, Arabic <dialog>.
  document.addEventListener("htmx:confirm", (event) => {
    if (!event.detail.question) return;
    event.preventDefault();
    const dialog = document.getElementById("confirm-dialog");
    const trigger = event.detail.elt;
    dialog.querySelector("[data-question]").textContent = event.detail.question;
    const confirm = dialog.querySelector("[data-confirm-button]");
    const danger = trigger.classList.contains("btn--danger");
    confirm.className = danger ? "btn btn--danger" : "btn btn--primary";
    confirm.textContent = trigger.textContent.trim();
    dialog.returnValue = "";
    dialog.addEventListener(
      "close",
      () => {
        if (dialog.returnValue === "confirm") event.detail.issueRequest(true);
        else trigger.focus();
      },
      { once: true },
    );
    dialog.showModal();
  });

  // ---------------------------------------------------------------- upload forms
  const formatSize = (bytes) => `${(bytes / (1024 * 1024)).toFixed(1)} ميجابايت`;

  function check(form, file) {
    const error = form.querySelector("[data-error]");
    const chosen = form.querySelector("[data-chosen]");
    const max = Number(form.dataset.maxBytes);
    let message = "";
    if (!file) message = "اختر ملفاً أولاً.";
    else if (!ALLOWED.test(file.name)) message = "نوع الملف غير مدعوم. الصيغ المدعومة: PDF نصي وMarkdown.";
    else if (file.size === 0) message = "الملف فارغ.";
    else if (max && file.size > max) message = `حجم الملف (${formatSize(file.size)}) يتجاوز الحد المسموح (${formatSize(max)}).`;
    chosen.textContent = file ? `الملف المختار: ${file.name}` : "";
    error.textContent = message;
    error.hidden = !message;
    return !message;
  }

  function wire(form) {
    if (form.dataset.wired) return;
    form.dataset.wired = "1";
    const input = form.querySelector('input[type="file"]');
    input.addEventListener("change", () => check(form, input.files[0]));
    ["dragenter", "dragover"].forEach((type) =>
      form.addEventListener(type, (e) => {
        e.preventDefault();
        form.classList.add("is-dragover");
      }),
    );
    ["dragleave", "drop"].forEach((type) =>
      form.addEventListener(type, () => form.classList.remove("is-dragover")),
    );
    form.addEventListener("drop", (e) => {
      e.preventDefault();
      if (e.dataTransfer.files.length) {
        input.files = e.dataTransfer.files;
        check(form, input.files[0]);
      }
    });
  }

  const wireAll = (root) => root.querySelectorAll("form[data-upload]").forEach(wire);
  document.addEventListener("DOMContentLoaded", () => wireAll(document));
  document.addEventListener("htmx:load", (e) => wireAll(e.detail.elt.parentElement || document));

  // Validate before sending; show upload progress; reset the form after success.
  document.addEventListener("htmx:beforeRequest", (e) => {
    const form = e.detail.elt;
    if (!form.matches?.("form[data-upload]")) return;
    const input = form.querySelector('input[type="file"]');
    if (!check(form, input.files[0])) e.preventDefault();
  });
  document.addEventListener("htmx:xhr:progress", (e) => {
    const form = e.detail.elt;
    if (!form.matches?.("form[data-upload]") || !e.detail.lengthComputable) return;
    const bar = form.querySelector("progress");
    bar.hidden = false;
    bar.value = Math.round((e.detail.loaded / e.detail.total) * 100);
  });
  document.addEventListener("htmx:afterRequest", (e) => {
    const form = e.detail.elt;
    if (!form.matches?.("form[data-upload]") || !form.isConnected) return;
    form.querySelector("progress").hidden = true;
    if (e.detail.successful) {
      form.reset();
      form.querySelector("[data-chosen]").textContent = "";
    }
  });
})();
