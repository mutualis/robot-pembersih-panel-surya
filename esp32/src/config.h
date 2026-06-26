/**
 * Configuration File - Konfigurasi Sistem
 * 
 * File ini berisi semua konfigurasi pin GPIO, parameter motor,
 * parameter PID, dan konstanta yang digunakan oleh sistem.
 * 
 * Hardware:
 * - ESP32 DevKit V1
 * - Motor Driver L298N
 * - DC Motor 12V + Encoder (Wiper)
 * - DC Motor 12V tanpa Encoder (Brush)
 * - Relay SPDT SONGLE SRD-5VDC-SL-C (Pump)
 * - Limit Switch x2 (dengan pull-up 10kΩ)
 * - Water Pump DC 12V (Rainolex 3A)
 * 
 * Author: Muhammad Ridho Assidiqi
 * Institution: Universitas Gadjah Mada
 */

#ifndef CONFIG_H
#define CONFIG_H

// ============================================
// PIN DEFINITIONS
// ============================================

// Wiper Motor (Motor DC dengan encoder) - L298N Driver
#define WIPER_ENA           14    // L298N ENA (PWM/Enable pin) — GPIO 14
#define WIPER_IN1           27    // L298N IN1 (Direction control 1)
#define WIPER_IN2           26    // L298N IN2 (Direction control 2)
#define WIPER_ENCODER_A     21    // Encoder Phase A (pin 3 dari motor)
#define WIPER_ENCODER_B     22    // Encoder Phase B (pin 4 dari motor)
// Encoder power: Pin 5 (Encoder+) -> 3.3V (JANGAN 5V, bisa merusak GPIO ESP32!)
// Encoder ground: Pin 2 (Encoder-) -> GND

// Brush Motor (Motor DC rotating brush) - L298N Driver
// L298N Connections:
// ENB -> PWM pin (speed control)
// IN3 -> Direction pin 1
// IN4 -> Direction pin 2
// Motor connections: Motor+ dan Motor- ke OUT3 dan OUT4
#define BRUSH_ENB           32    // L298N ENB (PWM/Enable pin)
#define BRUSH_IN3           25    // L298N IN3 (Direction control 1)
#define BRUSH_IN4           33    // L298N IN4 (Direction control 2)

// Water Pump (Relay control - Universal AC/DC)
// Circuit: 2N2222 transistor → Relay SPDT (SONGLE SRD-5VDC-SL-C)
// GPIO 12 → R6 (1kΩ) → 2N2222 Base → Relay Coil
// Relay NO → Fuse F1 (5A) → 12V → Pump
// Flyback diode D3 (1N4007) parallel relay coil
// Flyback diode D4 (1N4007) parallel pump motor
// Lihat REFERENCE.md untuk circuit diagram lengkap
#define PUMP_RELAY          13    // Relay control pin (via transistor 2N2222) — GPIO 13

// Limit Switches
// CATATAN: Pull-up untuk limit switch sudah disediakan oleh rangkaian PCB
// (resistor pull-up eksternal 10kΩ + kapasitor debounce 100nF per channel).
// Karena itu pin diinisialisasi sebagai INPUT biasa (bukan INPUT_PULLUP)
// di hardware.cpp — pull-up internal ESP32 TIDAK dipakai.
//
// Wiring limit switch (pull-up eksternal di PCB):
// - Switch normally open (NO)
// - Satu sisi switch ke GPIO (dengan pull-up 10kΩ ke 3.3V + 100nF ke GND)
// - Sisi lain switch ke GND
// - Saat tidak pressed: pull-up eksternal menahan GPIO HIGH
// - Saat switch pressed: GPIO ditarik ke GND = LOW (active LOW)
//
// Pembacaan: polling via digitalRead() + debounce software 50 ms
// (lihat LimitSwitch::update() di hardware.cpp). Bukan interrupt.
//
#define LIMIT_SWITCH_1      18    // Top position (pull-up eksternal di PCB)
#define LIMIT_SWITCH_2      19    // Bottom position (pull-up eksternal di PCB)

// Status LED
#define LED_STATUS          2     // Built-in LED

// ============================================
// PWM CONFIGURATION
// ============================================

#define PWM_FREQUENCY       20000  // 20 kHz (di atas ambang dengar -> motor tidak berdengung)
#define PWM_RESOLUTION      8     // 8-bit (0-255)
#define PWM_CHANNEL_WIPER   0     // PWM channel for wiper
#define PWM_CHANNEL_BRUSH   1     // PWM channel for brush

