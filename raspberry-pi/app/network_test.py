"""
Network Test Utilities — Pengujian Sistem Komunikasi Jaringan (Bab 4)
=====================================================================

Mengukur untuk Tabel tab:hasil_jaringan_ringkasan:
  - Latensi ping ke target tiap mode (WiFi AP/Client/Cloudflare)
  - Waktu muat (HTTP load) halaman dashboard
  - Uptime/downtime selama durasi pengujian (mis. 24 jam)

Hasil ditulis ke analysis_output/network/ sebagai TXT (siap baca + baris
LaTeX) dan CSV (data mentah) sehingga bisa langsung diunduh dari web.

Catatan: dijalankan di Raspberry Pi (Linux). Ada fallback untuk Windows (dev).
"""

import subprocess
import platform
import time
import statistics
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Callable

OUT_DIR = Path("analysis_output/network")

_IS_WIN = platform.system().lower().startswith("win")


def ping_once(host: str, timeout_s: float = 1.0) -> Optional[float]:
    """Satu kali ping. Mengembalikan RTT (ms) atau None bila gagal/timeout."""
    if not host:
        return None
    try:
        if _IS_WIN:
            cmd = ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), host]
        else:
            cmd = ["ping", "-c", "1", "-W", str(int(max(1, timeout_s))), host]
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout_s + 3)
        if out.returncode != 0:
            return None
        m = re.search(r"time[=<]\s*([\d.]+)\s*ms", out.stdout)
        return float(m.group(1)) if m else None
    except Exception:
        return None


