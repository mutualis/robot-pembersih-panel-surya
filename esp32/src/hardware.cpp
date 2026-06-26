/**
 * Hardware Control Implementation
 * 
 * Implementasi kontrol hardware meliputi:
 * - Motor: PWM control dengan PID (wiper) dan open-loop (brush)
 * - Encoder: Interrupt-based pulse counting untuk kalkulasi RPM
 * - Limit Switch: Debounced digital input dengan pull-up
 * - Pump: Relay ON/OFF dengan auto-off timer
 * 
 * Author: Muhammad Ridho Assidiqi
 * Institution: Universitas Gadjah Mada
 */

#include "hardware.h"
#include "driver/pcnt.h"   // Hardware Pulse Counter + glitch filter untuk encoder

#define PCNT_ENCODER_UNIT  PCNT_UNIT_0

// Global pointer (dipakai modul lain)
Hardware* g_hardware = nullptr;

// ============================================
// MOTOR CLASS IMPLEMENTATION
// ============================================

Motor::Motor(int pwm, int d1, int d2, int channel, float p, float i, float d)
    : pwmPin(pwm), dir1Pin(d1), dir2Pin(d2), pwmChannel(channel),
      kp(p), ki(i), kd(d), currentRPM(0), targetRPM(0), currentPWM(0),
      integral(0), lastError(0), lastPIDTime(0),
      startupKickRemaining(WIPER_STARTUP_KICK_TICKS), dirSign(0) {}

void Motor::init() {
    pinMode(dir1Pin, OUTPUT);
    pinMode(dir2Pin, OUTPUT);
    
    ledcSetup(pwmChannel, PWM_FREQUENCY, PWM_RESOLUTION);
    ledcAttachPin(pwmPin, pwmChannel);
    
    stop();
}

void Motor::setSpeed(float rpm) {
    targetRPM = constrain(abs(rpm), 0, WIPER_MAX_RPM);
    
    // Reset PID timing to prevent derivative kick on first update
    if (lastPIDTime == 0 || targetRPM == 0) {
        lastPIDTime = millis();
        integral = 0;
        lastError = 0;
        startupKickRemaining = WIPER_STARTUP_KICK_TICKS;
    }
    
    if (rpm > 0) {
        // Forward direction
        digitalWrite(dir1Pin, HIGH);
        digitalWrite(dir2Pin, LOW);
        dirSign = 1;   // naik (menuju LS1 atas)
    } else if (rpm < 0) {
        // Reverse direction
        digitalWrite(dir1Pin, LOW);
        digitalWrite(dir2Pin, HIGH);
        dirSign = -1;  // turun (menuju LS2 bawah)
    } else {
        digitalWrite(dir1Pin, LOW);
        digitalWrite(dir2Pin, LOW);
        dirSign = 0;
    }
}

void Motor::setSpeedOpenLoop(float rpm, float maxRPM) {
    // Open-loop control: langsung konversi RPM ke PWM
    // Untuk motor tanpa encoder (brush motor)
    targetRPM = constrain(rpm, 0, maxRPM);
    
    if (targetRPM > 0) {
        // Set direction (arah putar brush: dibalik agar memutar ke depan/forward)
        digitalWrite(dir1Pin, LOW);
        digitalWrite(dir2Pin, HIGH);
        
        // Calculate PWM: PWM = (target_rpm / max_rpm) * 255
        currentPWM = (int)((targetRPM / maxRPM) * 255.0);
        currentPWM = constrain(currentPWM, 0, 255);
        
        // Apply PWM immediately
        ledcWrite(pwmChannel, currentPWM);
        
        Serial.printf("Brush Open-Loop: %.1f RPM -> PWM %d\n", targetRPM, currentPWM);
    } else {
        stop();
    }
}

void Motor::setPID(float p, float i, float d) {
    // Update PID parameters (for tuning)
    kp = p;
    ki = i;
    kd = d;
    
    // Reset PID state
    integral = 0;
    lastError = 0;
    
    Serial.printf("PID Updated: Kp=%.3f, Ki=%.3f, Kd=%.3f\n", kp, ki, kd);
}

void Motor::stop() {
    targetRPM = 0;
    currentPWM = 0;
    dirSign = 0;
    ledcWrite(pwmChannel, 0);
    digitalWrite(dir1Pin, LOW);
    digitalWrite(dir2Pin, LOW);
    
    // Reset PID
    integral = 0;
    lastError = 0;
    startupKickRemaining = WIPER_STARTUP_KICK_TICKS;
}

