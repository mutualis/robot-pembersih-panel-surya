/**
 * Serial Communication Module
 * 
 * Modul komunikasi serial antara ESP32 dan Raspberry Pi
 * menggunakan protokol JSON melalui UART2 (GPIO 16/17).
 * 
 * Mendukung perintah dalam Bahasa Indonesia dan Inggris:
 * - siklus_pembersihan / clean_cycle
 * - mulai_wiper / start_wiper
 * - mulai_sikat / start_brush
 * - pompa_nyala / pump_on
 * - stop (emergency stop)
 * - status (request status)
 * 
 * Author: Muhammad Ridho Assidiqi
 * Institution: Universitas Gadjah Mada
 */

#ifndef SERIAL_COMM_H
#define SERIAL_COMM_H

#include <Arduino.h>
#include <ArduinoJson.h>
#include "config.h"

class SerialComm {
private:
    unsigned long lastStatusTime;
    unsigned long lastHeartbeatTime;
    
    // JSON document
    StaticJsonDocument<512> jsonDoc;
    
    // Command handlers
    void processCommand(String& jsonString);
    void handleCleaningCycleCommand(JsonObject& cmd);
    void handleWiperCommand(JsonObject& cmd);
    void handleBrushCommand(JsonObject& cmd);
    void handlePumpCommand(JsonObject& cmd);
    void handleStopCommand();
    void handleStatusCommand();
    
    // Response senders
    void sendAck(const char* command);
    void sendError(int code, const char* message);
    
public:
    SerialComm();
    void init();
    void handleIncoming();
    void sendStatus();
    void sendStatusOnStateChange();  // Send status immediately on state change
    void sendCompletion(unsigned long duration);
    void sendPeriodicStatus();
};

#endif // SERIAL_COMM_H
