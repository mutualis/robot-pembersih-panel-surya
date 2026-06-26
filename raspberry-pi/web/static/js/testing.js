// ===== TESTING PAGE JAVASCRIPT =====

// ===== STATE =====
let testingInProgress = false;  // Global lock to prevent concurrent tests
let testAborted = false;        // Emergency stop flag — cancels running tests
let encoderLiveInterval = null;
let cleaningLocked = false;     // True when automatic cleaning is in progress
let pidLoggingActive = false;   // True when PID data logger is running

// ===== LOG FUNCTION =====
function addLog(message) {
    const log = document.getElementById('testLog');
    if (!log) return;
    const time = new Date().toLocaleTimeString('id-ID');
    const line = document.createElement('div');
    line.textContent = `[${time}] ${message}`;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
    saveLogToSession();
}

// ===== SESSION PERSISTENCE =====
function saveStatusesToSession() {
    const statuses = {};
    document.querySelectorAll('[id^="status-"]').forEach(elem => {
        statuses[elem.id] = { className: elem.className, text: elem.textContent };
    });
    sessionStorage.setItem('testStatuses', JSON.stringify(statuses));
}

function restoreStatusesFromSession() {
    try {
        const saved = sessionStorage.getItem('testStatuses');
        if (!saved) return false;
        const statuses = JSON.parse(saved);
        let restored = false;
        for (const [id, data] of Object.entries(statuses)) {
            const elem = document.getElementById(id);
            if (elem) {
                elem.className = data.className;
                elem.textContent = data.text;
                restored = true;
            }
        }
        return restored;
    } catch { return false; }
}

function saveLogToSession() {
    const log = document.getElementById('testLog');
    if (!log) return;
    sessionStorage.setItem('testLog', log.innerHTML);
}

function restoreLogFromSession() {
    const log = document.getElementById('testLog');
    if (!log) return false;
    const saved = sessionStorage.getItem('testLog');
    if (saved) {
        log.innerHTML = saved;
        log.scrollTop = log.scrollHeight;
        return true;
    }
    return false;
}

// ===== BUTTON LOCKING =====
function setAllButtonsDisabled(disabled) {
    document.querySelectorAll('.test-grid .btn, #btnRunAll, #btnEmergency, #btnEncoderLive').forEach(btn => {
        // Emergency stop is NEVER disabled
        if (btn.id === 'btnEmergency') return;
        btn.disabled = disabled;
        btn.style.opacity = disabled ? '0.4' : '1';
        btn.style.cursor = disabled ? 'not-allowed' : 'pointer';
    });
}

// ===== TESTING MODE =====
// Testing mode removed — serial access is now thread-safe via lock.
// All test endpoints use send_and_receive() which is atomic.
async function beginTestingMode() { /* no-op */ }
async function endTestingMode() { /* no-op */ }

// Wrapper: lock buttons, enable testing mode, run test, unlock
async function withTestLock(fn) {
    if (testingInProgress) {
        showToast('Test sedang berjalan, tunggu selesai', 'warning');
        return;
    }
    if (pidLoggingActive) {
        showToast('PID logging aktif — hentikan dulu sebelum menjalankan test ESP32', 'warning');
        return;
    }
    testingInProgress = true;
    testAborted = false;
    setAllButtonsDisabled(true);
    await beginTestingMode();
    try {
        await fn();
    } finally {
        await endTestingMode();
        setAllButtonsDisabled(false);
        testingInProgress = false;
        testAborted = false;
    }
}

// ===== ESP32 CONNECTION CHECK =====
async function checkESP32() {
    try {
        const r = await fetch('/api/test/esp32/connection');
        const d = await r.json();
        return d.success;
    } catch { return false; }
}

// ===== ESP32 TESTING =====
async function testESP32Connection() {
    if (pidLoggingActive) { showToast('PID logging aktif — tidak bisa test ESP32', 'warning'); return; }
    updateTestStatus('esp32-connection', 'testing', 'Testing koneksi ESP32...');
    addLog('Testing ESP32 connection...');
    
    try {
        const response = await fetch('/api/test/esp32/connection');
        const data = await response.json();
        
        if (data.success) {
            updateTestStatus('esp32-connection', 'success', `Connected: ${data.message}`);
            addLog(`ESP32 connected: ${data.message}`);
        } else {
            updateTestStatus('esp32-connection', 'error', `Failed: ${data.message}`);
            addLog(`Error: ESP32 failed: ${data.message}`);
        }
    } catch (error) {
        updateTestStatus('esp32-connection', 'error', `Error: ${error.message}`);
        addLog(`Error: Error: ${error.message}`);
    }
}

async function testHoming() {
    if (!await checkESP32()) { updateTestStatus('motor-wiper', 'error', 'ESP32 tidak terhubung'); return; }
    const confirmed = await showDialog('Homing', 'Gerakkan wiper ke posisi home (atas / LS1)? Berhenti otomatis di limit switch.');
    if (!confirmed) return;

    await withTestLock(async () => {
        updateTestStatus('motor-wiper', 'testing', 'Homing ke posisi atas (LS1)...');
        try {
            const response = await fetch('/api/test/esp32/homing', { method: 'POST' });
            const data = await response.json();
            if (data.success) updateTestStatus('motor-wiper', 'success', data.message);
            else updateTestStatus('motor-wiper', 'error', data.message);
        } catch (error) {
            updateTestStatus('motor-wiper', 'error', `Error: ${error.message}`);
        }
    });
}