void Motor::updatePID(float measuredRPM) {
    currentRPM = measuredRPM;
    
    if (targetRPM == 0) {
        stop();
        return;
    }
    
    unsigned long now = millis();
    float dt = (now - lastPIDTime) / 1000.0; // Convert to seconds
    
    if (dt < 0.01) return; // Update at most 100Hz
    
    lastPIDTime = now;
    
    // Calculate error
    float error = targetRPM - currentRPM;
    
    // Deadband — prevents chatter around setpoint
    if (abs(error) < WIPER_PID_DEADBAND) {
        error = 0;
    }
    
    // Feedforward: basis PWM proporsional terhadap setpoint (lepas dead zone).
    // Tanpa ini, sinyal kontrol harus dibangun penuh dari integral -> tersendat.
    float ff = WIPER_FF_PWM_MIN + WIPER_FF_SLOPE * (targetRPM - WIPER_FF_RPM_MIN);
    
    // PID calculation
    float P = kp * error;
    // Conditional integration (anti-windup): akumulasi hanya saat error di dalam
    // pita aktif, supaya tidak windup pada fase rise (penyebab overshoot awal).
    if (abs(error) <= WIPER_INTEGRAL_BAND) {
        integral += error * dt;
        integral = constrain(integral, -50, 50); // Anti-windup
    }
    float I = ki * integral;
    float D = kd * (error - lastError) / dt;
    
    float output = ff + P + I + D;
    
    // Startup kick: saat motor masih diam (RPM < 5) di awal, dorong PWM agar
    // lepas dari dead zone gearbox; reset begitu motor mulai berputar.
    if (targetRPM > 0 && currentRPM < 5.0 && startupKickRemaining > 0) {
        output = max(output, (float)WIPER_STARTUP_KICK_PWM);
        startupKickRemaining--;
    } else if (currentRPM >= 5.0) {
        startupKickRemaining = 0;
    }
    
    // Convert to PWM (0-255)
    currentPWM = constrain((int)output, 0, 255);
    // Jaga PWM di atas dead zone saat motor diperintah bergerak
    if (targetRPM > 0 && currentPWM < WIPER_PWM_MIN_DRIVE) {
        currentPWM = WIPER_PWM_MIN_DRIVE;
    }
    
    // Apply PWM
    ledcWrite(pwmChannel, currentPWM);
    
    lastError = error;
}

// ============================================
// ENCODER CLASS IMPLEMENTATION
// ============================================

Encoder::Encoder(int a, int b, float ratio)
    : pinA(a), pinB(b), encoderCount(0), rpm(0), rawRPM(0),
      gearRatio(ratio), lastUpdateTime(0) {}

void Encoder::init() {
    pinMode(pinA, INPUT_PULLUP);
    pinMode(pinB, INPUT_PULLUP);

    // PCNT quadrature 1x: hitung RISING edge channel A (11 PPR), arah ditentukan
    // level channel B. Hasil count SIGNED — bertambah saat satu arah, berkurang
    // saat arah sebaliknya (untuk posisi/arah carriage yang benar). Glitch filter
    // membuang spike EMI motor.
    //   B HIGH  -> hitung naik (KEEP)
    //   B LOW   -> hitung turun (REVERSE)
    // Jika arah terbalik dengan gerak fisik, tukar REVERSE<->KEEP di bawah.
    pcnt_config_t cfg = {};
    cfg.pulse_gpio_num = pinA;
    cfg.ctrl_gpio_num  = pinB;             // pin B = penentu arah (quadrature)
    cfg.channel        = PCNT_CHANNEL_0;
    cfg.unit           = PCNT_ENCODER_UNIT;
    cfg.pos_mode       = PCNT_COUNT_INC;   // hitung tiap rising edge A
    cfg.neg_mode       = PCNT_COUNT_DIS;   // abaikan falling
    cfg.lctrl_mode     = PCNT_MODE_REVERSE; // B LOW  -> balik arah hitung (turun)
    cfg.hctrl_mode     = PCNT_MODE_KEEP;    // B HIGH -> arah hitung tetap (naik)
    cfg.counter_h_lim  = 32767;
    cfg.counter_l_lim  = -32768;
    pcnt_unit_config(&cfg);

    pcnt_set_filter_value(PCNT_ENCODER_UNIT, PCNT_GLITCH_FILTER);
    pcnt_filter_enable(PCNT_ENCODER_UNIT);

    pcnt_counter_pause(PCNT_ENCODER_UNIT);
    pcnt_counter_clear(PCNT_ENCODER_UNIT);
    pcnt_counter_resume(PCNT_ENCODER_UNIT);

    encoderCount = 0;
    rpm = 0;
    rawRPM = 0;
    lastUpdateTime = millis();
}

