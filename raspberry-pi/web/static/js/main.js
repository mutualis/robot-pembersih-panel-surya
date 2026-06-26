/**
 * Main Dashboard JavaScript
 * Solar Panel Cleaner - Web Interface
 */

let dialogCallback = null;

// ===== TOAST NOTIFICATION =====
function showToast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'toastOut 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ===== DIALOG =====
function showDialog(title, message) {
    return new Promise((resolve) => {
        document.getElementById('dialogTitle').textContent = title;
        document.getElementById('dialogMessage').textContent = message;
        document.getElementById('dialogOverlay').classList.add('show');
        dialogCallback = resolve;
    });
}

function closeDialog(result) {
    document.getElementById('dialogOverlay').classList.remove('show');
    if (dialogCallback) { dialogCallback(result); dialogCallback = null; }
}

// ===== PREVIEW =====
let previewActive = false;
let previewDetection = false;

function updatePreview() {
    // No-op — preview now uses MJPEG stream (/api/preview/stream).
    // Kept for compatibility with any remaining callers.
}

function _startMJPEGStream() {
    if (!previewActive) return;
    const img = document.getElementById('preview');
    if (!img) return;
    // Append timestamp to bust any cached connection
    img.src = `/api/preview/stream?t=${Date.now()}`;
    img.style.display = 'block';
    const off = document.getElementById('previewOff');
    if (off) off.style.display = 'none';
}

function _stopMJPEGStream() {
    const img = document.getElementById('preview');
    if (!img) return;
    // Setting src to empty stops the browser from holding the connection
    img.src = '';
    img.style.display = 'none';
    const off = document.getElementById('previewOff');
    if (off) off.style.display = 'flex';
}

async function togglePreview() {
    try {
        const r = await fetch('/api/preview/toggle', { method: 'POST' });
        // Jika ditolak (sesi habis / belum diizinkan), auth.js sudah memunculkan
        // modal login — hindari toast menyesatkan "preview dimatikan".
        if (r.status === 401) return;
        if (!r.ok) {
            showToast('Gagal toggle preview', 'error');
            return;
        }
        const data = await r.json();
        previewActive = data.preview_active;
        
        const btn = document.getElementById('btnTogglePreview');
        const btnDet = document.getElementById('btnToggleDetection');
        
        if (previewActive) {
            btn.textContent = 'Matikan Preview';
            btn.className = 'btn btn-danger';
            if (btnDet) btnDet.style.display = '';
            _startMJPEGStream();
            showToast('Preview kamera dinyalakan', 'success');
        } else {
            btn.textContent = 'Nyalakan Preview';
            btn.className = 'btn btn-success';
            if (btnDet) btnDet.style.display = 'none';
            _stopMJPEGStream();
            // Turn off detection overlay when preview is off
            if (previewDetection) {
                previewDetection = false;
                fetch('/api/preview/detection/toggle', { method: 'POST' });
                updateDetectionButton();
            }
            showToast('Preview kamera dimatikan', 'info');
        }
    } catch (e) {
        showToast('Gagal toggle preview', 'error');
    }
}

async function togglePreviewDetection() {
    try {
        const r = await fetch('/api/preview/detection/toggle', { method: 'POST' });
        if (r.status === 401) return;
        if (!r.ok) {
            showToast('Gagal toggle deteksi', 'error');
            return;
        }
        const data = await r.json();
        previewDetection = data.preview_detection;
        updateDetectionButton();
        showToast(previewDetection ? 'Deteksi YOLO dinyalakan pada preview' : 'Deteksi YOLO dimatikan', previewDetection ? 'success' : 'info');
    } catch (e) {
        showToast('Gagal toggle deteksi', 'error');
    }
}

function updateDetectionButton() {
    const btn = document.getElementById('btnToggleDetection');
    if (!btn) return;
    if (previewDetection) {
        btn.textContent = 'Deteksi: ON';
        btn.className = 'btn btn-success';
    } else {
        btn.textContent = 'Deteksi: OFF';
        btn.className = 'btn btn-outline';
    }
}

