/**
 * Serial Communication Implementation
 * 
 * Implementasi protokol komunikasi JSON antara ESP32 dan Raspberry Pi.
 * Menggunakan Serial2 (UART2) pada baudrate 115200.
 * Serial0 (USB) digunakan untuk debugging dan monitoring.
 * 
 * Format pesan: JSON diakhiri newline (\n)
 * Contoh: {"cmd":"clean_cycle","zone":0,"score":50.0}\n
 * 
 * Author: Muhammad Ridho Assidiqi
 * Institution: Universitas Gadjah Mada
 */

#include "serial_comm.h"
#include "hardware.h"
#include "state_machine.h"

extern Hardware hardware;
extern StateMachine stateMachine;

// ============================================
// CONSTRUCTOR & INITIALIZATION
// ============================================

SerialComm::SerialComm()
    : lastStatusTime(0), lastHeartbeatTime(0) {}

void SerialComm::init() {
    // Initialize Serial0 (USB) for debugging
    DEBUG_SERIAL.begin(DEBUG_BAUDRATE);
    DEBUG_SERIAL.setTimeout(20);   // jangan block lama di readStringUntil
    DEBUG_SERIAL.println("\n=== ESP32 Serial Communication ===");
    DEBUG_SERIAL.println("Serial0 (USB): Debugging & Monitoring");
    DEBUG_SERIAL.println("Serial2 (UART2): Raspberry Pi Communication");
    
    // Initialize Serial2 (UART2) for Raspberry Pi communication
    RPI_SERIAL.begin(RPI_BAUDRATE, SERIAL_8N1, RPI_RX_PIN, RPI_TX_PIN);
    RPI_SERIAL.setTimeout(20);     // timeout pendek: hindari loop ngeblok saat RX noise/mengambang
    DEBUG_SERIAL.printf("Serial2 initialized: RX=%d, TX=%d, Baud=%d\n", 
                        RPI_RX_PIN, RPI_TX_PIN, RPI_BAUDRATE);
    
    lastStatusTime = millis();
    lastHeartbeatTime = millis();
    
    DEBUG_SERIAL.println("Serial communication ready!\n");
    
    // Send initial status to Raspberry Pi so dashboard knows ESP32 is connected
    delay(500);  // Wait for Raspberry Pi to be ready
    sendStatus();
    DEBUG_SERIAL.println("Initial status sent to Raspberry Pi\n");
}

// ============================================
// INCOMING COMMAND HANDLER
// ============================================

void SerialComm::handleIncoming() {
    // Cek command dari Serial2 (Raspberry Pi via GPIO 16/17)
    // Hanya proses baris yang diawali '{' agar noise pada RX yang mengambang
    // (saat RPi belum terhubung) tidak dianggap perintah dan tidak spam error.
    if (RPI_SERIAL.available() > 0) {
        String jsonString = RPI_SERIAL.readStringUntil('\n');
        jsonString.trim();
        if (jsonString.length() > 0 && jsonString.startsWith("{")) {
            DEBUG_SERIAL.printf("RX from RPi (Serial2): %s\n", jsonString.c_str());
            processCommand(jsonString);
        }
    }
    
    // Cek command dari Serial0 (USB cable, untuk testing dari Windows)
    if (DEBUG_SERIAL.available() > 0) {
        String jsonString = DEBUG_SERIAL.readStringUntil('\n');
        jsonString.trim();
        if (jsonString.length() > 0 && jsonString.startsWith("{")) {
            DEBUG_SERIAL.printf("RX from USB: %s\n", jsonString.c_str());
            processCommand(jsonString);
        }
    }
}