void Encoder::updateRPM() {
    unsigned long now = millis();
    unsigned long dt = now - lastUpdateTime;
    if (dt < RPM_UPDATE_INTERVAL) return;

    // Baca pulsa terfilter dari PCNT lalu clear (hindari overflow 16-bit).
    int16_t pcntVal = 0;
    pcnt_get_counter_value(PCNT_ENCODER_UNIT, &pcntVal);
    pcnt_counter_clear(PCNT_ENCODER_UNIT);
    encoderCount += pcntVal;

    float deltaMinutes = dt / 60000.0;
    float rpmEncoder = fabsf(((float)pcntVal / (float)ENCODER_PPR) / deltaMinutes);
    float newRPM = rpmEncoder / gearRatio;

    // Glitch: pembacaan absurd diabaikan agar PID tidak react ke noise.
    // TIDAK pakai LPF (delay = dead-time yang merusak kestabilan PID).
    if (newRPM <= WIPER_MAX_ALLOWED_RPM) {
        rpm = newRPM;
        rawRPM = rpmEncoder;
    }

    lastUpdateTime = now;
}

void Encoder::setGearRatio(float ratio) {
    if (ratio > 0) {
        gearRatio = ratio;
        Serial.printf("Gear ratio updated: %.2f:1\n", ratio);
    }
}

void Encoder::resetPulseCount() {
    encoderCount = 0;
    pcnt_counter_clear(PCNT_ENCODER_UNIT);
}

// ============================================
// LIMIT SWITCH CLASS IMPLEMENTATION
// ============================================

LimitSwitch::LimitSwitch(int p1, int p2)
    : pin1(p1), pin2(p2), state1(false), state2(false),
      justPressed1(false), justPressed2(false),
      lastDebounceTime1(0), lastDebounceTime2(0) {}

void LimitSwitch::init() {
    // Pull-up INTERNAL diaktifkan (INPUT_PULLUP) agar pembacaan andal meskipun
    // pull-up eksternal PCB tidak terpasang/efektif — konsisten dengan firmware
    // motor_test (yang berfungsi). Pull-up internal (~45kΩ) paralel dengan
    // eksternal 10kΩ aman. Switch NO: HIGH = tidak pressed, LOW = pressed (active LOW).
    pinMode(pin1, INPUT_PULLUP);
    pinMode(pin2, INPUT_PULLUP);
}

void LimitSwitch::update() {
    unsigned long now = millis();
    
    // Read LS1 with proper debounce (Schmitt trigger pattern)
    bool reading1 = (digitalRead(pin1) == LOW); // Active LOW
    if (reading1 != state1 && (now - lastDebounceTime1 > 50)) {
        if (reading1 && !state1) justPressed1 = true; // edge LEPAS->TEKAN (latched)
        state1 = reading1;
        lastDebounceTime1 = now;
        if (state1) {
            Serial.println("Limit Switch 1 (ATAS) terpicu");
        }
    }
    
    // Read LS2 with proper debounce
    bool reading2 = (digitalRead(pin2) == LOW); // Active LOW
    if (reading2 != state2 && (now - lastDebounceTime2 > 50)) {
        if (reading2 && !state2) justPressed2 = true; // edge LEPAS->TEKAN (latched)
        state2 = reading2;
        lastDebounceTime2 = now;
        if (state2) {
            Serial.println("Limit Switch 2 (BAWAH) terpicu");
        }
    }
}

// ============================================
// PUMP CLASS IMPLEMENTATION
// ============================================

Pump::Pump(int pin)
    : relayPin(pin), isOn(false), startTime(0), duration(0) {}

void Pump::init() {
    pinMode(relayPin, OUTPUT);
    digitalWrite(relayPin, LOW);   // Relay OFF (active HIGH via NPN)
    isOn = false;
}

void Pump::turnOn(unsigned long durationMs) {
    // Safety: batas durasi maksimum pompa untuk cegah air meluap / pompa jalan kering.
    // 45 s dipilih agar menampung semprot KONTINU sepanjang 1 pass turun (~31 s pada
    // 35 RPM) tanpa terpotong; pada siklus, FSM mematikan pompa saat pass naik jauh
    // sebelum batas ini. Perintah manual (mis. uji pompa 3/5/8 s) tetap memakai
    // durasinya sendiri karena < batas ini.
    const unsigned long MAX_PUMP_DURATION = 45000;
    if (durationMs == 0 || durationMs > MAX_PUMP_DURATION) {
        durationMs = MAX_PUMP_DURATION;
        Serial.printf("Pompa: durasi dibatasi ke %lu ms (safety)\n", durationMs);
    }
    
    digitalWrite(relayPin, HIGH);  // Relay ON (NPN transistor conducts)
    isOn = true;
    startTime = millis();
    duration = durationMs;
    Serial.printf("Pompa: NYALA (%lu ms)\n", durationMs);
}

