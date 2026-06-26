/**
 * State Machine Module
 * 
 * Mengatur state dan flow siklus pembersihan panel surya.
 * 
 * State Flow:
 * IDLE → PRE_CHECK → MOVING_TO_START → SPRAYING_WATER
 *      → CLEANING_FORWARD → CLEANING_BACKWARD → STOPPING → DONE → IDLE
 * 
 * Catatan posisi: MOVING_TO_START homing ke LS1 (atas). CLEANING_FORWARD
 * bergerak LS1 atas → LS2 bawah. CLEANING_BACKWARD kembali LS2 → LS1.
 * 
 * Error handling: Motor stall, limit switch conflict, timeout
 * Emergency stop: Dari state manapun kembali ke IDLE
 * 
 * Author: Muhammad Ridho Assidiqi
 * Institution: Universitas Gadjah Mada
 */

#ifndef STATE_MACHINE_H
#define STATE_MACHINE_H

#include <Arduino.h>
#include "config.h"

// ============================================
// STATE DEFINITIONS (sesuai SYSTEM_WORKFLOW.md)
// ============================================

enum State {
    IDLE,                // Waiting for command
    PRE_CHECK,           // Pre-cleaning checks
    MOVING_TO_START,     // Move wiper to start position (LS1 atas)
    SPRAYING_WATER,      // Turn on water pump
    CLEANING_FORWARD,    // Wiper + brush moving forward (LS1 atas → LS2 bawah)
    CLEANING_BACKWARD,   // Wiper moving backward (LS2 bawah → LS1 atas)
    STOPPING,            // Stopping all motors
    DONE,                // Cleaning complete
    ERROR_STATE          // Error state
};

// ============================================
// CLEANING PARAMETERS
// ============================================

// Cleaning level berdasarkan score dari YOLO
enum CleaningLevel {
    CLEAN_LIGHT,    // Kotor ringan: semprot + wiper saja
    CLEAN_MEDIUM,   // Kotor sedang: semprot + wiper + brush
    CLEAN_HEAVY     // Kotor berat: semprot + wiper + brush intensif (2x pass)
};

struct CleaningParams {
    float wiperSpeed;       // RPM
    float brushSpeed;       // RPM (0 = brush mati)
    unsigned long duration; // Water spray duration (ms)
    int zone;               // Zone ID
    float score;            // Dirt score dari YOLO
    CleaningLevel level;    // Cleaning level
    int totalPasses;        // Jumlah pass (1 atau 2)
    int currentPass;        // Pass saat ini
    
    CleaningParams() : wiperSpeed(MEDIUM_WIPER_SPEED), 
                       brushSpeed(MEDIUM_BRUSH_SPEED),
                       duration(MEDIUM_SPRAY_DURATION),
                       zone(0), score(0),
                       level(CLEAN_MEDIUM),
                       totalPasses(1), currentPass(1) {}
};

// ============================================
// STATE MACHINE CLASS
// ============================================

class StateMachine {
private:
    State currentState;
    State previousState;
    CleaningParams params;
    
    // Timing variables
    unsigned long stateStartTime;
    unsigned long cleaningStartTime;
    unsigned long lastStatusTime;
    unsigned long lastErrorPrintTime;  // For error message throttling
    
    // Progress tracking
    int progress;
    
    // Error tracking
    int errorCode;
    String errorMessage;
    unsigned long stallStartTime;
    long stallLastPos;          // posisi encoder terakhir untuk deteksi stall berbasis gerak
    unsigned long dwellStart;   // timer jeda di ujung lintasan (0 = tidak sedang jeda)
    
    // State handlers
    void handleIdle();
    void handlePreCheck();
    void handleMovingToStart();
    void handleSprayingWater();
    void handleCleaningForward();
    void handleCleaningBackward();
    void handleStopping();
    void handleDone();
    void handleError();
    
    // Helper functions
    void changeState(State newState);
    void checkSafety();
    bool isMotorStalled();
    void calculateProgress();
    
public:
    StateMachine();
    void init();
    void update();
    
    // Command handlers
    void startCleaningCycle(float wiperSpeed, float brushSpeed, unsigned long duration);
    void startCleaningCycleAdaptive(float score);
    void emergencyStop();
    
    // Getters
    State getCurrentState() { return currentState; }
    String getStateName();
    int getProgress() { return progress; }
    int getErrorCode() { return errorCode; }
    String getErrorMessage() { return errorMessage; }
    unsigned long getUptime() { return millis(); }
    int getCurrentPass() { return params.currentPass; }
    int getTotalPasses() { return params.totalPasses; }
    String getCleaningLevel();
};

#endif // STATE_MACHINE_H
