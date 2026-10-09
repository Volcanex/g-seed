// Admin login + logout. Tiny - the gate is in server.py; this just
// wires up the UI handlers for the login form and any logout button.
//
// The login form is expected to live on the /admin/login page with id
// `admin-login-form` and a password input. On success it redirects to
// `?next=...` (or `/admin`).

(() => {
  // Login form (only present on /admin/login)
  const loginForm = document.getElementById('admin-login-form');
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fb = document.getElementById('login-feedback');
      const pw = loginForm.elements.password.value;
      if (fb) { fb.textContent = '…'; fb.className = 'feedback'; }
      try {
        const r = await fetch('/api/admin/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: pw }),
        });
        if (!r.ok) throw new Error('wrong password');
        if (fb) { fb.textContent = 'In.'; fb.className = 'feedback ok'; }
        const next = new URLSearchParams(location.search).get('next') || '/admin';
        location.assign(next);
      } catch (err) {
        if (fb) { fb.textContent = String(err.message || err); fb.className = 'feedback err'; }
      }
    });
  }

  // Logout button (any page that includes one with id `admin-logout`)
  const logout = document.getElementById('admin-logout');
  if (logout) {
    logout.addEventListener('click', async () => {
      await fetch('/api/admin/logout', { method: 'POST' });
      location.assign('/admin/login');
    });
  }
})();
