/**
 * State Machine Implementation
 * 
 * Implementasi state machine untuk siklus pembersihan panel surya.
 * Setiap state memiliki handler, timeout, dan error handling.
 * 
 * Fase Pembersihan:
 * 1. Pemeriksaan awal (limit switch, motor)
 * 2. Bergerak ke posisi awal (LS1 atas)
 * 3. Penyemprotan air (pompa ON)
 * 4. Pembersihan maju (LS1 atas → LS2 bawah) dengan wiper + brush
 * 5. Pembersihan mundur (LS2 bawah → LS1 atas) dengan wiper + brush
 * 6. Menghentikan semua motor dan pompa
 * 7. Selesai, kembali ke IDLE
 * 
 * Author: Muhammad Ridho Assidiqi
 * Institution: Universitas Gadjah Mada
 */

#include "state_machine.h"
#include "hardware.h"
#include "serial_comm.h"

extern Hardware hardware;
extern SerialComm serialComm;

// Use DEBUG_SERIAL for monitoring output
#define Serial DEBUG_SERIAL

// ============================================
// CONSTRUCTOR & INITIALIZATION
// ============================================

StateMachine::StateMachine()
    : currentState(IDLE), previousState(IDLE), progress(0),
      errorCode(0), stateStartTime(0), cleaningStartTime(0),
      lastStatusTime(0), lastErrorPrintTime(0), stallStartTime(0), dwellStart(0), stallLastPos(0) {}

void StateMachine::init() {
    currentState = IDLE;
    progress = 0;
    errorCode = 0;
    lastErrorPrintTime = 0;
    
    Serial.println("State Machine: SIAGA");
    
    // Debug: Print limit switch status
    delay(100);  // Wait for hardware to stabilize
    Serial.println("\n=== STATUS LIMIT SWITCH ===");
    Serial.printf("LS1 (GPIO %d): %s\n", LIMIT_SWITCH_1, 
                  hardware.limitSwitch.isLS1Active() ? "AKTIF" : "TIDAK AKTIF");
    Serial.printf("LS2 (GPIO %d): %s\n", LIMIT_SWITCH_2, 
                  hardware.limitSwitch.isLS2Active() ? "AKTIF" : "TIDAK AKTIF");
    
    if (hardware.limitSwitch.isBothActive()) {
        Serial.println("PERINGATAN: Kedua limit switch aktif!");
        Serial.println("   Cek koneksi limit switch atau gunakan pull-down resistor");
    }
    Serial.println();
}

// ============================================
// MAIN UPDATE LOOP
// ============================================

void StateMachine::update() {
    // Check safety conditions
    checkSafety();
    
    // Catat state SEBELUM handler. Setelah handler, bila state TIDAK berubah,
    // set previousState = currentState agar blok "first entry" (if previousState
    // != STATE) hanya berjalan SEKALI tiap masuk state. Tanpa ini first-entry
    // berjalan TIAP loop → delay(500) berulang & dwellStart ter-reset terus →
    // siklus tak pernah balik arah di LS (BUG carriage kepentok di LS2).
    State stateBeforeHandler = currentState;
    
    // Handle current state
    switch (currentState) {
        case IDLE:
            handleIdle();
            break;
        case PRE_CHECK:
            handlePreCheck();
            break;
        case MOVING_TO_START:
            handleMovingToStart();
            break;
        case SPRAYING_WATER:
            handleSprayingWater();
            break;
        case CLEANING_FORWARD:
            handleCleaningForward();
            break;
        case CLEANING_BACKWARD:
            handleCleaningBackward();
            break;
        case STOPPING:
            handleStopping();
            break;
        case DONE:
            handleDone();
            break;
        case ERROR_STATE:
            handleError();
            break;
    }
    
    // Bila handler TIDAK mengganti state, tandai sudah diproses (first-entry sekali).
    // Bila handler memanggil changeState (currentState berubah), JANGAN timpa —
    // biarkan state baru terdeteksi first-entry pada loop berikutnya.
    if (currentState == stateBeforeHandler) {
        previousState = currentState;
    }
}

// ============================================
// STATE HANDLERS
// ============================================

