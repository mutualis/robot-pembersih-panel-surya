# Robot Pembersih Panel Surya Otonom

Implementasi Two-Stage Detection YOLOv11 dan Kendali PID pada Sistem Robot Pembersih Panel Surya Otonom Berbasis Klasifikasi Tingkat Kekotoran.

**Tugas Akhir D4 Teknologi Rekayasa Instrumentasi dan Kontrol**
Universitas Gadjah Mada — 2026
Penyusun: Muhammad Ridho Assidiqi (22/505759/SV/21913)
Pembimbing: Dr. Ir. Atikah Surriani, S.T., M.Eng., IPM.

---

## Struktur Repositori

```
├── esp32/          # Firmware ESP32 (PlatformIO) — FSM, PID, komunikasi serial
└── raspberry-pi/   # Aplikasi Raspberry Pi 5 (Python/Flask) — vision, web interface
```

## esp32/

Firmware berbasis PlatformIO untuk ESP32 yang menangani:
- **Finite State Machine (FSM)** 9 state untuk siklus pembersihan adaptif
- **Kendali PID closed-loop** motor wiper dengan umpan balik rotary encoder (PCNT hardware)
- **Komunikasi serial UART** (115200 bps, format JSON) dengan Raspberry Pi
- Kendali aktuator: motor wiper, motor sikat, pompa, relay, limit switch

**Cara upload:**
```bash
cd esp32
pio run --target upload --environment production
```

## raspberry-pi/

Aplikasi Python untuk Raspberry Pi 5 yang menangani:
- **Two-Stage Detection YOLOv11**: deteksi panel (YOLOv11n) → klasifikasi kekotoran (YOLOv11n-cls)
- **Weighted score** untuk penentuan level kekotoran (Bersih / Ringan / Sedang / Berat)
- **Antarmuka web Flask** dengan live feed kamera, visualisasi 3D carriage, dan log
- **Monitoring otonom berkelanjutan** dengan loop deteksi → bersihkan → verifikasi

**Cara instalasi:**
```bash
cd raspberry-pi
pip install -r requirements.txt
cp .env.example .env   # sesuaikan konfigurasi
python main.py
```

> **Catatan model:** File bobot YOLOv11 (`.pt`) tidak disertakan di repositori karena ukurannya besar. Tempatkan secara manual di `raspberry-pi/models/` sesuai `models/README.md`.

## Arsitektur Sistem

```
Raspberry Pi 5                        ESP32
┌─────────────────────┐              ┌──────────────────────┐
│  Kamera → YOLOv11   │   UART JSON  │  FSM → PID → Motor   │
│  Two-Stage Pipeline  │ ──────────► │  Wiper / Brush / Pump│
│  Flask Web Interface │ ◄────────── │  Encoder Feedback    │
└─────────────────────┘              └──────────────────────┘
```

## Hasil Utama

| Metrik | Nilai |
|--------|-------|
| mAP@0.5 deteksi panel | 99,43% |
| Akurasi klasifikasi kekotoran | 98,00% |
| Kecepatan inferensi (RPi 5) | 2,02 FPS (494,77 ms) |
| Overshoot PID motor wiper | < 10% |
| Success rate komunikasi serial | 100% (100/100 perintah) |
| Success rate monitoring otonom | 93,33% (14/15 sesi) |
