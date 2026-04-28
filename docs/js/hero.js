/* Hero token-multiplier counter.
 * Animates a value from 10 → 1000 with easeOutExpo, holds at the peak,
 * then loops. Reads min/max from `data-min` / `data-max` (defaults 10
 * and 1000). Honors prefers-reduced-motion (lands a static "1000×").
 * Re-binds on mkdocs-material's `document$` so it survives instant
 * page transitions. */

(function () {
  const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function easeOutExpo(t) {
    return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
  }

  let activeRaf = 0;
  let activeTimer = 0;

  function start() {
    cancelAnimationFrame(activeRaf);
    clearTimeout(activeTimer);

    const el = document.querySelector('.cmcp-hero-counter');
    if (!el) return;

    const min = Number(el.dataset.min) || 10;
    const max = Number(el.dataset.max) || 1000;
    const duration = 2400;
    const hold = 1800;

    if (REDUCED) {
      el.textContent = max + '×';
      return;
    }

    function loop() {
      const t0 = performance.now();
      function step(now) {
        const progress = Math.min((now - t0) / duration, 1);
        const value = Math.round(min + (max - min) * easeOutExpo(progress));
        el.textContent = value + '×';
        if (progress < 1) {
          activeRaf = requestAnimationFrame(step);
        } else {
          activeTimer = setTimeout(loop, hold);
        }
      }
      activeRaf = requestAnimationFrame(step);
    }
    loop();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  // mkdocs-material instant navigation: rebind on every page transition.
  if (typeof window !== 'undefined' && window.document$ && typeof window.document$.subscribe === 'function') {
    window.document$.subscribe(start);
  }
})();
