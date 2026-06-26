# 🛠️ Development Guide

Panduan development dan testing sistem pembersih panel surya.

---

## 📋 Prerequisites

### Software
- **Python 3.11** dengan virtual environment (`venv311`)
- **Packages**: ultralytics, flask, opencv-python, pyserial, numpy, pandas, psutil
- **PlatformIO** (untuk ESP32 firmware)
- **Web Browser** (Chrome, Firefox, Edge)

### Hardware (Opsional untuk Development)
- **Webcam USB** (JETE W9 atau webcam lain)
- **ESP32 DevKit V1** via USB serial
- Model YOLO `.pt` di folder `models/`

---

## 🚀 Quick Start

### Windows (Recommended)

```bash
cd raspberry-pi

# Double-click atau jalankan:
run_app.bat
```

`run_app.bat` otomatis menggunakan `venv311` yang sudah terinstall ultralytics.

### Manual

```bash
cd raspberry-pi

# Gunakan venv311 yang punya ultralytics:
& "E:\Kuliah\Tugas Akhir\Program\image-processing\venv311\Scripts\python.exe" run_dev.py

# Atau jika venv sudah aktif:
python run_dev.py
```

### Production (Raspberry Pi)

```bash
cd raspberry-pi
python main.py
```

### Expected Output

```
============================================================
  SOLAR PANEL CLEANER - Development Mode
============================================================
Platform: Windows 10
Python:   3.11.x

Hardware:
  ESP32:    COM10
  Kamera:   Webcam (auto-detect)
  Detector: YOLO model (jika tersedia)

Web interface:
  Dashboard: http://localhost:5000/
  Testing:   http://localhost:5000/testing

Press Ctrl+C to stop
============================================================

Initializing system...
✓ Kamera 0 tersedia (on-demand mode)
✓ Panel detection model loaded: models/panel_detection_best.pt
✓ Dirt classification model loaded: models/dirt_classification_best.pt
✓ Using two-stage detection (Panel Detection → Dirt Classification)
✓ Connected to ESP32 on COM10
Solar panel monitoring started
✓ Monitoring loop started (auto capture + detection)

Server starting on http://localhost:5000/
```

---

## 📁 Project Structure

```
raspberry-pi/
├── app/
│   ├── camera.py             # Webcam USB (JETE W9, 1920×1080)
│   ├── two_stage_detector.py # YOLOv11 two-stage detection
│   ├── serial_comm.py        # ESP32 UART JSON communication
│   ├── controller.py         # SolarPanelController (main logic)
│   ├── config.py             # YAML configuration loader
│   ├── pid_logger.py         # PID data logger
│   └── performance_logger.py # Performance metrics
├── web/
│   ├── server.py             # Flask server + WebSocket
│   ├── templates/            # HTML (dashboard, testing, performance, report)
│   └── static/               # CSS, JS
├── config/
│   └── settings.yaml         # Main configuration
├── models/
│   ├── panel_detection_best.pt      # Stage 1 model
│   └── dirt_classification_best.pt  # Stage 2 model
├── run_dev.py                # Development entry point
├── run_app.bat               # Windows launcher (auto venv311)
└── main.py                   # Production entry point
```

---

## ⚙️ Arsitektur

### Tidak Ada Mock Mode

Sistem **tidak menggunakan mock/fake data**. Semua data berasal dari hardware asli:

- **Kamera**: Webcam USB (real capture)
- **Detector**: YOLO model `.pt` (real inference)
- **ESP32**: Serial UART (real communication)

### Graceful Fallbacks

Jika hardware tidak tersedia, sistem tetap jalan dengan fallback:

| Komponen | Tersedia | Tidak Tersedia |
|----------|----------|----------------|
| **Kamera** | Real webcam capture | `NoCamera` placeholder (frame hitam "NO CAMERA") |
| **YOLO Model** | Real detection + classification | `FallbackDetector` (panel_detected: false) |
| **ESP32** | Real serial communication | Auto-reconnect loop, dummy ESP32 |

### Controller

`run_dev.py` dan `main.py` keduanya menggunakan `SolarPanelController` yang sama:

