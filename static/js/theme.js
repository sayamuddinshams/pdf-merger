/* ============================================================
   MergePDF — theme toggle
   ------------------------------------------------------------
   Switches between the dark and light themes, persists the
   choice in localStorage, and syncs the browser chrome color
   (theme-color meta). The <head> snippet already applied the
   saved theme pre-paint; this wires up the button.
   ============================================================ */

(function () {
  "use strict";

  var KEY = "mergepdf-theme";
  var root = document.documentElement;
  var toggle = document.getElementById("themeToggle");
  if (!toggle) return;

  function current() {
    return root.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function apply(theme, save) {
    root.setAttribute("data-theme", theme);
    toggle.setAttribute("aria-pressed", String(theme === "light"));

    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute("content", theme === "light" ? "#f4f6fb" : "#060a15");
    }

    if (save) {
      try { localStorage.setItem(KEY, theme); } catch (e) { /* private mode */ }
    }
  }

  toggle.addEventListener("click", function () {
    apply(current() === "dark" ? "light" : "dark", true);
  });

  // Sync the button state with whatever the <head> snippet applied.
  apply(current(), false);
})();