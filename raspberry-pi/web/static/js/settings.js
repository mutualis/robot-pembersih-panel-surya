// ===== Settings - WiFi Management =====
// Memakai helper showToast() & showDialog() dari main.js

// Tampilkan kekuatan sinyal sebagai teks ringkas
function signalLabel(signal) {
  if (signal >= 75) return "▮▮▮▮";
  if (signal >= 50) return "▮▮▮";
  if (signal >= 25) return "▮▮";
  if (signal > 0) return "▮";
  return "—";
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

async function refreshStatus() {
  const dot = document.getElementById("wifiDot");
  const ssidEl = document.getElementById("wifiSsid");
  const metaEl = document.getElementById("wifiMeta");
  try {
    const res = await fetch("/api/wifi/status").then((r) => r.json());
    if (!res.success) {
      ssidEl.textContent = "WiFi tidak tersedia";
      metaEl.textContent = res.message || "";
      dot.classList.remove("on");
      return;
    }
    if (res.connected) {
      dot.classList.add("on");
      ssidEl.textContent = res.ssid;
      const parts = [];
      if (res.signal) parts.push(`Sinyal ${res.signal}%`);
      if (res.ip) parts.push(`IP ${res.ip}`);
      metaEl.textContent = parts.join(" · ");
    } else {
      dot.classList.remove("on");
      ssidEl.textContent = "Tidak terhubung ke WiFi";
      metaEl.textContent = res.message || "";
    }
  } catch (e) {
    ssidEl.textContent = "Gagal memuat status";
    metaEl.textContent = String(e);
  }
}

async function scanWifi() {
  const btn = document.getElementById("btnScan");
  const list = document.getElementById("wifiList");
  btn.disabled = true;
  btn.textContent = "Memindai...";
  list.innerHTML =
    '<li class="wifi-item"><span class="name">Memindai jaringan...</span></li>';
  try {
    const res = await fetch("/api/wifi/scan").then((r) => r.json());
    if (!res.success) {
      list.innerHTML = `<li class="wifi-item"><span class="name">${escapeHtml(
        res.message || "Scan gagal"
      )}</span></li>`;
      return;
    }
    if (!res.networks.length) {
      list.innerHTML =
        '<li class="wifi-item"><span class="name">Tidak ada jaringan ditemukan</span></li>';
      return;
    }
    list.innerHTML = "";
    res.networks.forEach((net) => {
      const li = document.createElement("li");
      li.className = "wifi-item" + (net.in_use ? " connected" : "");
      const authType = net.auth_type || "psk";
      const secured  = authType !== "open";
      const authBadge = authType === "enterprise"
        ? '<span class="lock" style="color:#003d7a;font-weight:700" title="WPA2-Enterprise — butuh username & password">🏢 802.1X</span>'
        : authType === "open"
        ? '<span class="lock">terbuka</span>'
        : '<span class="lock">🔒</span>';
      li.innerHTML = `
        <span class="name">${escapeHtml(net.ssid)}</span>
        ${net.in_use ? '<span class="tag">Terhubung</span>' : ""}
        ${authBadge}
        <span class="bars" title="${net.signal}%">${signalLabel(net.signal)}</span>`;
      li.onclick = () => connectTo(net.ssid, authType, net.in_use);
      list.appendChild(li);
    });
  } catch (e) {
    list.innerHTML = `<li class="wifi-item"><span class="name">Error: ${escapeHtml(
      String(e)
    )}</span></li>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Scan WiFi";
  }
}

async function connectTo(ssid, authType, alreadyConnected) {
  if (window.AUTH && !window.AUTH.isAdmin && window.AUTH.enabled) {
    if (typeof showLoginModal === "function") showLoginModal();
    showToast("Login admin diperlukan untuk mengganti WiFi", "error");
    return;
  }
  if (alreadyConnected) {
    showToast(`Sudah terhubung ke ${ssid}`, "info");
    return;
  }

  let creds = null;
  if (authType === "enterprise") {
    creds = await promptEnterprise(ssid);
  } else if (authType === "psk" || authType === "wep") {
    const pw = await promptPassword(ssid);
    if (pw === null) return;
    creds = { password: pw };
  }
  // open: creds tetap null, langsung connect

  showToast(`Menghubungkan ke ${ssid}...`, "info");
  try {
    const body = { ssid, auth_type: authType, ...(creds || {}) };
    const res = await fetch("/api/wifi/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());

    showToast(res.message, res.success ? "success" : "error", 5000);
    if (res.success) {
      setTimeout(refreshStatus, 2000);
      setTimeout(loadSaved, 2500);
    }
  } catch (e) {
    showToast("Gagal menghubungkan: " + e, "error");
  }
}

// Dialog password untuk WPA2-Personal
function promptPassword(ssid) {
  return new Promise((resolve) => {
    const overlay = document.getElementById("dialogOverlay");
    const title   = document.getElementById("dialogTitle");
    const body    = document.getElementById("dialogMessage");
    const footer  = overlay.querySelector(".dialog-footer");

    title.textContent = `Password WiFi untuk "${ssid}"`;
    body.innerHTML = `
      <input type="password" id="wifiPassInput" class="config-input" placeholder="Minimal 8 karakter" />
      <label class="ugm-check" style="margin-top:10px;">
        <input type="checkbox" id="wifiShowPass" /> Tampilkan password
      </label>`;

    const originalFooter = footer.innerHTML;
    footer.innerHTML = `
      <button class="dialog-btn dialog-btn-cancel" id="wifiCancel">Batal</button>
      <button class="dialog-btn" id="wifiOk">Sambungkan</button>`;

    overlay.classList.add("show");
    const input = document.getElementById("wifiPassInput");
    input.focus();

    document.getElementById("wifiShowPass").onchange = (e) => {
      input.type = e.target.checked ? "text" : "password";
    };

    function cleanup(result) {
      overlay.classList.remove("show");
      footer.innerHTML = originalFooter;
      resolve(result);
    }
    document.getElementById("wifiCancel").onclick = () => cleanup(null);
    document.getElementById("wifiOk").onclick = () => {
      const val = input.value;
      if (val.length < 8) { showToast("Password minimal 8 karakter", "error"); return; }
      cleanup(val);
    };
    input.onkeydown = (e) => {
      if (e.key === "Enter") document.getElementById("wifiOk").click();
      if (e.key === "Escape") cleanup(null);
    };
  });
}

// Dialog username + password untuk WPA2-Enterprise (802.1X)
function promptEnterprise(ssid) {
  return new Promise((resolve) => {
    const overlay = document.getElementById("dialogOverlay");
    const title   = document.getElementById("dialogTitle");
    const body    = document.getElementById("dialogMessage");
    const footer  = overlay.querySelector(".dialog-footer");

    title.textContent = `Login ke "${ssid}" (WPA2-Enterprise)`;
    body.innerHTML = `
      <p style="font-size:12px;color:#666;margin:0 0 12px">
        Jaringan ini memakai autentikasi institusi (802.1X).<br>
        Masukkan username dan password akun kampus/kantormu.
      </p>
      <label style="font-size:12px;color:#555;display:block;margin-bottom:4px">Username / NIM / Email</label>
      <input type="text" id="wifiEnterpriseUser" class="config-input"
        placeholder="Contoh: ridho@mail.ugm.ac.id" autocomplete="username" />
      <label style="font-size:12px;color:#555;display:block;margin:10px 0 4px">Password</label>
      <input type="password" id="wifiEnterprisePass" class="config-input"
        placeholder="Password akun institusi" autocomplete="current-password" />
      <label class="ugm-check" style="margin-top:10px;">
        <input type="checkbox" id="wifiEntShowPass" /> Tampilkan password
      </label>`;

    const originalFooter = footer.innerHTML;
    footer.innerHTML = `
      <button class="dialog-btn dialog-btn-cancel" id="wifiEntCancel">Batal</button>
      <button class="dialog-btn" id="wifiEntOk">Sambungkan</button>`;

    overlay.classList.add("show");
    const userInput = document.getElementById("wifiEnterpriseUser");
    const passInput = document.getElementById("wifiEnterprisePass");
    userInput.focus();

    document.getElementById("wifiEntShowPass").onchange = (e) => {
      passInput.type = e.target.checked ? "text" : "password";
    };

    function cleanup(result) {
      overlay.classList.remove("show");
      footer.innerHTML = originalFooter;
      resolve(result);
    }
    document.getElementById("wifiEntCancel").onclick = () => cleanup(null);
    document.getElementById("wifiEntOk").onclick = () => {
      const user = userInput.value.trim();
      const pass = passInput.value;
      if (!user) { showToast("Username tidak boleh kosong", "error"); return; }
      if (!pass)  { showToast("Password tidak boleh kosong", "error"); return; }
      cleanup({ username: user, password: pass });
    };
    passInput.onkeydown = (e) => {
      if (e.key === "Enter") document.getElementById("wifiEntOk").click();
      if (e.key === "Escape") cleanup(null);
    };
  });
}

async function loadSaved() {
  const el = document.getElementById("savedList");
  try {
    const res = await fetch("/api/wifi/saved").then((r) => r.json());
    if (!res.success || !res.networks.length) {
      el.innerHTML =
        '<span style="font-size:12px;color:#999">Belum ada profil tersimpan</span>';
      return;
    }
    el.innerHTML = "";
    res.networks.forEach((ssid) => {
      const chip = document.createElement("span");
      chip.className = "saved-chip";
      chip.innerHTML = `${escapeHtml(ssid)} <button title="Hapus profil">✕</button>`;
      chip.querySelector("button").onclick = () => forgetNetwork(ssid);
      el.appendChild(chip);
    });
  } catch (e) {
    el.innerHTML = `<span style="font-size:12px;color:#c0392b">Error: ${escapeHtml(
      String(e)
    )}</span>`;
  }
}

async function forgetNetwork(ssid) {
  if (window.AUTH && !window.AUTH.isAdmin && window.AUTH.enabled) {
    if (typeof showLoginModal === "function") showLoginModal();
    showToast("Login admin diperlukan", "error");
    return;
  }
  const ok = await showDialog("Hapus Profil WiFi", `Hapus profil "${ssid}"?`);
  if (!ok) return;
  try {
    const res = await fetch("/api/wifi/forget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssid }),
    }).then((r) => r.json());
    showToast(res.message, res.success ? "success" : "error");
    if (res.success) loadSaved();
  } catch (e) {
    showToast("Gagal menghapus: " + e, "error");
  }
}

// Inisialisasi saat halaman dibuka
document.addEventListener("DOMContentLoaded", () => {
  refreshStatus();
  loadSaved();
  loadConnectivity();
  loadAccessAddresses();
  loadApConfig();
  loadCaptiveConfig();
  loadModels();
  refreshPorts();
  loadOperationalConfig();

  // Tampilkan nama file terpilih pada file picker bertema
  const modelFileInput = document.getElementById("modelFile");
  if (modelFileInput) {
    modelFileInput.addEventListener("change", () => {
      const nameEl = document.getElementById("modelFileName");
      if (!nameEl) return;
      if (modelFileInput.files && modelFileInput.files.length) {
        nameEl.textContent = modelFileInput.files[0].name;
        nameEl.classList.add("has-file");
      } else {
        nameEl.textContent = "Belum ada file dipilih";
        nameEl.classList.remove("has-file");
      }
    });
  }
});

// ===== Captive Portal =====

// URL portal yang terdeteksi terakhir (disimpan untuk tombol "Buka Halaman Login")
let _captivePortalUrl = "";

function loadCaptiveConfig() {
  checkCaptiveStatus();
}

async function checkCaptiveStatus() {
  const box = document.getElementById("captiveStatusBox");
  const btnOpen = document.getElementById("btnOpenPortal");
  if (!box) return;
  box.innerHTML = '<div style="font-size:12px;color:#999">Mendeteksi captive portal...</div>';
  try {
    const res = await fetch("/api/wifi/captive/check").then((r) => r.json());
    if (res.internet) {
      box.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;background:#eef7f0;border:1px solid #a5d6b5;padding:10px 14px">
          <span style="width:10px;height:10px;border-radius:50%;background:#2e9e4f;box-shadow:0 0 6px #2e9e4f;flex-shrink:0;display:inline-block"></span>
          <span style="font-size:13px;color:#2e7d32;font-weight:600">Internet aktif — tidak perlu login portal</span>
        </div>`;
      if (btnOpen) btnOpen.style.display = "none";
      _captivePortalUrl = "";
      sessionStorage.removeItem("captivePortalOpened");
      return;
    }

    // Captive portal terdeteksi
    _captivePortalUrl = res.portal_url || "";
    const urlLabel = _captivePortalUrl
      ? `<div style="font-size:11px;color:#856404;margin-top:4px;font-family:Consolas,monospace">${escapeHtml(_captivePortalUrl)}</div>`
      : "";

    box.innerHTML = `
      <div style="background:#fff3cd;border:1px solid #ffeeba;padding:10px 14px">
        <div style="display:flex;align-items:center;gap:10px">
          <span style="width:10px;height:10px;border-radius:50%;background:#e67e22;flex-shrink:0;display:inline-block"></span>
          <div>
            <div style="font-size:13px;color:#856404;font-weight:600">
              Captive portal terdeteksi${_captivePortalUrl ? " — URL ditemukan otomatis" : " — URL tidak terdeteksi"}
            </div>
            ${urlLabel}
            <div style="font-size:11px;color:#856404;margin-top:4px">
              ${_captivePortalUrl
                ? 'Klik <strong>"Buka Halaman Login"</strong> — login di popup, lalu klik "Cek Ulang".'
                : 'Portal tidak bisa dideteksi URL-nya. Hubungkan lewat browser langsung.'}
            </div>
          </div>
        </div>
      </div>`;

    if (btnOpen) btnOpen.style.display = _captivePortalUrl ? "inline-block" : "none";

    // Auto-buka popup sekali per sesi jika URL tersedia
    if (_captivePortalUrl && !sessionStorage.getItem("captivePortalOpened")) {
      sessionStorage.setItem("captivePortalOpened", "1");
      setTimeout(() => openPortalPage(), 800);
    }
  } catch (e) {
    box.innerHTML = `<div style="font-size:12px;color:#999">Tidak dapat memeriksa status internet</div>`;
  }
}

