(function () {
  var STORAGE_KEY = 'foodmatch.sidebarCollapsed';
  var aside = document.querySelector('[data-app-sidebar]');
  var btn = document.querySelector('[data-sidebar-toggle]');
  if (!aside || !btn) return;

  var body = document.body;
  var desktop = window.matchMedia('(min-width: 1024px)');
  var backdrop = document.createElement('div');
  backdrop.setAttribute('aria-hidden', 'true');
  backdrop.style.cssText = 'display:none;position:fixed;inset:0;z-index:65;background:rgba(2,6,23,0.5);';
  body.appendChild(backdrop);

  try {
    if (localStorage.getItem(STORAGE_KEY) === '1') body.classList.add('sidebar-collapsed');
  } catch (e) {}

  function syncAria() {
    var expanded = desktop.matches
      ? !body.classList.contains('sidebar-collapsed')
      : aside.classList.contains('is-open');
    btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
  }

  function setDrawer(open) {
    aside.classList.toggle('is-open', open);
    backdrop.style.display = open ? 'block' : 'none';
    body.style.overflow = open ? 'hidden' : '';
    syncAria();
  }

  function setCollapsed(collapsed) {
    body.classList.toggle('sidebar-collapsed', collapsed);
    try { localStorage.setItem(STORAGE_KEY, collapsed ? '1' : '0'); } catch (e) {}
    syncAria();
  }

  btn.addEventListener('click', function () {
    if (desktop.matches) {
      setCollapsed(!body.classList.contains('sidebar-collapsed'));
    } else {
      setDrawer(!aside.classList.contains('is-open'));
    }
  });
  backdrop.addEventListener('click', function () { setDrawer(false); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && aside.classList.contains('is-open')) setDrawer(false);
  });
  var onBreakpointChange = function () { setDrawer(false); };
  if (desktop.addEventListener) desktop.addEventListener('change', onBreakpointChange);
  else if (desktop.addListener) desktop.addListener(onBreakpointChange);

  syncAria();
})();