void StateMachine::handleIdle() {
    // Blink LED slowly (heartbeat)
    static unsigned long lastBlink = 0;
    if (millis() - lastBlink > 1000) {
        digitalWrite(LED_STATUS, !digitalRead(LED_STATUS));
        lastBlink = millis();
    }
    
    // Just waiting for command
    // Command will be handled by serial_comm module
}

void StateMachine::handlePreCheck() {
    // Print header only on first entry
    if (previousState != PRE_CHECK) {
        Serial.println("\n=== FASE 1: PEMERIKSAAN AWAL ===");
    }
    
    // Check if both limit switches are active (error condition)
    if (hardware.limitSwitch.isBothActive()) {
        errorCode = ERROR_LIMIT_CONFLICT;
        errorMessage = "Kedua limit switch aktif";
        changeState(ERROR_STATE);
        return;
    }
    
    // Check motors are stopped
    if (hardware.wiperMotor.getCurrentRPM() > 5) {
        if (previousState != PRE_CHECK) {
            Serial.println("Wiper masih bergerak, menghentikan...");
            hardware.wiperMotor.stop();
        }
        // Will re-enter this state next loop and RPM should be lower
        return;
    }
    
    // All checks passed
    Serial.println("Pemeriksaan awal selesai");
    progress = 5;
    changeState(MOVING_TO_START);
}

void StateMachine::handleMovingToStart() {
    // First entry: start moving
    if (previousState != MOVING_TO_START) {
        Serial.println("\n=== FASE 2: BERGERAK KE POSISI AWAL (ATAS) ===");
        
        // Check if already at start position (LS1 = atas)
        if (hardware.limitSwitch.isLS1Active()) {
            Serial.println("Sudah di posisi awal (LS1 atas)");
            hardware.wiperMotor.stop();
            hardware.wiperEncoder.resetPulseCount();
            progress = 10;
            changeState(SPRAYING_WATER);
            return;
        }
        
        // Move to start position (ke atas, menuju LS1)
        Serial.println("Bergerak ke posisi awal (LS1 atas)...");
        Serial.printf("  Motor speed: %.1f RPM (naik menuju LS1)\n", POSITIONING_SPEED);
        Serial.printf("  LS1 status: %s\n", hardware.limitSwitch.isLS1Active() ? "AKTIF" : "TIDAK AKTIF");
        Serial.printf("  LS2 status: %s\n", hardware.limitSwitch.isLS2Active() ? "AKTIF" : "TIDAK AKTIF");
        hardware.wiperMotor.setSpeed(POSITIONING_SPEED);
        stallStartTime = millis();
        stallLastPos = hardware.wiperEncoder.getPulseCount();
        hardware.limitSwitch.clearEvents();  // buang edge basi sebelum homing
    }
    
    // Check if reached LS1
    if (hardware.limitSwitch.isLS1Active() || hardware.limitSwitch.consumeLS1JustPressed()) {
        Serial.println("Mencapai posisi awal (LS1 atas)");
        hardware.wiperMotor.stop();
        hardware.wiperEncoder.resetPulseCount();
        progress = 10;
        changeState(SPRAYING_WATER);
        return;
    }
    
    // Print status every 2 seconds during homing
    static unsigned long lastHomingLog = 0;
    if (millis() - lastHomingLog > 2000) {
        float rpm = hardware.wiperEncoder.getRPM();
        Serial.printf("  Homing... RPM: %.1f | LS1: %s | LS2: %s | Elapsed: %lu ms\n",
                     rpm,
                     hardware.limitSwitch.isLS1Active() ? "ON" : "OFF",
                     hardware.limitSwitch.isLS2Active() ? "ON" : "OFF",
                     millis() - stateStartTime);
        lastHomingLog = millis();
    }
    
    // Check for motor stall during positioning
    if (isMotorStalled()) {
        hardware.wiperMotor.stop();
        errorCode = ERROR_MOTOR_STALL;
        errorMessage = "Motor macet saat positioning";
        changeState(ERROR_STATE);
        return;
    }
    
    // Check timeout
    if (millis() - stateStartTime > POSITIONING_TIMEOUT) {
        hardware.wiperMotor.stop();
        errorCode = ERROR_COMMAND_TIMEOUT;
        errorMessage = "Timeout positioning ke atas";
        changeState(ERROR_STATE);
    }
}