function openPortalPage() {
  if (!_captivePortalUrl) {
    showToast("URL portal belum terdeteksi — klik 'Cek Ulang' dulu", "error");
    return;
  }
  const w = 520, h = 680;
  const left = Math.round(window.screen.width / 2 - w / 2);
  const top  = Math.round(window.screen.height / 2 - h / 2);
  const popup = window.open(
    _captivePortalUrl, "captive_portal_login",
    `width=${w},height=${h},left=${left},top=${top},resizable=yes,scrollbars=yes`
  );
  if (!popup || popup.closed || typeof popup.closed === "undefined") {
    showToast("Popup diblokir — membuka di tab baru", "info");
    window.open(_captivePortalUrl, "_blank");
  } else {
    showToast("Login di popup, lalu tutup dan klik 'Cek Ulang'", "info", 5000);
  }
}

// ===== Manajemen Model YOLO =====
async function loadModels() {
  try {
    const res = await fetch("/api/models").then((r) => r.json());
    if (!res.success) {
      renderModelList("detection", null, res.message);
      renderModelList("classification", null, res.message);
      return;
    }
    renderModelList("detection", res.stages.detection);
    renderModelList("classification", res.stages.classification);
  } catch (e) {
    renderModelList("detection", null, String(e));
    renderModelList("classification", null, String(e));
  }
}

