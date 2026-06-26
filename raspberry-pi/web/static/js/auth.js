// ===== AUTH: login admin / view-only =====
// Memproteksi aksi di sisi UI. Backend tetap penjaga utama (before_request).
// Strategi: bungkus window.fetch agar setiap respons 401 (auth_required)
// otomatis menampilkan modal login, tanpa perlu mengubah tiap pemanggil.

window.AUTH = { isAdmin: false, enabled: true, username: null };

// --- Bungkus fetch untuk menangani 401 secara global ---
(function () {
  const _origFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const res = await _origFetch(input, init);
    try {
      // Hanya intip method non-GET (aksi)
      const method = (init && init.method ? init.method : "GET").toUpperCase();
      if (res.status === 401 && method !== "GET") {
        // Clone agar body tetap bisa dibaca pemanggil asli
        const clone = res.clone();
        const data = await clone.json().catch(() => ({}));
        if (data && data.auth_required) {
          showLoginModal();
          if (typeof showToast === "function") {
            showToast("Login admin diperlukan untuk aksi ini", "error");
          }
        }
      }
    } catch (e) {
      /* abaikan */
    }
    return res;
  };
})();

async function refreshAuthStatus() {
  try {
    const res = await fetch("/api/auth/status").then((r) => r.json());
    window.AUTH.isAdmin = !!res.is_admin;
    window.AUTH.enabled = res.auth_enabled !== false;
    window.AUTH.username = res.username || null;
  } catch (e) {
    window.AUTH.isAdmin = false;
  }
  applyAuthUI();
  return window.AUTH;
}

// Sesuaikan tampilan navbar (badge + tombol login/logout)
function applyAuthUI() {
  const box = document.getElementById("authBox");
  if (box) {
    if (!window.AUTH.enabled) {
      box.innerHTML = "";
    } else if (window.AUTH.isAdmin) {
      box.innerHTML = `
        <span class="auth-badge admin" title="Mode Admin — semua fitur aktif">
          🔓 ${escapeAuth(window.AUTH.username || "admin")}
        </span>
        <button class="auth-btn" onclick="doLogout()">Logout</button>`;
    } else {
      box.innerHTML = `
        <span class="auth-badge view" title="Mode lihat saja">👁 View-only</span>
        <button class="auth-btn" onclick="showLoginModal()">Login</button>`;
    }
  }
  // Tandai <body> agar CSS bisa menyembunyikan kontrol bila perlu.
  // Saat auth dinonaktifkan, semua orang dianggap admin (akses penuh).
  const effectiveAdmin = window.AUTH.isAdmin || !window.AUTH.enabled;
  document.body.classList.toggle("is-admin", effectiveAdmin);
  document.body.classList.toggle(
    "is-viewer",
    !window.AUTH.isAdmin && window.AUTH.enabled
  );

  applyViewerLock();
  toggleViewerBanner();
  _startAuthObserver();
}

// --- Daftar tombol yang TETAP aktif untuk viewer (hanya melihat) ---
// Dicocokkan berdasarkan substring pada atribut onclick.
const VIEWER_SAFE_ONCLICK = [
  "togglePreview", // nyalakan/matikan preview (tidak mengubah hardware)
  "togglePreviewDetection",
  "window.location", // navigasi
  "showLoginModal",
  "doLogout",
  "doLogin",
  "closeLoginModal",
  "closeDialog",
];

function _isViewerSafe(btn) {
  if (btn.closest("#loginOverlay")) return true; // tombol di modal login
  if (btn.classList.contains("nav-tab")) return true; // navigasi
  if (btn.classList.contains("auth-btn")) return true; // login/logout
  if (btn.id === "dialogConfirm" || btn.classList.contains("dialog-btn"))
    return true; // tombol dialog konfirmasi
  const onclick = btn.getAttribute("onclick") || "";
  return VIEWER_SAFE_ONCLICK.some((s) => onclick.includes(s));
}

