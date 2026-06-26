"""
Cleaning Session Logger — Solar Panel Cleaning Robot

Mencatat setiap siklus pembersihan end-to-end secara terstruktur: level
kekotoran, score sebelum & sesudah, penurunan score, jumlah percobaan, durasi
per tahap, dan status keberhasilan. Data ini melengkapi laporan pengujian
sistem terintegrasi (skenario pembersihan, verifikasi otomatis & efektivitas,
serta waktu siklus end-to-end).

Tiap sesi disimpan ke CSV (append) dan dipertahankan di memori (recent) untuk
ditampilkan & diunduh dari halaman Report. Aman untuk operasi produksi:
ringan, tidak memblokir, dan tidak mengganggu loop monitoring.

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import csv
import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# Pemetaan score → label level (konsisten dengan threshold sistem)
def score_to_level(score: float) -> str:
    if score < 70:
        return "bersih"
    if score < 170:
        return "ringan"
    if score < 270:
        return "sedang"
    return "berat"


def time_of_day(dt: Optional[datetime] = None) -> str:
    """Label waktu pengujian (pagi/siang/sore/malam) dari jam lokal.

    Membantu analisis konsistensi deteksi terhadap kondisi pencahayaan tanpa
    perlu input manual operator.
    """
    h = (dt or datetime.now()).hour
    if 5 <= h < 11:
        return "pagi"
    if 11 <= h < 15:
        return "siang"
    if 15 <= h < 18:
        return "sore"
    return "malam"


class CleaningSessionLogger:
    """Pencatat siklus pembersihan untuk laporan pengujian terintegrasi."""

    CSV_HEADER = [
        "session_id", "timestamp", "time_of_day", "level", "score_before",
        "score_after", "score_drop_pct", "attempts", "max_attempts", "success",
        "detect_time_s", "cleaning_time_s", "verify_time_s", "total_time_s",
    ]

    def __init__(self, log_dir: str = "logs/cleaning", recent_size: int = 200):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.csv_file = self.log_dir / "cleaning_sessions.csv"

        self._lock = threading.Lock()
        self._recent: deque = deque(maxlen=recent_size)
        self._active: Optional[Dict] = None  # sesi yang sedang berjalan

        # Muat ulang riwayat dari CSV (agar tabel tidak kosong setelah restart)
        self._load_existing()

    # ------------------------------------------------------------------
    def _load_existing(self):
        if not self.csv_file.exists():
            return
        try:
            with open(self.csv_file, "r", newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    self._recent.append(row)
        except Exception as e:
            print(f"[CleaningLogger] Gagal memuat riwayat: {e}")

    def _ensure_csv(self):
        if not self.csv_file.exists():
            with open(self.csv_file, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(self.CSV_HEADER)

    # ------------------------------------------------------------------
    # API dipanggil controller
    # ------------------------------------------------------------------
    def start_session(self, score_before: float, level: Optional[str] = None,
                      detect_time_s: float = 0.0) -> str:
        """Mulai mencatat satu siklus pembersihan. Mengembalikan session_id."""
        with self._lock:
            sid = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._active = {
                "session_id": sid,
                "start_ts": time.time(),
                "timestamp": datetime.now().isoformat(),
                "level": level or score_to_level(score_before),
                "score_before": round(float(score_before), 2),
                "score_after": None,
                "attempts": 0,
                "detect_time_s": round(float(detect_time_s), 2),
                "cleaning_time_s": 0.0,    # akumulasi durasi aktuasi ESP32
                "verify_time_s": 0.0,
                "_verify_start": None,
            }
            return sid

    def record_attempt(self):
        """Tandai satu percobaan pembersihan dimulai."""
        with self._lock:
            if self._active:
                self._active["attempts"] += 1

    def record_cleaning_duration(self, duration_ms: float):
        """Akumulasi durasi aktuasi (dari field 'duration' ESP32, ms)."""
        with self._lock:
            if self._active:
                self._active["cleaning_time_s"] += round(duration_ms / 1000.0, 2)

    def mark_verify_start(self):
        """Deprecated: dipertahankan untuk kompatibilitas. Gunakan add_verify_time()."""
        # Tidak melakukan apa-apa; durasi verifikasi kini diakumulasi via add_verify_time().
        return

    def add_verify_time(self, seconds: float):
        """Akumulasi durasi deteksi pada fase verifikasi (per percobaan)."""
        with self._lock:
            if self._active:
                self._active["verify_time_s"] = round(
                    self._active.get("verify_time_s", 0.0) + float(seconds), 2)

    def finish_session(self, score_after: float, success: bool,
                       max_attempts: int = 5) -> Optional[Dict]:
        """Selesaikan sesi, hitung metrik, simpan ke CSV + memori."""
        with self._lock:
            if not self._active:
                return None
            a = self._active
            self._active = None

        now = time.time()
        score_before = a["score_before"]
        score_after = round(float(score_after), 2)
        drop_pct = 0.0
        if score_before > 0:
            drop_pct = round((score_before - score_after) / score_before * 100.0, 1)
        verify_time = round(a.get("verify_time_s", 0.0), 2)
        total_time = round(now - a["start_ts"], 2)

        record = {
            "session_id": a["session_id"],
            "timestamp": a["timestamp"],
            "time_of_day": time_of_day(),
            "level": a["level"],
            "score_before": score_before,
            "score_after": score_after,
            "score_drop_pct": drop_pct,
            "attempts": a["attempts"],
            "max_attempts": max_attempts,
            "success": "Ya" if success else "Tidak",
            "detect_time_s": a["detect_time_s"],
            "cleaning_time_s": round(a["cleaning_time_s"], 2),
            "verify_time_s": verify_time,
            "total_time_s": total_time,
        }

        with self._lock:
            self._recent.append(record)
            try:
                self._ensure_csv()
                with open(self.csv_file, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([record[k] for k in self.CSV_HEADER])
            except Exception as e:
                print(f"[CleaningLogger] Gagal tulis CSV: {e}")

        return record

    # ------------------------------------------------------------------
    # API dipanggil web
    # ------------------------------------------------------------------
    def get_sessions(self) -> List[Dict]:
        with self._lock:
            return list(self._recent)

    def get_summary(self) -> Dict:
        """Ringkasan agregat per level + keseluruhan (untuk halaman & ekspor)."""
        with self._lock:
            rows = list(self._recent)

        def _num(v, cast=float, default=0.0):
            try:
                return cast(v)
            except (ValueError, TypeError):
                return default

        per_level: Dict[str, Dict] = {}
        per_time: Dict[str, Dict] = {}
        total_success = 0
        for r in rows:
            lvl = r.get("level") or "?"
            d = per_level.setdefault(lvl, {
                "count": 0, "success": 0, "drop_sum": 0.0,
                "attempts_sum": 0, "total_time_sum": 0.0,
            })
            d["count"] += 1
            is_ok = str(r.get("success")).lower() in ("ya", "true", "1")
            d["success"] += 1 if is_ok else 0
            total_success += 1 if is_ok else 0
            d["drop_sum"] += _num(r.get("score_drop_pct"))
            d["attempts_sum"] += int(_num(r.get("attempts"), int, 0))
            d["total_time_sum"] += _num(r.get("total_time_s"))

            # Agregasi per waktu pengujian (konsistensi pencahayaan)
            tod = r.get("time_of_day") or "?"
            t = per_time.setdefault(tod, {"count": 0, "success": 0})
            t["count"] += 1
            t["success"] += 1 if is_ok else 0

        levels_out = {}
        for lvl, d in per_level.items():
            c = max(1, d["count"])
            levels_out[lvl] = {
                "count": d["count"],
                "success": d["success"],
                "success_rate": round(d["success"] / c * 100, 1),
                "avg_drop_pct": round(d["drop_sum"] / c, 1),
                "avg_attempts": round(d["attempts_sum"] / c, 2),
                "avg_total_time_s": round(d["total_time_sum"] / c, 1),
            }

        total = len(rows)
        time_out = {}
        for tod, t in per_time.items():
            c = max(1, t["count"])
            time_out[tod] = {
                "count": t["count"],
                "success": t["success"],
                "success_rate": round(t["success"] / c * 100, 1),
            }
        return {
            "total_sessions": total,
            "total_success": total_success,
            "overall_success_rate": round(total_success / total * 100, 1) if total else 0.0,
            "per_level": levels_out,
            "per_time_of_day": time_out,
        }

    def record_clean_detection(self, score: float, detect_time_s: float = 0.0,
                               max_attempts: int = 5) -> Optional[Dict]:
        """Catat deteksi panel BERSIH (tidak ada pembersihan) ke riwayat.

        Memberi gambaran adil di laporan: sistem benar memutuskan TIDAK
        membersihkan panel yang sudah bersih (keputusan = bersih, tanpa aktuasi).
        """
        with self._lock:
            sid = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            record = {
                "session_id": sid,
                "timestamp": datetime.now().isoformat(),
                "time_of_day": time_of_day(),
                "level": "bersih",
                "score_before": round(float(score), 2),
                "score_after": round(float(score), 2),
                "score_drop_pct": 0.0,
                "attempts": 0,
                "max_attempts": max_attempts,
                "success": "Ya",
                "detect_time_s": round(float(detect_time_s), 2),
                "cleaning_time_s": 0.0,
                "verify_time_s": 0.0,
                "total_time_s": round(float(detect_time_s), 2),
            }
            self._recent.append(record)
            try:
                self._ensure_csv()
                with open(self.csv_file, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([record[k] for k in self.CSV_HEADER])
            except Exception as e:
                print(f"[CleaningLogger] Gagal tulis CSV (bersih): {e}")
            return record

    def export_report(self, output_dir: str = "analysis_output/cleaning") -> Dict:
        """Tulis ringkasan + CSV ke folder analisis, kembalikan path file."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary = self.get_summary()
        rows = self.get_sessions()

        # JSON
        json_file = out / f"cleaning_report_{ts}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump({"summary": summary, "sessions": rows}, f, indent=2)

        # TXT ringkas
        txt_file = out / f"cleaning_report_{ts}.txt"
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write("=" * 70 + "\n")
            f.write("LAPORAN SIKLUS PEMBERSIHAN\n")
            f.write(f"Waktu        : {datetime.now().isoformat()}\n")
            f.write(f"Total sesi   : {summary['total_sessions']}\n")
            f.write(f"Berhasil     : {summary['total_success']} "
                    f"({summary['overall_success_rate']}%)\n")
            f.write("=" * 70 + "\n\n")
            f.write("RINGKASAN PER LEVEL\n")
            f.write("-" * 70 + "\n")
            for lvl, d in summary["per_level"].items():
                f.write(f"  {str(lvl).upper()}\n")
                f.write(f"    Jumlah sesi      : {d['count']}\n")
                f.write(f"    Success rate     : {d['success_rate']}% "
                        f"({d['success']}/{d['count']})\n")
                f.write(f"    Rata-rata attempt: {d['avg_attempts']}/{rows and rows[0].get('max_attempts', 5) or 5}\n")
                f.write(f"    Penurunan score  : {d['avg_drop_pct']}%\n")
                f.write(f"    Waktu siklus     : {d['avg_total_time_s']} detik\n\n")
            f.write(f"Data lengkap (CSV): {self.csv_file}\n")
            f.write("=" * 70 + "\n")

        return {
            "csv": str(self.csv_file),
            "json": str(json_file),
            "txt": str(txt_file),
        }

    def clear(self) -> int:
        """Kosongkan riwayat (memori + CSV). Mengembalikan jumlah dihapus."""
        with self._lock:
            n = len(self._recent)
            self._recent.clear()
            try:
                if self.csv_file.exists():
                    self.csv_file.unlink()
            except OSError:
                pass
            return n
