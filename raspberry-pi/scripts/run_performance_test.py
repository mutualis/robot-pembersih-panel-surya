#!/usr/bin/env python3
"""
Performance Testing Mode for Raspberry Pi
Enables performance logging for Bab 4 data collection

Usage:
    python run_performance_test.py --duration 300  # Run for 5 minutes
    python run_performance_test.py --samples 100   # Collect 100 samples

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import os
import sys
import time
import argparse
from pathlib import Path


def print_banner():
    print("\n" + "=" * 70)
    print("  PERFORMANCE TESTING MODE - Data Collection for Bab 4")
    print("=" * 70)
    print()
    print("This mode enables detailed performance logging:")
    print("  ✓ Two-stage inference time (Stage 1 + Stage 2)")
    print("  ✓ FPS and latency measurements")
    print("  ✓ Memory and CPU usage")
    print("  ✓ Per-detection metrics")
    print()
    print("Output:")
    print("  logs/performance/metrics_YYYYMMDD_HHMMSS.csv")
    print("  logs/performance/session_YYYYMMDD_HHMMSS.json")
    print("  analysis_output/bab4_performance/")
    print()
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description='Performance Testing Mode')
    parser.add_argument('--duration', type=int, default=0,
                        help='Test duration in seconds (0 = manual stop)')
    parser.add_argument('--samples', type=int, default=0,
                        help='Number of samples to collect (0 = unlimited)')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Interval between captures (seconds)')
    parser.add_argument('--export', action='store_true',
                        help='Auto-export for Bab 4 when done')
    args = parser.parse_args()

    print_banner()

    # Check dependencies
    try:
        from app.config import Config
        from app.two_stage_detector import TwoStageDetector
        from app.camera import Camera
        from app.performance_logger import PerformanceLogger
    except ImportError as e:
        print(f"Error: Missing dependency - {e}")
        print("Make sure you're in the raspberry-pi directory")
        sys.exit(1)

    # Load config
    config = Config()

    # Initialize camera
    print("Initializing camera...")
    try:
        camera = Camera(
            device_id=config.get('camera.device_id', 0),
            resolution=tuple(config.get('camera.resolution', [640, 480]))
        )
        print("  ✓ Camera ready")
    except Exception as e:
        print(f"  ✗ Camera error: {e}")
        sys.exit(1)

    # Initialize detector with performance logging ENABLED
    print("Loading YOLO models...")
    panel_model = config.get('models.panel_detection', 'models/panel_detection.pt')
    dirt_model = config.get('models.dirt_classification', 'models/dirt_classification.pt')
    
    detector = TwoStageDetector(
        panel_model_path=panel_model,
        dirt_model_path=dirt_model,
        panel_confidence=config.get('detection.panel_confidence', 0.5),
        dirt_confidence=config.get('detection.dirt_confidence', 0.5),
        enable_performance_logging=True  # ENABLE LOGGING
    )
    print("  ✓ Models loaded with performance logging enabled")

    # Test parameters
    duration = args.duration
    max_samples = args.samples
    interval = args.interval

    print(f"\nTest Configuration:")
    print(f"  Duration: {duration if duration > 0 else 'Manual stop (Ctrl+C)'} seconds")
    print(f"  Max Samples: {max_samples if max_samples > 0 else 'Unlimited'}")
    print(f"  Interval: {interval} seconds")
    print(f"  Auto-export: {'Yes' if args.export else 'No'}")
    print()

    # Start test
    print("Starting performance test...")
    print("Press Ctrl+C to stop\n")

    start_time = time.time()
    sample_count = 0

    try:
        while True:
            # Check stop conditions
            if duration > 0 and (time.time() - start_time) >= duration:
                print("\n✓ Duration limit reached")
                break
            
            if max_samples > 0 and sample_count >= max_samples:
                print("\n✓ Sample limit reached")
                break

            # Capture and detect
            frame = camera.capture()
            if frame is None:
                print("  ✗ Failed to capture frame")
                time.sleep(interval)
                continue

            result = detector.detect(frame)
            sample_count += 1

            # Print progress
            if 'total_time_ms' in result:
                print(f"[{sample_count:4d}] "
                      f"Total: {result['total_time_ms']:6.2f}ms | "
                      f"Stage1: {result['stage1_time_ms']:6.2f}ms | "
                      f"Stage2: {result['stage2_time_ms']:6.2f}ms | "
                      f"Dirt: {result['dirt_level']:15s} | "
                      f"Score: {result['weighted_score']:6.2f}")
            else:
                print(f"[{sample_count:4d}] Detection complete (no timing)")

            # Wait for next sample
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\n✓ Test stopped by user")

    # Generate report
    print("\n" + "=" * 70)
    print("Generating performance report...")
    print("=" * 70 + "\n")

    report = detector.generate_performance_report()
    
    if report and 'error' not in report:
        print(f"✓ Report generated successfully")
        print(f"  Total samples: {report['total_detections']}")
        print(f"  Avg inference time: {report['inference_time']['total_ms']['mean']} ms")
        print(f"  Avg FPS: {report['fps']['mean']}")
        print(f"  Avg memory: {report['resources']['memory_mb']['mean']} MB")
        print(f"  Files:")
        print(f"    CSV:  {report['files']['csv']}")
        print(f"    JSON: {report['files']['json']}")
    else:
        print("✗ Failed to generate report")

    # Export for Bab 4
    if args.export:
        print("\n" + "=" * 70)
        print("Exporting for Bab 4...")
        print("=" * 70 + "\n")
        
        result = detector.export_performance_for_bab4()
        if result:
            print("✓ Bab 4 export complete:")
            print(f"  LaTeX report: {result['latex_file']}")
            print(f"  CSV data: {result['csv_file']}")
            print(f"  JSON report: {result['json_file']}")
        else:
            print("✗ Export failed")

    print("\n" + "=" * 70)
    print("Performance test complete!")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    main()