// ===== STATUS UPDATE (from WebSocket or polling) =====
function updateStatus(data) {
    const mode = document.getElementById('systemMode');
    const esp32 = document.getElementById('esp32Status');
    const cleaning = document.getElementById('cleaningStatus');
    const lastCapture = document.getElementById('lastCapture');
    const cameraStatus = document.getElementById('cameraStatus');
    const yoloStatus = document.getElementById('yoloStatus');
    const serialStatus = document.getElementById('serialStatus');

    // Track previous cleaning state to detect transitions
    if (!window._prevCleaningActive) window._prevCleaningActive = false;
    const wasCleaningActive = window._prevCleaningActive;
    const isCleaningActive = data.cleaning_active || false;
    window._prevCleaningActive = isCleaningActive;

    // Reset progress bar when cleaning finishes (transition from active to inactive)
    if (wasCleaningActive && !isCleaningActive) {
        const bar = document.getElementById('liveProgress');
        const barText = document.getElementById('liveProgressText');
        if (bar) {
            bar.style.width = '0%';
            bar.textContent = '0%';
        }
        if (barText) {
            barText.textContent = '0%';
        }
        console.log('[Dashboard] Progress bar reset (cleaning finished)');
    }

    if (mode) {
        // Mode display berdasarkan status sistem
        if (data.cleaning_active) {
            mode.textContent = 'Pembersihan';
            mode.style.color = '#dc3545';
        } else if (data.mode === 'verifying') {
            mode.textContent = 'Verifikasi';
            mode.style.color = '#ffc107';
        } else if (data.mode === 'waiting_camera') {
            mode.textContent = 'Menunggu Kamera';
            mode.style.color = '#dc3545';
        } else if (data.mode === 'detect_only') {
            mode.textContent = 'Deteksi Saja';
            mode.style.color = '#ffc107';
        } else if (data.mode === 'monitoring' || data.running) {
            mode.textContent = 'Monitoring';
            mode.style.color = '#28a745';
        } else {
            mode.textContent = 'Siaga';
            mode.style.color = '#6c757d';
        }
    }
    if (esp32) {
        esp32.textContent = data.esp32_connected ? 'Terhubung' : 'Terputus';
        esp32.style.color = data.esp32_connected ? '#28a745' : '#dc3545';
    }
    if (cleaning) {
        cleaning.textContent = data.cleaning_active ? 'Aktif' : 'Tidak Aktif';
        cleaning.style.color = data.cleaning_active ? '#28a745' : '#003d7a';
    }

    // Last cleaning time
    const lastCleaning = document.getElementById('lastCleaning');
    if (lastCleaning) {
        if (data.last_cleaning) {
            lastCleaning.textContent = new Date(data.last_cleaning).toLocaleTimeString('id-ID');
            lastCleaning.style.color = '#28a745';
        } else {
            lastCleaning.textContent = 'Belum pernah';
            lastCleaning.style.color = '#666';
        }
    }

    // Cooldown remaining — frontend calculates from timestamp for smooth countdown
    const cooldownStatus = document.getElementById('cooldownStatus');
    if (cooldownStatus) {
        const mode = data.mode || '';
        if (mode === 'verifying' || data.cleaning_active) {
            cooldownStatus.textContent = 'Menunggu Pembersihan';
            cooldownStatus.style.color = '#17a2b8';
            if (window._cooldownTimer) {
                clearInterval(window._cooldownTimer);
                window._cooldownTimer = null;
            }
        } else if (mode === 'waiting_camera') {
            cooldownStatus.textContent = 'Menunggu Kamera';
            cooldownStatus.style.color = '#dc3545';
            if (window._cooldownTimer) {
                clearInterval(window._cooldownTimer);
                window._cooldownTimer = null;
            }
        } else if (mode === 'off_hours') {
            const wh = data.working_hours || {};
            cooldownStatus.textContent = 'Di luar jam kerja' + (wh.start ? ` (${wh.start}-${wh.stop})` : '');
            cooldownStatus.style.color = '#6c757d';
            if (window._cooldownTimer) {
                clearInterval(window._cooldownTimer);
                window._cooldownTimer = null;
            }
        } else if (mode === 'detect_only' && !data.cooldown_start) {
            cooldownStatus.textContent = 'Pause (ESP32 Terputus)';
            cooldownStatus.style.color = '#dc3545';
            if (window._cooldownTimer) {
                clearInterval(window._cooldownTimer);
                window._cooldownTimer = null;
            }
        } else if (data.cooldown_start && data.cooldown_duration > 0) {
            // Start client-side countdown timer if not already running
            if (!window._cooldownTimer || window._cooldownStart !== data.cooldown_start) {
                window._cooldownStart = data.cooldown_start;
                window._cooldownDuration = data.cooldown_duration;
                if (window._cooldownTimer) clearInterval(window._cooldownTimer);
                
                const updateCooldown = () => {
                    const startTime = new Date(window._cooldownStart).getTime();
                    const now = Date.now();
                    const elapsed = (now - startTime) / 1000;
                    const remaining = Math.max(0, Math.ceil(window._cooldownDuration - elapsed));
                    
                    if (remaining > 0) {
                        const min = Math.floor(remaining / 60);
                        const sec = remaining % 60;
                        cooldownStatus.textContent = `${min}m ${String(sec).padStart(2, '0')}s`;
                        cooldownStatus.style.color = '#ffc107';
                    } else {
                        cooldownStatus.textContent = 'Siap';
                        cooldownStatus.style.color = '#28a745';
                        clearInterval(window._cooldownTimer);
                        window._cooldownTimer = null;
                        window._cooldownStart = null;
                    }
                };
                updateCooldown();
                window._cooldownTimer = setInterval(updateCooldown, 1000);
            }
        } else {
            // No cooldown active
            if (window._cooldownTimer) {
                clearInterval(window._cooldownTimer);
                window._cooldownTimer = null;
                window._cooldownStart = null;
            }
            cooldownStatus.textContent = 'Siap';
            cooldownStatus.style.color = '#28a745';
        }
    }

    if (lastCapture && data.last_capture) {
        lastCapture.textContent = new Date(data.last_capture).toLocaleTimeString('id-ID');
    }

    // Raspberry Pi component status
    if (cameraStatus) {
        if (data.camera_type === 'real') {
            cameraStatus.textContent = 'Terhubung';
            cameraStatus.style.color = '#28a745';
        } else {
            cameraStatus.textContent = 'Tidak Terdeteksi';
            cameraStatus.style.color = '#dc3545';
        }
    }
    if (yoloStatus) {
        if (data.yolo_type === 'two_stage') {
            yoloStatus.textContent = 'Two-Stage';
            yoloStatus.style.color = '#28a745';
        } else if (data.yolo_type === 'single_stage') {
            yoloStatus.textContent = 'Single-Stage';
            yoloStatus.style.color = '#28a745';
        } else {
            yoloStatus.textContent = 'Belum Di-load';
            yoloStatus.style.color = '#dc3545';
        }
    }
    if (serialStatus) {
        if (data.serial_open) {
            serialStatus.textContent = data.serial_port || 'Open';
            serialStatus.style.color = '#28a745';
        } else {
            serialStatus.textContent = 'Tidak terhubung';
            serialStatus.style.color = '#dc3545';
        }
    }

    // Disable/enable hardware-dependent buttons
    const btnCapture = document.querySelector('[onclick="captureNow()"]');
    const btnClean = document.querySelector('[onclick="triggerCleaning()"]');
    const btnStop = document.querySelector('[onclick="emergencyStop()"]');
    
    const cameraConnected = data.camera_type === 'real';
    const esp32Connected = data.esp32_connected;
    
    // Capture button - requires camera
    if (btnCapture) {
        btnCapture.disabled = !cameraConnected;
        btnCapture.style.opacity = cameraConnected ? '1' : '0.4';
        btnCapture.style.cursor = cameraConnected ? 'pointer' : 'not-allowed';
    }
    
    // Clean & Stop buttons - require ESP32
    if (btnClean) {
        const canClean = esp32Connected && !data.cleaning_active;
        btnClean.disabled = !canClean;
        btnClean.style.opacity = canClean ? '1' : '0.4';
        btnClean.style.cursor = canClean ? 'pointer' : 'not-allowed';
        btnClean.textContent = data.cleaning_active ? 'Membersihkan...' : 'Deteksi & Bersihkan';
    }
    if (btnStop) {
        btnStop.disabled = !esp32Connected;
        btnStop.style.opacity = esp32Connected ? '1' : '0.4';
        btnStop.style.cursor = esp32Connected ? 'pointer' : 'not-allowed';
    }

    // Update live cleaning data from ESP32 (selalu update)
    updateCleaningLive(data);

    // Sync preview state from WebSocket
    if (data.preview_active !== undefined && data.preview_active !== previewActive) {
        previewActive = data.preview_active;
        const btn    = document.getElementById('btnTogglePreview');
        const btnDet = document.getElementById('btnToggleDetection');
        if (btn) {
            if (previewActive) {
                btn.textContent = 'Matikan Preview';
                btn.className = 'btn btn-danger';
                if (btnDet) btnDet.style.display = '';
                _startMJPEGStream();
            } else {
                btn.textContent = 'Nyalakan Preview';
                btn.className = 'btn btn-success';
                if (btnDet) btnDet.style.display = 'none';
                _stopMJPEGStream();
            }
        }
    }

    // Update detection result if available
    if (data.last_detection && data.last_detection.results) {
        updateDetectionDisplay(data.last_detection.results[0], data.last_detection.timestamp);
    }
}

