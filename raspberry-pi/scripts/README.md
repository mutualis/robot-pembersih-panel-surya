# Utility Scripts

Folder ini berisi script-script utility untuk analisis dan monitoring sistem.

## 📁 Daftar Script

### 1. PID Analysis Scripts

#### `plot_pid_response.py`
Plot grafik RPM vs Time dari single CSV file PID logger.

**Usage**:
```bash
cd raspberry-pi
python scripts/plot_pid_response.py logs/pid/pid_step_response_30rpm_20260413_103000.csv
```

**Output**:
- PNG file (grafik publication-quality)
- Parameter transient response di console

#### `plot_all_pid_responses.py`
Batch plot semua CSV files di folder `logs/pid/`.

**Usage**:
```bash
cd raspberry-pi
python scripts/plot_all_pid_responses.py
```

**Output**:
- Multiple PNG files di `analysis_output/pid/graphs/`
- Summary di console

### 2. Performance Monitoring Scripts

#### `monitor_performance.py`
Monitor CPU, Memory, dan Temperature Raspberry Pi secara real-time.

**Usage**:
```bash
cd raspberry-pi
python scripts/monitor_performance.py -d 60
```

**Options**:
- `-d, --duration`: Durasi monitoring dalam detik (default: 60)
- `-i, --interval`: Interval update dalam detik (default: 1.0)

**Output**:
```
[10:30:00] CPU:   8.5% | Cores:  5.2%  8.1% 10.3%  9.8% | RAM:  12.3% (0.5GB) | Temp: 52.3°C | Flask: CPU 1.8% MEM 2.1%
```

#### `run_performance_test.py`
Test standalone untuk performance logger (Two-Stage Detection).

**Usage**:
```bash
cd raspberry-pi
python scripts/run_performance_test.py
```

**Output**:
- Performance metrics di console
- CSV/JSON/TXT files di `logs/performance/`

## 📦 Dependencies

### For PID Scripts:
```bash
pip install pandas matplotlib
```

### For Monitoring Scripts:
```bash
pip install psutil
```

## 🎯 Use Cases

### Untuk Laporan (Bab 4)

#### 1. Generate Grafik PID
```bash
# Plot single test
python scripts/plot_pid_response.py logs/pid/pid_step_response_30rpm_*.csv

# Plot all tests
python scripts/plot_all_pid_responses.py
```

#### 2. Monitor Performance Saat Test
```bash
# Monitor selama 5 menit
python scripts/monitor_performance.py -d 300

# Monitor dengan interval 0.5s (lebih responsive)
python scripts/monitor_performance.py -i 0.5
```

#### 3. Test Performance Logger
```bash
# Test performance logging
python scripts/run_performance_test.py
```

## 📊 Output Locations

```
raspberry-pi/
├── logs/
│   ├── pid/                    # PID logger CSV/JSON
│   └── performance/            # Performance logger CSV/JSON
├── analysis_output/
│   ├── pid/
│   │   └── graphs/             # PID graphs (PNG)
│   └── performance/            # Performance reports (TXT)
└── scripts/                    # Utility scripts (this folder)
```

## 💡 Tips

### Workflow Efisien:

1. **Jalankan test** di web interface (http://localhost:5000/testing)
2. **Monitor performance** dengan `monitor_performance.py`
3. **Generate grafik** dengan `plot_all_pid_responses.py`
4. **Copy grafik** ke folder laporan
5. **Insert ke LaTeX**

### Automation:

Buat batch script untuk otomasi:

**Windows** (`analyze_all.bat`):
```batch
@echo off
echo Generating PID graphs...
python scripts/plot_all_pid_responses.py

echo Monitoring performance...
python scripts/monitor_performance.py -d 60

echo Done!
pause
```

**Linux/Mac** (`analyze_all.sh`):
```bash
#!/bin/bash
echo "Generating PID graphs..."
python scripts/plot_all_pid_responses.py

echo "Monitoring performance..."
python scripts/monitor_performance.py -d 60

echo "Done!"
```

## 🔧 Troubleshooting

### Error: Module not found
```bash
pip install pandas matplotlib psutil
```

### Error: Permission denied (Linux/Mac)
```bash
chmod +x scripts/*.py
```

### Error: File not found
Pastikan Anda menjalankan script dari folder `raspberry-pi/`:
```bash
cd raspberry-pi
python scripts/plot_pid_response.py ...
```

## 📚 Documentation

Untuk dokumentasi lengkap, lihat:
- `PID_GRAPH_GUIDE.md` - Panduan grafik PID
- `GUI_PERFORMANCE_ANALYSIS.md` - Analisis performa GUI
- `PERFORMANCE_TESTING.md` - Panduan performance testing

## 👨‍💻 Author

Muhammad Ridho Assidiqi  
Universitas Gadjah Mada
