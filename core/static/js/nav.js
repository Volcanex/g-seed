// Hamburger drawer + admin-aware nav sections.
// On load, asks /api/admin/verify whether the visitor is logged in;
// if yes, reveals the admin section in the drawer (and hides the login link).
//
// Pairs with nav.css (drawer + burger styles) and shell.html (markup).

(() => {
  const burger    = document.getElementById('nav-burger');
  const drawer    = document.getElementById('nav-drawer');
  const backdrop  = document.getElementById('nav-backdrop');
  const closeBtn  = document.getElementById('nav-drawer-close');
  const adminSec  = document.getElementById('nav-admin-section');
  const loginSec  = document.getElementById('nav-login-section');
  const logoutBtn = document.getElementById('nav-logout');

  if (!burger || !drawer || !backdrop) return;

  function open() {
    drawer.hidden = false;
    backdrop.hidden = false;
    burger.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(() => closeBtn?.focus());
  }
  function close() {
    drawer.hidden = true;
    backdrop.hidden = true;
    burger.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
    burger.focus();
  }

  burger.addEventListener('click', () => {
    if (drawer.hidden) open(); else close();
  });
  closeBtn?.addEventListener('click', close);
  backdrop.addEventListener('click', close);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !drawer.hidden) close();
  });

  // Logout button (drawer)
  logoutBtn?.addEventListener('click', async () => {
    try { await fetch('/api/admin/logout', { method: 'POST' }); } catch {}
    location.assign('/admin/login');
  });

  // Verify admin status on load - show the right drawer section.
  // If the admin API isn't mounted (project hasn't added it), this
  // request 404s and the drawer simply keeps the public sections.
  fetch('/api/admin/verify')
    .then(r => r.ok ? r.json() : { admin: false })
    .then(({ admin }) => {
      if (admin) {
        if (adminSec) adminSec.hidden = false;
        if (loginSec) loginSec.hidden = true;
      } else {
        if (adminSec) adminSec.hidden = true;
        if (loginSec) loginSec.hidden = false;
      }
    })
    .catch(() => {});
})();