function renderModelList(stage, data, errMsg) {
  const id =
    stage === "detection" ? "modelListDetection" : "modelListClassification";
  const box = document.getElementById(id);
  if (!box) return;
  if (errMsg) {
    box.innerHTML = `<div style="font-size:12px;color:#c0392b">${escapeHtml(
      errMsg
    )}</div>`;
    return;
  }
  const models = (data && data.models) || [];
  if (!models.length) {
    box.innerHTML =
      '<div style="font-size:12px;color:#999">Belum ada model. Upload model .pt di atas.</div>';
    return;
  }
  box.innerHTML = "";
  models.forEach((m) => {
    const item = document.createElement("div");
    item.className = "model-item" + (m.active ? " active" : "");
    item.innerHTML = `
      <div class="m-info">
        <div class="m-name">${escapeHtml(m.name)}</div>
        <div class="m-meta">${m.size_mb} MB · ${escapeHtml(m.modified)}</div>
      </div>
      ${m.active ? '<span class="m-tag">Aktif</span>' : ""}
      <button class="m-btn btn-select" ${m.active ? "disabled" : ""}>
        ${m.active ? "Terpilih" : "Aktifkan"}
      </button>
      <button class="m-btn danger btn-del" ${m.active ? "disabled" : ""}>Hapus</button>`;
    item.querySelector(".btn-select").onclick = () => selectModel(stage, m.name);
    item.querySelector(".btn-del").onclick = () => deleteModel(stage, m.name);
    box.appendChild(item);
  });
}