async function testMotorWiper(direction = 'naik') {
    if (!await checkESP32()) { updateTestStatus('motor-wiper', 'error', 'ESP32 tidak terhubung'); return; }
    const arahLabel = direction === 'turun' ? 'turun (ke LS2 bawah)' : 'naik (ke LS1 atas)';
    const confirmed = await showDialog('Konfirmasi', `Gerakkan motor wiper ${arahLabel}? Berhenti otomatis di limit switch.`);
    if (!confirmed) return;

    await withTestLock(async () => {
        updateTestStatus('motor-wiper', 'testing', `Wiper bergerak ${direction}...`);
        try {
            const response = await fetch('/api/test/esp32/motor_wiper', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ direction })
            });
            const data = await response.json();
            if (data.success) updateTestStatus('motor-wiper', 'success', data.message);
            else updateTestStatus('motor-wiper', 'error', data.message);
        } catch (error) {
            updateTestStatus('motor-wiper', 'error', `Error: ${error.message}`);
        }
    });
}

async function testMotorBrush() {
    if (!await checkESP32()) { updateTestStatus('motor-brush', 'error', 'ESP32 tidak terhubung'); return; }
    const confirmed = await showDialog('Konfirmasi', 'Test motor sikat? Motor akan berputar sebentar.');
    if (!confirmed) return;
    
    await withTestLock(async () => {
        updateTestStatus('motor-brush', 'testing', 'Testing motor sikat...');
        try {
            const response = await fetch('/api/test/esp32/motor_brush', { method: 'POST' });
            const data = await response.json();
            if (data.success) updateTestStatus('motor-brush', 'success', data.message);
            else updateTestStatus('motor-brush', 'error', data.message);
        } catch (error) {
            updateTestStatus('motor-brush', 'error', `Error: ${error.message}`);
        }
    });
}

async function testPump() {
    if (!await checkESP32()) { updateTestStatus('pump', 'error', 'ESP32 tidak terhubung'); return; }
    const confirmed = await showDialog('Konfirmasi', 'Test pompa air? Pompa akan menyala 3 detik.');
    if (!confirmed) return;
    
    await withTestLock(async () => {
        updateTestStatus('pump', 'testing', 'Testing pompa air...');
        try {
            const response = await fetch('/api/test/esp32/pump', { method: 'POST' });
            const data = await response.json();
            if (data.success) updateTestStatus('pump', 'success', data.message);
            else updateTestStatus('pump', 'error', data.message);
        } catch (error) {
            updateTestStatus('pump', 'error', `Error: ${error.message}`);
        }
    });
}

// ===== LIMIT SWITCH TESTING =====
async function testLimitSwitches() {
    await testLS('both');
}

async function testLS(which) {
    if (pidLoggingActive) { showToast('PID logging aktif — tidak bisa test limit switch', 'warning'); return; }
    if (!await checkESP32()) { 
        if (which === 'ls1' || which === 'both') updateTestStatus('ls1', 'error', 'ESP32 tidak terhubung');
        if (which === 'ls2' || which === 'both') updateTestStatus('ls2', 'error', 'ESP32 tidak terhubung');
        return; 
    }
    const label = which === 'ls1' ? 'LS1 (Atas)' : which === 'ls2' ? 'LS2 (Bawah)' : 'LS1 & LS2';
    addLog(`Testing ${label}...`);
    
    if (which === 'ls1' || which === 'both') updateTestStatus('ls1', 'testing', 'LS1 (Atas): Membaca...');
    if (which === 'ls2' || which === 'both') updateTestStatus('ls2', 'testing', 'LS2 (Bawah): Membaca...');
    
    try {
        const response = await fetch('/api/test/esp32/limit_switches');
        const data = await response.json();
        
        if (data.success) {
            if (which === 'ls1' || which === 'both') {
                const ls1State = data.ls1 ? 'AKTIF (Pressed)' : 'Tidak aktif (Open)';
                const ls1Status = data.ls1 ? 'success' : 'testing';
                document.getElementById('status-ls1').className = `test-status ${ls1Status}`;
                document.getElementById('status-ls1').textContent = `LS1 (Atas): ${ls1State}`;
                addLog(`  LS1: ${ls1State}`);
            }
            if (which === 'ls2' || which === 'both') {
                const ls2State = data.ls2 ? 'AKTIF (Pressed)' : 'Tidak aktif (Open)';
                const ls2Status = data.ls2 ? 'success' : 'testing';
                document.getElementById('status-ls2').className = `test-status ${ls2Status}`;
                document.getElementById('status-ls2').textContent = `LS2 (Bawah): ${ls2State}`;
                addLog(`  LS2: ${ls2State}`);
            }
            saveStatusesToSession();
        } else {
            if (which === 'ls1' || which === 'both') updateTestStatus('ls1', 'error', `LS1: ${data.message}`);
            if (which === 'ls2' || which === 'both') updateTestStatus('ls2', 'error', `LS2: ${data.message}`);
            addLog(`Error: Limit switch error: ${data.message}`);
        }
    } catch (error) {
        addLog(`Error: Error: ${error.message}`);
    }
}

// ===== ENCODER TESTING =====
async function testEncoder() {
    await testEncoderOnce();
}

