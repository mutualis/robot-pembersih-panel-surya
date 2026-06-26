# PID Data Logger - Complete Documentation

## 🚀 Quick Start

### 1. Start Web Server
```bash
cd raspberry-pi
python run_dev.py
```

### 2. Open Testing Page
Browser: **http://localhost:5000/testing** → Scroll to "PID Data Logger"

### 3. Run Test
1. Select setpoint: **30 RPM** or **45 RPM**
2. Select condition: **Tanpa Beban** / **Dengan Beban** / **Siklus Pembersihan**
3. Click **"Mulai Logging"**
4. Run motor wiper test (ESP32 Hardware section)
5. Wait 10-15 seconds
6. Click **"Berhenti"**
7. View results in "HASIL ANALISIS RESPONS TRANSIEN" panel

### 4. Results Display
Results appear automatically in the panel:
- **Rise Time (tr)**: Time to reach 10%-90% of setpoint
- **Overshoot**: Percentage overshoot
- **Settling Time (ts)**: Time to settle within ±2%
- **Steady-State Error (ess)**: Average error at steady state
- **Statistics**: Mean, Std Dev, Min, Max RPM

### 5. Export (Optional)
Click **"Ekspor Data"** to generate files for backup/analysis.

## 📊 Features

### Real-Time Monitoring
- **Chart**: RPM vs TIME with setpoint line
- **Status**: Current RPM, data points, elapsed time
- **Update Rate**: Every 200ms (5 Hz)

### Automatic Analysis
- Rise time calculation (10% to 90%)
- Overshoot detection
- Settling time (±2% tolerance)
- Steady-state error (last 20% of data)
- Statistical analysis (mean, std dev, min, max)

### Results Display
- **Always visible** panel with parameter values
- **No export needed** to see results
- **Direct copy** to LaTeX tables
- **Auto-scroll** to results after test

## 📁 Output Files (Optional Export)

### Locations:
```
raspberry-pi/
├── logs/pid/                    # Raw data
│   ├── *.csv                    # Timestamp, RPM, error, PWM
│   └── *.json                   # Full report with analysis
└── analysis_output/pid/         # LaTeX-friendly reports
    └── *.txt                    # Parameters for Bab 4
```

### CSV Format:
```csv
timestamp,elapsed_time,setpoint,rpm_actual,error,pwm
2026-04-13T10:30:00.000,0.0,30,0.00,30.00,0
2026-04-13T10:30:00.200,0.2,30,5.23,24.77,45
```

### TXT Format (LaTeX-friendly):
```
TRANSIENT RESPONSE PARAMETERS
Rise Time (tr):           1.234 seconds
Overshoot:                5.67%
Settling Time (ts):       2.345 seconds
Steady-State Error (ess): 0.89 RPM

STATISTICS
Mean RPM:     29.11 RPM
Std Dev:      1.23 RPM
```

## 🎯 Tests for Bab 4

### Required Tests:
1. **30 RPM Tanpa Beban** - Step response without load
2. **30 RPM Dengan Beban** - Step response with panel contact
3. **45 RPM Tanpa Beban** - Step response without load
4. **45 RPM Dengan Beban** - Step response with panel contact
5. **Siklus Pembersihan** - Full cleaning cycle @ 45 RPM

### Workflow:
```
For each test:
1. Setup parameters
2. Start logging
3. Run motor
4. Wait 10-15s
5. Stop logging
6. View results in panel ← Copy values here!
7. (Optional) Export for backup
```

## 📋 Copy to LaTeX

### From Results Panel → Tabel 4.X:
```latex
\begin{table}[H]
\centering
\caption{Parameter Respons PID pada \textit{Setpoint} 30 RPM}
\begin{tabular}{|l|c|}
\hline
\textit{Rise time} ($t_r$) & 1.234 s \\      % ← From panel
\textit{Overshoot} & 5.67 \% \\              % ← From panel
\textit{Settling time} ($t_s$) & 2.345 s \\  % ← From panel
\textit{Steady-state error} ($e_{ss}$) & 0.89 RPM \\ % ← From panel
\hline
\end{tabular}
\end{table}
```

### Generate Graphs:
```bash
# From CSV files (optional, for publication-quality graphs)
python scripts/plot_pid_response.py logs/pid/pid_step_response_30rpm_*.csv
python scripts/plot_all_pid_responses.py  # Batch process all
```

## ⚙️ Technical Details

### Backend: `app/pid_logger.py`
- PIDLogger class with buffer management
- Transient response calculation algorithms
- Export to CSV/JSON/TXT formats

### API Endpoints: `web/server.py`
- `POST /api/pid/start` - Start session
- `POST /api/pid/log` - Log data point
- `POST /api/pid/stop` - Stop and analyze
- `GET /api/pid/status` - Get status
- `GET /api/pid/data` - Get buffer
- `POST /api/pid/export` - Export files

### Frontend: `web/templates/testing.html`
- Chart.js for real-time graphing
- Auto-polling ESP32 encoder (200ms)
- Results panel with parameter display
- Export functionality

### Data Flow:
```
ESP32 Encoder → Serial → Raspberry Pi
                           ↓
                    PID Logger (backend)
                           ↓
                    Web UI (frontend)
                           ↓
                    Results Panel ← View here!
```

## 💡 Tips

### For Best Results:
1. **Calibrate encoder** before testing
2. **Wait for stability** (minimum 10 seconds)
3. **Repeat 3x** for each condition, take average
4. **Note conditions** (temperature, load, etc.)

### Troubleshooting:
- **RPM = 0**: Check encoder connection, test encoder first
- **Chart not updating**: Refresh page (F5), check ESP32 connection
- **No results**: Ensure logging ran for at least 5 seconds
- **Export fails**: Check directory permissions

## 📚 References

- **Backend Code**: `app/pid_logger.py`
- **API Code**: `web/server.py` (lines 500-600)
- **Frontend Code**: `web/templates/testing.html`
- **Scripts**: `scripts/plot_pid_response.py`, `scripts/plot_all_pid_responses.py`
- **Laporan**: `Laporan PA/chapters/bab4.tex` (Section 4.4)

---

**Author**: Muhammad Ridho Assidiqi  
**Institution**: Universitas Gadjah Mada