async function uploadModel() {
  const stage = document.getElementById("modelStage").value;
  const fileInput = document.getElementById("modelFile");
  const btn = document.getElementById("btnModelUpload");
  const prog = document.getElementById("modelUploadProgress");

  if (!fileInput.files || !fileInput.files.length) {
    showToast("Pilih file .pt dulu", "error");
    return;
  }
  const file = fileInput.files[0];
  if (!file.name.toLowerCase().endsWith(".pt")) {
    showToast("File harus berformat .pt", "error");
    return;
  }

  const form = new FormData();
  form.append("file", file);
  form.append("stage", stage);

  btn.disabled = true;
  btn.textContent = "Mengupload…";
  prog.classList.remove("hidden");
  prog.textContent = `Mengupload ${file.name} (${(file.size / 1048576).toFixed(
    1
  )} MB)… memverifikasi model…`;

  try {
    const res = await fetch("/api/models/upload", {
      method: "POST",
      body: form,
    });
    if (res.status === 401) {
      prog.classList.add("hidden");
      return;
    }
    const data = await res.json();
    showToast(data.message, data.success ? "success" : "error", 6000);
    if (data.success) {
      fileInput.value = "";
      const nameEl = document.getElementById("modelFileName");
      if (nameEl) {
        nameEl.textContent = "Belum ada file dipilih";
        nameEl.classList.remove("has-file");
      }
      loadModels();
    }
  } catch (e) {
    showToast("Gagal upload: " + e, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Upload";
    prog.classList.add("hidden");
  }
}

async function selectModel(stage, name) {
  showToast(`Mengaktifkan ${name}…`, "info");
  try {
    const res = await fetch("/api/models/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage, name }),
    });
    if (res.status === 401) return;
    const data = await res.json();
    showToast(data.message, data.success ? "success" : "error", 5000);
    if (data.success) loadModels();
  } catch (e) {
    showToast("Gagal mengaktifkan: " + e, "error");
  }
}