void StateMachine::handleSprayingWater() {
    // First entry: aktifkan pompa hanya bila level memakai semprotan (duration > 0).
    if (previousState != SPRAYING_WATER) {
        if (params.duration > 0) {
            // Semprot saat pass turun: pompa NYALA di awal pass turun. Nozzle (di
            // depan carriage) membasahi panel dari atas ke bawah seiring carriage
            // menurun, bukan menyemprot diam di posisi atas.
            Serial.println("\n=== FASE 3: PENYEMPROTAN AIR (kontinu, saat pass turun) ===");
            Serial.println("Pompa nyala kontinu sepanjang pass turun (dimatikan saat pass naik)");
            hardware.pump.turnOn(params.duration);
        } else {
            // Level ringan: penyikatan kering tanpa air.
            Serial.println("\n=== FASE 3: TANPA PENYEMPROTAN (level ringan, sikat kering) ===");
            hardware.pump.turnOff();
        }
        progress = 15;
    }

    // Jeda singkat untuk priming pompa (bila menyemprot) sebelum carriage turun.
    unsigned long wait = (params.duration > 0) ? 1000 : 200;
    if (millis() - stateStartTime >= wait) {
        changeState(CLEANING_FORWARD);
    }
}

void StateMachine::handleCleaningForward() {
    // Start brush and wiper on first entry
    if (previousState != CLEANING_FORWARD) {
        Serial.printf("\n=== FASE 4: PEMBERSIHAN MAJU (Pass %d/%d) ===\n", 
                     params.currentPass, params.totalPasses);
        Serial.printf("Kecepatan wiper: %.1f RPM\n", params.wiperSpeed);
        
        // Start brush motor hanya jika speed > 0 (selalu aktif pada strategi baru)
        if (params.brushSpeed > 0) {
            Serial.printf("Kecepatan sikat: %.1f RPM\n", params.brushSpeed);
            hardware.brushMotor.setSpeedOpenLoop(params.brushSpeed, BRUSH_MAX_RPM);
            delay(500);
        } else {
            Serial.println("Sikat: MATI");
        }
        
        // Semprot saat pass turun: pastikan pompa aktif (termasuk pass turun ke-2
        // pada level berat). Pada pass turun pertama pompa sudah menyala dari
        // SPRAYING_WATER, sehingga tidak di-restart agar timer durasi tidak reset.
        if (params.duration > 0 && !hardware.pump.getState()) {
            hardware.pump.turnOn(params.duration);
        }
        
        // Start wiper motor — TURUN ke LS2 (reverse, sesuai konvensi: naik=forward,
        // turun=reverse). Identik dengan motor_test yang terbukti reverse benar.
        hardware.wiperMotor.setSpeed(-params.wiperSpeed);
        
        cleaningStartTime = millis();
        stallStartTime = millis();
        stallLastPos = hardware.wiperEncoder.getPulseCount();
        dwellStart = 0;
        hardware.limitSwitch.clearEvents();  // buang edge basi sebelum pass turun
    }
    
    // Check if reached bottom (LS2). Pakai level ATAU edge one-shot (latched) agar
    // kontak singkat/terganggu EMI tidak terlewat. Sekali terdeteksi (dwellStart
    // != 0) proses jeda+balik tetap diselesaikan walau level sempat berkedip.
    bool reachedLS2 = hardware.limitSwitch.isLS2Active()
                      || hardware.limitSwitch.consumeLS2JustPressed();
    if (reachedLS2 || dwellStart != 0) {
        hardware.wiperMotor.stop();
        // Jeda di ujung bawah sebelum balik arah (kurangi sentakan gearbox +
        // beri waktu air/kotoran meresap). Brush tetap berputar selama jeda,
        // tetapi pompa LANGSUNG dimatikan begitu mencapai LS2 (akhir pass turun)
        // — tidak ikut menunggu jeda dwell.
        if (dwellStart == 0) {
            Serial.println("Mencapai posisi bawah (LS2), pompa OFF, jeda sebelum balik arah...");
            hardware.pump.turnOff();   // pompa mati seketika di akhir pass turun (jeda hanya untuk brush)
            dwellStart = millis();
            return;
        }
        if (millis() - dwellStart < CLEANING_DWELL_MS) return;
        dwellStart = 0;
        progress = 60;
        changeState(CLEANING_BACKWARD);
        return;
    }
    
    // Calculate progress (15% to 60%)
    calculateProgress();
    
    // Send status update every second
    if (millis() - lastStatusTime > 1000) {
        Serial.printf("Progres: %d%% | Wiper: %.1f RPM | Sikat: %.1f RPM\n",
                     progress, hardware.wiperEncoder.getRPM(), params.brushSpeed);
        lastStatusTime = millis();
    }
    
    // Check for motor stall
    if (isMotorStalled()) {
        errorCode = ERROR_MOTOR_STALL;
        errorMessage = "Motor wiper macet";
        changeState(ERROR_STATE);
    }
}