// ===== CLEANING LIVE VISUALIZATION =====
// Map ESP32 states (Indonesian) to 3D viewer FSM states (English)
const esp32ToFSM = {
    '': 'IDLE',  // Empty string = idle
    'IDLE': 'IDLE',
    'PRE_CHECK': 'HOMING',
    'MOVING_TO_START': 'HOMING',
    'SPRAYING_WATER': 'SPRAYING',
    'CLEANING_FORWARD': 'CLEANING_DOWN',
    'CLEANING_BACKWARD': 'CLEANING_UP',
    'STOPPING': 'RETURNING',
    'DONE': 'IDLE',
    'ERROR_STATE': 'ERROR'
};

// ESP32 state descriptions (label tampilan Bahasa Indonesia, di-key dengan
// nama state English yang dikirim ESP32)
const esp32StateDescriptions = {
    '': 'Siaga - Menunggu perintah pembersihan',
    'IDLE': 'Siaga - Menunggu perintah pembersihan',
    'PRE_CHECK': 'Pemeriksaan awal - Cek limit switch dan motor',
    'MOVING_TO_START': 'Bergerak ke posisi awal (LS1 atas)',
    'SPRAYING_WATER': 'Penyemprotan air - Pompa aktif',
    'CLEANING_FORWARD': 'Pembersihan maju - Wiper + brush bergerak ke bawah',
    'CLEANING_BACKWARD': 'Pembersihan mundur - Wiper kembali ke atas (pengeringan)',
    'STOPPING': 'Menghentikan - Mematikan semua motor',
    'DONE': 'Selesai - Pembersihan selesai',
    'ERROR_STATE': 'Error - Terjadi kesalahan'
};

