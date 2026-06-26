# Performance Monitoring - Complete Documentation

## 🚀 Quick Start

### 1. Performance Dashboard
**URL**: http://localhost:5000/performance

**Features**:
- Real-time performance metrics
- FPS, inference time, memory, CPU usage
- Interactive charts (bar + line graphs)
- Detailed detection history table
- Export functionality

### 2. System Monitor
```bash
# Monitor Raspberry Pi performance
python scripts/monitor_performance.py -d 60

# Output:
[10:30:00] CPU: 8.5% | RAM: 12.3% | Temp: 52.3°C | Flask: CPU 1.8%
```

## 📊 Performance Dashboard

### Access
Navigate to: **http://localhost:5000/performance**

### Metrics Displayed

#### Real-Time Stats Cards:
- **Average FPS**: Frames per second
- **Avg Inference Time**: Detection processing time (ms)
- **Memory Usage**: RAM consumption (MB)
- **CPU Usage**: Processor utilization (%)

#### Kartu Sistem Raspberry Pi (baru):
Bagian "Sistem Raspberry Pi" di atas kartu metrik menampilkan kondisi board
secara live (refresh 2 detik via WebSocket, tetap tampil walau logging belum
aktif):
- **Uptime** — lama Pi menyala sejak boot
- **Suhu CPU** (°C) — bar berubah kuning >70°C, merah >80°C (ambang throttle)
- **RAM** — persen + detail used/total MB
- **CPU Load** — persen + frekuensi (MHz) & jumlah core
- **Penyimpanan** — persen + used/total GB
- **Daya / Throttle** — status `vcgencmd get_throttled` (undervoltage /
  throttling, sekarang & pernah-terjadi)

Sumber data: `get_system_info()` di `app/performance_logger.py`. Field khas RPi
(suhu, throttle, model) bernilai `N/A` saat dijalankan di Windows dev.

#### Charts:
1. **Bar Chart**: Average metrics comparison
2. **Line Chart**: Metrics over time (last 50 detections)

#### Detection History Table:
- Timestamp
- Stage 1 time (panel detection)
- Stage 2 time (dirt classification)
- Total inference time
- FPS

### Export Data
Click **"Export"** button to generate:
- **CSV**: Raw performance data
- **JSON**: Structured report with statistics
- **TXT**: LaTeX-friendly summary

**Output Location**: `analysis_output/performance/`

## 🔧 System Monitoring

### Monitor Script
```bash
python scripts/monitor_performance.py [options]
```

**Options**:
- `-d, --duration`: Monitoring duration in seconds (default: 60)
- `-i, --interval`: Update interval in seconds (default: 1.0)

**Examples**:
```bash
# Monitor for 5 minutes
python scripts/monitor_performance.py -d 300

# Monitor with 0.5s interval (more responsive)
python scripts/monitor_performance.py -i 0.5

# Monitor during test
python scripts/monitor_performance.py -d 120 &
python run_dev.py
```

### Output Format:
```
[HH:MM:SS] CPU: X.X% | Cores: X.X% X.X% X.X% X.X% | RAM: X.X% (X.XGB) | Temp: XX.X°C | Flask: CPU X.X% MEM X.X%
```

### Summary Report:
```
SUMMARY
======================================================================
Average CPU Usage:    8.5%
Memory Usage:         12.3% (0.5GB / 4.0GB)
CPU Temperature:      52.3°C
✅ Temperature normal.
```

## 📈 Performance Analysis

### GUI Performance Impact

#### Beban Raspberry Pi 5:
| Component | CPU | Memory | Impact |
|-----------|-----|--------|--------|
| Flask Server | 1-2% | 50-100 MB | Minimal ✅ |
| PID Logger | <1% | 10-20 MB | Minimal ✅ |
| Serial Comm | <1% | 5-10 MB | Minimal ✅ |
| YOLOv11 | 60-80% | 500-800 MB | Heavy ⚠️ |

**Total GUI Overhead**: ~3-5% CPU, ~100 MB RAM

#### Network Bandwidth:
- Polling rate: 5 Hz (every 200ms)
- Data size: ~100 bytes per request
- **Bandwidth**: 0.5 KB/s (negligible)

### Thermal Analysis

**Raspberry Pi 5 Temperature**:
- **Normal**: 40-60°C
- **Elevated**: 60-70°C
- **High**: 70-80°C (consider cooling)
- **Throttling**: >80°C (automatic slowdown)

**GUI Impact**: +2-5°C (minimal)

### Performance Scenarios

#### Scenario A: PID Test (No YOLO)
```
CPU:  9% (Flask 2% + PID 1% + Serial 1% + OS 5%)
RAM:  0.5 GB
Temp: 52°C
Status: ✅ VERY SAFE
```

#### Scenario B: Detection + Cleaning (With YOLO)
```
CPU:  79% (YOLO 70% + Flask 2% + Others 7%)
RAM:  1.9 GB
Temp: 70°C
Status: ✅ SAFE
```

## 🎯 Recommendations