async function testEncoderOnce() {
    if (pidLoggingActive) { showToast('PID logging aktif — tidak bisa test encoder', 'warning'); return; }
    if (!await checkESP32()) { 
        document.getElementById('status-encoder-rpm').className = 'test-status error';
        document.getElementById('status-encoder-rpm').textContent = 'ESP32 tidak terhubung';
        return; 
    }

    addLog('Testing encoder — sampling 2 detik...');
    document.getElementById('status-encoder-rpm').className = 'test-status testing';
    document.getElementById('status-encoder-rpm').textContent = 'RPM: Sampling...';
    document.getElementById('status-encoder-pulse').className = 'test-status testing';
    document.getElementById('status-encoder-pulse').textContent = 'Pulses: Sampling...';

    try {
        const response = await fetch('/api/test/esp32/encoder');
        const data = await response.json();

        if (data.success) {
            const rpm = data.rpm ? data.rpm.toFixed(1) : '0';
            const pulses = data.pulses || 0;
            const hasSignal = data.rpm > 0.5 || pulses !== 0;

            document.getElementById('status-encoder-rpm').className = `test-status ${hasSignal ? 'success' : 'testing'}`;
            document.getElementById('status-encoder-rpm').textContent = `RPM: ${rpm}`;
            document.getElementById('status-encoder-pulse').className = `test-status ${hasSignal ? 'success' : 'testing'}`;
            document.getElementById('status-encoder-pulse').textContent = `Pulses: ${pulses}`;
            saveStatusesToSession();

            addLog(`  Encoder: ${rpm} RPM, ${pulses} pulses ${hasSignal ? '(sinyal terdeteksi)' : '(tidak ada sinyal — putar motor saat test)'}`);
        } else {
            document.getElementById('status-encoder-rpm').className = 'test-status error';
            document.getElementById('status-encoder-rpm').textContent = `Error: ${data.message}`;
            saveStatusesToSession();
            addLog(`Error: Encoder: ${data.message}`);
        }
    } catch (error) {
        addLog(`Error: ${error.message}`);
    }
}

// Encoder live monitor callback — receives data from WS status broadcast
let _encoderLiveCallback = null;

function toggleEncoderLive() {
    const btn = document.getElementById('btnEncoderLive');

    if (_encoderLiveCallback) {
        // Stop: unregister WS callback
        if (typeof statusMonitor !== 'undefined') {
            statusMonitor.statusCallbacks = statusMonitor.statusCallbacks.filter(
                cb => cb !== _encoderLiveCallback
            );
        }
        _encoderLiveCallback = null;
        // encoderLiveInterval kept as truthy sentinel for PID lock check — clear it
        encoderLiveInterval = null;
        btn.textContent = 'Live Monitor';
        btn.className = 'btn btn-outline';
        addLog('Encoder live monitor stopped');
        endTestingMode();
    } else {
        if (pidLoggingActive) { showToast('PID logging aktif — tidak bisa live monitor encoder', 'warning'); return; }
        btn.textContent = 'Stop Monitor';
        btn.className = 'btn btn-danger';
        addLog('Encoder live monitor started (via WebSocket)');
        beginTestingMode();
        encoderLiveInterval = true; // sentinel so PID lock check still works

        _encoderLiveCallback = function(data) {
            // WS status already contains wiper_rpm and position from ESP32
            const rpm     = data.wiper_rpm != null ? parseFloat(data.wiper_rpm) : 0;
            const pulses  = data.position  != null ? data.position : 0;
            const hasSignal = rpm > 0.5;

            const rpmEl    = document.getElementById('status-encoder-rpm');
            const pulseEl  = document.getElementById('status-encoder-pulse');
            if (rpmEl) {
                rpmEl.className = `test-status ${hasSignal ? 'success' : 'testing'}`;
                rpmEl.textContent = `RPM: ${rpm.toFixed(1)}`;
            }
            if (pulseEl) {
                pulseEl.className = `test-status ${hasSignal ? 'success' : 'testing'}`;
                pulseEl.textContent = `Pulses: ${pulses}`;
            }
        };

        if (typeof statusMonitor !== 'undefined') {
            statusMonitor.onStatusUpdate(_encoderLiveCallback);
        } else {
            setTimeout(() => {
                if (typeof statusMonitor !== 'undefined') {
                    statusMonitor.onStatusUpdate(_encoderLiveCallback);
                }
            }, 1000);
        }
    }
}

// ===== CLEANING CYCLE TEST =====

/**
 * Shared polling loop for cleaning cycle test.
 * Returns true if completed successfully, false on error/timeout/abort.
 */
async function _pollCleaningCycle() {
    const MAX_WAIT_MS  = 120000; // 2 menit max
    const POLL_MS      = 1000;   // poll setiap 1 detik
    const IDLE_GRACE_MS = 8000;  // tunggu 8 detik sebelum anggap idle = selesai
    const startTime    = Date.now();
    let firstIdleTime  = null;   // kapan pertama kali kembali ke idle setelah mulai

    addLog('Cleaning cycle started — monitoring progress...');

    while (Date.now() - startTime < MAX_WAIT_MS) {
        await new Promise(r => setTimeout(r, POLL_MS));

        if (testAborted) {
            updateTestStatus('cleaning-cycle', 'error', 'Dihentikan — Emergency Stop');
            addLog('Cleaning cycle stopped by emergency stop');
            return false;
        }

        try {
            const pollRes = await fetch('/api/test/esp32/cleaning_status');
            const poll    = await pollRes.json();

            if (!poll.success) {
                updateTestStatus('cleaning-cycle', 'error', poll.message || 'Lost connection');
                return false;
            }

            const state     = poll.state     || '';
            const progress  = poll.progress  || 0;
            const espStatus = poll.esp32_status || '';
            const wiperRpm  = poll.wiper_rpm ? poll.wiper_rpm.toFixed(1) : '0';
            const ls1       = poll.ls1 ? '[LS1]' : '';
            const ls2       = poll.ls2 ? '[LS2]' : '';
            const lsInfo    = [ls1, ls2].filter(Boolean).join(' ') || '';

            updateTestStatus('cleaning-cycle', 'testing',
                `${state} — ${progress}% | Wiper: ${wiperRpm} RPM ${lsInfo}`);

            // Done: server already normalises "done" status
            if (espStatus === 'done') {
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                updateTestStatus('cleaning-cycle', 'success', `Cleaning cycle selesai — ${elapsed}s`);
                addLog(`Cleaning cycle selesai dalam ${elapsed}s`);
                return true;
            }

            // Error state
            if (espStatus === 'error') {
                updateTestStatus('cleaning-cycle', 'error',
                    `Error: ${poll.message || 'Unknown'} (kode: ${poll.error || '?'})`);
                return false;
            }

            // ESP32 returned to idle — could be done (fast cycle) or unexpected stop.
            // Wait IDLE_GRACE_MS before deciding: if still idle → treat as done.
            if (espStatus === 'idle') {
                if (firstIdleTime === null) {
                    firstIdleTime = Date.now();
                } else if (Date.now() - firstIdleTime >= IDLE_GRACE_MS) {
                    // Still idle after grace period — cycle finished
                    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
                    updateTestStatus('cleaning-cycle', 'success', `Cleaning cycle selesai — ${elapsed}s`);
                    addLog(`Cleaning cycle selesai dalam ${elapsed}s`);
                    return true;
                }
            } else {
                firstIdleTime = null; // Reset if it goes active again
            }

        } catch (pollErr) {
            addLog(`Poll error: ${pollErr.message}`);
        }
    }

    updateTestStatus('cleaning-cycle', 'error', 'Timeout — cleaning cycle tidak selesai dalam 2 menit');
    return false;
}

