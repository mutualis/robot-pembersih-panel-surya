#!/usr/bin/env python3
"""
Diagnostic Script - Check Performance Logging Status

Checks:
1. Configuration (enable_performance_logging)
2. Camera availability
3. Model loading
4. Performance logger initialization
5. Detection execution

Author: Muhammad Ridho Assidiqi
"""

import sys
import os

# Ensure working directory
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
sys.path.insert(0, script_dir)

print("\n" + "=" * 70)
print("PERFORMANCE LOGGING DIAGNOSTIC")
print("=" * 70 + "\n")

# 1. Check configuration
print("[1/5] Checking configuration...")
try:
    from app.config import Config
    config = Config()
    perf_enabled = config.get('detection.enable_performance_logging', False)
    print(f"  ✓ Config loaded")
    print(f"  enable_performance_logging: {perf_enabled}")
    if not perf_enabled:
        print("  ⚠ WARNING: Performance logging is DISABLED in settings.yaml")
        print("  → Set 'detection.enable_performance_logging: true' in config/settings.yaml")
except Exception as e:
    print(f"  ✗ ERROR: {e}")
    sys.exit(1)

# 2. Check camera
print("\n[2/5] Checking camera...")
try:
    from app.camera import Camera
    camera = Camera(
        device_id=config.get('camera.device_id', 0),
        resolution=tuple(config.get('camera.resolution', [1920, 1080]))
    )
    frame = camera.capture()
    if frame is not None:
        print(f"  ✓ Camera working (resolution: {frame.shape[1]}x{frame.shape[0]})")
    else:
        print(f"  ✗ Camera capture returned None")
    camera.release()
except Exception as e:
    print(f"  ✗ ERROR: {e}")
    print("  → Auto-monitoring will NOT run without camera")

# 3. Check models
print("\n[3/5] Checking models...")
try:
    panel_path = config.get('detection.panel_model_path', 'models/panel_detection_best.pt')
    dirt_path = config.get('detection.dirt_model_path', 'models/dirt_classification_best.pt')
    
    if os.path.exists(panel_path):
        print(f"  ✓ Panel model found: {panel_path}")
    else:
        print(f"  ✗ Panel model NOT found: {panel_path}")
    
    if os.path.exists(dirt_path):
        print(f"  ✓ Dirt model found: {dirt_path}")
    else:
        print(f"  ✗ Dirt model NOT found: {dirt_path}")
    
    # Try loading detector
    from app.two_stage_detector import TwoStageDetector
    detector = TwoStageDetector(
        panel_model_path=panel_path,
        dirt_model_path=dirt_path,
        panel_confidence=config.get('detection.panel_confidence', 0.7),
        dirt_confidence=config.get('detection.dirt_confidence', 0.7),
        enable_performance_logging=perf_enabled
    )
    
    if detector.panel_model is not None:
        print(f"  ✓ Panel model loaded successfully")
    else:
        print(f"  ✗ Panel model failed to load")
    
    if detector.dirt_model is not None:
        print(f"  ✓ Dirt model loaded successfully")
    else:
        print(f"  ✗ Dirt model failed to load")
    
except Exception as e:
    print(f"  ✗ ERROR: {e}")

# 4. Check performance logger
print("\n[4/5] Checking performance logger...")
try:
    if detector.enable_performance_logging:
        print(f"  ✓ Performance logging ENABLED in detector")
        if detector.performance_logger is not None:
            print(f"  ✓ Performance logger initialized")
            print(f"  Log directory: {detector.performance_logger.log_dir}")
            print(f"  Session ID: {detector.performance_logger.session_id}")
        else:
            print(f"  ✗ Performance logger is None")
    else:
        print(f"  ✗ Performance logging DISABLED in detector")
except Exception as e:
    print(f"  ✗ ERROR: {e}")

# 5. Test detection
print("\n[5/5] Testing detection...")
try:
    from app.camera import Camera
    camera = Camera(
        device_id=config.get('camera.device_id', 0),
        resolution=tuple(config.get('camera.resolution', [1920, 1080]))
    )
    frame = camera.capture()
    
    if frame is not None:
        print(f"  Running detection...")
        result = detector.detect(frame)
        
        print(f"  ✓ Detection completed")
        print(f"    Panel detected: {result.get('panel_detected', False)}")
        print(f"    Dirt level: {result.get('dirt_level', 'unknown')}")
        
        if 'stage1_time_ms' in result:
            print(f"    Stage 1 time: {result['stage1_time_ms']} ms")
            print(f"    Stage 2 time: {result['stage2_time_ms']} ms")
            print(f"    Total time: {result['total_time_ms']} ms")
        
        # Check if data was logged
        if detector.performance_logger:
            stats = detector.performance_logger.get_realtime_stats()
            print(f"\n  Performance Logger Stats:")
            print(f"    Total detections: {stats['total_detections']}")
            print(f"    Buffer size: {stats.get('buffer_size', 0)}")
            
            if stats['total_detections'] > 0:
                print(f"    ✓ Data is being logged!")
            else:
                print(f"    ✗ No data logged yet")
    else:
        print(f"  ✗ Cannot capture frame")
    
    camera.release()
    
except Exception as e:
    print(f"  ✗ ERROR: {e}")
    import traceback
    traceback.print_exc()

# Summary
print("\n" + "=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
print("\nIf all checks passed (✓), performance logging should work.")
print("If you see errors (✗), fix them before running main.py")
print("\nTo run the main program:")
print("  python3 main.py")
print("\nTo check performance page:")
print("  http://192.168.1.9:5000/performance")
print("=" * 70 + "\n")