// FSM state icons
const fsmIcons = {
    'IDLE': '◇',
    'HOMING': '↑',
    'SPRAYING': '💧',
    'CLEANING_DOWN': '↓',
    'CLEANING_UP': '↑',
    'RETURNING': '⤴',
    'ERROR': '!'
};

/**
 * Update status display in dashboard
 */
function updateStatusDisplay(esp32State, fsmState) {
    const statusText = document.getElementById('statusText');
    const statusIcon = document.getElementById('statusIcon');
    
    if (statusText) {
        const description = esp32StateDescriptions[esp32State] || 'Status tidak diketahui';
        statusText.textContent = description;
    }
    
    if (statusIcon) {
        const icon = fsmIcons[fsmState] || '◇';
        statusIcon.textContent = icon;
    }
}

/**
 * Update wiper position display
 */
function updateWiperPosition(position_mm) {
    const positionEl = document.getElementById('wiperPosition');
    if (positionEl) {
        if (position_mm !== undefined && position_mm !== null) {
            positionEl.textContent = `Posisi: ${position_mm.toFixed(1)} mm`;
        } else {
            positionEl.textContent = 'Posisi: -- mm';
        }
    }
}

function updateCleaningLive(data) {
    const progress = data.progress || 0;
    const state    = data.esp32_state || '';
    const wiperRpm = data.wiper_rpm || 0;
    const wiperTarget = data.wiper_target || 0;
    const brushRpm = data.brush_rpm || 0;
    const brushTarget = data.brush_target || 0;
    const pump     = data.pump || false;
    const ls1      = data.ls1 || false;
    const ls2      = data.ls2 || false;
    const level    = data.cleaning_level || '';
    const currentPass = data.current_pass || 0;
    const totalPasses = data.total_passes || 0;

    // Progress bar - update if cleaning is active OR if we just finished (to show 100%)
    // After cleaning finishes, updateStatus() will reset it to 0%
    const isCleaningActive = data.cleaning_active || false;
    const bar = document.getElementById('liveProgress');
    const barText = document.getElementById('liveProgressText');
    
    if (isCleaningActive || progress === 100) {
        // Cleaning active or just finished (100%) - update progress
        if (bar) {
            bar.style.width = progress + '%';
            bar.textContent = progress + '%';
        }
        if (barText) {
            barText.textContent = progress + '%';
        }
    } else if (progress > 0 && !isCleaningActive) {
        // Stale data (progress > 0 but cleaning not active) - force to 0%
        if (bar && bar.style.width !== '0%') {
            bar.style.width = '0%';
            bar.textContent = '0%';
        }
        if (barText && barText.textContent !== '0%') {
            barText.textContent = '0%';
        }
    }

    // Wiper — tampilkan aktual vs target (memvisualkan kerja PID closed-loop)
    const wiperEl = document.getElementById('liveWiperRpm');
    if (wiperEl) {
        if (wiperRpm > 0 || wiperTarget > 0) {
            wiperEl.textContent = `${wiperRpm.toFixed(1)} / ${wiperTarget.toFixed(0)} RPM`;
        } else {
            wiperEl.textContent = 'Mati';
        }
    }

    // Brush — open-loop, tampilkan target RPM
    const brushEl = document.getElementById('liveBrushRpm');
    if (brushEl) {
        const b = brushTarget > 0 ? brushTarget : brushRpm;
        brushEl.textContent = b > 0 ? `${b.toFixed(0)} RPM` : 'Mati';
    }

    // Strategi adaptif: level + pass (inti Bab 4)
    const levelBadge = document.getElementById('cleaningLevelBadge');
    const passBadge = document.getElementById('cleaningPassBadge');
    const showStrategy = isCleaningActive && level &&
                         level !== 'TIDAK_DIKETAHUI';
    if (levelBadge) {
        if (showStrategy) {
            levelBadge.textContent = 'Level: ' + level;
            levelBadge.style.display = 'inline-block';
        } else {
            levelBadge.style.display = 'none';
        }
    }
    if (passBadge) {
        if (showStrategy && totalPasses > 0) {
            passBadge.textContent = `Pass: ${currentPass}/${totalPasses}`;
            passBadge.style.display = 'inline-block';
        } else {
            passBadge.style.display = 'none';
        }
    }

    // Pump
    const pumpEl = document.getElementById('livePump');
    if (pumpEl) {
        pumpEl.textContent = pump ? 'Aktif' : 'Mati';
        pumpEl.style.color = pump ? '#007bff' : '#666';
    }

    // Limit switches
    const lsEl = document.getElementById('liveLS');
    if (lsEl) lsEl.textContent = `LS1: ${ls1 ? 'ON' : '-'} | LS2: ${ls2 ? 'ON' : '-'}`;
}
function updateDetectionDisplay(result, timestamp) {
    const panel = document.getElementById('panelDetected');
    const dirt = document.getElementById('dirtLevel');
    const conf = document.getElementById('dirtConfidence');
    const score = document.getElementById('weightedScore');
    const decision = document.getElementById('decision');
    const timeEl = document.getElementById('detectionTime');

    // Format waktu deteksi (ISO → "DD Mon YYYY, HH.MM.SS") bila tersedia
    if (timeEl) {
        if (timestamp) {
            const d = new Date(timestamp);
            if (!isNaN(d.getTime())) {
                const tgl = d.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
                const jam = d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                timeEl.textContent = `${tgl}, ${jam}`;
            } else {
                timeEl.textContent = '--';
            }
        } else if (!result) {
            timeEl.textContent = '--';
        }
    }

    if (!result) {
        if (panel) panel.textContent = 'Tidak';
        if (dirt) dirt.textContent = '--';
        if (conf) conf.textContent = '--';
        if (score) score.textContent = '--';
        if (decision) { decision.textContent = 'Tidak ada panel terdeteksi'; decision.style.color = '#999'; }
        return;
    }

    if (panel) panel.textContent = result.panel_detected ? 'Ya' : 'Tidak';
    if (dirt) dirt.textContent = result.dirt_level || '--';
    if (conf) conf.textContent = result.dirt_confidence ? (result.dirt_confidence * 100).toFixed(1) + '%' : '--';
    if (score) score.textContent = result.weighted_score !== undefined ? result.weighted_score.toFixed(1) : '--';
    if (decision) {
        if (!result.panel_detected) {
            decision.textContent = 'Panel tidak terdeteksi';
            decision.style.color = '#999';
        } else if (result.dirt_level === 'unknown') {
            decision.textContent = 'Model belum di-load';
            decision.style.color = '#999';
        } else if (result.clean) {
            decision.textContent = 'Bersih - Tidak perlu pembersihan';
            decision.style.color = '#28a745';
        } else {
            decision.textContent = 'Kotor - Perlu pembersihan!';
            decision.style.color = '#dc3545';
        }
    }
}