// ============================================
// MOTOR PARAMETERS
// ============================================

// Wiper Motor (dengan encoder, closed-loop PID control)
#define WIPER_MAX_RPM       50.0  // Maximum RPM (karakterisasi: PWM 255 = ~50 RPM)
#define WIPER_MIN_RPM       15.0  // Minimum RPM (di atas dead zone gerak motor)
#define WIPER_DEFAULT_RPM   45.0  // Default cleaning speed

// Brush Motor (tanpa encoder, open-loop PWM control)
// Spec motor: 170 RPM @ 12V; kecepatan MAKSIMUM TERUKUR ~152 RPM @ PWM 255
// (lihat Laporan PA Bab 4, tab:hasil_brush). Nilai max memakai hasil ukur nyata.
#define BRUSH_MAX_RPM       152.0 // Maximum RPM (terukur @ PWM 255, bukan spec 170)
#define BRUSH_MIN_RPM       50.0  // Minimum RPM (30% PWM)
#define BRUSH_DEFAULT_RPM   150.0 // Default: mendekati kecepatan maksimum terukur

// ============================================
// ENCODER PARAMETERS
// ============================================

#define ENCODER_PPR         11    // Pulses Per Revolution (encoder spec)
#define RPM_UPDATE_INTERVAL 100   // Update RPM every 100ms

// GEARBOX RATIO
// Rasio gearbox: output_rpm = motor_rpm / GEAR_RATIO
// Motor type: GB37 series with 90:1 gearbox
// 
// Spesifikasi motor:
// - Model: GB37Y3530-12V-90EN (atau equivalent)
// - Voltage: 12V DC
// - Gear Ratio: 90:1 (standard)
// - Output Speed: ~60 RPM @ 12V
// - Motor Speed: ~5400 RPM @ 12V (before gearbox)
// - Encoder: Hall Effect, 11 PPR on motor shaft
// - Output Counts: 990 counts/rev (11 × 90)
// 
// CARA KALIBRASI:
// 1. Jalankan motor dengan PWM 255 (full speed)
// 2. Ukur RPM encoder (sebelum gearbox) via Serial Monitor
// 3. Ukur RPM output (setelah gearbox) dengan tachometer
// 4. Hitung: GEAR_RATIO = RPM_encoder / RPM_output
// 
// Contoh pengukuran:
//   Encoder reading: 5346 RPM @ PWM 255
//   Tachometer reading: 60 RPM @ PWM 255
//   GEAR_RATIO = 5346 / 60 = 89.1 (close to 90:1 standard)
//
#define WIPER_GEAR_RATIO    100.0 // Hasil kalibrasi tachometer (PWM 255 -> 51 RPM). Lihat Bab 4 tab:validasi_encoder
#define BRUSH_GEAR_RATIO    1.0   // Default 1.0 (no gearbox), adjust setelah kalibrasi

// CATATAN KALIBRASI:
// Setelah mengukur dengan tachometer, update nilai di atas
// Misalnya jika hasil kalibrasi WIPER_GEAR_RATIO = 5.0:
// #define WIPER_GEAR_RATIO    5.0
//
// RPM yang ditampilkan akan otomatis terkoreksi:
// RPM_actual = RPM_encoder / GEAR_RATIO

// ============================================
// PID PARAMETERS
// ============================================

// Wiper PID (closed-loop control dengan encoder feedback)
// Hasil penalaan Ziegler-Nichols Ultimate Gain (Ku=0.5, Tu=0.258 s) + validasi
// step response motor wiper (tanpa beban, setpoint 30 RPM). Lihat Laporan PA
// Bab 4 (eq:pid_params_result). Gain ini dipakai bersama kompensasi feedforward
// (lihat WIPER_FF_* di bawah) — tanpa feedforward motor akan tersendat.
#define WIPER_KP            0.3     // Proportional gain (0.6*Ku)
#define WIPER_KI            2.329   // Integral gain (2*Kp/Tu)
#define WIPER_KD            0.0097  // Derivative gain (Kp*Tu/8)

// Deadband galat PID (RPM). Kecil — encoder bersih, integral boleh menutup
// error hingga ~0 tanpa parkir di offset.
#define WIPER_PID_DEADBAND      0.5
// Conditional integration: integral hanya diakumulasi saat |error| <= band ini,
// supaya tidak windup pada fase rise (mis. 0->30 RPM) yang memicu overshoot.
#define WIPER_INTEGRAL_BAND     8.0
// PWM minimum agar motor lepas dari dead zone (hasil karakterisasi: <150 = diam).
#define WIPER_PWM_MIN_DRIVE     150