async function testCleaningCycle() {
    if (!await checkESP32()) { updateTestStatus('cleaning-cycle', 'error', 'ESP32 tidak terhubung'); return; }
    const confirmed = await showDialog('Konfirmasi',
        'Test siklus pembersihan?\n\nMode: ringan (wiper + brush 1 pass, tanpa semprot).\nPastikan area sekitar robot aman.');
    if (!confirmed) return;

    await withTestLock(async () => {
        updateTestStatus('cleaning-cycle', 'testing', 'Memulai cleaning cycle...');
        try {
            const startRes  = await fetch('/api/test/esp32/cleaning_cycle', { method: 'POST' });
            const startData = await startRes.json();
            if (!startData.success) {
                updateTestStatus('cleaning-cycle', 'error', startData.message);
                return;
            }
            await _pollCleaningCycle();
        } catch (error) {
            updateTestStatus('cleaning-cycle', 'error', `Error: ${error.message}`);
        }
    });
}

// Uji pembersihan adaptif per level (Ringan/Sedang/Berat).
// Lewat /api/trigger (test=true) → controller: aman tabrakan dengan monitoring
// (loop deteksi di-pause), menjalankan VERIFIKASI via deteksi + cooldown, dan
// TIDAK dicatat ke activity log / cleaning report. Treatment tampil di Dashboard & 3D.
let _cleanDemo = { active: false, level: '', sawCleaning: false, t0: 0 };

async function triggerCleaningLevel(level) {
    if (!await checkESP32()) { updateTestStatus('clean-demo', 'error', 'ESP32 tidak terhubung'); return; }
    const scores = { ringan: 100, sedang: 200, berat: 300 };
    const score = scores[level] || 100;
    const wet = (level !== 'ringan');
    // Checkbox: bila dicentang, siklus dijalankan sebagai pembersihan NYATA
    // (test=false) sehingga tercatat ke laporan/CSV cleaning_logger.
    const logToReport = false;
    const confirmed = await showDialog('Uji Pembersihan Adaptif',
        `Jalankan pembersihan level ${level.toUpperCase()} (score ${score})?\n\n` +
        (wet ? 'Pompa MENYEMPROT air saat pass turun. ' : 'Sikat kering, tanpa air. ') +
        'Setelah selesai, sistem memverifikasi panel via deteksi YOLO (bisa berulang).\n' +
        (logToReport
            ? 'Mode PENGAMBILAN DATA: siklus DICATAT ke laporan (CSV cleaning). '
            : 'Mode uji: TIDAK dicatat ke log/report. ') +
        'Monitoring dijeda otomatis. Pastikan area aman.');
    if (!confirmed) return;

    updateTestStatus('clean-demo', 'testing', `Pembersihan ${level.toUpperCase()} dimulai...`);
    try {
        const res = await fetch('/api/trigger', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ zone: 0, weighted_score: score, test: !logToReport })
        });
        const data = await res.json();
        if (!data.success) {
            updateTestStatus('clean-demo', 'error', data.message || 'Gagal memulai (mungkin sedang membersihkan?)');
            return;
        }
        addLog(`Uji pembersihan ${level} (score ${score}) dimulai` +
               (logToReport ? ' [DICATAT ke laporan]' : ' [tidak masuk log]'));
        _cleanDemo = { active: true, level: level, sawCleaning: false, t0: Date.now() };
    } catch (error) {
        updateTestStatus('clean-demo', 'error', `Error: ${error.message}`);
    }
}

// Progres demo dibaca dari status WebSocket controller (bukan polling serial
// ke ESP32), supaya tidak bertabrakan dengan pembacaan status oleh controller
// selama cleaning.
function updateCleanDemoProgress(data) {
    if (!_cleanDemo || !_cleanDemo.active) return;
    const lvl = _cleanDemo.level.toUpperCase();
    if (data.cleaning_active) {
        _cleanDemo.sawCleaning = true;
        const state = data.esp32_state || '...';
        const prog = data.progress || 0;
        const wiper = (data.wiper_rpm || 0).toFixed(1);
        const pump = data.pump ? '💧' : '';
        updateTestStatus('clean-demo', 'testing', `${lvl}: ${state} ${prog}% | Wiper ${wiper} RPM ${pump}`);
    } else if (_cleanDemo.sawCleaning) {
        // cleaning_active true → false: treatment + verifikasi selesai
        _cleanDemo.active = false;
        updateTestStatus('clean-demo', 'success',
            `Pembersihan ${lvl} selesai (pembersihan + verifikasi deteksi). Tidak dicatat ke log.`);
        addLog(`Uji pembersihan ${_cleanDemo.level} selesai`);
    } else if (Date.now() - _cleanDemo.t0 > 15000) {
        // 15 s tapi belum terlihat cleaning aktif → kemungkinan gagal mulai
        _cleanDemo.active = false;
        updateTestStatus('clean-demo', 'error', 'Tidak terdeteksi proses pembersihan (cek ESP32/keadaan).');
    }
}