void SerialComm::processCommand(String& jsonString) {
    // Buffer overflow protection: reject commands larger than JSON buffer
    if (jsonString.length() > 384) {
        DEBUG_SERIAL.printf("Command too long (%d bytes), max 384\n", jsonString.length());
        sendError(ERROR_INVALID_COMMAND, "Command terlalu panjang");
        return;
    }
    
    // Parse JSON
    DeserializationError error = deserializeJson(jsonDoc, jsonString);
    
    if (error) {
        DEBUG_SERIAL.printf("JSON Parse Error: %s\n", error.c_str());
        sendError(ERROR_INVALID_COMMAND, "Format JSON tidak valid");
        return;
    }
    
    JsonObject cmd = jsonDoc.as<JsonObject>();
    
    // Get command name
    if (!cmd.containsKey("cmd")) {
        DEBUG_SERIAL.println("Missing 'cmd' field");
        sendError(ERROR_INVALID_COMMAND, "Field 'cmd' tidak ada");
        return;
    }
    
    String cmdName = cmd["cmd"].as<String>();
    
    DEBUG_SERIAL.printf("Command: %s\n", cmdName.c_str());
    
    // Route command
    if (cmdName == "siklus_pembersihan" || cmdName == "clean_cycle") {
        handleCleaningCycleCommand(cmd);
    }
    else if (cmdName == "mulai_wiper" || cmdName == "start_wiper") {
        handleWiperCommand(cmd);
    }
    else if (cmdName == "berhenti_wiper" || cmdName == "stop_wiper") {
        hardware.wiperMotor.stop();
        sendAck(cmdName.c_str());
    }
    else if (cmdName == "mulai_sikat" || cmdName == "start_brush") {
        handleBrushCommand(cmd);
    }
    else if (cmdName == "berhenti_sikat" || cmdName == "stop_brush") {
        hardware.brushMotor.stop();
        sendAck(cmdName.c_str());
    }
    else if (cmdName == "pompa_nyala" || cmdName == "pump_on") {
        handlePumpCommand(cmd);
    }
    else if (cmdName == "pompa_mati" || cmdName == "pump_off") {
        hardware.pump.turnOff();
        sendAck(cmdName.c_str());
    }
    else if (cmdName == "stop") {
        handleStopCommand();
    }
    else if (cmdName == "status") {
        handleStatusCommand();
    }
    else {
        sendError(ERROR_INVALID_COMMAND, "Perintah tidak dikenal");
    }
}

// ============================================
// COMMAND HANDLERS
// ============================================

void SerialComm::handleCleaningCycleCommand(JsonObject& cmd) {
    // Parse score dari Raspberry Pi
    float score = cmd["score"] | 0.0;
    int zone = cmd["zone"] | 0;
    
    Serial.printf("Zona: %d, Score: %.1f\n", zone, score);
    
    // Send acknowledgment
    String cmdName = cmd["cmd"].as<String>();
    sendAck(cmdName.c_str());
    
    // Gunakan adaptive cleaning berdasarkan score
    if (score > 0) {
        // Score dari YOLO → adaptive cleaning
        stateMachine.startCleaningCycleAdaptive(score);
    } else {
        // Manual trigger tanpa score → cek parameter manual
        float wiperSpeed = cmd["speed"] | MEDIUM_WIPER_SPEED;
        float brushSpeed = cmd["brush_speed"] | MEDIUM_BRUSH_SPEED;
        unsigned long duration = cmd["duration"] | MEDIUM_SPRAY_DURATION;
        
        // Validate parameters
        if (wiperSpeed < WIPER_MIN_RPM || wiperSpeed > WIPER_MAX_RPM) {
            sendError(ERROR_INVALID_PARAM, "Kecepatan wiper tidak valid");
            return;
        }
        
        stateMachine.startCleaningCycle(wiperSpeed, brushSpeed, duration);
    }
}

void SerialComm::handleWiperCommand(JsonObject& cmd) {
    float speed = cmd["speed"] | WIPER_DEFAULT_RPM;
    int direction = cmd["direction"] | 1;
    
    if (direction == 1) {
        hardware.wiperMotor.setSpeed(speed);
    } else {
        hardware.wiperMotor.setSpeed(-speed);
    }
    
    sendAck("mulai_wiper");
}

void SerialComm::handleBrushCommand(JsonObject& cmd) {
    float speed = cmd["speed"] | BRUSH_DEFAULT_RPM;
    hardware.brushMotor.setSpeedOpenLoop(speed, BRUSH_MAX_RPM);
    sendAck("mulai_sikat");
}

void SerialComm::handlePumpCommand(JsonObject& cmd) {
    unsigned long duration = cmd["duration"] | (unsigned long)3000;  // Default 3s if not specified
    Serial.printf("Pump command: duration=%lu ms\n", duration);
    hardware.pump.turnOn(duration);
    sendAck("pompa_nyala");
}

void SerialComm::handleStopCommand() {
    stateMachine.emergencyStop();
    sendAck("stop");
    
    // Send "stopped" status so Raspberry Pi immediately clears waiting state
    StaticJsonDocument<128> doc;
    doc["status"] = "stopped";
    doc["message"] = "Emergency stop executed";
    doc["timestamp"] = millis();
    serializeJson(doc, RPI_SERIAL);
    RPI_SERIAL.println();
    serializeJson(doc, DEBUG_SERIAL);
    DEBUG_SERIAL.println();
}

void SerialComm::handleStatusCommand() {
    sendStatus();
}

// ============================================
// RESPONSE SENDERS
// ============================================

