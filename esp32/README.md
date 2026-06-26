# ESP32 - Solar Panel Cleaning Robot

Program ESP32 untuk mengontrol robot pembersih panel surya.

**Muhammad Ridho Assidiqi** — 22/505759/SV/21913  
Tugas Akhir Sarjana Terapan — Universitas Gadjah Mada  
Departemen Teknik Elektro dan Informatika, Sekolah Vokasi  
Program Studi: Teknologi Rekayasa Instrumentasi dan Kontrol  
2026

---

## Quick Start

```bash
cd esp32
pio run --target upload      # build & flash firmware produksi
pio device monitor           # monitor serial (115200)
```

Firmware langsung masuk **Normal Mode** tanpa menu — siap dikendalikan Raspberry Pi via UART2 (GPIO 16/17) JSON 115200. Tidak ada mode dev/kalibrasi/tuning di firmware; semuanya sudah final di `config.h`.

---

## Dokumentasi

### 📖 Panduan Utama

1. **README.md** - File ini (overview & quick start)
2. **REFERENCE.md** - Referensi teknis (pinout, protocol, specs)

### 📁 File Program

```
src/
├── main.cpp                  → Entry point produksi (Normal Mode)
├── config.h                  → Konfigurasi pin & parameter (sumber kebenaran)
├── hardware.h/cpp            → Motor, encoder, sensor, PID
├── state_machine.h/cpp       → State machine cleaning (9 states)
└── serial_comm.h/cpp         → Komunikasi serial JSON dengan Raspberry Pi
```

---

## Workflow

Firmware sudah final dan production-ready. Parameter PID (Kp/Ki/Kd) dan gear
ratio sudah ditetapkan di `config.h` berdasarkan kalibrasi & tuning yang telah
dilakukan (lihat Laporan PA Bab 3-4). Untuk deploy:

```bash
cd esp32
pio run --target upload
```

Firmware langsung jalan dan menunggu perintah dari Raspberry Pi. Uji per-komponen
(motor, pompa, encoder, limit switch) dilakukan dari halaman **Testing** di web
Raspberry Pi, bukan dari menu firmware.

---

## Hardware

### Driver Motor
- L298N Dual H-Bridge

### Motor
- Wiper: DC 12V dengan encoder 11 PPR (15-60 RPM, closed-loop PID)
- Brush: DC 12V tanpa encoder (50-170 RPM, open-loop PWM)

### Pin Configuration (Sesuai PCB Schematic)

| Fungsi | GPIO | Keterangan |
|--------|------|------------|
| **Wiper Motor** | | |
| WIPER_ENA | **14** | L298N ENA (PWM/Enable) |
| WIPER_IN1 | **27** | L298N IN1 (Direction) |
| WIPER_IN2 | **26** | L298N IN2 (Direction) |
| **Brush Motor** | | |
| BRUSH_ENB | **32** | L298N ENB (PWM/Enable) |
| BRUSH_IN3 | **25** | L298N IN3 (Direction) |
| BRUSH_IN4 | **33** | L298N IN4 (Direction) |
| **Encoder** | | |
| ENCODER_A | **21** | Encoder Phase A |
| ENCODER_B | **22** | Encoder Phase B |
| **Limit Switches** | | |
| LS1 | **18** | Top position (pull-up eksternal di PCB) |
| LS2 | **19** | Bottom position (pull-up eksternal di PCB) |
| **Pump** | | |
| PUMP_RELAY | **13** | Relay control (via 2N2222 transistor) |
| **Serial2 (UART2)** | | |
| TX2 | **17** | → Raspberry Pi RX |
| RX2 | **16** | ← Raspberry Pi TX |
| **Status** | | |
| LED_STATUS | **2** | Built-in LED |

### Encoder Notes
- 11 PPR (Pulses Per Revolution)
- Interrupt on CHANGE (2× resolution = 22 edges/rev)
- Power: 3.3V (JANGAN 5V — bisa merusak GPIO ESP32!)
- Update rate: 100ms (10 Hz)

