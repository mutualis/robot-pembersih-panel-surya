/**
 * Solar Panel Cleaning Robot - ESP32 Main Controller
 * 
 * Sistem pembersihan panel surya otomatis dengan:
 * - Wiper motor (dengan encoder dan PID control)
 * - Brush motor (rotating brush)
 * - Water pump (relay control)
 * - Limit switches (safety)
 * - Serial communication dengan Raspberry Pi
 * 
 * Author: Muhammad Ridho Assidiqi
 * Institution: Universitas Gadjah Mada
 */

#include <Arduino.h>
#include "config.h"
#include "hardware.h"
#include "state_machine.h"
#include "serial_comm.h"

// ============================================
// GLOBAL OBJECTS
// ============================================

Hardware hardware;
StateMachine stateMachine;
SerialComm serialComm;

// ============================================
// SETUP
// ============================================

void setup() {
    // PALING AWAL: paksa pin motor & pompa ke LOW agar tidak bergerak saat boot/reset
    // (mis. saat RPi membuka port serial -> DTR/RTS auto-reset ESP32).
    hardware.preInitSafe();

    // Initialize serial communication
    // Serial0 (USB) and Serial2 (UART2) will be initialized in serialComm.init()
    delay(100);
    
    Serial.begin(115200);  // Initialize USB Serial for early messages
    Serial.println("\n\n========================================");
    Serial.println("Robot Pembersih Panel Surya - ESP32");
    Serial.println("Muhammad Ridho Assidiqi - UGM");
    Serial.println("========================================\n");
    
    // Initialize hardware
    Serial.println("Menginisialisasi hardware...");
    hardware.init();
    Serial.println("✓ Hardware berhasil diinisialisasi\n");
    
    // Initialize state machine
    Serial.println("Menginisialisasi state machine...");
    stateMachine.init();
    Serial.println("✓ State machine berhasil diinisialisasi\n");
    
    // Initialize serial communication (will setup Serial2)
    Serial.println("Menginisialisasi komunikasi serial...");
    serialComm.init();
    Serial.println("✓ Komunikasi serial berhasil diinisialisasi\n");
    
    Serial.println("Sistem siap!");
    Serial.println("Serial0 (USB): Monitoring & Debug");
    Serial.println("Serial2 (GPIO16/17): Raspberry Pi Communication");
    Serial.println("Menunggu perintah dari Raspberry Pi...\n");
}

// ============================================
// MAIN LOOP
// ============================================

void loop() {
    // Update hardware (read sensors, update motors)
    hardware.update();
    
    // Handle incoming serial commands
    serialComm.handleIncoming();
    
    // Update state machine
    stateMachine.update();
    
    // Send periodic status updates
    serialComm.sendPeriodicStatus();
    
    // Small delay for stability
    delay(10); // 100Hz loop rate
}