void StateMachine::handleCleaningBackward() {
    // Start backward motion on first entry
    if (previousState != CLEANING_BACKWARD) {
        Serial.printf("\n=== FASE 5: PEMBERSIHAN MUNDUR (Pass %d/%d) ===\n",
                     params.currentPass, params.totalPasses);
        
        // Pass NAIK: tidak menyemprot. Wiper memimpin (menyeka kering), pompa OFF
        // agar tidak membasahi ulang area yang baru dikeringkan.
        hardware.pump.turnOff();
        
        // Brush dimatikan saat pass naik: menggosok tanpa air kurang efektif.
        // Pembersihan (gosok) dilakukan saat pass turun. Brush dinyalakan lagi
        // pada pass turun berikutnya (multi-pass) di handleCleaningForward.
        hardware.brushMotor.stop();
        
        // Reverse wiper direction — NAIK ke LS1 (forward/positif). Pass naik =
        // pengembalian + pengeringan (bukan pembersihan), jadi memakai kecepatan
        // transit cepat (POSITIONING_SPEED), bukan kecepatan cleaning per level.
        hardware.wiperMotor.setSpeed(POSITIONING_SPEED);
        
        stallStartTime = millis();
        stallLastPos = hardware.wiperEncoder.getPulseCount();
        dwellStart = 0;
        hardware.limitSwitch.clearEvents();  // buang edge basi sebelum pass naik
    }
    
    // Check if reached top (LS1). Pakai level ATAU edge one-shot (latched) agar
    // kontak singkat tak terlewat; dwellStart != 0 melatch proses multi-pass.
    bool reachedLS1 = hardware.limitSwitch.isLS1Active()
                      || hardware.limitSwitch.consumeLS1JustPressed();
    if (reachedLS1 || dwellStart != 0) {
        hardware.wiperMotor.stop();
        
        // Cek apakah perlu pass tambahan
        if (params.currentPass < params.totalPasses) {
            // Jeda di ujung atas sebelum turun lagi (multi-pass): kurangi sentakan.
            if (dwellStart == 0) {
                Serial.println("Mencapai posisi atas (LS1), jeda sebelum pass berikutnya...");
                dwellStart = millis();
                return;
            }
            if (millis() - dwellStart < CLEANING_DWELL_MS) return;
            dwellStart = 0;
            params.currentPass++;
            Serial.printf("\n>>> Pass %d/%d dimulai...\n", params.currentPass, params.totalPasses);
            progress = 60;
            changeState(CLEANING_FORWARD); // Kembali turun
        } else {
            Serial.println("Mencapai posisi atas (LS1), siklus selesai");
            progress = 90;
            changeState(STOPPING);
        }
        return;
    }
    
    // Calculate progress (60% to 90%)
    calculateProgress();
    
    // Send status update
    if (millis() - lastStatusTime > 1000) {
        Serial.printf("Progres: %d%% | Wiper: %.1f RPM\n",
                     progress, hardware.wiperEncoder.getRPM());
        lastStatusTime = millis();
    }
    
    // Check for motor stall
    if (isMotorStalled()) {
        errorCode = ERROR_MOTOR_STALL;
        errorMessage = "Motor wiper macet";
        changeState(ERROR_STATE);
    }
}

