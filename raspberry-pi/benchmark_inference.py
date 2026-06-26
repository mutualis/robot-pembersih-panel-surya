#!/usr/bin/env python3
"""
benchmark_inference.py — Benchmark Kecepatan Inferensi di Raspberry Pi 5

Mengukur waktu inferensi YOLOv11 two-stage (deteksi panel + klasifikasi
kekotoran) pada Raspberry Pi 5 sebanyak N kali, lalu menghasilkan statistik
kecepatan inferensi (ms/frame stage 1 & 2, total, dan FPS) plus snapshot
kondisi sistem (suhu, throttle).

Sumber citra (urut prioritas):
  1. --image <path>     : pakai file citra tertentu (paling reproducible)
  2. kamera (default)   : ambil 1 frame dari webcam, lalu ulangi inferensinya
  3. --synthetic        : citra dummy 1920x1080 (kalau tak ada kamera & file)

Output:
  - Ringkasan ke terminal
  - analysis_output/performance/inference_benchmark_<timestamp>.txt  (LaTeX-friendly)
  - analysis_output/performance/inference_benchmark_<timestamp>.json

Pakai (di Raspberry Pi, dalam venv):
  python3 benchmark_inference.py --runs 100
  python3 benchmark_inference.py --runs 100 --image test_samples/kotor_sedang.jpg
  python3 benchmark_inference.py --runs 50 --synthetic

Author: Muhammad Ridho Assidiqi — UGM Sekolah Vokasi (TRIK)
"""

import argparse
import os
import sys

# Pastikan working dir = lokasi script (agar path model & config benar)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, SCRIPT_DIR)


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark inferensi YOLOv11 two-stage di Raspberry Pi 5"
    )
    parser.add_argument("--runs", type=int, default=100,
                        help="Jumlah iterasi inferensi (default 100)")
    parser.add_argument("--warmup", type=int, default=5,
                        help="Iterasi pemanasan yang tidak dihitung (default 5)")
    parser.add_argument("--image", type=str, default=None,
                        help="Path citra uji (opsional, paling reproducible)")
    parser.add_argument("--synthetic", action="store_true",
                        help="Pakai citra dummy bila kamera/file tidak ada")
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  BENCHMARK INFERENSI YOLOv11 TWO-STAGE — RASPBERRY PI 5")
    print("=" * 70)

    # --- Load config & model ---
    try:
        import numpy as np
        from app.config import Config
        from app.two_stage_detector import TwoStageDetector
    except Exception as e:
        print(f"[ERROR] Gagal import dependensi: {e}")
        sys.exit(1)

    config = Config()
    panel_path = config.get("detection.panel_model_path", "models/panel_detection_best.pt")
    dirt_path = config.get("detection.dirt_model_path", "models/dirt_classification_best.pt")

    print(f"  Model deteksi   : {panel_path}")
    print(f"  Model klasifikasi: {dirt_path}")
    print(f"  Iterasi         : {args.runs} (warmup {args.warmup})")

    # Performance logging dimatikan agar tidak menulis CSV tiap iterasi benchmark
    detector = TwoStageDetector(
        panel_model_path=panel_path,
        dirt_model_path=dirt_path,
        panel_confidence=config.get("detection.panel_confidence", 0.7),
        dirt_confidence=config.get("detection.dirt_confidence", 0.7),
        enable_performance_logging=False,
    )

    if detector.panel_model is None or detector.dirt_model is None:
        print("[ERROR] Model gagal dimuat. Pastikan file .pt ada & valid.")
        sys.exit(1)

    # --- Siapkan frame uji ---
    frame = None
    source = ""

    if args.image:
        try:
            import cv2
            frame = cv2.imread(args.image)
            if frame is not None:
                source = f"file: {args.image}"
        except Exception as e:
            print(f"[WARN] Gagal baca citra {args.image}: {e}")

    if frame is None and not args.synthetic:
        # Coba kamera
        try:
            from app.camera import Camera
            cam = Camera(
                device_id=config.get("camera.device_id", 0),
                resolution=tuple(config.get("camera.resolution", [1920, 1080])),
            )
            frame = cam.capture()
            if frame is not None:
                source = f"kamera ({frame.shape[1]}x{frame.shape[0]})"
            cam.release()
        except Exception as e:
            print(f"[WARN] Kamera tidak tersedia: {e}")

    if frame is None:
        # Fallback dummy
        import numpy as np
        frame = (np.random.rand(1080, 1920, 3) * 255).astype("uint8")
        source = "synthetic 1920x1080 (dummy)"

    print(f"  Sumber citra    : {source}")
    print("-" * 70)

    # --- Jalankan benchmark via fungsi bersama (dipakai web juga) ---
    from app.performance_logger import run_inference_benchmark

    def _progress(done, total):
        if done % 20 == 0 or done == total:
            print(f"    {done}/{total} selesai", flush=True)

    print(f"  Pemanasan {args.warmup} iterasi + mengukur {args.runs} iterasi...",
          flush=True)
    payload = run_inference_benchmark(
        detector, frame, runs=args.runs, warmup=args.warmup,
        source=source, progress_cb=_progress,
    )

    s1_stat = payload.get("stage1_ms")
    s2_stat = payload.get("stage2_ms")
    tot_stat = payload.get("total_ms")
    fps = payload.get("fps_mean", 0)
    sysinfo = payload.get("system", {})

    # --- Output terminal ---
    print("\n" + "=" * 70)
    print("  HASIL BENCHMARK")
    print("=" * 70)

    def _print_block(label, st):
        if not st:
            print(f"  {label}: (tidak ada data)")
            return
        print(f"  {label}:")
        print(f"    mean   = {st['mean']} ms")
        print(f"    median = {st['median']} ms")
        print(f"    stdev  = {st['stdev']} ms")
        print(f"    min    = {st['min']} ms")
        print(f"    max    = {st['max']} ms")

    _print_block("Stage 1 (deteksi panel)", s1_stat)
    _print_block("Stage 2 (klasifikasi)", s2_stat)
    _print_block("Total pipeline", tot_stat)
    print(f"\n  FPS (rata-rata) = {fps}")
    if sysinfo:
        print(f"  Suhu CPU saat benchmark = {sysinfo.get('cpu_temp_c', 'N/A')} °C")
        thr = sysinfo.get("throttled")
        if thr:
            print(f"  Throttled saat ini = {thr.get('throttled_now')} "
                  f"| Undervoltage = {thr.get('undervoltage_now')}")

    files = payload.get("files", {})
    print(f"\n  Tersimpan:")
    print(f"    {files.get('txt')}")
    print(f"    {files.get('json')}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
