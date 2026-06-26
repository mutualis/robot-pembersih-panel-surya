"""
Performance Logger for Two-Stage Detection System
Logs inference time, FPS, memory usage, and Raspberry Pi system metrics.

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import time
import psutil
import json
import csv
import os
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from collections import deque
import statistics


def _read_cpu_temperature() -> Optional[float]:
    """
    Baca suhu CPU dalam °C. Mencoba beberapa sumber secara berurutan agar
    tahan lintas-platform (Raspberry Pi, Linux umum, Windows dev).
    """
    # 1. psutil sensors (Linux): 'cpu_thermal' di Raspberry Pi
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for key in ("cpu_thermal", "coretemp", "k10temp", "acpitz"):
                if key in temps and temps[key]:
                    return round(temps[key][0].current, 1)
            # fallback: ambil sensor pertama yang ada
            for entries in temps.values():
                if entries:
                    return round(entries[0].current, 1)
    except (AttributeError, NotImplementedError, Exception):
        pass

    # 2. sysfs thermal zone (Raspberry Pi / Linux)
    try:
        zone = Path("/sys/class/thermal/thermal_zone0/temp")
        if zone.exists():
            milli = int(zone.read_text().strip())
            return round(milli / 1000.0, 1)
    except (ValueError, OSError):
        pass

    return None


def _read_throttled_state() -> Optional[Dict]:
    """
    Baca status throttling Raspberry Pi via `vcgencmd get_throttled`.
    Mengembalikan flag undervoltage & throttling (penting untuk validasi
    bahwa Pi 5 tidak ter-throttle saat menjalankan YOLO). None bila bukan RPi.
    """
    try:
        out = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if out.returncode != 0:
            return None
        # format: throttled=0x0
        raw = out.stdout.strip().split("=")[-1]
        val = int(raw, 16)
        return {
            "raw": raw,
            "undervoltage_now": bool(val & 0x1),
            "throttled_now": bool(val & 0x4),
            "undervoltage_occurred": bool(val & 0x10000),
            "throttled_occurred": bool(val & 0x40000),
        }
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired, Exception):
        return None


def _read_pi_model() -> Optional[str]:
    """Baca model board dari device-tree (Raspberry Pi)."""
    try:
        model = Path("/proc/device-tree/model")
        if model.exists():
            return model.read_text().strip().replace("\x00", "")
    except OSError:
        pass
    return None


def get_system_info() -> Dict:
    """
    Snapshot info sistem Raspberry Pi untuk halaman performance.

    Tidak bergantung pada PerformanceLogger — bisa dipanggil kapan saja.
    Mencakup: uptime, suhu CPU, RAM, CPU load/frekuensi, disk, throttling,
    model board, hostname. Semua field aman bila sumbernya tidak tersedia
    (mengembalikan None / 0) agar tetap jalan di Windows saat dev.
    """
    info: Dict = {}

    # Uptime sistem
    try:
        boot = psutil.boot_time()
        uptime_sec = max(0, int(time.time() - boot))
        info["uptime_sec"] = uptime_sec
        days, rem = divmod(uptime_sec, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        if days > 0:
            info["uptime_human"] = f"{days}h {hours}j {minutes}m {seconds}d"
        elif hours > 0:
            info["uptime_human"] = f"{hours}j {minutes}m {seconds}d"
        elif minutes > 0:
            info["uptime_human"] = f"{minutes}m {seconds}d"
        else:
            info["uptime_human"] = f"{seconds}d"
    except Exception:
        info["uptime_sec"] = 0
        info["uptime_human"] = "-"

    # CPU
    try:
        info["cpu_percent"] = round(psutil.cpu_percent(interval=0.1), 1)
        info["cpu_count"] = psutil.cpu_count(logical=True)
        freq = psutil.cpu_freq()
        info["cpu_freq_mhz"] = round(freq.current, 0) if freq else None
        load1, load5, load15 = (psutil.getloadavg()
                                if hasattr(psutil, "getloadavg") else (0, 0, 0))
        info["load_avg"] = [round(load1, 2), round(load5, 2), round(load15, 2)]
    except Exception:
        info["cpu_percent"] = 0
        info["cpu_count"] = 0
        info["cpu_freq_mhz"] = None
        info["load_avg"] = [0, 0, 0]

    # Memori
    try:
        vm = psutil.virtual_memory()
        info["mem_total_mb"] = round(vm.total / 1024 / 1024, 0)
        info["mem_used_mb"] = round(vm.used / 1024 / 1024, 0)
        info["mem_percent"] = round(vm.percent, 1)
    except Exception:
        info["mem_total_mb"] = 0
        info["mem_used_mb"] = 0
        info["mem_percent"] = 0

    # Disk (root)
    try:
        du = psutil.disk_usage("/")
        info["disk_total_gb"] = round(du.total / 1024 / 1024 / 1024, 1)
        info["disk_used_gb"] = round(du.used / 1024 / 1024 / 1024, 1)
        info["disk_percent"] = round(du.percent, 1)
    except Exception:
        info["disk_total_gb"] = 0
        info["disk_used_gb"] = 0
        info["disk_percent"] = 0

    # Suhu & throttling (khas Raspberry Pi)
    info["cpu_temp_c"] = _read_cpu_temperature()
    info["throttled"] = _read_throttled_state()

    # Identitas
    try:
        info["hostname"] = socket.gethostname()
    except Exception:
        info["hostname"] = "-"
    info["model"] = _read_pi_model()
    info["timestamp"] = datetime.now().isoformat()

    return info


class PerformanceLogger:
    """Log and analyze two-stage detection performance"""
    
    def __init__(self, log_dir: str = "logs/performance", buffer_size: int = 100):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.buffer_size = buffer_size
        self.metrics_buffer = deque(maxlen=buffer_size)
        
        # Real-time metrics
        self.total_detections = 0
        self.start_time = time.time()
        
        # Session info
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = self.log_dir / f"session_{self.session_id}.json"
        self.csv_file = self.log_dir / f"metrics_{self.session_id}.csv"
        
        # CSV dibuat LAZY — hanya saat deteksi pertama, supaya tidak menumpuk
        # file kosong (header saja) tiap kali aplikasi start tanpa ada deteksi.
        self._csv_initialized = False
        
        print(f"[PerformanceLogger] Session: {self.session_id}")
        print(f"[PerformanceLogger] Logs: {self.log_dir}")
    
    def _init_csv(self):
        """Buat file CSV + tulis header (dipanggil saat deteksi pertama)."""
        if self._csv_initialized:
            return
        with open(self.csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp',
                'detection_id',
                'stage1_time_ms',
                'stage2_time_ms',
                'total_time_ms',
                'fps',
                'panel_detected',
                'panel_confidence',
                'dirt_level',
                'dirt_confidence',
                'weighted_score',
                'memory_mb',
                'cpu_percent'
            ])
        self._csv_initialized = True
    
    def log_detection(
        self,
        stage1_time: float,
        stage2_time: float,
        panel_detected: bool,
        panel_confidence: float,
        dirt_level: str,
        dirt_confidence: float,
        weighted_score: float
    ) -> Dict:
        """
        Log a single detection event
        
        Args:
            stage1_time: Panel detection time (seconds)
            stage2_time: Dirt classification time (seconds)
            panel_detected: Whether panel was detected
            panel_confidence: Panel detection confidence
            dirt_level: Dirt classification result
            dirt_confidence: Dirt classification confidence
            weighted_score: Final weighted score
        
        Returns:
            Dictionary with logged metrics
        """
        self.total_detections += 1
        
        # Calculate metrics
        total_time = stage1_time + stage2_time
        fps = 1.0 / total_time if total_time > 0 else 0
        
        # System metrics
        memory_mb = psutil.Process().memory_info().rss / 1024 / 1024
        cpu_percent = psutil.cpu_percent(interval=0.1)
        
        # Create metrics dict
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'detection_id': self.total_detections,
            'stage1_time_ms': round(stage1_time * 1000, 2),
            'stage2_time_ms': round(stage2_time * 1000, 2),
            'total_time_ms': round(total_time * 1000, 2),
            'fps': round(fps, 2),
            'panel_detected': panel_detected,
            'panel_confidence': round(panel_confidence, 4),
            'dirt_level': dirt_level,
            'dirt_confidence': round(dirt_confidence, 4),
            'weighted_score': round(weighted_score, 2),
            'memory_mb': round(memory_mb, 2),
            'cpu_percent': round(cpu_percent, 2)
        }
        
        # Add to buffer
        self.metrics_buffer.append(metrics)
        
        # Write to CSV (buat file + header saat deteksi pertama)
        self._init_csv()
        with open(self.csv_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                metrics['timestamp'],
                metrics['detection_id'],
                metrics['stage1_time_ms'],
                metrics['stage2_time_ms'],
                metrics['total_time_ms'],
                metrics['fps'],
                metrics['panel_detected'],
                metrics['panel_confidence'],
                metrics['dirt_level'],
                metrics['dirt_confidence'],
                metrics['weighted_score'],
                metrics['memory_mb'],
                metrics['cpu_percent']
            ])
        
        return metrics
    
    def get_realtime_stats(self) -> Dict:
        """Get real-time statistics from buffer"""
        if not self.metrics_buffer:
            return {
                'total_detections': 0,
                'avg_fps': 0,
                'avg_total_time_ms': 0,
                'avg_stage1_time_ms': 0,
                'avg_stage2_time_ms': 0,
                'avg_memory_mb': 0,
                'avg_cpu_percent': 0,
                # Durasi sesi logging selalu dikirim (sejak logger dibuat),
                # walau belum ada deteksi — agar timer di web tidak beku.
                'session_start': self.start_time,
                'session_duration_sec': round(time.time() - self.start_time, 2),
                'system': get_system_info(),
            }
        
        # Calculate averages
        fps_values = [m['fps'] for m in self.metrics_buffer]
        total_time_values = [m['total_time_ms'] for m in self.metrics_buffer]
        stage1_values = [m['stage1_time_ms'] for m in self.metrics_buffer]
        stage2_values = [m['stage2_time_ms'] for m in self.metrics_buffer]
        memory_values = [m['memory_mb'] for m in self.metrics_buffer]
        cpu_values = [m['cpu_percent'] for m in self.metrics_buffer]
        
        return {
            'total_detections': self.total_detections,
            'buffer_size': len(self.metrics_buffer),
            'avg_fps': round(statistics.mean(fps_values), 2),
            'min_fps': round(min(fps_values), 2),
            'max_fps': round(max(fps_values), 2),
            'avg_total_time_ms': round(statistics.mean(total_time_values), 2),
            'min_total_time_ms': round(min(total_time_values), 2),
            'max_total_time_ms': round(max(total_time_values), 2),
            # Stage 1 — nilai NYATA (bukan estimasi proporsi di frontend)
            'avg_stage1_time_ms': round(statistics.mean(stage1_values), 2),
            'min_stage1_time_ms': round(min(stage1_values), 2),
            'max_stage1_time_ms': round(max(stage1_values), 2),
            'median_stage1_time_ms': round(statistics.median(stage1_values), 2),
            # Stage 2 — nilai NYATA
            'avg_stage2_time_ms': round(statistics.mean(stage2_values), 2),
            'min_stage2_time_ms': round(min(stage2_values), 2),
            'max_stage2_time_ms': round(max(stage2_values), 2),
            'median_stage2_time_ms': round(statistics.median(stage2_values), 2),
            'median_total_time_ms': round(statistics.median(total_time_values), 2),
            'avg_memory_mb': round(statistics.mean(memory_values), 2),
            'avg_cpu_percent': round(statistics.mean(cpu_values), 2),
            'session_start': self.start_time,
            'session_duration_sec': round(time.time() - self.start_time, 2),
            # Info sistem Raspberry Pi (uptime, suhu, RAM, throttling, dst.)
            'system': get_system_info(),
        }
    
    def generate_summary_report(self) -> Dict:
        """Generate comprehensive summary report"""
        if not self.metrics_buffer:
            return {'error': 'No data collected'}
        
        # Read all data from CSV
        all_metrics = []
        with open(self.csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                all_metrics.append({
                    'stage1_time_ms': float(row['stage1_time_ms']),
                    'stage2_time_ms': float(row['stage2_time_ms']),
                    'total_time_ms': float(row['total_time_ms']),
                    'fps': float(row['fps']),
                    'panel_detected': row['panel_detected'] == 'True',
                    'dirt_level': row['dirt_level'],
                    'memory_mb': float(row['memory_mb']),
                    'cpu_percent': float(row['cpu_percent'])
                })
        
        if not all_metrics:
            return {'error': 'No data in CSV'}
        
        # Calculate statistics
        total_times = [m['total_time_ms'] for m in all_metrics]
        stage1_times = [m['stage1_time_ms'] for m in all_metrics]
        stage2_times = [m['stage2_time_ms'] for m in all_metrics]
        fps_values = [m['fps'] for m in all_metrics]
        memory_values = [m['memory_mb'] for m in all_metrics]
        cpu_values = [m['cpu_percent'] for m in all_metrics]
        
        # Dirt level distribution
        dirt_counts = {}
        for m in all_metrics:
            level = m['dirt_level']
            dirt_counts[level] = dirt_counts.get(level, 0) + 1
        
        # Panel detection rate
        panel_detected_count = sum(1 for m in all_metrics if m['panel_detected'])
        panel_detection_rate = panel_detected_count / len(all_metrics) * 100
        
        report = {
            'session_id': self.session_id,
            'total_detections': len(all_metrics),
            'session_duration_sec': round(time.time() - self.start_time, 2),
            
            # Timing statistics
            'inference_time': {
                'total_ms': {
                    'mean': round(statistics.mean(total_times), 2),
                    'median': round(statistics.median(total_times), 2),
                    'min': round(min(total_times), 2),
                    'max': round(max(total_times), 2),
                    'stdev': round(statistics.stdev(total_times), 2) if len(total_times) > 1 else 0
                },
                'stage1_ms': {
                    'mean': round(statistics.mean(stage1_times), 2),
                    'median': round(statistics.median(stage1_times), 2),
                    'min': round(min(stage1_times), 2),
                    'max': round(max(stage1_times), 2)
                },
                'stage2_ms': {
                    'mean': round(statistics.mean(stage2_times), 2),
                    'median': round(statistics.median(stage2_times), 2),
                    'min': round(min(stage2_times), 2),
                    'max': round(max(stage2_times), 2)
                }
            },
            
            # FPS statistics
            'fps': {
                'mean': round(statistics.mean(fps_values), 2),
                'median': round(statistics.median(fps_values), 2),
                'min': round(min(fps_values), 2),
                'max': round(max(fps_values), 2)
            },
            
            # System resources
            'resources': {
                'memory_mb': {
                    'mean': round(statistics.mean(memory_values), 2),
                    'max': round(max(memory_values), 2)
                },
                'cpu_percent': {
                    'mean': round(statistics.mean(cpu_values), 2),
                    'max': round(max(cpu_values), 2)
                }
            },
            
            # Detection statistics
            'detection': {
                'panel_detection_rate': round(panel_detection_rate, 2),
                'dirt_level_distribution': dirt_counts
            },
            
            # Info sistem Raspberry Pi (snapshot saat report dibuat)
            'system': get_system_info(),
            
            # Files
            'files': {
                'csv': str(self.csv_file),
                'json': str(self.session_file)
            }
        }
        
        # Save report to JSON
        with open(self.session_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n[PerformanceLogger] Summary Report Generated:")
        print(f"  Total Detections: {report['total_detections']}")
        print(f"  Avg Inference Time: {report['inference_time']['total_ms']['mean']} ms")
        print(f"  Avg FPS: {report['fps']['mean']}")
        print(f"  Avg Memory: {report['resources']['memory_mb']['mean']} MB")
        print(f"  Report saved: {self.session_file}")
        
        return report
    
    def export_for_bab4(self, output_dir: str = "analysis_output/performance"):
        """Export formatted data for analysis"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        report = self.generate_summary_report()
        
        if 'error' in report:
            print(f"[PerformanceLogger] Cannot export: {report['error']}")
            return
        
        # Generate LaTeX-friendly text file
        latex_file = output_path / f"performance_report_{self.session_id}.txt"
        
        with open(latex_file, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("TWO-STAGE DETECTION PERFORMANCE REPORT\n")
            f.write(f"Session: {self.session_id}\n")
            f.write("=" * 70 + "\n\n")
            
            f.write("INFERENCE TIME (milliseconds)\n")
            f.write("-" * 70 + "\n")
            f.write(f"Total Pipeline:\n")
            f.write(f"  Mean:   {report['inference_time']['total_ms']['mean']} ms\n")
            f.write(f"  Median: {report['inference_time']['total_ms']['median']} ms\n")
            f.write(f"  Min:    {report['inference_time']['total_ms']['min']} ms\n")
            f.write(f"  Max:    {report['inference_time']['total_ms']['max']} ms\n")
            f.write(f"  StdDev: {report['inference_time']['total_ms']['stdev']} ms\n\n")
            
            f.write(f"Stage 1 (Panel Detection):\n")
            f.write(f"  Mean:   {report['inference_time']['stage1_ms']['mean']} ms\n")
            f.write(f"  Median: {report['inference_time']['stage1_ms']['median']} ms\n")
            f.write(f"  Min:    {report['inference_time']['stage1_ms']['min']} ms\n")
            f.write(f"  Max:    {report['inference_time']['stage1_ms']['max']} ms\n\n")
            
            f.write(f"Stage 2 (Dirt Classification):\n")
            f.write(f"  Mean:   {report['inference_time']['stage2_ms']['mean']} ms\n")
            f.write(f"  Median: {report['inference_time']['stage2_ms']['median']} ms\n")
            f.write(f"  Min:    {report['inference_time']['stage2_ms']['min']} ms\n")
            f.write(f"  Max:    {report['inference_time']['stage2_ms']['max']} ms\n\n")
            
            f.write("FRAMES PER SECOND (FPS)\n")
            f.write("-" * 70 + "\n")
            f.write(f"  Mean:   {report['fps']['mean']} FPS\n")
            f.write(f"  Median: {report['fps']['median']} FPS\n")
            f.write(f"  Min:    {report['fps']['min']} FPS\n")
            f.write(f"  Max:    {report['fps']['max']} FPS\n\n")
            
            f.write("SYSTEM RESOURCES\n")
            f.write("-" * 70 + "\n")
            f.write(f"Memory Usage:\n")
            f.write(f"  Mean: {report['resources']['memory_mb']['mean']} MB\n")
            f.write(f"  Max:  {report['resources']['memory_mb']['max']} MB\n\n")
            f.write(f"CPU Usage:\n")
            f.write(f"  Mean: {report['resources']['cpu_percent']['mean']}%\n")
            f.write(f"  Max:  {report['resources']['cpu_percent']['max']}%\n\n")
            
            f.write("DETECTION STATISTICS\n")
            f.write("-" * 70 + "\n")
            f.write(f"Total Detections: {report['total_detections']}\n")
            f.write(f"Panel Detection Rate: {report['detection']['panel_detection_rate']}%\n")
            f.write(f"Session Duration: {report['session_duration_sec']} seconds\n\n")
            
            f.write("DIRT LEVEL DISTRIBUTION\n")
            f.write("-" * 70 + "\n")
            for level, count in report['detection']['dirt_level_distribution'].items():
                percentage = count / report['total_detections'] * 100
                f.write(f"  {level}: {count} ({percentage:.1f}%)\n")
            
            # Info sistem Raspberry Pi (snapshot kondisi board)
            sysinfo = report.get('system', {})
            if sysinfo:
                f.write("\nRASPBERRY PI SYSTEM INFO (snapshot)\n")
                f.write("-" * 70 + "\n")
                f.write(f"  Model:        {sysinfo.get('model') or '-'}\n")
                f.write(f"  Hostname:     {sysinfo.get('hostname') or '-'}\n")
                f.write(f"  Uptime:       {sysinfo.get('uptime_human') or '-'}\n")
                temp = sysinfo.get('cpu_temp_c')
                f.write(f"  CPU Temp:     {temp if temp is not None else '-'} C\n")
                f.write(f"  CPU Usage:    {sysinfo.get('cpu_percent', 0)}%\n")
                freq = sysinfo.get('cpu_freq_mhz')
                f.write(f"  CPU Freq:     {freq if freq is not None else '-'} MHz\n")
                f.write(f"  CPU Cores:    {sysinfo.get('cpu_count', 0)}\n")
                la = sysinfo.get('load_avg', [0, 0, 0])
                f.write(f"  Load Avg:     {la[0]} / {la[1]} / {la[2]} (1/5/15 min)\n")
                f.write(f"  RAM Used:     {sysinfo.get('mem_used_mb', 0)} / "
                        f"{sysinfo.get('mem_total_mb', 0)} MB "
                        f"({sysinfo.get('mem_percent', 0)}%)\n")
                f.write(f"  Disk Used:    {sysinfo.get('disk_used_gb', 0)} / "
                        f"{sysinfo.get('disk_total_gb', 0)} GB "
                        f"({sysinfo.get('disk_percent', 0)}%)\n")
                thr = sysinfo.get('throttled')
                if thr:
                    f.write(f"  Throttled:    raw={thr.get('raw')} | "
                            f"undervolt_now={thr.get('undervoltage_now')} | "
                            f"throttled_now={thr.get('throttled_now')} | "
                            f"undervolt_ever={thr.get('undervoltage_occurred')} | "
                            f"throttled_ever={thr.get('throttled_occurred')}\n")
                else:
                    f.write(f"  Throttled:    - (vcgencmd tidak tersedia)\n")
            
            f.write("\n" + "=" * 70 + "\n")
            f.write("DATA FILES\n")
            f.write(f"  CSV:  {report['files']['csv']}\n")
            f.write(f"  JSON: {report['files']['json']}\n")
            f.write("=" * 70 + "\n")
        
        print(f"\n[PerformanceLogger] Export Complete:")
        print(f"  LaTeX Report: {latex_file}")
        print(f"  CSV Data: {self.csv_file}")
        print(f"  JSON Report: {self.session_file}")
        
        return {
            'latex_file': str(latex_file),
            'csv_file': str(self.csv_file),
            'json_file': str(self.session_file)
        }


# ============================================================================
# BENCHMARK INFERENSI (dipakai bersama oleh CLI benchmark_inference.py & web)
# ============================================================================

def _bench_stats(values: List[float]) -> Optional[Dict]:
    """Statistik deskriptif (ms) dari list nilai."""
    if not values:
        return None
    return {
        "mean": round(statistics.mean(values), 2),
        "median": round(statistics.median(values), 2),
        "stdev": round(statistics.stdev(values), 2) if len(values) > 1 else 0.0,
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "count": len(values),
    }


def run_inference_benchmark(detector, frame, runs: int = 100, warmup: int = 5,
                            source: str = "unknown",
                            output_dir: str = "analysis_output/performance",
                            progress_cb=None) -> Dict:
    """
    Jalankan benchmark inferensi two-stage dan tulis hasil ke file.

    Dipakai oleh CLI (benchmark_inference.py) maupun endpoint web supaya logika
    pengukuran identik. Mengembalikan dict ringkasan + path file hasil.

    Args:
        detector: instance TwoStageDetector (sudah load model).
        frame: citra (numpy array) untuk diinferensi berulang.
        runs: jumlah iterasi terukur.
        warmup: iterasi pemanasan (tidak dihitung).
        source: deskripsi sumber citra (untuk laporan).
        output_dir: folder output file hasil.
        progress_cb: callable(done:int, total:int) opsional untuk progress.
    """
    # Warmup
    for _ in range(max(0, warmup)):
        detector.detect(frame)

    stage1_times, stage2_times, total_times = [], [], []
    for i in range(runs):
        result = detector.detect(frame) or {}
        s1 = result.get("stage1_time_ms")
        s2 = result.get("stage2_time_ms")
        tot = result.get("total_time_ms")
        if s1 is None or tot is None:
            t0 = time.perf_counter()
            detector.detect(frame)
            tot = (time.perf_counter() - t0) * 1000.0
            s1 = tot
            s2 = 0.0
        stage1_times.append(s1)
        stage2_times.append(s2 if s2 is not None else 0.0)
        total_times.append(tot)
        if progress_cb and ((i + 1) % 5 == 0 or i + 1 == runs):
            try:
                progress_cb(i + 1, runs)
            except Exception:
                pass

    s1_stat = _bench_stats(stage1_times)
    s2_nonzero = [t for t in stage2_times if t > 0]
    s2_stat = _bench_stats(s2_nonzero) or _bench_stats(stage2_times)
    tot_stat = _bench_stats(total_times)
    mean_total = tot_stat["mean"] if tot_stat else 0
    fps = round(1000.0 / mean_total, 2) if mean_total > 0 else 0

    sysinfo = get_system_info()

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    payload = {
        "timestamp": datetime.now().isoformat(),
        "device": sysinfo.get("model") or "Raspberry Pi (model tidak terbaca)",
        "runs": runs,
        "warmup": warmup,
        "image_source": source,
        "stage1_ms": s1_stat,
        "stage2_ms": s2_stat,
        "total_ms": tot_stat,
        "fps_mean": fps,
        # Data MENTAH per-iterasi (bukti pengukuran) — dipakai juga untuk CSV.
        "raw": {
            "stage1_ms": [round(t, 3) for t in stage1_times],
            "stage2_ms": [round(t, 3) for t in stage2_times],
            "total_ms": [round(t, 3) for t in total_times],
        },
        "system": sysinfo,
    }

    json_file = out_dir / f"inference_benchmark_{ts}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    # CSV data mentah per-iterasi (bukti pengukuran, mudah dibuka di Excel/LaTeX)
    csv_file = out_dir / f"inference_benchmark_{ts}.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["iterasi", "stage1_ms", "stage2_ms", "total_ms", "fps"])
        for i in range(len(total_times)):
            tot_i = total_times[i]
            fps_i = round(1000.0 / tot_i, 2) if tot_i > 0 else 0
            w.writerow([
                i + 1,
                round(stage1_times[i], 3),
                round(stage2_times[i], 3),
                round(tot_i, 3),
                fps_i,
            ])

    txt_file = out_dir / f"inference_benchmark_{ts}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("BENCHMARK INFERENSI YOLOv11 TWO-STAGE — RASPBERRY PI 5\n")
        f.write(f"Waktu      : {payload['timestamp']}\n")
        f.write(f"Device     : {payload['device']}\n")
        f.write(f"Iterasi    : {runs} (warmup {warmup})\n")
        f.write(f"Sumber     : {source}\n")
        f.write("=" * 70 + "\n\n")

        def _w_block(label, st, unit="ms"):
            f.write(f"{label}\n")
            f.write("-" * 70 + "\n")
            if st:
                f.write(f"  Mean   : {st['mean']} {unit}\n")
                f.write(f"  Median : {st['median']} {unit}\n")
                f.write(f"  StdDev : {st['stdev']} {unit}\n")
                f.write(f"  Min    : {st['min']} {unit}\n")
                f.write(f"  Max    : {st['max']} {unit}\n")
            else:
                f.write("  (tidak ada data)\n")
            f.write("\n")

        _w_block("STAGE 1 — DETEKSI PANEL", s1_stat)
        _w_block("STAGE 2 — KLASIFIKASI KEKOTORAN", s2_stat)
        _w_block("TOTAL PIPELINE", tot_stat)
        f.write(f"FPS (rata-rata) : {fps}\n\n")

        f.write("RINGKASAN KECEPATAN INFERENSI (Raspberry Pi 5)\n")
        f.write("-" * 70 + "\n")
        if s1_stat:
            f.write(f"  Stage 1 (deteksi panel)   : {s1_stat['mean']} ms/frame\n")
        if s2_stat:
            f.write(f"  Stage 2 (klasifikasi)     : {s2_stat['mean']} ms/frame\n")
        if tot_stat:
            f.write(f"  Total pipeline            : {tot_stat['mean']} ms/frame "
                    f"({fps} FPS)\n")
        f.write("\n")

        if sysinfo:
            f.write("KONDISI SISTEM SAAT BENCHMARK\n")
            f.write("-" * 70 + "\n")
            f.write(f"  Suhu CPU   : {sysinfo.get('cpu_temp_c', 'N/A')} C\n")
            f.write(f"  CPU usage  : {sysinfo.get('cpu_percent', 0)}%\n")
            f.write(f"  RAM        : {sysinfo.get('mem_used_mb', 0)} / "
                    f"{sysinfo.get('mem_total_mb', 0)} MB\n")
            thr = sysinfo.get("throttled")
            if thr:
                f.write(f"  Throttled  : now={thr.get('throttled_now')} "
                        f"undervolt={thr.get('undervoltage_now')}\n")
        f.write("=" * 70 + "\n")

    payload["files"] = {"txt": str(txt_file), "json": str(json_file), "csv": str(csv_file)}
    return payload
