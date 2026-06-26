# Solar Panel Cleaning Robot — Raspberry Pi Controller

Sistem pembersih panel surya otonom: deteksi kekotoran dengan YOLOv11 two-stage, pengambilan keputusan adaptif, dan orkestrasi pembersihan via ESP32. Modul ini adalah unit Raspberry Pi (vision + web + decision).

**Author:** Muhammad Ridho Assidiqi — 22/505759/SV/21913
**Institusi:** Universitas Gadjah Mada, Sekolah Vokasi — Teknologi Rekayasa Instrumentasi dan Kontrol
**Tahun:** 2026

---

## Daftar Isi

1. [Arsitektur Sistem](#1-arsitektur-sistem)
2. [Prasyarat Hardware](#2-prasyarat-hardware)
3. [Setup dari Nol — Raspberry Pi](#3-setup-dari-nol--raspberry-pi)
4. [Setup Jaringan (Dual WiFi + Akses)](#4-setup-jaringan-dual-wifi--akses)
5. [Izin Kontrol Sistem (WiFi, Reboot, Model)](#5-izin-kontrol-sistem)
6. [Menjalankan sebagai Service (Auto-start)](#6-menjalankan-sebagai-service)
7. [Antarmuka Web & Login](#7-antarmuka-web--login)
8. [Manajemen Model YOLO](#8-manajemen-model-yolo)
9. [Konfigurasi](#9-konfigurasi)
10. [Development di Windows](#10-development-di-windows)
11. [Operasi Harian & Pemeliharaan](#11-operasi-harian--pemeliharaan)
12. [Troubleshooting](#12-troubleshooting)
13. [Struktur Proyek](#13-struktur-proyek)

---

## 1. Arsitektur Sistem

Sistem memakai dua pengendali yang terpisah tugasnya:

```
Raspberry Pi 5                UART 115200 JSON           ESP32 DevKit V1
[Vision + Web + Decision] <───────────────────────────> [Motor + Sensor + FSM + PID]
        │                                                       │
   USB Webcam                                    Wiper (PID) · Brush (PWM) · Pump (Relay)
```

- **Raspberry Pi 5** — akuisisi citra, inferensi YOLOv11 two-stage, keputusan pembersihan, server web Flask.
- **ESP32** — kendali motor deterministik (FSM 9 state + PID wiper 10 Hz), terpisah dari RPi.
- **Komunikasi** — UART kabel langsung (bukan WiFi), JSON 115200 baud. Real-time dan andal.

Alur kerja: capture → deteksi panel (Stage 1) → crop → klasifikasi kekotoran (Stage 2) → skor hybrid → trigger pembersihan bila skor ≥ 70 → ESP32 menjalankan siklus → verifikasi ulang (maks 5×) → cooldown.

---

## 2. Prasyarat Hardware

| Komponen | Spesifikasi | Fungsi |
|----------|-------------|--------|
| Raspberry Pi 5 | 4 GB RAM, ARM Cortex-A76 2.4 GHz | Vision, web, decision |
| ESP32 DevKit V1 | Dual-core 240 MHz | Motor, sensor, FSM, PID |
| Webcam USB | JETE W9 Full HD 1920×1080, autofocus | Capture citra panel |
| Motor DC + encoder | 12V, JGA25-370, 11 PPR, gear 90:1 | Wiper (closed-loop PID) |
| Motor DC | 12V, 170 RPM | Brush (open-loop PWM) |
| Pompa air | 12V DC 2.5–3A | Semprot air |
| Driver L298N | Dual H-Bridge 2A/channel | Penggerak motor |
| Relay SPDT 5V | Via transistor 2N2222 | Kontrol pompa |
| Limit switch ×2 | NO, pull-up eksternal di PCB | Deteksi ujung lintasan |

Koneksi RPi ↔ ESP32: UART2 (RPi GPIO TX/RX ke ESP32 GPIO 16/17), atau via kabel USB. Encoder **wajib 3.3V** (5V merusak GPIO ESP32).

---

## 3. Setup dari Nol — Raspberry Pi

Panduan ini mengasumsikan Raspberry Pi 5 baru tanpa OS.

### 3.1 Flash Raspberry Pi OS

1. Pasang **Raspberry Pi Imager** di laptop.
2. Pilih **Raspberry Pi OS (64-bit)** — disarankan Bookworm.
3. Klik ikon gear (⚙) untuk pra-konfigurasi:
   - Set hostname (mis. `mutualis`)
   - Aktifkan SSH (password atau key)
   - Set username & password
   - Konfigurasi WiFi awal + locale
4. Flash ke microSD (≥ 16 GB), masukkan ke Pi, nyalakan.

### 3.2 Update sistem & dependensi dasar

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip git libgl1 libglib2.0-0
```

`libgl1` dan `libglib2.0-0` diperlukan oleh OpenCV.

### 3.3 Clone repository

```bash
cd ~
git clone <URL_REPO> wipevision
cd wipevision/raspberry-pi
```

### 3.4 Buat virtual environment & install dependensi

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Catatan: `requirements.txt` memakai PyTorch CPU-only (tanpa CUDA) — tepat untuk Raspberry Pi. Proses install bisa lama karena mengunduh torch + ultralytics.

### 3.5 Siapkan model YOLO

Letakkan dua model di `models/` (atau upload via web setelah aplikasi jalan — lihat [bagian 8](#8-manajemen-model-yolo)):

```
models/panel_detection_best.pt        # Stage 1 — deteksi panel
models/dirt_classification_best.pt    # Stage 2 — klasifikasi kekotoran
```

### 3.6 Aktifkan UART GPIO untuk ESP32

Sistem ini memakai **UART GPIO** (pin RX/TX header), bukan kabel USB.

**Raspberry Pi 5 — wajib dua langkah berikut:**

**Langkah 1 — Tambahkan overlay UART di `/boot/firmware/config.txt`:**
```bash
sudo nano /boot/firmware/config.txt
# Tambahkan di bagian [all]:
dtoverlay=uart0-pi5
```
> Jangan pakai `dtparam=uart0=on` atau `enable_uart=1` saja — keduanya tidak cukup di RPi 5.

**Langkah 2 — Hapus serial console dari `/boot/firmware/cmdline.txt`:**
```bash
sudo nano /boot/firmware/cmdline.txt
# Hapus bagian: console=serial0,115200
# Biarkan console=tty1 tetap ada
```
> Selama `console=serial0,115200` masih ada, kernel memakai port tersebut sebagai console sehingga ESP32 tidak bisa berkomunikasi.

```bash
sudo reboot
```

Verifikasi setelah reboot — GPIO 14/15 harus terbaca sebagai TXD0/RXD0:
```bash
pinctrl get 14   # harus: a4 | hi // GPIO14 = TXD0
pinctrl get 15   # harus: a4 | pu | hi // GPIO15 = RXD0
```

Wiring (crossover, ground bersama):

| Raspberry Pi 5 | ESP32 |
|----------------|-------|
| GPIO 14 (TXD, pin 8) | GPIO 16 / RX2 |
| GPIO 15 (RXD, pin 10) | GPIO 17 / TX2 |
| GND (pin 6) | GND |

Port di `config/settings.yaml` diset `serial.port: auto` (default). Mode `auto` mencoba port GPIO UART dan USB-serial satu per satu dengan **handshake nyata** — port yang dibalas ESP32 (JSON valid) yang dipakai. Jadi sistem jalan baik kamu colok via GPIO maupun USB tanpa ubah config. Untuk mengunci port, set manual: `/dev/ttyAMA0` (GPIO RPi 5) atau `/dev/ttyUSB0` (USB).

### 3.7 Uji jalan manual

```bash
source venv/bin/activate
python main.py
```

Buka `http://<ip-pi>:5000/` dari perangkat di jaringan yang sama. Bila tampil dashboard, setup inti berhasil. Lanjut ke konfigurasi jaringan dan service.

---

## 4. Setup Jaringan + Izin + Service (satu langkah)

Seluruh setup ditangani satu script `setup.sh` (dependensi, WiFi AP, izin web,
service auto-start):

```bash
cd ~/wipevision/raspberry-pi
sudo bash setup.sh
sudo reboot
```

Setelah reboot:
- **WiFi Client (wlan0)** → terhubung router, IP DHCP. Untuk internet & remote.
- **WiFi AP (uap0)** → SSID `SolarPanelCleaner`, IP statis `192.168.50.1`. Untuk lapangan tanpa router.
- **Izin web** (polkit + sudoers) untuk ganti WiFi/reboot/restart dari Settings.
- **Service** `solar-panel-cleaner` auto-start saat boot.

Panduan lengkap + troubleshooting: **`docs/SETUP.md`**.

### 4.1 Cara akses antarmuka web

| Jalur | Alamat | Kapan dipakai |
|-------|--------|---------------|
| WiFi AP (hotspot robot) | `http://192.168.50.1:5000` | Di lapangan, tanpa router |
| WiFi / jaringan lokal | `http://<ip-wlan0>:5000` | Di lab dengan router |
| LAN (kabel) | `http://<ip-eth0>:5000` | Koneksi kabel |
| Remote (opsional) | `https://wipevision.my.id` | Via Cloudflare Tunnel |

Alamat aktif ditampilkan otomatis di **Settings → Alamat Akses Web**.

### 4.2 Ganti WiFi tanpa edit kode

Karena AP selalu aktif, di lokasi baru: sambungkan ke `SolarPanelCleaner` → buka
`http://192.168.50.1:5000/settings` → Scan WiFi → pilih jaringan → masukkan password.

> **Catatan Pi 5:** AP & client berbagi satu radio, jadi channel AP wajib sama
> dengan channel router. `setup.sh` menyamakannya otomatis. Bila pindah ke router
> dengan channel berbeda, jalankan ulang `sudo bash setup.sh wifi`.

### 4.3 Menjalankan sebagian setup

```bash
sudo bash setup.sh deps      # hanya dependensi
sudo bash setup.sh wifi      # hanya WiFi AP+client
sudo bash setup.sh perms     # hanya izin web (polkit+sudoers)
sudo bash setup.sh service   # hanya service auto-start
```

Perintah service berguna:
```bash
sudo systemctl status solar-panel-cleaner      # cek status
sudo systemctl restart solar-panel-cleaner     # restart manual
sudo journalctl -u solar-panel-cleaner -f      # log real-time
```

---


## 7. Antarmuka Web & Login

### 7.1 Tingkat akses

| Peran | Bisa lihat | Bisa aksi (trigger, testing, WiFi, model, reboot) |
|-------|:---:|:---:|
| Pengunjung (tanpa login) | ✅ | ❌ |
| Admin (login) | ✅ | ✅ |

- **View-only** — siapa pun yang membuka web bisa memantau (dashboard, performance, report). Tombol aksi dinonaktifkan, muncul banner pengingat login.
- **Admin** — login untuk mengakses semua fitur.

Akun default: username `taridho`, password `2026`. Password disimpan sebagai **hash** (bukan plaintext) di `config/settings.yaml`. Cara ganti ada di `docs/AUTH_GUIDE.md`.

### 7.2 Halaman

| Halaman | Akses | Fungsi |
|---------|-------|--------|
| Dashboard (`/`) | Semua | Preview kamera, status real-time, kontrol, visualisasi 3D live |
| Performance (`/performance`) | Semua | Metrik FPS, waktu inferensi, CPU, memori |
| Report (`/report`) | Semua | Log aktivitas, statistik, export CSV |
| System Testing (`/testing`) | **Admin** | Uji motor, pompa, encoder, limit switch, kamera, YOLO |
| Settings (`/settings`) | **Admin** | WiFi, alamat akses, model YOLO, kontrol sistem |

Testing dan Settings disembunyikan dari navbar untuk non-admin, dan diakses langsung via URL pun akan dialihkan ke dashboard.

### 7.3 Visualisasi 3D real-time

Dashboard menampilkan model 3D robot yang **bergerak mengikuti data nyata ESP32** (posisi wiper, RPM, brush, pompa, limit switch, state FSM) via WebSocket. Saat ESP32 terputus, visualisasi menunjukkan status OFFLINE — tanpa simulasi palsu.

---

## 8. Manajemen Model YOLO

Upload, pilih, dan hapus model langsung dari web (admin) tanpa SSH.

**Settings → Manajemen Model YOLO:**
1. Pilih stage: Stage 1 (deteksi panel) atau Stage 2 (klasifikasi kekotoran).
2. Pilih file `.pt`, klik Upload. Sistem memverifikasi file sebagai model YOLO valid dan mencocokkan jenisnya dengan stage.
3. Klik **Aktifkan** pada model yang ingin dipakai. Model langsung dimuat ulang tanpa restart.
4. Hapus model lama yang tidak terpakai (model aktif tidak bisa dihapus).

Penyimpanan: `models/detection/` dan `models/classification/`, dengan `models/active.json` melacak model aktif per stage. Pilihan tetap bertahan setelah restart.

Keamanan: upload/pilih model diblokir saat siklus pembersihan berjalan (mencegah lonjakan CPU mengganggu timing). Inferensi yang sedang berjalan aman dari pergantian model (snapshot referensi + lock).

---

## 9. Konfigurasi

Sumber kebenaran konfigurasi RPi: `config/settings.yaml`.

```yaml
camera:
  resolution: [1920, 1080]
  device_id: 0                # 0 atau 1 — sesuaikan dengan webcam USB

detection:
  panel_model_path: models/panel_detection_best.pt
  panel_confidence: 0.7
  dirt_model_path: models/dirt_classification_best.pt
  dirt_confidence: 0.7

cleaning:
  trigger_threshold: 70       # trigger pembersihan bila skor ≥ 70
  cooldown_after_success: 300 # jeda antar siklus deteksi (detik)
  cycles:
    max_attempts: 5           # maksimal pembersihan berturut-turut

serial:
  port: auto                  # deteksi pintar GPIO & USB via handshake. Atau set /dev/serial0 (GPIO) / /dev/ttyUSB0 (USB)
  baudrate: 115200

web:
  host: 0.0.0.0
  port: 5000

wifi:
  client_interface: wlan0
  ap_interface: uap0
  lan_interface: eth0
  ap_ip: 192.168.50.1

auth:
  enabled: true
  admin_username: taridho
  admin_password_hash: "scrypt:..."   # ganti via docs/AUTH_GUIDE.md
  secret_key: "..."                    # ganti dengan nilai acak Anda
  session_hours: 12
```

### Formula skor & strategi pembersihan

Skor: `S = 100 × w × (0.7 + 0.3 × confidence)`, dengan bobot `w = {bersih:0, ringan:1, sedang:2, berat:3}`.

| Level | Skor | Spray | Wiper RPM | Brush RPM | Pass |
|-------|------|-------|-----------|-----------|------|
| Bersih | < 70 | — | — | — | — |
| Ringan | 70–169 | — | 45 | 120 | 1 |
| Sedang | 170–269 | Saat turun | 40 | 120 | 1 |
| Berat | ≥ 270 | Saat turun | 35 | 150 | 2 |

> Spray kontinu sepanjang pass turun (LS1→LS2), mati saat pass naik. Ringan = sikat kering tanpa air.
Konstanta ini harus konsisten dengan `esp32/src/config.h`.

---

## 10. Development di Windows

Untuk pengembangan di laptop Windows, `run_dev.py` menjalankan controller yang **sama persis** dengan produksi (komponen real: kamera, YOLO, ESP32). Tidak ada mode mock — bila hardware tidak ada, sistem menunggu dengan graceful fallback dan auto-reconnect.

```bat
cd raspberry-pi
run_app.bat
```

`run_app.bat` otomatis memakai `venv311` dari root proyek dan menjalankan `run_dev.py`. Bedanya dengan produksi: auto-deteksi port ESP32 untuk Windows (COM port bisa berubah).

Akses: `http://localhost:5000/`.

Verifikasi syntax sebelum commit:
```bash
python -m py_compile main.py run_dev.py app/*.py web/server.py
```

---

## 11. Operasi Harian & Pemeliharaan

### Update kode di Raspberry Pi
```bash
cd ~/wipevision/raspberry-pi
git pull
sudo systemctl restart solar-panel-cleaner
```

Bila ada perubahan CSS/JS, lakukan hard refresh di browser (Ctrl+Shift+R).

### Restart / reboot dari web
**Settings → Sistem:**
- **Restart Aplikasi** — restart service, butuh konfirmasi password.
- **Reboot Raspberry Pi** — reboot OS penuh, butuh konfirmasi password.

Keduanya diblokir saat pembersihan aktif dan mengirim perintah stop ke ESP32 dulu agar aktuator mati dengan aman.

### Data untuk laporan (Bab 4)
- **Performance** (`/performance`) — FPS, waktu inferensi, CPU, memori.
- **Report** (`/report`) — log aktivitas, export CSV.
- **PID step response** — diambil via tool khusus `motor_test_gui/` (20 Hz, metrik otomatis, export CSV/TXT/PNG), bukan dari web.

---

## 12. Troubleshooting

**ESP32 tampil "Terputus" padahal kabel tersambung**
Status koneksi berbasis handshake nyata (ESP32 harus membalas), bukan sekadar port terbuka. Periksa pin RX/TX tidak tertukar, ESP32 menyala, dan baud 115200. Pada UART hardware, port selalu "terbuka" walau tidak ada perangkat — jadi status mengandalkan balasan ESP32.

**Kamera tidak terdeteksi**
Coba ganti `camera.device_id` (0 atau 1) di `settings.yaml`. Auto-reconnect berjalan tiap 10 detik. Uji di halaman Testing.

**Model YOLO tidak ditemukan**
Pastikan file `.pt` ada di `models/` (atau upload via Settings). Format harus PyTorch `.pt`. Pastikan `ultralytics` terpasang di venv.

**Fitur ganti WiFi AP / reboot / restart gagal "perlu izin sudo"**
Jalankan `sudo bash setup.sh perms` lalu reboot. Itu memasang aturan polkit + sudoers.

**Info WiFi AP / alamat akses tidak muncul di Settings**
`hostapd.conf` hanya bisa dibaca root; aplikasi membacanya via `sudo cat`. Pastikan `sudo bash setup.sh perms` sudah dijalankan.

**Tombol redup / tidak bisa diklik**
Anda dalam mode view-only. Login admin (`taridho` / `2026`) untuk mengaktifkan tombol aksi.

**Halaman tidak berubah setelah git pull**
Hard refresh browser (Ctrl+Shift+R) untuk memuat ulang CSS/JS. Untuk perubahan Python, restart service.

---

## 13. Struktur Proyek

```
raspberry-pi/
├── app/
│   ├── camera.py               # Webcam USB
│   ├── two_stage_detector.py   # YOLOv11 Stage 1 + Stage 2 (+ reload model)
│   ├── serial_comm.py          # ESP32 UART JSON (+ is_alive handshake)
│   ├── controller.py           # SolarPanelController (monitor loop + FSM orkestrasi)
│   ├── config.py               # Config YAML dot-notation
│   ├── wifi_manager.py         # nmcli: WiFi client/AP, konektivitas, alamat akses
│   ├── model_manager.py        # Upload/pilih/hapus model YOLO
│   ├── pid_logger.py           # (dorman) logger PID
│   └── performance_logger.py   # Metrik performa
├── web/
│   ├── server.py               # Flask + WebSocket + REST API + auth
│   ├── templates/              # dashboard, testing, performance, report, settings
│   └── static/                 # css/main.css, js/, 3d-visualization.html
├── config/settings.yaml        # Sumber kebenaran config RPi
├── models/
│   ├── detection/              # model deteksi (.pt)
│   ├── classification/         # model klasifikasi (.pt)
│   └── active.json             # model aktif per stage
├── scripts/                    # plot PID, monitor performa
├── main.py                     # Entry point produksi (Raspberry Pi)
├── run_dev.py                  # Entry point development (Windows)
├── run_app.bat                 # Launcher Windows (auto venv311)
├── setup.sh                    # Setup all-in-one (deps/wifi/perms/service)
├── restore_single_wifi.sh      # Matikan AP, kembali client-only
├── uninstall_service.sh        # Hapus service auto-start
└── solar-panel-cleaner.service # Definisi systemd service
```

### Dokumen pendukung
- `docs/SETUP.md` — panduan setup produksi (jaringan, izin, service, troubleshooting)
- `docs/AUTH_GUIDE.md` — autentikasi & ganti password
- `docs/CLOUDFLARE_TUNNEL_GUIDE.md` — akses remote (opsional)
- `docs/DEVELOPMENT.md` — catatan pengembangan (Windows dev)
- `docs/PID_LOGGER.md` — panduan PID Data Logger
- `docs/PERFORMANCE.md` — panduan metrik performa

---

**Author:** Muhammad Ridho Assidiqi — Universitas Gadjah Mada, Sekolah Vokasi (TRIK)
**Terakhir diperbarui:** Juni 2026
