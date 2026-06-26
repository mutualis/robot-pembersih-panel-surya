# Technical Reference - Referensi Teknis

Referensi lengkap untuk konfigurasi hardware, protokol komunikasi, dan spesifikasi motor.

---

## Pin Configuration

### Driver Motor L298N

**Wiper Motor:**
```
ENA  → GPIO 13 (PWM Channel 0)
IN1  → GPIO 27
IN2  → GPIO 26
```

**Brush Motor:**
```
ENB  → GPIO 32 (PWM Channel 1)
IN3  → GPIO 25
IN4  → GPIO 33
```

### Encoder Motor Wiper

```
Phase A → GPIO 21
Phase B → GPIO 22
Power   → 5V
GND     → GND
```

### Limit Switches

**GPIO:**
```
LS1 (Top)    → GPIO 18 (dengan internal pull-up)
LS2 (Bottom) → GPIO 19 (dengan internal pull-up)
```

**Wiring (Normally Open):**
```
Switch LS1:
  Terminal 1 → GPIO 18
  Terminal 2 → GND

Switch LS2:
  Terminal 1 → GPIO 19
  Terminal 2 → GND
```

**Logic:**
- HIGH (3.3V) = Switch tidak pressed (pull-up aktif)
- LOW (0V) = Switch pressed (terhubung ke GND)

**PENTING untuk Kabel Panjang (1 meter):**
- Internal pull-up ESP32 sudah cukup untuk kabel 1-2 meter
- Jika masih ada noise, tambahkan capacitor 100nF di GPIO ke GND
- Atau gunakan pull-up external 10kΩ untuk lebih stabil

**Alternatif: Pull-Down External (jika tidak mau ganti GPIO):**
```
GPIO 34/35 ──┬── Switch ── VCC (3.3V)
             └── 10kΩ ── GND

Logic: LOW = tidak pressed, HIGH = pressed
```

### Water Pump (Relay Control - Universal AC/DC)

**Circuit: 2N2222 Transistor + Relay SPDT (Finder 36.11)**

```
Control Side:
GPIO 12 ── R6 (1kΩ) ── Q2 (2N2222) Base
                       Q2 Emitter ── GND
                       Q2 Collector ── Relay Coil (Pin A2)

5V ──┬── Relay Coil (Pin A1)
     ├── R5 (1kΩ) ── D1 (LED) ── GND (indicator)
     └── D3 (1N4007) Cathode ── Relay Coil (Pin A1)
         D3 Anode ── Q2 Collector (flyback protection)

Power Side:
12V ── F1 (5A Fuse) ── Relay COM (Pin 11)
                       Relay NO (Pin 14) ── POWER_PUMP_OUT ── Pump+
                       
Pump- ── GND

Flyback diode pump:
POWER_PUMP_OUT ── D4 (1N4007) Cathode
12V ── D4 Anode
```

**Komponen:**
- Relay: SONGLE SRD-5VDC-SL-C SPDT 5V (10A contact)
- Q2: 2N2222 NPN Transistor (TO-92)
- D3: 1N4007 (flyback diode relay coil)
- D4: 1N4007 (flyback diode pump motor)
- F1: Fuse 5A slow blow (5×20mm)
- R5: 1kΩ (LED current limiting)
- R6: 1kΩ (transistor base resistor)
- D1: LED 5mm (indicator pump ON)

**KiCad Footprints:**
- Relay: `Relay_THT:Relay_SPDT_Finder_40.52`
- 2N2222: `Package_TO_SOT_THT:TO-92_Inline`
- 1N4007: `Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal`
- Fuse holder: `Fuse:Fuseholder_Cylinder-5x20mm_Stelvio-Kontek_PTF78_Horizontal_Open`
- R5, R6: `Resistor_SMD:R_1206_3216Metric`
- LED: `LED_THT:LED_D5.0mm`

**Pump Spec (Rainolex DC 12V):**
- Voltage: DC 12V
- Current: 2.5-3A
- Flow: 4 LPM
- Pressure: 90 PSI
- Fitur: Auto Cut-Off, Thermal Protected