void SerialComm::sendAck(const char* command) {
    StaticJsonDocument<128> doc;
    doc["ack"] = command;
    doc["timestamp"] = millis();
    
    // Send to Raspberry Pi (Serial2)
    serializeJson(doc, RPI_SERIAL);
    RPI_SERIAL.println();
    
    // Send to USB (Serial0) - untuk testing dari Windows
    serializeJson(doc, DEBUG_SERIAL);
    DEBUG_SERIAL.println();
}

void SerialComm::sendStatus() {
    StaticJsonDocument<512> doc;
    
    // Status
    State state = stateMachine.getCurrentState();
    if (state == IDLE || state == DONE) {
        doc["status"] = "idle";
    } else if (state == ERROR_STATE) {
        doc["status"] = "error";
    } else {
        // Send "cleaning" status for compatibility with Raspberry Pi
        doc["status"] = "cleaning";
    }
    
    // State name
    doc["state"] = stateMachine.getStateName();
    
    // Progress
    doc["progress"] = stateMachine.getProgress();
    
    // Motor status
    doc["wiper_rpm"] = hardware.wiperEncoder.getRPM();
    doc["wiper_target"] = hardware.wiperMotor.getTargetRPM();
    doc["brush_rpm"] = 0; // Brush doesn't have encoder
    doc["brush_target"] = hardware.brushMotor.getTargetRPM();
    
    // Pump status
    doc["pump"] = hardware.pump.getState();
    
    // Limit switches
    doc["ls1"] = hardware.limitSwitch.isLS1Active();
    doc["ls2"] = hardware.limitSwitch.isLS2Active();
    
    // Position (encoder pulses)
    doc["position"] = hardware.wiperEncoder.getPulseCount();
    
    // Uptime
    doc["uptime"] = millis();
    
    // Cleaning pass info
    doc["current_pass"] = stateMachine.getCurrentPass();
    doc["total_passes"] = stateMachine.getTotalPasses();
    doc["cleaning_level"] = stateMachine.getCleaningLevel();
    
    // Error info (if in error state)
    if (state == ERROR_STATE) {
        doc["error"] = stateMachine.getErrorCode();
        doc["message"] = stateMachine.getErrorMessage();
    }
    
    // Send to Raspberry Pi (Serial2)
    serializeJson(doc, RPI_SERIAL);
    RPI_SERIAL.println();
    
    // Send to USB (Serial0) - untuk testing dari Windows
    serializeJson(doc, DEBUG_SERIAL);
    DEBUG_SERIAL.println();
}

void SerialComm::sendCompletion(unsigned long duration) {
    StaticJsonDocument<256> doc;
    doc["status"] = "done";
    doc["duration"] = duration;
    doc["distance"] = hardware.wiperEncoder.getPulseCount();
    
    // Send to Raspberry Pi (Serial2)
    serializeJson(doc, RPI_SERIAL);
    RPI_SERIAL.println();
    
    // Send to USB (Serial0) - untuk testing dari Windows
    serializeJson(doc, DEBUG_SERIAL);
    DEBUG_SERIAL.println();
}

void SerialComm::sendError(int code, const char* message) {
    StaticJsonDocument<256> doc;
    doc["error"] = code;
    doc["message"] = message;
    doc["state"] = stateMachine.getStateName();
    doc["timestamp"] = millis();
    
    // Send to Raspberry Pi (Serial2)
    serializeJson(doc, RPI_SERIAL);
    RPI_SERIAL.println();
    
    // Send to USB (Serial0) - untuk testing dari Windows
    serializeJson(doc, DEBUG_SERIAL);
    DEBUG_SERIAL.println();
}

// ============================================
// PERIODIC STATUS UPDATES
// ============================================

void SerialComm::sendPeriodicStatus() {
    State state = stateMachine.getCurrentState();
    
    // Send status every second during cleaning
    if (state != IDLE && state != DONE && state != ERROR_STATE) {
        if (millis() - lastStatusTime >= STATUS_UPDATE_INTERVAL) {
            sendStatus();
            lastStatusTime = millis();
        }
    }
    
    // Send heartbeat every 5 seconds when idle
    if (state == IDLE) {
        if (millis() - lastHeartbeatTime >= HEARTBEAT_INTERVAL) {
            // Just blink LED, don't spam serial
            digitalWrite(LED_STATUS, !digitalRead(LED_STATUS));
            lastHeartbeatTime = millis();
        }
    }
}

void SerialComm::sendStatusOnStateChange() {
    // Send status immediately when state changes (for real-time dashboard updates)
    sendStatus();
    lastStatusTime = millis();
}