### Limit Switch Wiring
- Normally Open (NO) configuration
- Pull-up eksternal di PCB (10kΩ) + kapasitor 100nF untuk debounce
- HIGH = not pressed, LOW = pressed (active low)
- Pin diinisialisasi sebagai INPUT biasa; pembacaan via polling + debounce software 50ms

---

## State Machine (9 States)

```
                    ┌──────────────────────────────────────────────┐
                    │                                              │
                    ▼                                              │
┌──────┐    ┌───────────┐    ┌────────────────┐    ┌──────────────────┐
│ IDLE │───▶│ PRE_CHECK │───▶│ MOVING_TO_START│───▶│ SPRAYING_WATER   │
└──────┘    └───────────┘    └────────────────┘    └──────────────────┘
   ▲                                                       │
   │                                                       ▼
┌──────┐    ┌──────────┐    ┌──────────────────┐   ┌──────────────────┐
│ DONE │◀───│ STOPPING │◀───│CLEANING_BACKWARD │◀──│ CLEANING_FORWARD │
└──────┘    └──────────┘    └──────────────────┘   └──────────────────┘
                                                           │
              ┌─────────────┐                              │
              │ ERROR_STATE │◀─────── (dari state manapun) ┘
              └─────────────┘
```

### State Descriptions

| State | Deskripsi |
|-------|-----------|
| **IDLE** | Menunggu command dari Raspberry Pi |
| **PRE_CHECK** | Cek limit switch, motor, safety checks |
| **MOVING_TO_START** | Gerakkan wiper ke posisi awal (LS2) |
| **SPRAYING_WATER** | Nyalakan pompa air (durasi sesuai level) |
| **CLEANING_FORWARD** | Wiper + brush maju (LS2 → LS1) |
| **CLEANING_BACKWARD** | Wiper mundur (LS1 → LS2) |
| **STOPPING** | Matikan semua motor |
| **DONE** | Pembersihan selesai, kirim laporan ke RPi |
| **ERROR_STATE** | Error handling (stall, timeout, limit switch conflict) |

### Multi-Pass Logic
- **1 pass** = CLEANING_FORWARD + CLEANING_BACKWARD
- **2 pass** (kotor berat) = ulangi SPRAYING → FORWARD → BACKWARD dua kali
- Setelah semua pass selesai → STOPPING → DONE → IDLE

---

## Communication

### Serial0 (USB)
- Baud: 115200
- Fungsi: Debugging & Monitoring via laptop

### Serial2 (UART2)
- Baud: 115200
- Pin: TX2 (GPIO 17), RX2 (GPIO 16)
- Fungsi: Komunikasi dengan Raspberry Pi
- Raspberry Pi port: `/dev/serial0`
- Windows: auto-detect COM port

### Protocol (JSON)

**Command dari Raspberry Pi → ESP32:**
```json
{"cmd":"siklus_pembersihan","score":182.5,"zone":0}
```

**Status dari ESP32 → Raspberry Pi:**
```json
{
  "status": "cleaning",
  "state": "CLEANING_FORWARD",
  "progress": 45,
  "wiper_rpm": 44.8,
  "wiper_target": 45.0,
  "brush_rpm": 0,
  "brush_target": 120.0,
  "pump": true,
  "ls1": false,
  "ls2": false,
  "position": 1234,
  "uptime": 45000
}
```

**Completion:**
```json
{"status":"done","duration":25000,"distance":4500}
```

**Error:**
```json
{"error":201,"message":"Motor stall detected","state":"CLEANING_FORWARD","timestamp":45000}
```

### Supported Commands
| Command | Deskripsi |
|---------|-----------|
| `siklus_pembersihan` / `clean_cycle` | Start adaptive cleaning cycle |
| `mulai_wiper` / `start_wiper` | Start wiper motor |
| `berhenti_wiper` / `stop_wiper` | Stop wiper motor |
| `mulai_sikat` / `start_brush` | Start brush motor |
| `berhenti_sikat` / `stop_brush` | Stop brush motor |
| `pompa_nyala` / `pump_on` | Turn on water pump |
| `pompa_mati` / `pump_off` | Turn off water pump |
| `stop` | Emergency stop |
| `status` | Request current status |