async function deleteModel(stage, name) {
  const ok = await showDialog("Hapus Model", `Hapus model "${name}"?`);
  if (!ok) return;
  try {
    const res = await fetch("/api/models/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stage, name }),
    });
    if (res.status === 401) return;
    const data = await res.json();
    showToast(data.message, data.success ? "success" : "error");
    if (data.success) loadModels();
  } catch (e) {
    showToast("Gagal menghapus: " + e, "error");
  }
}

// ===== Sistem: restart aplikasi / reboot ====
// Prompt password admin untuk aksi berisiko tinggi (sekaligus konfirmasi).
function promptAdminPassword(title, warningHtml) {
  return new Promise((resolve) => {
    const overlay = document.getElementById("dialogOverlay");
    const titleEl = document.getElementById("dialogTitle");
    const body = document.getElementById("dialogMessage");
    const footer = overlay.querySelector(".dialog-footer");

    titleEl.textContent = title;
    body.innerHTML = `
      ${warningHtml ? `<p style="margin:0 0 10px;font-size:13px;color:#856404;">${warningHtml}</p>` : ""}
      <p style="margin:0 0 10px;font-size:13px;">Masukkan password admin untuk melanjutkan:</p>
      <input type="password" id="sysPassInput" class="config-input"
        placeholder="Password" autocomplete="current-password" />`;

    const originalFooter = footer.innerHTML;
    footer.innerHTML = `
      <button class="dialog-btn dialog-btn-cancel" id="sysCancel">Batal</button>
      <button class="dialog-btn" id="sysOk">Lanjutkan</button>`;

    overlay.classList.add("show");
    const input = document.getElementById("sysPassInput");
    input.focus();

    function cleanup(result) {
      overlay.classList.remove("show");
      footer.innerHTML = originalFooter;
      resolve(result);
    }
    document.getElementById("sysCancel").onclick = () => cleanup(null);
    document.getElementById("sysOk").onclick = () => {
      const val = input.value;
      if (!val) {
        showToast("Password tidak boleh kosong", "error");
        return;
      }
      cleanup(val);
    };
    input.onkeydown = (e) => {
      if (e.key === "Enter") document.getElementById("sysOk").click();
      if (e.key === "Escape") cleanup(null);
    };
  });
}

async function systemRestartApp() {
  const password = await promptAdminPassword("Restart Aplikasi");
  if (password === null) return;
  await _systemAction("/api/system/restart_app", password, "Merestart aplikasi…");
}

async function systemReboot() {
  const password = await promptAdminPassword(
    "Reboot Raspberry Pi",
    "Reboot mematikan seluruh sistem ~1 menit. Pastikan tidak ada proses penting berjalan."
  );
  if (password === null) return;
  await _systemAction("/api/system/reboot", password, "Mereboot Raspberry Pi…");
}

async function _systemAction(url, password, pendingMsg) {
  showToast(pendingMsg, "info");
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (res.status === 401) {
      const d = await res.json().catch(() => ({}));
      showToast(d.message || "Password salah", "error");
      return;
    }
    const data = await res.json();
    showToast(data.message, data.success ? "success" : "error", 8000);
  } catch (e) {
    // Koneksi terputus saat restart/reboot itu wajar
    showToast("Perintah dikirim. Koneksi mungkin terputus sementara.", "info", 8000);
  }
}