void StateMachine::handleStopping() {
    Serial.println("\n=== FASE 6: MENGHENTIKAN ===");
    
    // Stop wiper
    hardware.wiperMotor.stop();
    
    // Brush: pada FSM ini brush SUDAH dimatikan saat pass naik (CLEANING_BACKWARD),
    // jadi di sini cukup pastikan mati. JANGAN ramp-down dari brushSpeed karena
    // itu justru menyalakan ulang brush sesaat di posisi home (bug "brush
    // berputar sebentar saat sampai atas").
    hardware.brushMotor.stop();
    
    // Turn off pump (if still on)
    hardware.pump.turnOff();
    
    Serial.println("Semua motor berhenti");
    progress = 95;
    changeState(DONE);
}

void StateMachine::handleDone() {
    Serial.println("\n=== SIKLUS PEMBERSIHAN SELESAI ===");
    
    unsigned long totalDuration = millis() - cleaningStartTime;
    Serial.printf("Durasi total: %lu ms (%.1f detik)\n", 
                 totalDuration, totalDuration / 1000.0);
    
    progress = 100;
    
    // Send completion message to Raspberry Pi (once)
    serialComm.sendCompletion(totalDuration);
    
    // Blink LED to indicate completion
    hardware.blinkLED(5);
    
    // Return to IDLE
    changeState(IDLE);
}

void StateMachine::handleError() {
    // Stop everything
    hardware.emergencyStop();
    
    // Blink LED rapidly
    static unsigned long lastBlink = 0;
    if (millis() - lastBlink > 200) {
        digitalWrite(LED_STATUS, !digitalRead(LED_STATUS));
        lastBlink = millis();
    }
    
    // Print error (throttled to once per second to avoid spam)
    if (millis() - lastErrorPrintTime > 1000) {
        Serial.printf("KESALAHAN %d: %s\n", errorCode, errorMessage.c_str());
        Serial.println("  Auto-recovery dalam 2 detik...");
        lastErrorPrintTime = millis();
    }
    
    // Auto-recovery after 2 seconds in error state
    // This allows the system to recover quickly without manual intervention
    if (millis() - stateStartTime > 2000) {
        Serial.println("\n>>> Auto-recovery: Kembali ke IDLE setelah 2 detik di ERROR_STATE");
        errorCode = 0;
        errorMessage = "";
        changeState(IDLE);
    }
}

// ============================================
// HELPER FUNCTIONS
// ============================================

void StateMachine::changeState(State newState) {
    String oldName = getStateName();  // Capture name BEFORE changing state
    previousState = currentState;
    currentState = newState;
    stateStartTime = millis();
    
    Serial.printf("\n>>> State: %s → %s\n", 
                 oldName.c_str(), getStateName().c_str());
    
    // Send status update immediately when state changes (for real-time dashboard)
    serialComm.sendStatusOnStateChange();
}

void StateMachine::checkSafety() {
    // Check for limit switch conflict
    if (hardware.limitSwitch.isBothActive() && currentState != ERROR_STATE) {
        errorCode = ERROR_LIMIT_CONFLICT;
        errorMessage = "Both limit switches active";
        changeState(ERROR_STATE);
    }

    // JARING PENGAMAN ANTI-KEPENTOK (independen dari handler FSM, jalan tiap loop):
    // Bila sedang TURUN (CLEANING_FORWARD) dan LS2 (bawah) aktif, atau sedang NAIK
    // (CLEANING_BACKWARD/MOVING_TO_START) dan LS1 (atas) aktif, PAKSA wiper berhenti
    // seketika. Ini mencegah carriage menyodok ujung rel walau ada kasus tepi pada
    // logika handler. Transisi state tetap ditangani oleh handler masing-masing.
    if (currentState == CLEANING_FORWARD && hardware.limitSwitch.isLS2Active()) {
        hardware.wiperMotor.stop();
    }
    if ((currentState == CLEANING_BACKWARD || currentState == MOVING_TO_START)
        && hardware.limitSwitch.isLS1Active()) {
        hardware.wiperMotor.stop();
    }

    // PENGAMAN MANUAL (FSM IDLE — mis. test wiper naik/turun dari web/GUI):
    // hentikan wiper bila mencapai LS sesuai arah gerak. Arah dari dirSign yang
    // di-set saat setSpeed: +1 = naik (mentok LS1 atas), -1 = turun (mentok LS2
    // bawah). Pengaman ini di firmware (loop 100Hz) sehingga tidak bergantung
    // pada polling Raspberry Pi yang lebih lambat.
    if (currentState == IDLE && hardware.wiperMotor.getTargetRPM() > 0) {
        int dir = hardware.wiperMotor.getDirSign();
        if (dir > 0 && hardware.limitSwitch.isLS1Active()) {
            hardware.wiperMotor.stop();
        } else if (dir < 0 && hardware.limitSwitch.isLS2Active()) {
            hardware.wiperMotor.stop();
        }
    }
}