// ===== CAMERA TESTING =====
async function testCamera() {
    updateTestStatus('camera', 'testing', 'Testing camera...');
    
    try {
        const response = await fetch('/api/test/camera');
        const data = await response.json();
        
        if (data.success) {
            updateTestStatus('camera', 'success', `Kamera OK - ${data.width}x${data.height}`);
        } else {
            updateTestStatus('camera', 'error', data.message);
        }
    } catch (error) {
        updateTestStatus('camera', 'error', `Error: ${error.message}`);
    }
}

async function testYOLO() {
    updateTestStatus('yolo', 'testing', 'Testing YOLO model...');
    
    try {
        const response = await fetch('/api/test/yolo');
        const data = await response.json();
        
        if (data.success) {
            if (data.type === 'two_stage') {
                updateTestStatus('yolo', 'success', 'Two-Stage Model loaded');
            } else {
                updateTestStatus('yolo', 'success', `Model loaded (${data.type})`);
            }
        } else {
            updateTestStatus('yolo', 'error', data.message || 'Model not loaded');
        }
    } catch (error) {
        updateTestStatus('yolo', 'error', `Error: ${error.message}`);
    }
}

async function testDetection() {
    updateTestStatus('detection', 'testing', 'Capturing & running YOLO...');

    try {
        const response = await fetch('/api/test/detection', { method: 'POST' });
        const data = await response.json();

        if (data.success) {
            if (!data.panel_detected) {
                // Panel not detected — show as warning, not success
                updateTestStatus('detection', 'error',
                    'Panel tidak terdeteksi — arahkan kamera ke panel surya');
            } else {
                const dirt  = data.dirt_level || 'unknown';
                const conf  = data.dirt_confidence !== undefined
                    ? (data.dirt_confidence * 100).toFixed(1) + '%' : '--';
                const score = data.weighted_score !== undefined
                    ? data.weighted_score.toFixed(1) : '0';
                const clean = data.clean ? 'Bersih' : 'Kotor';

                updateTestStatus('detection', 'success',
                    `Panel: Ya | ${dirt} (${conf}) | Score: ${score} | ${clean}`);
            }

            // Show annotated frame in the preview area on dashboard (if visible)
            if (data.image) {
                const img = document.getElementById('preview');
                const off = document.getElementById('previewOff');
                if (img) { img.src = data.image; img.style.display = 'block'; }
                if (off) off.style.display = 'none';
            }
        } else {
            updateTestStatus('detection', 'error', data.message);
        }
    } catch (error) {
        updateTestStatus('detection', 'error', `Error: ${error.message}`);
    }
}

// ===== SYSTEM TESTING =====
async function testSerial() {
    if (pidLoggingActive) { showToast('PID logging aktif — tidak bisa test serial', 'warning'); return; }
    updateTestStatus('serial', 'testing', 'Testing serial communication...');
    
    try {
        const response = await fetch('/api/test/serial');
        const data = await response.json();
        
        if (data.success) {
            updateTestStatus('serial', 'success', `Serial OK - Port: ${data.port}, Baud: ${data.baudrate}`);
        } else {
            updateTestStatus('serial', 'error', data.message);
        }
    } catch (error) {
        updateTestStatus('serial', 'error', `Error: ${error.message}`);
    }
}

async function testConfig() {
    updateTestStatus('config', 'testing', 'Testing configuration...');
    
    try {
        const response = await fetch('/api/test/config');
        const data = await response.json();
        
        if (data.success) {
            const info = [
                `Threshold: ${data.trigger_threshold}`,
                `Monitor: ${data.monitor_interval}s`,
                `Cooldown: ${data.cooldown}s`,
                `Max Attempt: ${data.max_attempts}`,
                `Conf Panel: ${data.panel_confidence}`,
                `Conf Dirt: ${data.dirt_confidence}`,
                `Serial: ${data.serial_port}`
            ].join(' | ');
            updateTestStatus('config', 'success', info);
        } else {
            updateTestStatus('config', 'error', data.message);
        }
    } catch (error) {
        updateTestStatus('config', 'error', `Error: ${error.message}`);
    }
}

// ===== RUN ALL TESTS =====

// Internal test functions (no confirmation dialog, for use in runAllTests)
async function _testMotorWiperInternal() {
    updateTestStatus('motor-wiper', 'testing', 'Testing motor wiper...');
    try {
        const response = await fetch('/api/test/esp32/motor_wiper', { method: 'POST' });
        const data = await response.json();
        if (data.success) updateTestStatus('motor-wiper', 'success', data.message);
        else updateTestStatus('motor-wiper', 'error', data.message);
    } catch (error) {
        updateTestStatus('motor-wiper', 'error', `Error: ${error.message}`);
    }
}

async function _testMotorBrushInternal() {
    updateTestStatus('motor-brush', 'testing', 'Testing motor sikat...');
    try {
        const response = await fetch('/api/test/esp32/motor_brush', { method: 'POST' });
        const data = await response.json();
        if (data.success) updateTestStatus('motor-brush', 'success', data.message);
        else updateTestStatus('motor-brush', 'error', data.message);
    } catch (error) {
        updateTestStatus('motor-brush', 'error', `Error: ${error.message}`);
    }
}