// ===== Alamat Akses Web =====
async function loadAccessAddresses() {
  const box = document.getElementById("accessList");
  if (!box) return;
  try {
    const res = await fetch("/api/wifi/access").then((r) => r.json());
    if (!res.success || !res.addresses || !res.addresses.length) {
      box.innerHTML = `<div style="font-size:12px;color:#999">${escapeHtml(
        res.message || "Alamat tidak tersedia"
      )}</div>`;
      return;
    }
    box.innerHTML = "";
    res.addresses.forEach((a) => {
      const isPrimary = a.type === res.primary;
      const item = document.createElement("div");
      item.className = "access-item" + (isPrimary ? " primary" : "");
      item.innerHTML = `
        <div class="access-info">
          <div class="access-label">${escapeHtml(a.label)}</div>
          <div class="access-url">${escapeHtml(a.url)}</div>
          ${a.note ? `<div class="access-note">${escapeHtml(a.note)}</div>` : ""}
        </div>
        ${isPrimary ? '<span class="access-tag">Aktif</span>' : ""}
        <button class="ap-copy" title="Salin alamat">Salin</button>`;
      item.querySelector("button").onclick = async () => {
        try {
          await navigator.clipboard.writeText(a.url);
          showToast("Alamat disalin: " + a.url, "success");
        } catch (e) {
          showToast("Gagal menyalin (clipboard tidak diizinkan)", "error");
        }
      };
      box.appendChild(item);
    });
  } catch (e) {
    box.innerHTML = `<div style="font-size:12px;color:#c0392b">Error: ${escapeHtml(
      String(e)
    )}</div>`;
  }
}

// ===== Status Koneksi (WiFi / LAN) =====
async function loadConnectivity() {
  const box = document.getElementById("connBox");
  if (!box) return;
  try {
    const res = await fetch("/api/wifi/connectivity").then((r) => r.json());
    if (!res.success) {
      box.innerHTML = `<div style="font-size:12px;color:#999">${escapeHtml(
        res.message || "Tidak tersedia"
      )}</div>`;
      return;
    }
    const lan = res.lan || {};
    const wifi = res.wifi || {};
    const lanActive = lan.connected;
    const wifiActive = wifi.connected;

    box.innerHTML = `
      <div class="conn-card ${lanActive ? "active" : ""}">
        <div class="conn-title">
          🔌 LAN (Kabel)
          ${res.primary === "lan" ? '<span class="primary-tag">Utama</span>' : ""}
        </div>
        <div class="conn-state">${
          lanActive ? "Terhubung" : "Tidak terhubung"
        }</div>
        <div class="conn-ip">${lanActive && lan.ip ? "IP " + escapeHtml(lan.ip) : "&nbsp;"}</div>
      </div>
      <div class="conn-card ${wifiActive ? "active" : ""}">
        <div class="conn-title">
          📶 WiFi
          ${res.primary === "wifi" ? '<span class="primary-tag">Utama</span>' : ""}
        </div>
        <div class="conn-state">${
          wifiActive
            ? "Terhubung ke " + escapeHtml(wifi.ssid || "?")
            : "Tidak terhubung"
        }</div>
        <div class="conn-ip">${
          wifiActive && wifi.ip ? "IP " + escapeHtml(wifi.ip) : "&nbsp;"
        }</div>
      </div>`;
  } catch (e) {
    box.innerHTML = `<div style="font-size:12px;color:#c0392b">Error: ${escapeHtml(
      String(e)
    )}</div>`;
  }
}

// ===== Konfigurasi WiFi AP =====
async function loadApConfig() {
  const setCur = (ssid, pass, channel, msg) => {
    const sEl = document.getElementById("apCurSsid");
    const pEl = document.getElementById("apCurPass");
    const cEl = document.getElementById("apCurChannel");
    if (sEl) sEl.textContent = ssid || (msg || "tidak tersedia");
    if (pEl) {
      // simpan password asli di dataset, tampilkan tersembunyi dulu
      pEl.dataset.real = pass || "";
      pEl.dataset.shown = "0";
      pEl.textContent = pass ? "••••••••" : (msg ? "—" : "tidak ada");
    }
    if (cEl) cEl.textContent = channel || "—";
  };

  try {
    const res = await fetch("/api/wifi/ap").then((r) => r.json());
    const chEl = document.getElementById("apChannel");
    if (!res.success) {
      if (chEl) chEl.textContent = res.message || "Konfigurasi AP tidak tersedia";
      setCur(null, null, null, res.message || "tidak tersedia");
      return;
    }
    // Isi form edit
    document.getElementById("apSsid").value = res.ssid || "";
    document.getElementById("apPass").value = res.password || "";
    if (chEl)
      chEl.textContent = res.channel
        ? `Channel saat ini: ${res.channel} (mengikuti channel router)`
        : "";
    // Isi kartu info ringkas
    setCur(res.ssid, res.password, res.channel);
  } catch (e) {
    setCur(null, null, null, "gagal memuat");
  }
}

