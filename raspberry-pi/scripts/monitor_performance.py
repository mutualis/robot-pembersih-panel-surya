"""
Monitor Raspberry Pi Performance During Testing
Mengukur CPU, Memori, dan Suhu RPi, lalu MENYIMPAN data + ringkasan
(mean/median/min/max) untuk dipakai pada Bab 4.

Usage (di Raspberry Pi):
    # Pantau 5 menit saat sistem monitoring berjalan, beri label mode
    python3 scripts/monitor_performance.py -d 300 --label monitoring

    # Saat idle (sistem nyala tapi tanpa inferensi/aktuasi)
    python3 scripts/monitor_performance.py -d 120 --label idle

    # Saat siklus pembersihan berjalan
    python3 scripts/monitor_performance.py -d 180 --label cleaning

Output (folder analysis_output/performance/):
    sysres_<label>_<timestamp>.csv   -> data mentah per sampel
    sysres_<label>_<timestamp>.txt   -> ringkasan (mean/median/min/max), LaTeX-friendly

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada (Sekolah Vokasi, TRIK)
"""

import psutil
import time
import os
import csv
import statistics
from datetime import datetime


def get_cpu_temp():
    """Baca suhu CPU (khusus Raspberry Pi). Return float °C atau None."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            return float(f.read()) / 1000.0
    except Exception:
        return None


def _summary(values):
    """Statistik ringkas dari list angka (abaikan None)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return {
        'mean': round(statistics.mean(vals), 2),
        'median': round(statistics.median(vals), 2),
        'min': round(min(vals), 2),
        'max': round(max(vals), 2),
        'n': len(vals),
    }


def monitor_performance(duration=60, interval=1.0, label='operasi', outdir='analysis_output/performance'):
    """
    Pantau performa sistem dan simpan hasilnya.

    Args:
        duration: durasi total (detik). 0 = sampai Ctrl+C.
        interval: jeda antar sampel (detik).
        label: nama mode operasi (idle/monitoring/cleaning/...) untuk penamaan file.
        outdir: folder output.
    """
    os.makedirs(outdir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    base = os.path.join(outdir, f'sysres_{label}_{ts}')
    csv_path = base + '.csv'
    txt_path = base + '.txt'

    print("=" * 70)
    print("RASPBERRY PI SYSTEM RESOURCE MONITOR")
    print("=" * 70)
    print(f"Label mode : {label}")
    print(f"Durasi     : {duration if duration > 0 else 'manual (Ctrl+C)'} s | interval {interval} s")
    print(f"Output     : {csv_path}")
    print("Tekan Ctrl+C untuk berhenti lebih awal\n")

    # total RAM (MB) untuk konteks
    ram_total_mb = round(psutil.virtual_memory().total / 1024 / 1024, 1)

    samples = []  # (elapsed_s, cpu_pct, ram_pct, ram_used_mb, temp_c)
    start = time.time()

    try:
        while True:
            if duration > 0 and (time.time() - start) >= duration:
                break

            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            ram_pct = mem.percent
            ram_used_mb = round(mem.used / 1024 / 1024, 1)
            temp = get_cpu_temp()
            elapsed = round(time.time() - start, 1)

            samples.append((elapsed, cpu, ram_pct, ram_used_mb, temp))

            line = (f"\r[{time.strftime('%H:%M:%S')}] CPU {cpu:5.1f}% | "
                    f"RAM {ram_pct:5.1f}% ({ram_used_mb/1024:.2f}GB)")
            if temp is not None:
                line += f" | Suhu {temp:4.1f}C"
            print(line + "      ", end='', flush=True)

            # interval - 0.1 (sudah dipakai cpu_percent)
            sleep_left = interval - 0.1
            if sleep_left > 0:
                time.sleep(sleep_left)

    except KeyboardInterrupt:
        print("\n\nDihentikan oleh pengguna.")

    if not samples:
        print("\n[!] Tidak ada sampel terkumpul.")
        return

    # --- Simpan CSV mentah ---
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['elapsed_s', 'cpu_pct', 'ram_pct', 'ram_used_mb', 'temp_c'])
        for row in samples:
            w.writerow(row)

    # --- Ringkasan ---
    cpu_stat = _summary([s[1] for s in samples])
    rampct_stat = _summary([s[2] for s in samples])
    rammb_stat = _summary([s[3] for s in samples])
    temp_stat = _summary([s[4] for s in samples])

    lines = []
    lines.append("=" * 70)
    lines.append("RINGKASAN UTILISASI SUMBER DAYA SISTEM")
    lines.append("=" * 70)
    lines.append(f"Label mode      : {label}")
    lines.append(f"Jumlah sampel   : {len(samples)} (interval {interval} s)")
    lines.append(f"RAM total       : {ram_total_mb} MB ({ram_total_mb/1024:.2f} GB)")
    lines.append("")

    def fmt(name, st, unit):
        if not st:
            return f"{name:18s}: (tidak ada data)"
        return (f"{name:18s}: mean {st['mean']}{unit} | median {st['median']}{unit} | "
                f"min {st['min']}{unit} | max {st['max']}{unit}")

    lines.append(fmt("CPU", cpu_stat, "%"))
    lines.append(fmt("Memori (persen)", rampct_stat, "%"))
    lines.append(fmt("Memori (MB)", rammb_stat, " MB"))
    lines.append(fmt("Suhu CPU", temp_stat, " C"))
    lines.append("=" * 70)

    report = "\n".join(lines)
    print("\n" + report)

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(report + "\n")

    if temp_stat and temp_stat['max'] > 80:
        print("\n[!] PERINGATAN: suhu maksimum > 80C, pertimbangkan pendinginan.")

    print(f"\nTersimpan:\n  {csv_path}\n  {txt_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Monitor & simpan utilisasi sumber daya Raspberry Pi')
    parser.add_argument('-d', '--duration', type=int, default=60,
                        help='Durasi (detik). 0 = manual stop. Default 60.')
    parser.add_argument('-i', '--interval', type=float, default=1.0,
                        help='Interval antar sampel (detik). Default 1.0.')
    parser.add_argument('-l', '--label', type=str, default='operasi',
                        help='Label mode operasi (idle/monitoring/cleaning). Default operasi.')
    parser.add_argument('-o', '--outdir', type=str, default='analysis_output/performance',
                        help='Folder output.')
    args = parser.parse_args()

    monitor_performance(duration=args.duration, interval=args.interval,
                        label=args.label, outdir=args.outdir)


if __name__ == "__main__":
    main()
