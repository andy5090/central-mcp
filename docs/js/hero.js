/* Token-multiplier ticker on the index hero.
 * Cycles a span's text through values listed in its `data-values`
 * attribute (pipe-separated), with a soft fade between swaps.
 * No-ops when the user prefers reduced motion or the element is missing. */

(function () {
  function start() {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const el = document.querySelector('.cmcp-hero-counter');
    if (!el) return;

    const values = (el.dataset.values || '').split('|').map(s => s.trim()).filter(Boolean);
    if (values.length < 2) return;

    let i = Math.max(0, values.indexOf(el.textContent.trim()));

    setInterval(() => {
      i = (i + 1) % values.length;
      el.style.opacity = '0';
      setTimeout(() => {
        el.textContent = values[i];
        el.style.opacity = '1';
      }, 320);
    }, 2200);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  // mkdocs-material navigation.instant swaps content without full reload —
  // re-bind on its custom event so the ticker keeps working after navigation.
  if (typeof document !== 'undefined' && 'document$' in window) {
    window.document$.subscribe(start);
  }
})();