// ============================================
// FEEDFORWARD WIPER (kunci agar closed-loop semulus open-loop)
// ============================================
// u_ff(rpm) = WIPER_FF_PWM_MIN + WIPER_FF_SLOPE * (rpm - WIPER_FF_RPM_MIN)
// Kalibrasi empiris open-loop motor wiper:
//   PWM 150 -> 20 RPM (titik mulai gerak); PWM 255 -> 50 RPM (maks)
//   slope = (255-150)/(50-20) = 3.5 PWM/RPM
#define WIPER_FF_PWM_MIN        150.0
#define WIPER_FF_RPM_MIN        20.0
#define WIPER_FF_SLOPE          3.5

// Startup kick: dorong PWM sesaat agar motor lepas dari diam saat setpoint > 0
#define WIPER_STARTUP_KICK_PWM   160
#define WIPER_STARTUP_KICK_TICKS 2
// Pembacaan RPM di atas ini dianggap noise (glitch encoder) dan diabaikan
#define WIPER_MAX_ALLOWED_RPM    100.0
// PCNT hardware glitch filter (siklus APB 80MHz, ~12,5us). Buang spike EMI motor.
#define PCNT_GLITCH_FILTER       1000

// Brush PID (TIDAK DIGUNAKAN - open-loop control)
// Brush motor tidak memiliki encoder, menggunakan PWM langsung
// PWM 255 (100%) = ~152 RPM @ 12V (terukur, bukan spec 170)
// PWM dihitung: PWM = (target_rpm / 152.0) * 255
#define BRUSH_KP            0.0   // Not used (open-loop)
#define BRUSH_KI            0.0   // Not used (open-loop)
#define BRUSH_KD            0.0   // Not used (open-loop)

// ============================================
// CLEANING CYCLE PARAMETERS
// ============================================

#define POSITIONING_SPEED       45.0  // RPM untuk homing/positioning (cepat, bukan cleaning)
#define CLEANING_DWELL_MS       1500  // jeda di ujung lintasan sebelum balik arah (kurangi sentakan + air meresap)
// Timeout homing/positioning. Full travel (LS1<->LS2) di POSITIONING_SPEED 45 RPM
// memakan ~23 s (lihat Bab 4, ringan 1 pass). 15 s TERLALU PENDEK: bila carriage
// mulai homing dari posisi jauh, timeout memicu ERROR_STATE (motor mati) sebelum
// mencapai LS atas. Set 40 s (margin ~75%). Stall detection (2 s) tetap menangani
// macet mekanis dengan cepat, jadi timeout panjang aman sebagai backstop.
#define POSITIONING_TIMEOUT     40000 // 40 detik (cukup untuk full travel + margin)

// ============================================
// ADAPTIVE CLEANING STRATEGY
// Pola pembersihan berbeda berdasarkan tingkat kotoran (score dari YOLO)
// ============================================
// Formula Weighted Score (Hybrid): S = 100 × w × (0.7 + 0.3 × conf)
// Dimana:
//   w = bobot kategori (bersih: 0, kotor_ringan: 1, kotor_sedang: 2, kotor_berat: 3)
//   conf = confidence score (0.7 - 1.0)
// 
// Rentang Score per Kategori:
//   Bersih:        0
//   Kotor Ringan:  70 - 169   (rentang 100 unit)
//   Kotor Sedang:  170 - 269  (rentang 100 unit)
//   Kotor Berat:   >= 270     (rentang 30+ unit)
// ============================================

// Threshold untuk menentukan level pembersihan
#define CLEAN_SCORE_THRESHOLD   70.0   // Score >= 70 = Perlu pembersihan
#define CLEAN_SCORE_LIGHT       170.0  // Score < 170 = Kotor Ringan (wiper saja)
#define CLEAN_SCORE_MEDIUM      270.0  // Score < 270 = Kotor Sedang (wiper + brush)
                                       // Score >= 270 = Kotor Berat (intensif, 2x pass)