bool StateMachine::isMotorStalled() {
    // Deteksi stall berbasis PERGERAKAN POSISI (encoder quadrature directional).
    // Selama carriage masih bergerak (pulsa berubah > STALL_MIN_PULSES dalam
    // jendela timeout), motor TIDAK dianggap macet — walau RPM sesaat drop di
    // bawah threshold karena sag tegangan saat pompa + brush nyala (sedang/berat).
    // Macet sejati = carriage benar-benar diam selama MOTOR_STALL_TIMEOUT.
    long pos = hardware.wiperEncoder.getPulseCount();

    if (labs(pos - stallLastPos) > STALL_MIN_PULSES) {
        stallLastPos = pos;
        stallStartTime = millis();   // bergerak → reset timer
        return false;
    }

    // Tidak bergerak: macet bila melewati timeout
    return (millis() - stallStartTime > MOTOR_STALL_TIMEOUT);
}

void StateMachine::calculateProgress() {
    // Estimasi progres berbasis waktu (bukan posisi encoder) untuk kemudahan tampilan.
    // 30 detik per pass adalah perkiraan kasar (durasi nyata bervariasi 20-50 s
    // tergantung kecepatan cleaning dan level kotoran). Nilai di-constrain agar
    // progres tidak "melompat" di atas batas masing-masing fase.
    if (currentState == CLEANING_FORWARD) {
        // Progress from 15% to 60%
        unsigned long elapsed = millis() - stateStartTime;
        progress = 15 + (elapsed * 45 / 30000); // Estimasi 30 s untuk pass turun
        progress = constrain(progress, 15, 60);
    } else if (currentState == CLEANING_BACKWARD) {
        // Progress from 60% to 90%
        unsigned long elapsed = millis() - stateStartTime;
        progress = 60 + (elapsed * 30 / 30000); // Estimasi 30 s untuk pass naik
        progress = constrain(progress, 60, 90);
    }
}

String StateMachine::getStateName() {
    switch (currentState) {
        case IDLE: return "IDLE";
        case PRE_CHECK: return "PRE_CHECK";
        case MOVING_TO_START: return "MOVING_TO_START";
        case SPRAYING_WATER: return "SPRAYING_WATER";
        case CLEANING_FORWARD: return "CLEANING_FORWARD";
        case CLEANING_BACKWARD: return "CLEANING_BACKWARD";
        case STOPPING: return "STOPPING";
        case DONE: return "DONE";
        case ERROR_STATE: return "ERROR_STATE";
        default: return "UNKNOWN";
    }
}

String StateMachine::getCleaningLevel() {
    switch (params.level) {
        case CLEAN_LIGHT:  return "RINGAN";
        case CLEAN_MEDIUM: return "SEDANG";
        case CLEAN_HEAVY:  return "BERAT";
        default:           return "TIDAK_DIKETAHUI";
    }
}

// ============================================
// COMMAND HANDLERS
// ============================================

