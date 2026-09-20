/* ============================================================
   MergePDF — minimal interactive background
   ------------------------------------------------------------
   Graph-paper style: a static, faint cyan-tinted grid is lit by
   a single soft glow that eases toward the cursor. Only one
   `transform` is written per animation frame (GPU-composited).
   Bails out for touch devices and `prefers-reduced-motion`.
   ============================================================ */

(function () {
  "use strict";

  // The glow is interactive, desktop-pointer work — skip it for
  // reduced-motion and touch users (CSS keeps the static grid).
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (!window.matchMedia("(pointer: fine)").matches) return;

  var spotlight = document.getElementById("bgSpotlight");
  if (!spotlight) return;

  var SMOOTHING = 0.06; // lerp factor — lower = silkier, more lag

  var vw = window.innerWidth;
  var vh = window.innerHeight;

  // Target vs. eased cursor position (start at a calm resting spot).
  var tx = vw * 0.5, ty = vh * 0.42;
  var cx = tx, cy = ty;
  var seen = false;

  function onPointerMove(e) {
    tx = e.clientX;
    ty = e.clientY;
    if (!seen) {
      seen = true;
      cx = tx;
      cy = ty;
      spotlight.classList.add("is-visible");
    }
  }

  function frame() {
    vw = window.innerWidth;
    vh = window.innerHeight;

    cx += (tx - cx) * SMOOTHING;
    cy += (ty - cy) * SMOOTHING;

    // Keep the glow centered on the eased cursor position.
    spotlight.style.transform =
      "translate3d(" + cx.toFixed(2) + "px," + cy.toFixed(2) + "px,0)";

    requestAnimationFrame(frame);
  }

  window.addEventListener("pointermove", onPointerMove, { passive: true });
  requestAnimationFrame(frame);
})();