```
SolarPanelController
├── Camera (webcam USB, auto-reconnect 10s)
├── TwoStageDetector (YOLOv11)
├── ESP32Communicator (serial UART, auto-reconnect 5s)
└── Monitor Loop:
    ├── Hardware check (camera + ESP32 live check)
    ├── Cooldown countdown (jeda antar deteksi)
    ├── YOLO two-stage detection
    ├── Cleaning trigger (score ≥ 70)
    ├── Cleaning cycle (via ESP32 FSM)
    └── Verification (score < 70 = bersih)
```

### Cooldown System

Cooldown = jeda antar siklus deteksi YOLO. Setelah setiap deteksi (bersih atau selesai cleaning), cooldown countdown mulai. Selama countdown, YOLO tidak jalan.

| Kondisi | Cooldown Dashboard |
|---------|-------------------|
| Countdown aktif | `4m 30s` (kuning) |
| Cleaning/verifikasi | `Menunggu Pembersihan` (biru) |
| Kamera disconnect | `Menunggu Kamera` (merah) |
| ESP32 disconnect | `Pause (ESP32 Terputus)` (merah) |
| Siap deteksi | `Siap` (hijau) |

- Cooldown **pause** saat hardware disconnect, **resume** dari sisa waktu saat reconnect
- Perubahan cooldown via dashboard berlaku di **siklus berikutnya** (tidak potong yang sedang jalan)
- Frontend menghitung countdown sendiri via client-side timer (smooth per detik)

### Hardware Disconnect Protection

| Skenario | Mode | Aksi |
|----------|------|------|
| 📷✅ 🔌✅ | Monitoring | Full operation |
| 📷✅ 🔌❌ | Deteksi Saja | Cooldown pause, auto-reconnect ESP32 |
| 📷❌ 🔌✅ | Menunggu Kamera | Cooldown pause, auto-reconnect kamera |
| 📷❌ 🔌❌ | Menunggu Kamera | Semua pause, auto-reconnect keduanya |
| Cleaning + 🔌 cabut | Monitoring | Abort cleaning, cooldown mulai |
| Cleaning + 📷 cabut | Menunggu Kamera | Abort cleaning, cooldown reset |

---

## 🌐 Web Interface (4 Halaman)

| Halaman | URL | Fungsi |
|---------|-----|--------|
| **Dashboard** | `/` | Preview kamera, status real-time, kontrol, konfigurasi |
| **Testing** | `/testing` | Hardware tests, PID logger, cleaning cycle test |
| **Performance** | `/performance` | Real-time metrics, FPS, inference time |
| **Report** | `/report` | Activity log, statistik, filter, export CSV |

### Dashboard Features
- **Preview kamera** MJPEG stream (~10 FPS) dengan toggle ON/OFF
- **Deteksi YOLO overlay** toggle (bounding box panel + klasifikasi)
- **Status sistem** real-time via WebSocket (500ms update):
  - Mode: Monitoring / Deteksi Saja / Menunggu Kamera / Pembersihan / Verifikasi
  - ESP32 + Serial Port: tersinkronisasi dari satu live check
  - Cooldown countdown (client-side timer)
  - Cleaning progress: FSM state, progress bar, RPM, pump, limit switches
- **Capture & Analisis** manual (annotated image)
- **Bersihkan Manual** + **Emergency Stop**
- **Konfigurasi**: Max Attempts, Cooldown (dengan dialog konfirmasi)
  - Trigger threshold (70) fix dari rumus, tidak bisa diubah
  - Perubahan berlaku di siklus berikutnya

---

## 🔧 Configuration

### settings.yaml

```yaml
camera:
  resolution: [1920, 1080]
  device_id: 0              # 0 = Integrated, 1 = USB Camera

detection:
  panel_model_path: "models/panel_detection_best.pt"
  panel_confidence: 0.7     # Threshold Stage 1
  dirt_model_path: "models/dirt_classification_best.pt"
  dirt_confidence: 0.7      # Threshold Stage 2

cleaning:
  trigger_threshold: 70     # Score ≥ 70 = perlu pembersihan (fix, dari rumus)
  monitor_interval: 300     # Fallback interval (cooldown menggantikan ini)
  cooldown_after_success: 300  # Cooldown antar siklus deteksi (5 menit)
  verify_interval: 2        # Interval verifikasi setelah cleaning (2 detik)
  cycles:
    max_attempts: 5         # Maks pembersihan berturut-turut
    verify_delay: 2         # Delay sebelum verifikasi

serial:
  port: "/dev/serial0"      # RPi: /dev/serial0, Windows: auto-detect
  baudrate: 115200
```