// Nonaktifkan semua tombol aksi saat view-only; pulihkan saat admin.
function applyViewerLock() {
  const viewer = !window.AUTH.isAdmin && window.AUTH.enabled;
  document.querySelectorAll("button.btn, .auth-btn").forEach((btn) => {
    if (_isViewerSafe(btn)) {
      if (btn.dataset.lockedByAuth === "1") {
        btn.disabled = false;
        btn.classList.remove("is-disabled");
        btn.title = btn.dataset.prevTitle || "";
        delete btn.dataset.lockedByAuth;
        delete btn.dataset.prevTitle;
      }
      return;
    }
    if (viewer) {
      if (btn.dataset.lockedByAuth !== "1") {
        btn.dataset.lockedByAuth = "1";
        btn.dataset.prevTitle = btn.title || "";
        btn.title = "Login admin diperlukan untuk aksi ini";
      }
      btn.disabled = true;
      btn.classList.add("is-disabled");
    } else if (btn.dataset.lockedByAuth === "1") {
      btn.disabled = false;
      btn.classList.remove("is-disabled");
      btn.title = btn.dataset.prevTitle || "";
      delete btn.dataset.lockedByAuth;
      delete btn.dataset.prevTitle;
    }
  });
}

// Banner pemberitahuan di atas konten saat view-only
function toggleViewerBanner() {
  const content = document.querySelector(".content");
  if (!content) return;
  let banner = document.getElementById("viewerBanner");
  const viewer = !window.AUTH.isAdmin && window.AUTH.enabled;
  if (viewer) {
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "viewerBanner";
      banner.className = "viewer-banner";
      banner.innerHTML = `
        <span class="vb-icon">👁</span>
        <span>Mode <strong>lihat saja</strong>. Login sebagai admin untuk mengakses tombol aksi.</span>
        <button onclick="showLoginModal()">Login Admin</button>`;
      content.insertBefore(banner, content.firstChild);
    }
  } else if (banner) {
    banner.remove();
  }
}

// Pantau tombol yang ditambahkan secara dinamis (modal, hasil fetch, dll)
let _authObserver = null;
function _startAuthObserver() {
  if (_authObserver) return;
  _authObserver = new MutationObserver(() => {
    if (_authObserver._scheduled) return;
    _authObserver._scheduled = true;
    requestAnimationFrame(() => {
      _authObserver._scheduled = false;
      applyViewerLock();
    });
  });
  _authObserver.observe(document.body, { childList: true, subtree: true });
}

function escapeAuth(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

// --- Modal login ---
function showLoginModal() {
  if (document.getElementById("loginOverlay")) return; // sudah terbuka
  const overlay = document.createElement("div");
  overlay.id = "loginOverlay";
  overlay.className = "login-overlay";
  overlay.innerHTML = `
    <div class="login-box">
      <div class="login-header">Login Admin</div>
      <div class="login-body">
        <label>Username</label>
        <input type="text" id="loginUser" autocomplete="username" placeholder="username" />
        <label>Password</label>
        <input type="password" id="loginPass" autocomplete="current-password" placeholder="password" />
        <div class="login-error" id="loginError"></div>
      </div>
      <div class="login-footer">
        <button class="dialog-btn dialog-btn-cancel" onclick="closeLoginModal()">Batal</button>
        <button class="dialog-btn" id="loginSubmit">Masuk</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const user = document.getElementById("loginUser");
  const pass = document.getElementById("loginPass");
  user.focus();

  document.getElementById("loginSubmit").onclick = doLogin;
  pass.onkeydown = (e) => {
    if (e.key === "Enter") doLogin();
  };
  user.onkeydown = (e) => {
    if (e.key === "Enter") pass.focus();
  };
  overlay.onclick = (e) => {
    if (e.target === overlay) closeLoginModal();
  };
}

function closeLoginModal() {
  const o = document.getElementById("loginOverlay");
  if (o) o.remove();
}

async function doLogin() {
  const username = document.getElementById("loginUser").value.trim();
  const password = document.getElementById("loginPass").value;
  const errEl = document.getElementById("loginError");
  errEl.textContent = "";
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (data.success) {
      closeLoginModal();
      await refreshAuthStatus();
      if (typeof showToast === "function") showToast(data.message, "success");
    } else {
      errEl.textContent = data.message || "Login gagal";
    }
  } catch (e) {
    errEl.textContent = "Error: " + e;
  }
}

async function doLogout() {
  try {
    await fetch("/api/logout", { method: "POST" });
  } catch (e) {
    /* abaikan */
  }
  await refreshAuthStatus();
  if (typeof showToast === "function") showToast("Anda telah logout", "info");
}

document.addEventListener("DOMContentLoaded", refreshAuthStatus);