void Pump::turnOff() {
    digitalWrite(relayPin, LOW);   // Relay OFF (NPN transistor off)
    isOn = false;
    duration = 0;
    Serial.println("Pompa: MATI");
}

void Pump::update() {
    if (isOn && duration > 0) {
        if (millis() - startTime >= duration) {
            turnOff();
        }
    }
}

// ============================================
// HARDWARE MANAGER IMPLEMENTATION
// ============================================

Hardware::Hardware()
    : wiperMotor(WIPER_ENA, WIPER_IN1, WIPER_IN2, PWM_CHANNEL_WIPER, 
                 WIPER_KP, WIPER_KI, WIPER_KD),
      brushMotor(BRUSH_ENB, BRUSH_IN3, BRUSH_IN4, PWM_CHANNEL_BRUSH,
                 BRUSH_KP, BRUSH_KI, BRUSH_KD),
      wiperEncoder(WIPER_ENCODER_A, WIPER_ENCODER_B, WIPER_GEAR_RATIO),
      limitSwitch(LIMIT_SWITCH_1, LIMIT_SWITCH_2),
      pump(PUMP_RELAY) {
    g_hardware = this;
}

void Hardware::preInitSafe() {
    // Dipanggil PALING AWAL di setup() (sebelum delay/Serial). Memaksa semua pin
    // kontrol motor & pompa ke OUTPUT LOW secepat mungkin agar motor TIDAK bergerak
    // saat power-on/reset. Penting karena: (1) GPIO14 (WIPER_ENA) mengeluarkan sinyal
    // PWM bawaan saat boot ESP32; (2) input L298N mengambang sebelum pin dikonfigurasi;
    // (3) saat RPi membuka port serial, DTR/RTS mereset ESP32 -> boot ulang.
    pinMode(WIPER_ENA, OUTPUT);  digitalWrite(WIPER_ENA, LOW);
    pinMode(WIPER_IN1, OUTPUT);  digitalWrite(WIPER_IN1, LOW);
    pinMode(WIPER_IN2, OUTPUT);  digitalWrite(WIPER_IN2, LOW);
    pinMode(BRUSH_ENB, OUTPUT);  digitalWrite(BRUSH_ENB, LOW);
    pinMode(BRUSH_IN3, OUTPUT);  digitalWrite(BRUSH_IN3, LOW);
    pinMode(BRUSH_IN4, OUTPUT);  digitalWrite(BRUSH_IN4, LOW);
    pinMode(PUMP_RELAY, OUTPUT); digitalWrite(PUMP_RELAY, LOW);
}

void Hardware::init() {
    // Initialize LED
    pinMode(LED_STATUS, OUTPUT);
    digitalWrite(LED_STATUS, LOW);
    
    // Initialize motors
    wiperMotor.init();
    brushMotor.init();
    
    // Initialize encoder (PCNT hardware counter, tidak perlu attachInterrupt)
    wiperEncoder.init();
    
    // Initialize limit switches
    limitSwitch.init();
    
    // Initialize pump
    pump.init();
    
    // Blink LED to indicate initialization
    blinkLED(3);
}

void Hardware::update() {
    // Update encoder RPM
    wiperEncoder.updateRPM();
    
    // Update motor PID controllers
    wiperMotor.updatePID(wiperEncoder.getRPM());
    
    // Brush motor: open-loop control (no encoder, no PID)
    // brushMotor.updatePID(0) tidak diperlukan karena sudah set PWM langsung
    
    // Update limit switches
    limitSwitch.update();
    
    // Update pump (auto-off after duration)
    pump.update();
}

void Hardware::emergencyStop() {
    wiperMotor.stop();
    brushMotor.stop();
    pump.turnOff();
    Serial.println("BERHENTI DARURAT!");
}

void Hardware::blinkLED(int times) {
    for (int i = 0; i < times; i++) {
        digitalWrite(LED_STATUS, HIGH);
        delay(100);
        digitalWrite(LED_STATUS, LOW);
        delay(100);
    }
}