### ESP32 Auto-Detect (Windows)

`run_dev.py` otomatis mendeteksi ESP32 berdasarkan VID:PID (CP2102, CH340, dll). Atau manual:

```bash
python run_dev.py COM10
```

---

## 🔄 Development Workflow

### Typical Session

```bash
# 1. Jalankan server
cd raspberry-pi
run_app.bat

# 2. Buka browser
# http://localhost:5000/

# 3. Edit code
# - Python: app/*.py, web/server.py
# - HTML: web/templates/*.html
# - JS: web/static/js/*.js
# - CSS: web/static/css/*.css

# 4. Restart server (Ctrl+C → run_app.bat lagi)
# Flask debug mode auto-reload untuk Python files

# 5. Hard refresh browser (Ctrl+F5) untuk CSS/JS changes
```

### Sebelum Restart

Selalu kill proses Python dulu untuk release kamera dan serial port:

```bash
taskkill /F /IM python.exe
```

### Hot Reload

Flask debug mode enabled → Python files auto-reload.

| File Type | Auto-reload? |
|-----------|-------------|
| Python (`.py`) | ✅ Ya |
| HTML templates | ⚠️ Refresh browser |
| CSS/JS | ⚠️ Ctrl+F5 (hard refresh) |

---

## 🧪 Testing

### Via Web Interface

Buka http://localhost:5000/testing untuk:

**Hardware Tests:**
- ESP32 connection, config, limit switch, encoder
- Motor wiper & brush (individual PWM)
- Water pump (duration control)
- Full cleaning cycle

**Camera & Detection Tests:**
- Camera capture
- YOLO model loading
- Two-stage detection

**PID Data Logger:**
- Step response (30/45 RPM)
- With/without load
- Export: CSV, JSON, TXT

---

## � Troubleshooting

### "ultralytics tidak terinstall"
Kamu menjalankan dengan Python yang salah. Gunakan `run_app.bat` atau jalankan dengan `venv311`:
```bash
& "path\to\venv311\Scripts\python.exe" run_dev.py
```

### Kamera tidak terdeteksi
- Cek USB webcam terhubung
- Coba ganti `device_id` di `settings.yaml` (0 atau 1)
- Kill proses Python lain yang mungkin lock kamera:
  ```bash
  taskkill /F /IM python.exe
  ```

### ESP32 tidak terhubung
- Cek kabel USB
- Cek COM port di Device Manager
- Manual: `python run_dev.py COM10`

### Port 5000 sudah dipakai
```bash
# Windows:
netstat -ano | findstr :5000
taskkill /PID <PID> /F
```

### Model YOLO tidak di-load
- Pastikan file `.pt` ada di `models/`:
  - `panel_detection_best.pt`
  - `dirt_classification_best.pt`
- Copy dari `training/runs/detect/.../weights/best.pt`

---

## 📊 Deploy ke Raspberry Pi

### 1. Copy Files

```bash
scp -r raspberry-pi/ pi@raspberrypi.local:~/image-processing/
```

### 2. Install Dependencies

```bash
ssh pi@raspberrypi.local
cd ~/image-processing/raspberry-pi
pip install -r requirements.txt
```

### 3. Configure Serial Port

Edit `config/settings.yaml`:
```yaml
serial:
  port: "/dev/serial0"    # GPIO UART (bukan USB)
```

### 4. Run Production

```bash
python main.py
```

### Perbedaan Dev vs Production

| Aspek | Development (Windows) | Production (RPi) |
|-------|----------------------|-------------------|
| Entry point | `run_dev.py` / `run_app.bat` | `main.py` |
| Serial port | Auto-detect COM | `/dev/serial0` |
| Camera | USB webcam | USB webcam |
| Controller | `SolarPanelController` | `SolarPanelController` |
| YOLO model | Same `.pt` files | Same `.pt` files |
| Behavior | **Identik** | **Identik** |

Kedua mode menggunakan controller dan logic yang **sama persis**.

---

**Author:** Muhammad Ridho Assidiqi — 22/505759/SV/21913  
**Institution:** Universitas Gadjah Mada, Sekolah Vokasi  
**Last Updated:** Mei 2026