async function _testPumpInternal() {
    updateTestStatus('pump', 'testing', 'Testing pompa air...');
    try {
        const response = await fetch('/api/test/esp32/pump', { method: 'POST' });
        const data = await response.json();
        if (data.success) updateTestStatus('pump', 'success', data.message);
        else updateTestStatus('pump', 'error', data.message);
    } catch (error) {
        updateTestStatus('pump', 'error', `Error: ${error.message}`);
    }
}

async function _testCleaningCycleInternal() {
    updateTestStatus('cleaning-cycle', 'testing', 'Memulai cleaning cycle...');
    try {
        const startRes  = await fetch('/api/test/esp32/cleaning_cycle', { method: 'POST' });
        const startData = await startRes.json();
        if (!startData.success) {
            updateTestStatus('cleaning-cycle', 'error', startData.message);
            return;
        }
        await _pollCleaningCycle();
    } catch (error) {
        updateTestStatus('cleaning-cycle', 'error', `Error: ${error.message}`);
    }
}

async function runAllTests() {
    if (pidLoggingActive) {
        showToast('PID logging aktif — hentikan dulu sebelum Run All Tests', 'warning');
        return;
    }
    const confirmed = await showDialog('Konfirmasi', 
        'Jalankan SEMUA test termasuk motor, pompa, dan cleaning cycle?\n\n' +
        'Urutan: Serial → Config → Camera → YOLO → Detection → ESP32 → Limit Switch → Encoder → Motor Wiper → Motor Sikat → Pompa → Cleaning Cycle.\n\n' +
        'Pastikan area sekitar robot aman!');
    if (!confirmed) return;
    
    await withTestLock(async () => {
        addLog('========== RUN ALL TESTS ==========');
        let passed = 0;
        let failed = 0;
        let skipped = 0;
        
        // Reset all statuses
        document.querySelectorAll('[id^="status-"]').forEach(elem => {
            elem.className = 'test-status';
            elem.textContent = 'Waiting...';
        });
        saveStatusesToSession();
        
        function countResult(testId) {
            const elem = document.getElementById(`status-${testId}`);
            if (!elem) return;
            if (elem.classList.contains('success')) passed++;
            else if (elem.classList.contains('error')) failed++;
        }
        
        // ===== Phase 1: System (no ESP32 needed) =====
        addLog('--- Phase 1: System ---');
        
        await testSerial();
        countResult('serial');
        if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
        await new Promise(r => setTimeout(r, 200));
        
        await testConfig();
        countResult('config');
        if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
        await new Promise(r => setTimeout(r, 200));
        
        // ===== Phase 2: Camera & Detection =====
        addLog('--- Phase 2: Camera & Detection ---');
        
        await testCamera();
        countResult('camera');
        if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
        await new Promise(r => setTimeout(r, 200));
        
        await testYOLO();
        countResult('yolo');
        if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
        await new Promise(r => setTimeout(r, 200));
        
        await testDetection();
        countResult('detection');
        if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
        await new Promise(r => setTimeout(r, 200));
        
        // ===== Phase 3: ESP32 Hardware =====
        addLog('--- Phase 3: ESP32 Hardware ---');
        
        await testESP32Connection();
        const esp32Ok = document.getElementById('status-esp32-connection')?.classList.contains('success');
        countResult('esp32-connection');
        if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
        
        if (esp32Ok) {
            await new Promise(r => setTimeout(r, 300));
            
            await testLS('both');
            countResult('ls1');
            countResult('ls2');
            if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
            await new Promise(r => setTimeout(r, 300));
            
            await testEncoderOnce();
            countResult('encoder-rpm');
            if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
            await new Promise(r => setTimeout(r, 500));
            
            // ===== Phase 4: Actuators =====
            addLog('--- Phase 4: Actuators ---');
            
            await _testMotorWiperInternal();
            countResult('motor-wiper');
            if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
            await new Promise(r => setTimeout(r, 500));
            
            await _testMotorBrushInternal();
            countResult('motor-brush');
            if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
            await new Promise(r => setTimeout(r, 500));
            
            await _testPumpInternal();
            countResult('pump');
            if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
            await new Promise(r => setTimeout(r, 4000)); // tunggu pompa selesai 3 detik + buffer
            
            // ===== Phase 5: Full Cleaning Cycle =====
            addLog('--- Phase 5: Cleaning Cycle ---');
            
            await _testCleaningCycleInternal();
            countResult('cleaning-cycle');
            if (testAborted) { addLog('Dihentikan oleh Emergency Stop'); return; }
            
        } else {
            // ESP32 not connected — skip all hardware tests
            ['ls1', 'ls2', 'encoder-rpm', 'encoder-pulse', 
             'motor-wiper', 'motor-brush', 'pump', 'cleaning-cycle'].forEach(id => {
                const elem = document.getElementById(`status-${id}`);
                if (elem) {
                    elem.className = 'test-status error';
                    elem.textContent = 'Skipped — ESP32 tidak terhubung';
                }
            });
            skipped += 7;
            addLog('ESP32 tidak terhubung, skip semua hardware tests');
            saveStatusesToSession();
        }
        
        // ===== Summary =====
        addLog('========== HASIL ==========');
        addLog(`Passed: ${passed} | Failed: ${failed} | Skipped: ${skipped}`);
        
        if (failed === 0 && skipped === 0) {
            showToast(`Semua ${passed} test passed!`, 'success', 5000);
        } else {
            showToast(`Selesai: ${passed} passed, ${failed} failed, ${skipped} skipped`, failed > 0 ? 'warning' : 'info', 5000);
        }
    });
}

