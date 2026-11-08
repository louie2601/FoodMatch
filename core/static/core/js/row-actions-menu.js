(function () {
  // Row "Actions" menus ([data-row-menu]). The panel stays inside its table row
  // (so the page's other scripts still find the row and form around each item)
  // but is shown with position: fixed, so the table's scroll box can't clip it.
  var openMenu = null;

  function parts(menu) {
    return {
      toggle: menu.querySelector('[data-row-menu-toggle]'),
      panel: menu.querySelector('[data-row-menu-panel]')
    };
  }

  function items(menu) {
    return Array.prototype.slice.call(parts(menu).panel.querySelectorAll('[role="menuitem"]:not([disabled])'));
  }

  function place(menu) {
    var p = parts(menu);
    p.panel.style.position = 'fixed';
    p.panel.classList.remove('hidden');
    var r = p.toggle.getBoundingClientRect();
    var width = p.panel.offsetWidth;
    var height = p.panel.offsetHeight;
    var left = Math.min(Math.max(8, r.right - width), window.innerWidth - width - 8);
    var below = r.bottom + 6;
    var above = r.top - height - 6;
    var y0 = below;
    if (below + height > window.innerHeight - 8) {
      // No room below (rows near the bottom of the screen): open upward, or
      // on a very short screen keep the whole menu inside the screen.
      y0 = above >= 8 ? above : Math.max(8, window.innerHeight - height - 8);
    }
    p.panel.style.left = left + 'px';
    p.panel.style.top = y0 + 'px';
  }

  function follow() {
    if (!openMenu) return;
    var r = parts(openMenu).toggle.getBoundingClientRect();
    // Close once the row's button has scrolled out of sight; otherwise move with it.
    if (r.bottom < 0 || r.top > window.innerHeight || r.width === 0) close(false);
    else place(openMenu);
  }

  function close(returnFocus) {
    if (!openMenu) return;
    var p = parts(openMenu);
    p.panel.classList.add('hidden');
    p.toggle.setAttribute('aria-expanded', 'false');
    if (returnFocus) p.toggle.focus();
    openMenu = null;
  }

  function open(menu) {
    close(false);
    openMenu = menu;
    parts(menu).toggle.setAttribute('aria-expanded', 'true');
    place(menu);
    var first = items(menu)[0];
    if (first) first.focus({ preventScroll: true });
  }

  document.addEventListener('click', function (e) {
    var toggle = e.target.closest('[data-row-menu-toggle]');
    if (toggle) {
      var menu = toggle.closest('[data-row-menu]');
      if (openMenu === menu) close(false);
      else open(menu);
      return;
    }
    if (!openMenu) return;
    if (e.target.closest('[data-row-menu-panel] [role="menuitem"]')) {
      // Let the item's own action (drawer, confirmation window, form) run first.
      setTimeout(function () { close(false); }, 0);
      return;
    }
    if (!e.target.closest('[data-row-menu-panel]')) close(false);
  });

  document.addEventListener('keydown', function (e) {
    if (!openMenu) return;
    if (e.key === 'Escape') { close(true); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      var list = items(openMenu);
      var i = list.indexOf(document.activeElement);
      var next = e.key === 'ArrowDown' ? (i + 1) % list.length : (i - 1 + list.length) % list.length;
      if (list.length) list[next].focus();
    }
    if (e.key === 'Tab') close(false);
  });

  // The menu is placed on the screen, so keep it next to its button when the
  // page or the table scrolls, or the screen size changes (phone address bar).
  window.addEventListener('resize', follow);
  window.addEventListener('scroll', follow, true);
})();
