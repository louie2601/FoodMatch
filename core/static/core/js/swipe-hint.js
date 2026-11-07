(function () {
  // On phones and tablets, a table (or tab strip) wider than the screen scrolls
  // sideways inside its box. Show a small "Swipe sideways" line above it so
  // people find the columns and buttons on the right.
  var small = window.matchMedia('(max-width: 1023px)');
  var ARROWS = '<svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 7 3 12l5 5"></path><path d="m16 7 5 5-5 5"></path><path d="M3 12h18"></path></svg>';

  function update() {
    document.querySelectorAll('.overflow-x-auto').forEach(function (box) {
      var before = box.previousElementSibling;
      var hint = before && before.hasAttribute('data-swipe-hint') ? before : null;
      var needed = small.matches && box.offsetParent !== null && box.scrollWidth > box.clientWidth + 8;
      if (needed && !hint) {
        hint = document.createElement('p');
        hint.setAttribute('data-swipe-hint', '');
        hint.className = 'flex items-center gap-1.5 px-1 py-1.5 text-xs font-medium text-slate-500';
        hint.innerHTML = ARROWS + '<span>Swipe sideways to see more</span>';
        box.parentNode.insertBefore(hint, box);
      } else if (hint) {
        hint.hidden = !needed;
      }
    });
  }

  var timer = null;
  function later() {
    clearTimeout(timer);
    timer = setTimeout(update, 120);
  }

  if (document.readyState === 'complete') update();
  else window.addEventListener('load', update);
  window.addEventListener('resize', later);
  // Tables inside tabs, drawers and modals become visible after a click.
  document.addEventListener('click', later);
})();