### Serial Communication

**Serial0 (USB):**
```
TX → GPIO 1
RX → GPIO 3
Baud Rate: 115200
Fungsi: Debugging & Monitoring
```

**Serial2 (UART2):**
```
TX → GPIO 17 (TX)
RX → GPIO 16 (RX)
Baud Rate: 115200
Fungsi: Komunikasi dengan Raspberry Pi
```

**PENTING:** Koneksi serial harus silang (TX → RX, RX → TX)

---

## Motor Specifications

### Wiper Motor

```
Type:       DC Motor 12V dengan encoder built-in
Speed:      60 RPM (maksimal)
Control:    Closed-loop PID
Encoder:    2 phase (A, B)
Gear Ratio: Perlu kalibrasi (default: 1.0)
```

### Brush Motor

```
Type:       DC Motor 12V tanpa encoder
Speed:      170 RPM (maksimal)
Control:    Open-loop PWM
Gear Ratio: N/A
```

### Speed Ratio

```
Brush / Wiper = 170 / 60 = 2.83:1

Rasio ini optimal untuk:
- Brush berputar lebih cepat untuk scrubbing
- Wiper bergerak lebih lambat untuk wiping
```

---

## Communication Protocol

### Command: Raspberry Pi → ESP32

**Format:** Plain text, diakhiri newline (`\n`)

**Commands:**
```
START_CLEANING    → Mulai cleaning cycle
STOP_CLEANING     → Stop cleaning cycle
GET_STATUS        → Request status update
```

**Contoh:**
```
START_CLEANING\n
```

### Response: ESP32 → Raspberry Pi

**Format:** JSON

**Status Update:**
```json
{
  "state": "CLEANING",
  "wiper_rpm": 58.5,
  "brush_rpm": 170.0,
  "timestamp": 12345
}
```

**Fields:**
- `state`: State saat ini (IDLE, CLEANING, DRYING, DONE)
- `wiper_rpm`: Kecepatan wiper aktual (RPM)
- `brush_rpm`: Kecepatan brush (RPM, estimasi)
- `timestamp`: Timestamp dalam milliseconds

**Periodic Update:**
- Dikirim setiap 1 detik saat state != IDLE
- Dikirim via Serial2 (UART2)

---

## Adaptive Cleaning Strategy

Pola pembersihan berbeda berdasarkan tingkat kotoran yang terdeteksi YOLO.

### Cleaning Levels

| Level | Score | Wiper | Brush | Semprot | Pass |
|-------|-------|-------|-------|---------|------|
| **Ringan** | 70-169 | 45 RPM | 120 RPM | -- | 1x |
| **Sedang** | 170-269 | 40 RPM | 120 RPM | Saat turun | 1x |
| **Berat** | >= 270 | 35 RPM | 150 RPM | Saat turun | 2x |

### Alur Pembersihan

**Kotor Ringan (debu tipis):**
```
Tanpa semprot (sikat kering) → Brush ON (120 RPM) + Wiper turun (45 RPM) → Wiper naik → Selesai
```

**Kotor Sedang (debu tebal, noda):**
```
Brush ON (120 RPM) + Wiper turun (40 RPM) + Semprot kontinu saat turun → Wiper naik (pompa & brush OFF) → Selesai
```

**Kotor Berat (lumut, kerak):**
```
Brush ON (150 RPM) + Wiper turun (35 RPM) + Semprot kontinu saat turun → naik → turun → naik → Selesai
```

### Score Calculation

```
Score = 100 × weight × confidence

Weight per kategori:
  bersih: 0
  kotor_ringan: 1.0
  kotor_sedang: 2.0
  kotor_berat: 3.0

Contoh: kotor_sedang dengan confidence 0.91 → Score = 100 × 2.0 × 0.91 = 182
```

---

## State Machine

### States