def default_gateway() -> Optional[str]:
    """Deteksi IP gateway default (untuk merepresentasikan latensi link WiFi Client)."""
    try:
        if _IS_WIN:
            return None
        out = subprocess.run(["ip", "route"], capture_output=True, text=True, timeout=3)
        m = re.search(r"default via ([\d.]+)", out.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


class NetworkTester:
    """Pengukur latensi, beban HTTP, dan uptime untuk subsistem jaringan."""

    def __init__(self, targets: Dict[str, str]):
        # targets: {label: host/ip}
        self.targets = {k: v for k, v in (targets or {}).items() if v}
        OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------
    def latency_test(self, count: int = 30, interval: float = 0.2,
                     progress_cb: Optional[Callable[[int, int], None]] = None) -> Dict:
        results = {}
        total = max(1, len(self.targets)) * count
        done = 0
        for label, host in self.targets.items():
            rtts = []
            loss = 0
            for _ in range(count):
                r = ping_once(host)
                if r is None:
                    loss += 1
                else:
                    rtts.append(r)
                done += 1
                if progress_cb:
                    progress_cb(done, total)
                time.sleep(interval)
            results[label] = {
                "host": host,
                "sent": count,
                "received": len(rtts),
                "loss_pct": round(loss / count * 100, 1) if count else 0.0,
                "mean": round(statistics.mean(rtts), 2) if rtts else None,
                "min": round(min(rtts), 2) if rtts else None,
                "max": round(max(rtts), 2) if rtts else None,
                "stdev": round(statistics.stdev(rtts), 2) if len(rtts) > 1 else 0.0,
            }
        return results

    # ----------------------------------------------------------
    def http_load_test(self, urls: Dict[str, str], repeat: int = 5) -> Dict:
        out = {}
        for label, url in (urls or {}).items():
            if not url:
                continue
            times = []
            for _ in range(repeat):
                t0 = time.time()
                if self._http_get(url):
                    times.append((time.time() - t0) * 1000.0)
                time.sleep(0.3)
            out[label] = {
                "url": url,
                "load_ms": round(statistics.mean(times), 1) if times else None,
                "samples": len(times),
            }
        return out

    @staticmethod
    def _http_get(url: str, timeout: float = 10.0) -> bool:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "net-test"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read(4096)
                return True
        except Exception:
            return False

    # ----------------------------------------------------------
    def uptime_monitor(self, duration_sec: float, interval_sec: float = 60.0,
                       progress_cb: Optional[Callable[[int, int], None]] = None,
                       stop_flag: Optional[Callable[[], bool]] = None) -> Dict:
        per = {lbl: {"host": h, "checks": 0, "fails": 0}
               for lbl, h in self.targets.items()}
        start = time.time()
        deadline = start + duration_sec
        while time.time() < deadline:
            if stop_flag and stop_flag():
                break
            for lbl, h in self.targets.items():
                r = ping_once(h)
                per[lbl]["checks"] += 1
                if r is None:
                    per[lbl]["fails"] += 1
            if progress_cb:
                progress_cb(int(time.time() - start), int(duration_sec))
            # tidur sisa interval (cek stop tiap detik agar responsif)
            slept = 0.0
            while slept < interval_sec and time.time() < deadline:
                if stop_flag and stop_flag():
                    break
                time.sleep(min(1.0, interval_sec - slept))
                slept += 1.0

        result = {}
        for lbl, d in per.items():
            checks, fails = d["checks"], d["fails"]
            up = checks - fails
            result[lbl] = {
                "host": d["host"],
                "checks": checks,
                "fails": fails,
                "uptime_pct": round(up / checks * 100, 2) if checks else 0.0,
                "downtime_min": round(fails * interval_sec / 60.0, 1),
            }
        result["_meta"] = {
            "duration_sec": round(time.time() - start),
            "interval_sec": interval_sec,
        }
        return result

    # ----------------------------------------------------------
    def generate_report(self, latency: Optional[Dict] = None,
                        load: Optional[Dict] = None,
                        uptime: Optional[Dict] = None,
                        prefix: str = "network") -> Dict:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        txt_path = OUT_DIR / f"{prefix}_report_{ts}.txt"
        csv_path = OUT_DIR / f"{prefix}_data_{ts}.csv"

        L = ["=" * 64,
             "PENGUJIAN SISTEM KOMUNIKASI JARINGAN",
             "=" * 64,
             f"Timestamp : {ts}", ""]

        if uptime:
            meta = uptime.get("_meta", {})
            L += ["-" * 64,
                  "A. KONEKTIVITAS & STABILITAS",
                  f"   Durasi pemantauan : {meta.get('duration_sec', 0)} detik "
                  f"(interval {meta.get('interval_sec', 0)} s)",
                  "-" * 64,
                  f"{'Mode/Target':<24}{'Uptime%':>10}{'Downtime(m)':>14}{'Gagal/Cek':>12}"]
            for lbl, d in uptime.items():
                if lbl == "_meta":
                    continue
                L.append(f"{lbl[:24]:<24}{d['uptime_pct']:>10.2f}"
                         f"{d['downtime_min']:>14.1f}{(str(d['fails'])+'/'+str(d['checks'])):>12}")
            L.append("")

        if latency:
            L += ["-" * 64,
                  "B. LATENSI PING",
                  "-" * 64,
                  f"{'Mode/Target':<24}{'Mean(ms)':>10}{'Min':>8}{'Max':>8}{'Std':>8}{'Loss%':>8}"]
            for lbl, d in latency.items():
                mean = d['mean'] if d['mean'] is not None else 0
                mn = d['min'] if d['min'] is not None else 0
                mx = d['max'] if d['max'] is not None else 0
                L.append(f"{lbl[:24]:<24}{mean:>10.2f}{mn:>8.2f}{mx:>8.2f}"
                         f"{d['stdev']:>8.2f}{d['loss_pct']:>8.1f}")
            L.append("")

        if load:
            L += ["-" * 64,
                  "   WAKTU MUAT HALAMAN (HTTP GET)",
                  "-" * 64]
            for lbl, d in load.items():
                lm = d['load_ms']
                L.append(f"{lbl[:30]:<30}: {lm if lm is not None else '-'} ms")
            L.append("")

        L += ["-" * 64,
              "C. PENGARUH KE OPERASI INTI",
              "   (CPU, memori, waktu inferensi YOLO, std RPM PID)",
              "   -> lihat halaman Performance / file performance_report_*.txt",
              "=" * 64, ""]

        # Baris LaTeX siap tempel
        L += ["Baris LaTeX (tab:hasil_jaringan_ringkasan):"]
        if uptime:
            for lbl, d in uptime.items():
                if lbl == "_meta":
                    continue
                L.append(f"  Uptime {lbl}: {d['uptime_pct']:.2f}\\% | "
                         f"Downtime: {d['downtime_min']:.1f} menit")
        if latency:
            for lbl, d in latency.items():
                if d['mean'] is not None:
                    L.append(f"  Latensi {lbl}: {d['mean']:.2f} ms")
        L.append("=" * 64)

        txt_path.write_text("\n".join(L), encoding="utf-8")

        # CSV mentah
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["kategori", "mode_target", "metrik", "nilai"])
            if uptime:
                for lbl, d in uptime.items():
                    if lbl == "_meta":
                        continue
                    w.writerow(["uptime", lbl, "uptime_pct", d["uptime_pct"]])
                    w.writerow(["uptime", lbl, "downtime_min", d["downtime_min"]])
                    w.writerow(["uptime", lbl, "fails", d["fails"]])
                    w.writerow(["uptime", lbl, "checks", d["checks"]])
            if latency:
                for lbl, d in latency.items():
                    for k in ("mean", "min", "max", "stdev", "loss_pct"):
                        w.writerow(["latency", lbl, k, d[k]])
            if load:
                for lbl, d in load.items():
                    w.writerow(["http_load", lbl, "load_ms", d["load_ms"]])

        return {"txt": str(txt_path), "csv": str(csv_path)}