void StateMachine::startCleaningCycle(float wiperSpeed, float brushSpeed, unsigned long duration) {
    if (currentState != IDLE) {
        Serial.println("Tidak dapat memulai pembersihan: tidak dalam status SIAGA");
        return;
    }
    
    // Tentukan cleaning level berdasarkan score
    // Score dikirim dari Raspberry Pi via parameter atau dari command JSON
    float score = 0;
    
    // Jika parameter default (dari manual trigger), gunakan medium
    // Jika dari RPi, score akan di-set via startCleaningCycleWithScore()
    params.wiperSpeed = constrain(wiperSpeed, WIPER_MIN_RPM, WIPER_MAX_RPM);
    params.brushSpeed = (brushSpeed <= 0) ? 0 : constrain(brushSpeed, BRUSH_MIN_RPM, BRUSH_MAX_RPM);
    params.duration = duration;
    params.score = score;
    params.level = CLEAN_MEDIUM;
    params.totalPasses = MEDIUM_PASS_COUNT;
    params.currentPass = 1;
    
    Serial.println("\n========================================");
    Serial.println("MEMULAI SIKLUS PEMBERSIHAN");
    Serial.println("========================================");
    Serial.printf("Level: SEDANG (manual trigger)\n");
    Serial.printf("Kecepatan wiper: %.1f RPM\n", params.wiperSpeed);
    Serial.printf("Kecepatan sikat: %.1f RPM\n", params.brushSpeed);
    Serial.printf("Durasi air: %lu ms\n", params.duration);
    Serial.printf("Jumlah pass: %d\n", params.totalPasses);
    Serial.println("========================================\n");
    
    progress = 0;
    cleaningStartTime = millis();
    changeState(PRE_CHECK);
}

void StateMachine::startCleaningCycleAdaptive(float score) {
    if (currentState != IDLE) {
        Serial.println("Tidak dapat memulai pembersihan: tidak dalam status SIAGA");
        return;
    }
    
    params.score = score;
    
    // Tentukan level berdasarkan score dari YOLO
    // Score < 70 seharusnya tidak sampai sini (difilter oleh Raspberry Pi),
    // tapi tambahkan safety check untuk konsistensi
    if (score < CLEAN_SCORE_THRESHOLD) {
        // Bersih: tidak perlu pembersihan (safety check)
        Serial.printf("Score %.1f < 70, panel bersih. Pembersihan dibatalkan.\n", score);
        return;
    } else if (score < CLEAN_SCORE_LIGHT) {
        // Kotor Ringan (score 70-169): sikat kering cepat, tanpa air
        params.level = CLEAN_LIGHT;
        params.wiperSpeed = LIGHT_WIPER_SPEED;
        params.brushSpeed = LIGHT_BRUSH_SPEED;
        params.duration = LIGHT_SPRAY_DURATION;
        params.totalPasses = LIGHT_PASS_COUNT;
    } else if (score < CLEAN_SCORE_MEDIUM) {
        // Kotor Sedang: semprot (saat turun) + wiper + brush, kecepatan sedang
        params.level = CLEAN_MEDIUM;
        params.wiperSpeed = MEDIUM_WIPER_SPEED;
        params.brushSpeed = MEDIUM_BRUSH_SPEED;
        params.duration = MEDIUM_SPRAY_DURATION;
        params.totalPasses = MEDIUM_PASS_COUNT;
    } else {
        // Kotor Berat: semprot (saat turun) + wiper + brush intensif, pelan, 2x pass
        params.level = CLEAN_HEAVY;
        params.wiperSpeed = HEAVY_WIPER_SPEED;
        params.brushSpeed = HEAVY_BRUSH_SPEED;
        params.duration = HEAVY_SPRAY_DURATION;
        params.totalPasses = HEAVY_PASS_COUNT;
    }
    params.currentPass = 1;
    
    // Nama level untuk log
    const char* levelNames[] = {"RINGAN", "SEDANG", "BERAT"};
    
    Serial.println("\n========================================");
    Serial.println("MEMULAI SIKLUS PEMBERSIHAN ADAPTIF");
    Serial.println("========================================");
    Serial.printf("Score: %.1f → Level: %s\n", score, levelNames[params.level]);
    Serial.printf("Kecepatan wiper: %.1f RPM\n", params.wiperSpeed);
    Serial.printf("Kecepatan sikat: %.1f RPM %s\n", params.brushSpeed, 
                  params.brushSpeed == 0 ? "(MATI)" : "");
    Serial.printf("Durasi air: %lu ms (%.1f detik)\n", params.duration, params.duration / 1000.0);
    Serial.printf("Jumlah pass: %d\n", params.totalPasses);
    Serial.println("========================================\n");
    
    progress = 0;
    cleaningStartTime = millis();
    changeState(PRE_CHECK);
}

void StateMachine::emergencyStop() {
    Serial.println("\nBERHENTI DARURAT DIPICU!");
    hardware.emergencyStop();
    changeState(IDLE);
    progress = 0;
}