// Semprot KONTINU sepanjang pass turun (LS1->LS2): pompa nyala saat pass turun,
// dimatikan oleh FSM saat pass naik (CLEANING_BACKWARD). SPRAY_CONTINUOUS_MS hanya
// batas aman pompa (lebih lama dari 1 pass turun ~31 s); pompa normalnya dimatikan
// FSM lebih dulu. 0 = level tanpa semprot (Ringan, sikat kering).
#define SPRAY_CONTINUOUS_MS     45000

// Level 1: Kotor Ringan (score 70-169) - Penyikatan kering cepat (TANPA air)
#define LIGHT_WIPER_SPEED       45.0   // RPM (cepat) - debu kering lepas, sapuan cepat
#define LIGHT_BRUSH_SPEED       120.0  // RPM - sikat kering mengangkat debu
#define LIGHT_SPRAY_DURATION    0      // 0 = TANPA semprot (debu kering)
#define LIGHT_PASS_COUNT        1      // 1x pass (maju-mundur)

// Level 2: Kotor Sedang (score 170-269) - Semprot (saat turun) + wiper + brush
#define MEDIUM_WIPER_SPEED      40.0   // RPM (sedang) - kontak lebih lama
#define MEDIUM_BRUSH_SPEED      120.0  // RPM (sedang)
#define MEDIUM_SPRAY_DURATION   SPRAY_CONTINUOUS_MS  // semprot kontinu saat pass turun
#define MEDIUM_PASS_COUNT       1      // 1x pass

// Level 3: Kotor Berat (score >= 270) - Semprot (saat turun) + wiper + brush intensif
#define HEAVY_WIPER_SPEED       35.0   // RPM (pelan). Variasi 35/40/45: semua >= 35 RPM
                                       // agar tracking PID tetap stabil di bawah beban
                                       // pompa (di <= 30 RPM kecepatan drop saat pompa nyala)
#define HEAVY_BRUSH_SPEED       150.0  // RPM (mendekati maksimum terukur ~152)
#define HEAVY_SPRAY_DURATION    SPRAY_CONTINUOUS_MS  // semprot kontinu saat pass turun
#define HEAVY_PASS_COUNT        2      // 2x pass (maju-mundur-maju-mundur)

// ============================================
// SAFETY PARAMETERS
// ============================================

#define MOTOR_STALL_THRESHOLD   10.0  // RPM below this = stall (cadangan; deteksi utama berbasis pergerakan posisi)
#define MOTOR_STALL_TIMEOUT     2000  // 2 seconds (reduced from 3s for faster protection)
// Stall berbasis posisi: carriage dianggap BERGERAK bila pulsa encoder berubah
// > nilai ini dalam jendela timeout. Mencegah false-stall saat RPM sesaat drop
// karena sag tegangan (pompa+brush nyala) padahal carriage masih jalan.
#define STALL_MIN_PULSES        50    // ~2 mm (24,1 pulsa/mm) — gerak minimum dianggap tidak macet
#define OVERCURRENT_THRESHOLD   3.0   // Amperes
#define HEARTBEAT_INTERVAL      5000  // 5 seconds

// ============================================
// SERIAL COMMUNICATION
// ============================================

// Serial0 (USB) - untuk debugging dan monitoring via laptop
// Pin: GPIO 1 (TX0), GPIO 3 (RX0) - Built-in USB
#define DEBUG_SERIAL            Serial
#define DEBUG_BAUDRATE          115200

// Serial2 (UART2) - untuk komunikasi dengan Raspberry Pi
// Pin: GPIO 16 (RX2), GPIO 17 (TX2)
#define RPI_SERIAL              Serial2
#define RPI_BAUDRATE            115200
#define RPI_RX_PIN              16    // GPIO16 (RX2) - Connect to Raspberry Pi TX
#define RPI_TX_PIN              17    // GPIO17 (TX2) - Connect to Raspberry Pi RX

#define SERIAL_TIMEOUT          1000  // 1 second
#define STATUS_UPDATE_INTERVAL  100   // Send status every 100ms (10 Hz) for real-time feedback

// ============================================
// ERROR CODES
// ============================================

#define ERROR_LIMIT_SWITCH_1    101
#define ERROR_LIMIT_SWITCH_2    102
#define ERROR_LIMIT_CONFLICT    103
#define ERROR_MOTOR_STALL       201
#define ERROR_OVERCURRENT       202
#define ERROR_MOTOR_OVERHEAT    203
#define ERROR_INVALID_COMMAND   301
#define ERROR_INVALID_PARAM     302
#define ERROR_COMMAND_TIMEOUT   303

#endif // CONFIG_H