// ===== CLEANING PROGRESS (from ESP32 response) =====
function updateCleaningProgress(progress, wiperRpm, brushRpm) {
    const bar = document.getElementById('cleaningProgress');
    const wiper = document.getElementById('wiperRpm');
    const brush = document.getElementById('brushRpm');

    if (bar) { bar.style.width = progress + '%'; bar.textContent = progress + '%'; }
    if (wiper) wiper.textContent = wiperRpm ? wiperRpm.toFixed(1) : '0';
    if (brush) brush.textContent = brushRpm ? brushRpm.toFixed(1) : '0';
}

// ===== CAPTURE & ANALYZE =====
async function captureNow() {
    // Cek camera connected
    const status = await fetch('/api/status').then(r => r.json()).catch(() => ({}));
    if (status.camera_type !== 'real') {
        showToast('Kamera tidak terdeteksi. Sambungkan kamera terlebih dahulu.', 'error', 4000);
        return;
    }

    const btn = document.querySelector('[onclick="captureNow()"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Memproses...'; }

    fetch('/api/capture', { method: 'POST' })
        .then(r => {
            if (!r.ok) return r.json().then(d => { throw d; });
            return r.json();
        })
        .then(data => {
            // Show annotated image directly in preview
            if (data.image) {
                const img = document.getElementById('preview');
                const off = document.getElementById('previewOff');
                if (img) { img.src = data.image; img.style.display = 'block'; }
                if (off) off.style.display = 'none';
            }

            // Update detection result panel with fresh data
            if (data.results && data.results.length > 0) {
                updateDetectionDisplay(data.results[0], data.timestamp || new Date().toISOString());
            } else {
                // No results — clear display
                updateDetectionDisplay(null);
            }

            showToast('Capture & analisis selesai', 'success');
        })
        .catch(err => {
            const msg = err.error || 'Capture gagal';
            showToast(msg, 'error');
        })
        .finally(() => {
            if (btn) { btn.disabled = false; btn.textContent = 'Capture & Analisis'; }
        });
}