// Toggle lihat password AP (form) + tombol mata/salin di kartu info
document.addEventListener("DOMContentLoaded", () => {
  const chk = document.getElementById("apShowPass");
  if (chk) {
    chk.addEventListener("change", (e) => {
      document.getElementById("apPass").type = e.target.checked
        ? "text"
        : "password";
    });
  }


  // Tombol mata di kartu info: tampilkan/sembunyikan password asli
  const eye = document.getElementById("apCurToggle");
  if (eye) {
    eye.addEventListener("click", () => {
      const pEl = document.getElementById("apCurPass");
      if (!pEl) return;
      const real = pEl.dataset.real || "";
      if (!real) {
        showToast("Password AP belum termuat", "info");
        return;
      }
      if (pEl.dataset.shown === "1") {
        pEl.textContent = "••••••••";
        pEl.dataset.shown = "0";
      } else {
        pEl.textContent = real;
        pEl.dataset.shown = "1";
      }
    });
  }

  // Tombol salin password
  const copy = document.getElementById("apCurCopy");
  if (copy) {
    copy.addEventListener("click", async () => {
      const pEl = document.getElementById("apCurPass");
      const real = pEl ? pEl.dataset.real || "" : "";
      if (!real) {
        showToast("Password AP belum termuat", "info");
        return;
      }
      try {
        await navigator.clipboard.writeText(real);
        showToast("Password AP disalin", "success");
      } catch (e) {
        showToast("Gagal menyalin (clipboard tidak diizinkan)", "error");
      }
    });
  }
});

async function saveApConfig() {
  const ssid = document.getElementById("apSsid").value.trim();
  const password = document.getElementById("apPass").value;
  const btn = document.getElementById("btnApSave");

  if (ssid.length < 1 || ssid.length > 32) {
    showToast("SSID harus 1-32 karakter", "error");
    return;
  }
  if (password && (password.length < 8 || password.length > 63)) {
    showToast("Password AP harus 8-63 karakter", "error");
    return;
  }

  const ok = await showDialog(
    "Ubah WiFi AP",
    `Simpan SSID "${ssid}" dan restart hotspot? Perangkat yang terhubung ke AP akan terputus sesaat.`
  );
  if (!ok) return;

  btn.disabled = true;
  btn.textContent = "Menyimpan...";
  try {
    const res = await fetch("/api/wifi/ap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssid, password }),
    }).then((r) => r.json());
    showToast(res.message, res.success ? "success" : "error", 6000);
    if (res.success) setTimeout(loadApConfig, 3000);
  } catch (e) {
    showToast("Gagal menyimpan AP: " + e, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Simpan & Restart AP";
  }
}


// ===== Manajemen Port Serial ESP32 =====

async function refreshPorts() {
  const statusBox = document.getElementById("portStatusBox");
  const sel = document.getElementById("portSelect");
  if (!statusBox || !sel) return;
  try {
    const r = await fetch("/api/serial/ports");
    const data = await r.json();
    if (!data.success) {
      statusBox.innerHTML = `<div style="color:#c62828;font-size:12px">${data.message || "Gagal memuat port"}</div>`;
      return;
    }

    // Status koneksi aktif
    const alive = data.alive;
    const active = data.active_port || "(belum terdeteksi)";
    const mode = data.auto_mode ? "Auto" : "Manual";
    statusBox.innerHTML = `
      <div class="conn-grid">
        <div class="conn-card ${alive ? "active" : ""}">
          <div class="conn-title">Mode: ${mode}</div>
          <div class="conn-state">${alive ? "ESP32 Terhubung" : "ESP32 Tidak terhubung"}</div>
          <div class="conn-ip">Port: ${escapeHtml(String(active))}</div>
        </div>
      </div>`;

    // Isi dropdown: Auto + tiap port
    const current = data.configured || "auto";
    let opts = `<option value="auto"${current === "auto" ? " selected" : ""}>Auto (deteksi otomatis)</option>`;
    (data.ports || []).forEach((p) => {
      const tag = p.likely_esp32 ? " ★" : "";
      const kind = p.is_gpio ? "GPIO" : "USB";
      const selected = current === p.device ? " selected" : "";
      opts += `<option value="${p.device}"${selected}>${p.device} — ${p.description} [${kind}]${tag}</option>`;
    });
    // Bila port tersimpan tidak ada di daftar (mis. perangkat belum colok), tetap tampilkan
    if (current !== "auto" && !(data.ports || []).some((p) => p.device === current)) {
      opts += `<option value="${current}" selected>${current} (tersimpan, tidak terdeteksi)</option>`;
    }
    sel.innerHTML = opts;
  } catch (e) {
    statusBox.innerHTML = `<div style="color:#c62828;font-size:12px">Error: ${e.message}</div>`;
  }
}