// ===== HELPER FUNCTIONS =====
function updateTestStatus(testId, status, message) {
    const elem = document.getElementById(`status-${testId}`);
    if (!elem) return;
    
    elem.className = `test-status ${status}`;
    elem.textContent = message;
    
    if (status === 'success') addLog(`OK: ${message}`);
    else if (status === 'error') addLog(`Error: ${message}`);
    else if (status === 'testing') addLog(`... ${message}`);
    
    saveStatusesToSession();
}

// ===== RESET & CLEAR =====
function resetAllTests() {
    if (testingInProgress) {
        showToast('Test sedang berjalan, tunggu selesai', 'warning');
        return;
    }
    document.querySelectorAll('[id^="status-"]').forEach(elem => {
        elem.className = 'test-status';
        elem.textContent = 'Not tested';
    });
    saveStatusesToSession();
    
    // Clear PID session data if the function exists (defined in testing.html)
    if (typeof clearPIDSession === 'function') {
        clearPIDSession();
        // Reset PID UI elements
        if (typeof pidChartData !== 'undefined' && typeof pidChart !== 'undefined') {
            pidChartData.labels = [];
            pidChartData.datasets[0].data = [];
            pidChartData.datasets[1].data = [];
            pidChart.update();
        }
        const pidStatus = document.getElementById('pidStatus');
        if (pidStatus) { pidStatus.textContent = 'Idle'; pidStatus.style.color = '#666'; }
        const pidCurrentRPM = document.getElementById('pidCurrentRPM');
        if (pidCurrentRPM) pidCurrentRPM.textContent = '-';
        const pidDataPoints = document.getElementById('pidDataPoints');
        if (pidDataPoints) pidDataPoints.textContent = '0';
        const pidElapsedTime = document.getElementById('pidElapsedTime');
        if (pidElapsedTime) pidElapsedTime.textContent = '0';
        const pidSetpointDisplay = document.getElementById('pidSetpointDisplay');
        if (pidSetpointDisplay) pidSetpointDisplay.textContent = '-';
        // Reset results panel
        ['resultRiseTime','resultOvershoot','resultSettlingTime','resultSSE',
         'resultMeanRPM','resultStdDev','resultMinRPM','resultMaxRPM'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = '-';
        });
        const resultTestInfo = document.getElementById('resultTestInfo');
        if (resultTestInfo) resultTestInfo.textContent = 'Belum ada data. Jalankan test terlebih dahulu.';
        const btnExportPID = document.getElementById('btnExportPID');
        if (btnExportPID) btnExportPID.disabled = true;
    }
    
    addLog('All test statuses reset.');
}

function clearLog() {
    const log = document.getElementById('testLog');
    if (log) log.innerHTML = '';
    sessionStorage.removeItem('testLog');
    addLog('Log cleared.');
}

// ===== EMERGENCY STOP =====
async function emergencyStop() {
    const confirmed = await showDialog('EMERGENCY STOP', 
        'Stop semua operasi sekarang?');
    if (!confirmed) return;
    
    // Set abort flag to cancel any running test/polling
    testAborted = true;
    
    try {
        const response = await fetch('/api/emergency_stop', { method: 'POST' });
        const data = await response.json();
        
        if (data.success) {
            showToast('Emergency stop executed', 'success');
            addLog('EMERGENCY STOP executed');
            // Bersihkan state lokal SEGERA agar UI tidak nyangkut walau broadcast
            // WebSocket telat. (Server sudah mereset cleaning_active=false.)
            testingInProgress = false;
            cleaningLocked = false;
            if (typeof _cleanDemo === 'object' && _cleanDemo) {
                _cleanDemo.active = false;
                _cleanDemo.sawCleaning = false;
                updateTestStatus('clean-demo', 'error', 'Dihentikan (Emergency Stop)');
            }
            setAllButtonsDisabled(false);  // buka kunci tombol; WebSocket akan merapikan sesuai koneksi
        } else {
            showToast('ESP32 tidak merespons', 'error');
        }
    } catch (error) {
        showToast('ESP32 tidak terhubung', 'error');
    }
}