```
IDLE → PRE_CHECK → MOVING_TO_START → SPRAYING_WATER
     → CLEANING_FORWARD → CLEANING_BACKWARD → STOPPING → DONE → IDLE
     
Multi-pass (kotor berat):
     → CLEANING_FORWARD → CLEANING_BACKWARD → CLEANING_FORWARD → CLEANING_BACKWARD → STOPPING
```

**IDLE:**
- Menunggu command dari Raspberry Pi
- Semua motor OFF

**PRE_CHECK:**
- Cek limit switch dan motor status

**MOVING_TO_START:**
- Wiper bergerak ke posisi awal atas (LS1)
- Jika sudah di LS1, langsung mulai cleaning

**SPRAYING_WATER:**
- Pompa ON (durasi sesuai level)

**CLEANING_FORWARD:**
- Wiper turun (LS1 atas → LS2 bawah)
- Brush ON (jika level sedang/berat)

**CLEANING_BACKWARD:**
- Wiper naik (LS2 bawah → LS1 atas)
- Jika multi-pass: kembali ke CLEANING_FORWARD

**STOPPING:**
- Stop semua motor secara bertahap

**DONE:**
- Kirim status selesai ke Raspberry Pi
- Kembali ke IDLE

---

## PID Parameters

### Default Values

```cpp
// Wiper Motor PID
#define WIPER_KP    1.0
#define WIPER_KI    0.5
#define WIPER_KD    0.1

// Gear Ratio
#define WIPER_GEAR_RATIO    1.0
```

**PENTING:** Nilai default ini hanya placeholder. Lakukan kalibrasi dan tuning untuk nilai optimal.

### Tuning Formula (Ziegler-Nichols)

```
Kp = 0.6 × Ku
Ki = 2 × Kp / Tu
Kd = Kp × Tu / 8

Ku = Ultimate Gain
Tu = Ultimate Period
```

---

## Build Configuration

### Development Build

**File:** `unified_main.cpp`  
**Command:** `pio run --target upload`

**Features:**
- Menu selection (Mode 1/2/3)
- Calibration mode
- Tuning mode
- Binary ~500KB

### Production Build

**File:** `main.cpp`  
**Command:** `pio run -e production --target upload`

**Features:**
- Langsung start tanpa menu
- Hanya Normal Mode
- Binary ~350KB
- Optimized (-Os)

---

## Hardware Wiring

### Motor Wiper (6 Pin)

```
Motor-    → L298N OUT1
Motor+    → L298N OUT2
Encoder-  → GND
Encoder A → GPIO 21
Encoder B → GPIO 22
Encoder+  → 5V
```

### Motor Brush (2 Pin)

```
Motor-    → L298N OUT3
Motor+    → L298N OUT4
```

### L298N Power

```
12V  → Power supply 12V
GND  → Power supply GND & ESP32 GND
5V   → Tidak digunakan (ESP32 pakai USB)
```

**PENTING:** Ground harus sama antara ESP32, L298N, dan power supply!

---

## Troubleshooting

### Motor Tidak Berputar
```
✓ Cek koneksi L298N
✓ Cek power supply 12V
✓ Cek pin di config.h
✓ Cek ground sama
```

### Encoder Tidak Terbaca
```
✓ Cek koneksi Phase A, B (GPIO 21, 22)
✓ Cek power encoder (5V)
✓ Cek ground encoder
```

### Serial Error
```
✓ Cek baud rate (115200)
✓ Cek koneksi Serial2 (GPIO 16, 17)
✓ Cek kabel TX/RX silang
✓ Cek ground sama
```

### PID Tidak Stabil
```
✓ Lakukan tuning ulang
✓ Cek gear ratio sudah benar
✓ Cek beban motor
✓ Cek power supply cukup
```

---

## Command Reference

### PlatformIO

```bash
# Development build
pio run --target upload

# Production build
pio run -e production --target upload

# Monitor
pio device monitor

# Clean
pio run --target clean
```

### Serial Monitor

```bash
# Buka monitor
pio device monitor

# Keluar monitor
Ctrl + C
```

---

**Muhammad Ridho Assidiqi**  
Tugas Akhir - Teknik Elektro UGM  
2025