async function testSelectedPort() {
  const sel = document.getElementById("portSelect");
  const resEl = document.getElementById("portTestResult");
  const btn = document.getElementById("testPortBtn");
  if (!sel || !resEl) return;
  const port = sel.value;

  if (port === "auto") {
    resEl.style.display = "block";
    resEl.style.color = "#666";
    resEl.textContent =
      "Mode Auto menguji semua port saat dijalankan. Pilih port spesifik untuk uji handshake langsung.";
    return;
  }

  btn.disabled = true;
  resEl.style.display = "block";
  resEl.style.color = "#666";
  resEl.textContent = `Menguji ${port}…`;
  try {
    const r = await fetch("/api/serial/test_port", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port: port }),
    });
    const data = await r.json();
    resEl.style.color = data.success ? "#2e7d32" : "#c62828";
    resEl.textContent = (data.success ? "✓ " : "✗ ") + (data.message || "");
  } catch (e) {
    resEl.style.color = "#c62828";
    resEl.textContent = "Error: " + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function saveSelectedPort() {
  const sel = document.getElementById("portSelect");
  const resEl = document.getElementById("portTestResult");
  const btn = document.getElementById("savePortBtn");
  if (!sel) return;
  const port = sel.value;

  const ok = await showDialog(
    "Simpan Port Serial",
    `Pindahkan koneksi ESP32 ke "${port}" dan simpan? Koneksi akan dihubungkan ulang.`,
  );
  if (!ok) return;

  btn.disabled = true;
  if (resEl) {
    resEl.style.display = "block";
    resEl.style.color = "#666";
    resEl.textContent = "Menyimpan & menghubungkan…";
  }
  try {
    const r = await fetch("/api/serial/set_port", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port: port }),
    });
    const data = await r.json();
    if (data.success) {
      showToast(data.message || "Port disimpan", "success");
    } else {
      showToast(data.message || "Port disimpan, menunggu koneksi", "info");
    }
    if (resEl) {
      resEl.style.color = data.success ? "#2e7d32" : "#e65100";
      resEl.textContent = (data.success ? "✓ " : "… ") + (data.message || "");
    }
    setTimeout(refreshPorts, 1500);
  } catch (e) {
    showToast("Error: " + e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

// ===== Konfigurasi Operasional (max attempts, cooldown, jam kerja) =====
function loadOperationalConfig() {
  fetch("/api/config")
    .then((r) => r.json())
    .then((data) => {
      const m = document.getElementById("maxAttemptsInput");
      const c = document.getElementById("cooldownInput");
      const ws = document.getElementById("whStartInput");
      const wp = document.getElementById("whStopInput");
      if (m) m.value = data.max_attempts || 5;
      if (c) c.value = data.cooldown || 300;
      const wh = data.working_hours || {};
      if (ws) ws.value = wh.start || "07:00";
      if (wp) wp.value = wh.stop || "17:00";
    })
    .catch(() => {});
}

async function saveOperationalConfig() {
  const mEl = document.getElementById("maxAttemptsInput");
  const cEl = document.getElementById("cooldownInput");
  const wsEl = document.getElementById("whStartInput");
  const wpEl = document.getElementById("whStopInput");

  const maxAttempts = mEl ? parseInt(mEl.value) || 5 : 5;
  const cooldown = cEl ? parseInt(cEl.value) || 300 : 300;
  const whStart = wsEl ? wsEl.value || "07:00" : "07:00";
  const whStop = wpEl ? wpEl.value || "17:00" : "17:00";

  if (maxAttempts < 1 || maxAttempts > 10) {
    showToast("Max Attempts harus 1-10", "error");
    return;
  }
  if (cooldown < 60 || cooldown > 3600) {
    showToast("Cooldown harus 60-3600 detik", "error");
    return;
  }

  const ok = await showDialog(
    "Simpan Konfigurasi",
    `Max Attempts: ${maxAttempts}x\nCooldown: ${cooldown} detik (${(
      cooldown / 60
    ).toFixed(1)} menit)\nJam kerja: ${whStart}-${whStop}\n\n` +
      "Perubahan langsung berlaku. Jika cooldown sedang berjalan, durasi baru " +
      "akan diterapkan pada siklus berikutnya."
  );
  if (!ok) return;

  const payload = {
    max_attempts: maxAttempts,
    cooldown: cooldown,
    working_hours: { enabled: true, start: whStart, stop: whStop },
  };

  try {
    const res = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => r.json());
    if (res.success) {
      showToast("Konfigurasi disimpan!", "success");
      loadOperationalConfig();
    } else {
      showToast(res.error || "Gagal menyimpan", "error");
    }
  } catch (err) {
    console.error("Save operational config error:", err);
    showToast("Gagal menyimpan konfigurasi", "error");
  }
}
