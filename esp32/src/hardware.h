/**
 * Hardware Control Module
 * 
 * Modul ini mengatur semua hardware pada sistem:
 * - Motor: Wiper (PID closed-loop) dan Brush (open-loop PWM)
 * - Encoder: Rotary encoder untuk feedback kecepatan wiper
 * - Limit Switch: Pembatas posisi atas dan bawah wiper
 * - Pump: Relay control untuk pompa air
 * - LED: Status indicator
 * 
 * Author: Muhammad Ridho Assidiqi
 * Institution: Universitas Gadjah Mada
 */

#ifndef HARDWARE_H
#define HARDWARE_H

#include <Arduino.h>
#include "config.h"

// ============================================
// MOTOR CLASS
// ============================================

class Motor {
private:
    int pwmPin;
    int dir1Pin;
    int dir2Pin;
    int pwmChannel;
    float currentRPM;
    float targetRPM;
    int currentPWM;
    
    // PID variables
    float kp, ki, kd;
    float integral;
    float lastError;
    unsigned long lastPIDTime;
    int startupKickRemaining;  // sisa tick startup kick (lepas dead zone)
    int dirSign;               // arah perintah terakhir: +1 naik (LS1), -1 turun (LS2), 0 stop

public:
    Motor(int pwm, int d1, int d2, int channel, float p, float i, float d);
    void init();
    void setSpeed(float rpm);                           // rpm > 0 = naik (LS1), rpm < 0 = turun (LS2), 0 = stop
    void setSpeedOpenLoop(float rpm, float maxRPM);    // Kontrol open-loop (brush, tanpa encoder/PID)
    void setPID(float p, float i, float d);             // Ubah gain PID saat runtime (kalibrasi)
    void stop();
    void updatePID(float measuredRPM);
    float getTargetRPM() { return targetRPM; }
    float getCurrentRPM() { return currentRPM; }
    int getCurrentPWM() { return currentPWM; }
    int getDirSign() { return dirSign; }  // arah gerak untuk pengaman LS manual
};

// ============================================
// ENCODER CLASS
// ============================================

class Encoder {
private:
    int pinA;
    int pinB;
    long encoderCount;        // akumulasi posisi (dari PCNT hardware)
    float rpm;                // RPM output (setelah koreksi gear ratio)
    float rawRPM;             // RPM poros encoder (sebelum gear ratio) — untuk kalibrasi
    float gearRatio;          // Gear ratio for RPM correction
    unsigned long lastUpdateTime;
    
public:
    Encoder(int a, int b, float ratio = 1.0);
    void init();              // setup PCNT + glitch filter
    void updateRPM();
    void setGearRatio(float ratio);  // For calibration
    float getRPM() { return rpm; }
    float getRawRPM() { return rawRPM; }  // RPM sebelum koreksi gear ratio
    long getPulseCount() { return encoderCount; }
    void resetPulseCount();   // reset akumulasi + PCNT counter
};

// ============================================
// LIMIT SWITCH CLASS
// ============================================

class LimitSwitch {
private:
    int pin1;
    int pin2;
    bool state1;
    bool state2;
    bool justPressed1;   // edge one-shot: di-set saat transisi LEPAS->TEKAN (0->1)
    bool justPressed2;
    unsigned long lastDebounceTime1;
    unsigned long lastDebounceTime2;
    
public:
    LimitSwitch(int p1, int p2);
    void init();
    void update();
    bool isLS1Active() { return state1; }
    bool isLS2Active() { return state2; }
    bool isBothActive() { return state1 && state2; }
    // Konsumsi event edge (latched): true sekali bila ada tekanan baru sejak
    // terakhir dikonsumsi. Menangkap kontak singkat yang bisa lolos cek level.
    bool consumeLS1JustPressed() { bool v = justPressed1; justPressed1 = false; return v; }
    bool consumeLS2JustPressed() { bool v = justPressed2; justPressed2 = false; return v; }
    void clearEvents() { justPressed1 = false; justPressed2 = false; }
};

// ============================================
// PUMP CLASS
// ============================================

class Pump {
private:
    int relayPin;
    bool isOn;
    unsigned long startTime;
    unsigned long duration;
    
public:
    Pump(int pin);
    void init();
    void turnOn(unsigned long durationMs = 0);
    void turnOff();
    void update();
    bool getState() { return isOn; }
};

// ============================================
// HARDWARE MANAGER CLASS
// ============================================

class Hardware {
public:
    Motor wiperMotor;
    Motor brushMotor;
    Encoder wiperEncoder;
    LimitSwitch limitSwitch;
    Pump pump;
    
    Hardware();
    void init();
    void preInitSafe();   // paksa pin motor/pompa LOW secepatnya (cegah gerak saat boot)
    void update();
    void emergencyStop();
    void blinkLED(int times = 1);
};

// Global hardware instance (untuk interrupt handlers)
extern Hardware* g_hardware;

#endif // HARDWARE_H