// ===== TRIGGER CLEANING =====
async function triggerCleaning() {
    // Cek ESP32 connected via cached WS status
    const status = await fetch('/api/status').then(r => r.json()).catch(() => ({}));
    if (!status.esp32_connected) {
        showToast('ESP32 tidak terhubung', 'error', 4000);
        return;
    }
    if (status.cleaning_active) {
        showToast('Pembersihan sudah berjalan', 'warning');
        return;
    }

    const confirmed = await showDialog('Bersihkan Manual',
        'Tangkap gambar → deteksi YOLO → bersihkan otomatis sesuai tingkat kekotoran yang terdeteksi.\n\n' +
        'Jika panel bersih (score < 70), pembersihan tidak dijalankan. Siklus ini DICATAT ke laporan.\nPastikan area sekitar robot aman.');
    if (!confirmed) return;

    const btn = document.querySelector('[onclick="triggerCleaning()"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Mendeteksi...'; }

    try {
        const r = await fetch('/api/detect_and_clean', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await r.json();

        if (data.success) {
            if (data.cleaning) {
                showToast(data.message || 'Pembersihan dimulai', 'success');
                // Tombol di-reset oleh updateStatus saat cleaning_active jadi false
            } else {
                // Panel bersih / tak terdeteksi — tidak ada pembersihan
                showToast(data.message || 'Panel bersih, tidak perlu pembersihan', 'info');
                if (btn) { btn.disabled = false; btn.textContent = 'Deteksi & Bersihkan'; }
            }
        } else {
            showToast(data.message || 'Gagal memulai pembersihan', 'error');
            if (btn) { btn.disabled = false; btn.textContent = 'Deteksi & Bersihkan'; }
        }
    } catch (err) {
        showToast('Gagal memulai pembersihan', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Deteksi & Bersihkan'; }
    }
}

// ===== EMERGENCY STOP =====
async function emergencyStop() {
    // Emergency stop langsung kirim tanpa cek (best effort)
    const confirmed = await showDialog('EMERGENCY STOP', 'Stop semua operasi sekarang?');
    if (confirmed) {
        fetch('/api/emergency_stop', { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.success) showToast('Emergency stop executed', 'success');
                else showToast('ESP32 tidak merespons', 'error');
            })
            .catch(() => showToast('ESP32 tidak terhubung', 'error'));
    }
}

// ===== CONFIG (view-only di dashboard; edit di halaman Settings) =====
function loadConfig() {
    fetch('/api/config')
        .then(r => r.json())
        .then(data => {
            const ma = document.getElementById('cfgMaxAttempts');
            const cd = document.getElementById('cfgCooldown');
            const wh = document.getElementById('cfgWorkingHours');
            if (ma) ma.textContent = (data.max_attempts || 5) + 'x';
            if (cd) {
                const s = data.cooldown || 300;
                cd.textContent = s + ' detik (' + (s / 60).toFixed(1) + ' menit)';
            }
            if (wh) {
                const w = data.working_hours || {};
                wh.textContent = (w.enabled === false)
                    ? 'Nonaktif (24 jam)'
                    : ((w.start || '07:00') + ' - ' + (w.stop || '17:00'));
            }
        })
        .catch(() => {});
}

// ===== INITIALIZATION =====
document.addEventListener('DOMContentLoaded', function() {
    // Dialog overlay click
    const overlay = document.getElementById('dialogOverlay');
    if (overlay) {
        overlay.addEventListener('click', (e) => {
            if (e.target.id === 'dialogOverlay') closeDialog(false);
        });
    }

    // Only init dashboard features if on dashboard page
    if (document.getElementById('preview')) {
        // Preview starts OFF — user must click to enable
        document.getElementById('preview').style.display = 'none';
        document.getElementById('previewOff').style.display = 'flex';
        
        loadConfig();
        // Preview uses MJPEG stream — no polling interval needed

        // Register WebSocket callback
        if (typeof statusMonitor !== 'undefined') {
            statusMonitor.onStatusUpdate(updateStatus);
        } else {
            setTimeout(() => {
                if (typeof statusMonitor !== 'undefined') {
                    statusMonitor.onStatusUpdate(updateStatus);
                }
            }, 1000);
        }
    }
});


// ===== 3D VISUALIZATION CONTROL =====
/**
 * Send command to 3D visualization iframe
 * @param {string} command - Command name (e.g., 'updateState', 'setPosition', 'toggleBrush', 'togglePump')
 * @param {object} data - Command data
 */
function send3DCommand(command, data = {}) {
    const iframe = document.getElementById('visualization3D');
    if (!iframe || !iframe.contentWindow) {
        console.warn('[3D] Iframe not ready');
        return;
    }
    
    console.log('[3D Command]', command, data);
    
    iframe.contentWindow.postMessage({
        type: '3d-control',
        command: command,
        data: data
    }, '*');
}

/**
 * Test 3D animation without ESP32 (for development/demo)
 */
function test3DAnimation() {
    console.log('[3D Test] Starting animation test sequence');
    
    // Simulate cleaning cycle
    setTimeout(() => {
        console.log('[3D Test] → HOMING');
        send3DCommand('updateState', { fsm: 'HOMING' });
    }, 500);
    
    setTimeout(() => {
        console.log('[3D Test] → CLEANING_DOWN');
        send3DCommand('updateState', { fsm: 'CLEANING_DOWN', brush_active: true });
    }, 5000);
    
    setTimeout(() => {
        console.log('[3D Test] → CLEANING_UP');
        send3DCommand('updateState', { fsm: 'CLEANING_UP', brush_active: true });
    }, 15000);
    
    setTimeout(() => {
        console.log('[3D Test] → RETURNING');
        send3DCommand('updateState', { fsm: 'RETURNING', brush_active: false });
    }, 25000);
    
    setTimeout(() => {
        console.log('[3D Test] → IDLE');
        send3DCommand('updateState', { fsm: 'IDLE' });
    }, 27000);
}

// Expose functions to console for testing
window.test3DAnimation = test3DAnimation;
window.send3DCommand = send3DCommand;

console.log('[3D] Test functions available: test3DAnimation(), send3DCommand(command, data)');

/**
 * Update 3D visualization based on system status
 * Called from websocket status updates
 */
function update3DVisualization(status) {
    if (!status) return;
    
    console.log('[3D Update] Received status:', {
        esp32_state: status.esp32_state,
        position_mm: status.position_mm,
        wiper_rpm: status.wiper_rpm,
        brush_rpm: status.brush_rpm,
        pump: status.pump
    });
    
    // Update FSM state - convert ESP32 state to 3D viewer FSM state
    // Handle empty string as undefined
    const esp32State = status.esp32_state || status.fsm_state || '';
    const fsmState = esp32ToFSM[esp32State] || 'IDLE';
    
    console.log('[3D Update] ESP32 state:', `"${esp32State}"`, '→ FSM state:', fsmState);
    
    // Update status text in dashboard
    updateStatusDisplay(esp32State, fsmState);
    
    // Update wiper position display
    updateWiperPosition(status.position_mm);
    
    // Only send position_mm if we have real data from ESP32 (not default 0)
    // This allows animation to work when ESP32 is not connected
    const hasRealPosition = status.position_mm !== undefined && status.position_mm !== null && status.position_mm > 0;
    
    // Brush TIDAK punya encoder → brush_rpm aktual selalu 0 dari ESP32.
    // Status aktif brush ditentukan dari brush_target (RPM yang diperintahkan).
    const brushActive = (status.brush_target || 0) > 0;
    
    send3DCommand('updateState', {
        fsm: fsmState,
        esp32_state: esp32State,  // Send detailed ESP32 state for display
        position_mm: hasRealPosition ? status.position_mm : undefined, // Don't send 0, let animation work
        rpm: status.wiper_rpm || 0,
        rpm_target: status.wiper_target || 0,
        brush_rpm: status.brush_target || 0,   // target karena tak ada encoder
        brush_active: brushActive,
        pump_active: status.pump || false,
        cleaning_level: status.cleaning_level || '',
        current_pass: status.current_pass || 0,
        total_passes: status.total_passes || 0,
        estop: status.emergency_stop || false
    });
    
    // Only update position if we have real data from ESP32
    if (hasRealPosition) {
        send3DCommand('setPosition', {
            position_mm: status.position_mm
        });
    }
    
    // Update brush motor
    send3DCommand('toggleBrush', {
        active: brushActive
    });
    
    // Update pump
    if (typeof status.pump === 'boolean') {
        send3DCommand('togglePump', {
            active: status.pump
        });
    }
}

// Listen for status updates from websocket and update 3D visualization
// Wait for statusMonitor to be initialized
function init3DIntegration() {
    // Check if statusMonitor exists (from websocket.js)
    if (window.statusMonitor && typeof window.statusMonitor.onStatusUpdate === 'function') {
        window.statusMonitor.onStatusUpdate((status) => {
            update3DVisualization(status);
        });
        console.log('[3D Integration] ✅ Connected to status monitor');
        return true;
    }
    return false;
}

// Retry mechanism with exponential backoff
let retryCount = 0;
const maxRetries = 10;

function tryInit3DIntegration() {
    if (init3DIntegration()) {
        console.log('[3D Integration] Successfully initialized');
        return;
    }
    
    retryCount++;
    if (retryCount < maxRetries) {
        const delay = Math.min(100 * Math.pow(1.5, retryCount), 3000); // Max 3s
        console.log(`[3D Integration] Retry ${retryCount}/${maxRetries} in ${delay}ms...`);
        setTimeout(tryInit3DIntegration, delay);
    } else {
        console.warn('[3D Integration] ⚠️ Failed to connect to status monitor after', maxRetries, 'retries');
        console.warn('[3D Integration] WebSocket updates will not work, but manual test functions are available');
    }
}

// Start trying to initialize
setTimeout(tryInit3DIntegration, 100);