---

## Adaptive Cleaning Strategy

Berdasarkan weighted score dari YOLO detection:

| Level | Score Range | Spray | Wiper RPM | Brush RPM | Pass |
|-------|------------|-------|-----------|-----------|------|
| **Bersih** | < 70 | — | — | — | — |
| **Ringan** | 70-169 | — | 45 | 120 | 1 |
| **Sedang** | 170-269 | Saat turun | 40 | 120 | 1 |
| **Berat** | ≥ 270 | Saat turun | 35 | 150 | 2 |

### Weighted Score Formula
```
S = 100 × w × (0.7 + 0.3 × confidence)

w = {bersih: 0, kotor_ringan: 1, kotor_sedang: 2, kotor_berat: 3}
```

---

## PID Parameters

| Parameter | Value | Keterangan |
|-----------|-------|------------|
| **Kp** | 2.0 | Proportional gain |
| **Ki** | 0.5 | Integral gain |
| **Kd** | 0.1 | Derivative gain |
| **Deadband** | ±2 RPM | Toleransi error |
| **Anti-windup** | ±50 | Batas integral |
| **Update rate** | 100ms | 10 Hz loop |
| **Wiper Max RPM** | 60 | Batas atas |
| **Wiper Min RPM** | 15 | Batas bawah |

---

## Build Commands

Firmware memakai **satu environment produksi** (`[env:production]`) dengan entry `main.cpp`.

```bash
# Build & upload firmware
pio run --target upload

# Build saja (verifikasi compile, tanpa upload)
pio run

# Monitor serial
pio device monitor

# Bersihkan build cache
pio run --target clean
```

Resource usage (perkiraan):
```
RAM:   ~7%  (≈23 KB / 320 KB)
Flash: ~25% (≈325 KB / 1.3 MB)
```

---

## Troubleshooting

### Motor tidak berputar
- Cek koneksi L298N
- Cek power 12V
- Cek ground sama antara ESP32 dan L298N

### Encoder tidak terbaca
- Cek koneksi GPIO 21 (Phase A), GPIO 22 (Phase B)
- Cek power encoder 3.3V (JANGAN 5V!)
- Pastikan interrupt terpasang

### Serial error
- Cek baud rate 115200
- Cek koneksi GPIO 16 (RX2), GPIO 17 (TX2)
- Cek TX/RX silang (ESP32 TX → RPi RX, ESP32 RX → RPi TX)

### Limit switch tidak terdeteksi
- Cek koneksi GPIO 18 (LS1), GPIO 19 (LS2)
- Cek wiring: satu sisi ke GPIO, sisi lain ke GND
- Internal pull-up aktif (HIGH = not pressed, LOW = pressed)

### Pump relay tidak aktif
- Cek GPIO 13 → R6 (1kΩ) → 2N2222 Base
- Cek power relay 5V
- Cek flyback diode (1N4007) terpasang

Lihat detail di **REFERENCE.md**

---

## Dependencies

```ini
platform = espressif32
board = esp32dev
framework = arduino
lib_deps = bblanchon/ArduinoJson@^6.21.3
```

---

## Error Codes

| Code | Deskripsi |
|------|-----------|
| 101 | Limit Switch 1 error |
| 102 | Limit Switch 2 error |
| 103 | Limit Switch conflict (both active) |
| 201 | Motor stall detected |
| 202 | Overcurrent detected |
| 203 | Motor overheat |
| 301 | Invalid command |
| 302 | Invalid parameter |
| 303 | Command timeout |

---

**Author:** Muhammad Ridho Assidiqi — 22/505759/SV/21913  
**Institution:** Universitas Gadjah Mada, Sekolah Vokasi  
**Program Studi:** Teknologi Rekayasa Instrumentasi dan Kontrol  
**© 2026**