### For Testing:
✅ **GUI is safe** - overhead <5% CPU  
✅ **Real-time monitoring helpful** for debugging  
✅ **No performance impact** on PID control (runs on ESP32)  
✅ **Minimal impact** on YOLO inference

### For 24/7 Operation:
⚠️ Consider headless mode (no GUI)  
⚠️ Reduce polling rate to 500ms (2 Hz)  
⚠️ Install cooling fan for thermal management

### For Presentation/Demo:
✅ GUI provides excellent visualization  
✅ Real-time charts impressive for audience  
✅ No need to worry about performance

## 📁 Output Files

### Performance Export:
```
raspberry-pi/
├── logs/performance/
│   ├── performance_session_*.csv    # Raw data
│   └── performance_session_*.json   # Full report
└── analysis_output/performance/
    └── performance_report_*.txt     # LaTeX-friendly
```

### TXT Format:
```
TWO-STAGE DETECTION PERFORMANCE REPORT
======================================================================
AVERAGE METRICS
FPS:                  15.23 fps
Inference Time:       65.7 ms
Stage 1 (Panel):      25.3 ms
Stage 2 (Dirt):       40.4 ms
Memory Usage:         512 MB
CPU Usage:            75.2%

STATISTICS
Min Inference Time:   45.2 ms
Max Inference Time:   89.3 ms
Std Dev:              8.7 ms
```

## 🔍 Troubleshooting

### High CPU Usage (>90%)
**Causes**:
- YOLO inference on high-resolution images
- Multiple processes running
- Insufficient cooling

**Solutions**:
- Reduce image resolution
- Close unnecessary processes
- Install heatsink + fan

### High Temperature (>75°C)
**Causes**:
- Continuous YOLO inference
- Poor ventilation
- No heatsink

**Solutions**:
- Install cooling fan
- Improve ventilation
- Reduce workload (lower FPS)

### Memory Issues
**Causes**:
- Memory leak in long-running processes
- Too many cached images

**Solutions**:
- Restart server periodically
- Clear cache
- Monitor with `free -h`

## 💡 Optimization Tips

### Reduce Polling Rate:
```javascript
// In testing.html, change from 200ms to 500ms
setInterval(updatePIDChart, 500);  // 2 Hz instead of 5 Hz
```

### Headless Mode:
```bash
# Run without GUI (logging only)
# Stop Flask server, use direct logging to CSV
```

### Resource Monitoring:
```bash
# Check CPU
top

# Check memory
free -h

# Check temperature
vcgencmd measure_temp

# Check processes
ps aux | grep python
```

## 🧪 Benchmark Inferensi untuk Bab 4

Untuk mengisi kolom **"Kecepatan inferensi (Raspberry Pi 5)"** pada Tabel
`hasil_stage1` & `hasil_stage2` di Bab 4 (yang masih `\ISI ms/frame`).

### Cara 1 — via Web (disarankan, tanpa SSH)
Buka **http://192.168.50.1:5000/performance** → bagian **"Benchmark Inferensi
YOLO"**:
1. Isi jumlah iterasi (default 100).
2. Klik **"Jalankan Benchmark"** (diblokir otomatis saat pembersihan berjalan).
3. Progres tampil real-time; hasil (mean/median/std/min/max stage 1, stage 2,
   total + FPS + suhu CPU) muncul di tabel.
4. File hasil otomatis muncul di bagian **"File Hasil"** — klik **Unduh** untuk
   menyimpan ke perangkat. (admin-only untuk menjalankan; melihat & unduh bebas)

### Cara 2 — via Terminal SSH
```bash
python3 benchmark_inference.py --runs 100
python3 benchmark_inference.py --runs 100 --image test_samples/kotor_sedang.jpg
python3 benchmark_inference.py --runs 50 --synthetic
```

Kedua cara memakai fungsi pengukuran yang sama (`run_inference_benchmark()` di
`app/performance_logger.py`), jadi hasilnya konsisten. Output disimpan di:

```
analysis_output/performance/inference_benchmark_<timestamp>.txt   # LaTeX-friendly
analysis_output/performance/inference_benchmark_<timestamp>.json
```

File `.txt` memuat baris khusus "UNTUK TABEL BAB 4" yang langsung menyebut angka
ms/frame untuk masing-masing tabel. Snapshot suhu penting: bila Pi ter-throttle
saat benchmark, angka inferensi tidak valid — pastikan `Throttled: now=False`.

### Unduh semua file hasil dari web
Bagian **"File Hasil"** di halaman performance menampilkan semua report, export,
dan benchmark (dari `analysis_output/performance/` & `logs/performance/`) dengan
tombol unduh. Tidak perlu `scp` lagi.



## 📚 References

- **Performance Logger + System Info**: `app/performance_logger.py` (`get_system_info()`)
- **Dashboard**: `web/templates/performance.html`
- **Benchmark Inferensi (Bab 4)**: `benchmark_inference.py`
- **Monitor Script**: `scripts/monitor_performance.py`
- **API Endpoints**: `web/server.py` (`/api/performance/*`, `/api/system/info`, `/ws/performance`)

---

**Author**: Muhammad Ridho Assidiqi  
**Institution**: Universitas Gadjah Mada