// ===== INITIALIZATION =====
document.addEventListener('DOMContentLoaded', function() {
    const log = document.getElementById('testLog');
    
    // Restore previous session data
    const hasLog = restoreLogFromSession();
    const hasStatuses = restoreStatusesFromSession();
    
    if (!hasLog && log) {
        log.innerHTML = '';
        addLog('Testing page ready. Klik tombol test untuk mulai.');
    }
    
    // Cleaning lock will be checked via WebSocket status updates (no HTTP needed)
    
    // Register WebSocket callback to disable ESP32 buttons when disconnected
    // AND check cleaning lock from status data
    function updateESP32Buttons(data) {
        // Update cleaning lock from WebSocket status (no polling needed)
        const wasLocked = cleaningLocked;
        cleaningLocked = data.cleaning_active || false;
        updateCleaningLockUI(wasLocked);
        
        // Sync PID logging state from server (handles case where server stops PID externally)
        if (data.pid_logging_active !== undefined && !data.pid_logging_active && pidLoggingActive) {
            // Server stopped PID logging (e.g., cleaning started) — sync frontend
            setPIDLoggingLock(false);
        }
        
        // If cleaning just started while PID logging was active,
        // the server already stopped PID — update frontend to match
        if (!wasLocked && cleaningLocked && pidLoggingActive) {
            setPIDLoggingLock(false);
            const pidStatusEl = document.getElementById('pidStatus');
            if (pidStatusEl) { pidStatusEl.textContent = 'Dihentikan (cleaning)'; pidStatusEl.style.color = '#856404'; }
            const btnStart = document.getElementById('btnStartPID');
            if (btnStart) btnStart.disabled = true;  // Keep disabled during cleaning
            const btnStop = document.getElementById('btnStopPID');
            if (btnStop) btnStop.disabled = true;
            const btnExport = document.getElementById('btnExportPID');
            if (btnExport) btnExport.disabled = false;
            if (typeof savePIDChartToSession === 'function') savePIDChartToSession();
            if (typeof savePIDStatusToSession === 'function') savePIDStatusToSession('Dihentikan (cleaning)', '#856404');
            addLog(`[PID] Logging dihentikan otomatis — pembersihan dimulai`);
        }
        
        // Don't override button states during testing
        if (testingInProgress) return;
        if (cleaningLocked) return;  // Lock UI handles buttons
        
        const connected = data.esp32_connected;
        
        // ESP32-dependent buttons
        const allTestBtns = document.querySelectorAll('.test-grid .btn');
        allTestBtns.forEach(btn => {
            const onclick = btn.getAttribute('onclick') || '';
            const isESP32Test = onclick.includes('testMotor') || onclick.includes('testPump') || 
                                onclick.includes('testLS') || onclick.includes('testEncoder') || 
                                onclick.includes('testCleaningCycle') || onclick.includes('triggerCleaningLevel');
            if (isESP32Test) {
                btn.disabled = !connected;
                btn.style.opacity = connected ? '1' : '0.4';
                btn.style.cursor = connected ? 'pointer' : 'not-allowed';
            }
        });
    }
    
    if (typeof statusMonitor !== 'undefined') {
        statusMonitor.onStatusUpdate(updateESP32Buttons);
        statusMonitor.onStatusUpdate(updateCleanDemoProgress);
    } else {
        setTimeout(() => {
            if (typeof statusMonitor !== 'undefined') {
                statusMonitor.onStatusUpdate(updateESP32Buttons);
                statusMonitor.onStatusUpdate(updateCleanDemoProgress);
            }
        }, 1000);
    }
});

// ===== CLEANING LOCK =====
async function checkCleaningLock() {
    try {
        const r = await fetch('/api/test/cleaning_lock');
        const data = await r.json();
        const wasLocked = cleaningLocked;
        cleaningLocked = data.locked;
        updateCleaningLockUI(wasLocked);
    } catch (e) {
        // Ignore fetch errors
    }
}

function updateCleaningLockUI(wasLocked) {
    const banner = document.getElementById('cleaningLockBanner');
    if (!banner) return;
    
    if (cleaningLocked) {
        banner.classList.remove('hidden');
        
        // Disable all action buttons (except Emergency Stop)
        document.querySelectorAll('.test-grid .btn, #btnStartPID, #btnRunAll, #btnReset').forEach(btn => {
            btn.disabled = true;
            btn.style.opacity = '0.4';
            btn.style.cursor = 'not-allowed';
        });
    } else {
        banner.classList.add('hidden');
        
        // Re-enable buttons (only if not in a test)
        if (!testingInProgress) {
            document.querySelectorAll('.test-grid .btn, #btnStartPID, #btnRunAll, #btnReset').forEach(btn => {
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.style.cursor = 'pointer';
            });
        }
        
        if (wasLocked && !cleaningLocked) {
            addLog('Pembersihan selesai. Testing kembali tersedia.');
        }
    }
}

// ===== PID LOGGING LOCK =====
// Called from testing.html when PID logging starts/stops
function setPIDLoggingLock(active) {
    pidLoggingActive = active;
    updatePIDLockUI();
}

function updatePIDLockUI() {
    const banner = document.getElementById('pidLockBanner');
    
    if (pidLoggingActive) {
        // Show banner
        if (banner) banner.classList.remove('hidden');
        
        // Disable ESP32-dependent buttons (but NOT PID controls or Emergency Stop)
        document.querySelectorAll('.test-grid .btn').forEach(btn => {
            const onclick = btn.getAttribute('onclick') || '';
            const isESP32Test = onclick.includes('testMotor') || onclick.includes('testPump') ||
                                onclick.includes('testLS') || onclick.includes('testEncoder') ||
                                onclick.includes('testCleaningCycle') || onclick.includes('testESP32') ||
                                onclick.includes('testSerial') || onclick.includes('toggleEncoderLive');
            if (isESP32Test) {
                btn.disabled = true;
                btn.style.opacity = '0.4';
                btn.style.cursor = 'not-allowed';
            }
        });
        
        // Disable Run All Tests (uses ESP32)
        const btnRunAll = document.getElementById('btnRunAll');
        if (btnRunAll) {
            btnRunAll.disabled = true;
            btnRunAll.style.opacity = '0.4';
            btnRunAll.style.cursor = 'not-allowed';
        }
    } else {
        // Hide banner
        if (banner) banner.classList.add('hidden');
        
        // Re-enable buttons (only if not in another lock state)
        if (!testingInProgress && !cleaningLocked) {
            document.querySelectorAll('.test-grid .btn').forEach(btn => {
                const onclick = btn.getAttribute('onclick') || '';
                const isESP32Test = onclick.includes('testMotor') || onclick.includes('testPump') ||
                                    onclick.includes('testLS') || onclick.includes('testEncoder') ||
                                    onclick.includes('testCleaningCycle') || onclick.includes('testESP32') ||
                                    onclick.includes('testSerial') || onclick.includes('toggleEncoderLive');
                if (isESP32Test) {
                    btn.disabled = false;
                    btn.style.opacity = '1';
                    btn.style.cursor = 'pointer';
                }
            });
            
            const btnRunAll = document.getElementById('btnRunAll');
            if (btnRunAll) {
                btnRunAll.disabled = false;
                btnRunAll.style.opacity = '1';
                btnRunAll.style.cursor = 'pointer';
            }
        }
    }
}
