#!/usr/bin/env python3
"""
Development Runner - Solar Panel Cleaner

Menjalankan sistem di PC/laptop untuk development dan testing.
Menggunakan komponen REAL yang sama persis dengan produksi (main.py):
- Kamera: webcam (real) via app.camera.Camera
- Detector: YOLO two-stage (real) via app.two_stage_detector.TwoStageDetector
- ESP32: via USB serial (real) via app.serial_comm.ESP32Communicator

TIDAK ADA data dummy/mock. Bila hardware belum tersambung, sistem tetap
berjalan dengan fallback graceful (komponen = None + auto-reconnect),
persis seperti di Raspberry Pi. Satu-satunya perbedaan dengan main.py:
auto-deteksi port ESP32 untuk Windows (COM port bisa berubah-ubah).

Penggunaan:
  python run_dev.py                  # Auto-detect ESP32
  python run_dev.py COM5             # Manual port (Windows)
  python run_dev.py /dev/ttyUSB0     # Manual port (Linux)

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import os
import sys
import platform
import subprocess
import argparse


def print_banner(serial_port):
    print("\n" + "=" * 60)
    print("  SOLAR PANEL CLEANER - Development Mode (REAL hardware)")
    print("=" * 60)
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python:   {sys.version.split()[0]}")
    print()
    print("Hardware:")
    if serial_port:
        print(f"  ESP32:    {serial_port}")
    else:
        print("  ESP32:    Menunggu koneksi (auto-detect)...")
    print("  Kamera:   Webcam (auto-detect)")
    print("  Detector: YOLO model (real)")
    print()
    print("Web interface:")
    print("  Dashboard: http://localhost:5000/")
    print("  Testing:   http://localhost:5000/testing")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 60 + "\n")


def check_python_version():
    if sys.version_info < (3, 8):
        print("Error: Python 3.8+ required")
        sys.exit(1)
    print(f"  Python {sys.version.split()[0]}")


def check_dependencies():
    required = ['flask', 'cv2', 'numpy', 'yaml']
    missing = []
    for module in required:
        try:
            if module == 'cv2':
                import cv2
            elif module == 'yaml':
                import yaml
            else:
                __import__(module)
        except ImportError:
            missing.append(module)

    if missing:
        print(f"  Missing: {', '.join(missing)}")
        req_file = 'requirements-windows.txt' if platform.system() == 'Windows' else 'requirements.txt'
        if os.path.exists(req_file):
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', req_file])
        else:
            print(f"  {req_file} not found!")
            sys.exit(1)
    print("  Dependencies OK")


def auto_detect_esp32():
    """Auto-detect ESP32 serial port by VID:PID or description"""
    try:
        import serial.tools.list_ports

        esp32_vid_pid = [
            (0x10C4, 0xEA60),  # CP2102
            (0x10C4, 0xEA70),  # CP2104
            (0x1A86, 0x7523),  # CH340
            (0x1A86, 0x55D4),  # CH9102
            (0x0403, 0x6001),  # FT232RL
            (0x303A, 0x1001),  # ESP32-S2 native USB
            (0x303A, 0x0002),  # ESP32-S3 native USB
        ]

        esp32_identifiers = [
            'CP210', 'CH340', 'CH910', 'FTDI',
            'USB Serial', 'USB-SERIAL',
        ]

        ports = list(serial.tools.list_ports.comports())
        if not ports:
            return None, "Tidak ada serial port terdeteksi"

        # Filter out Bluetooth and virtual ports
        physical_ports = [p for p in ports if 'bluetooth' not in (p.description or '').lower()
                          and 'bt ' not in (p.description or '').lower()]

        # Method 1: VID:PID match
        for port in physical_ports:
            if port.vid and port.pid:
                for vid, pid in esp32_vid_pid:
                    if port.vid == vid and port.pid == pid:
                        return port.device, f"{port.device}: {port.description}"

        # Method 2: Description match
        for port in physical_ports:
            desc = (port.description or '').upper()
            mfr = (port.manufacturer or '').upper()
            for ident in esp32_identifiers:
                if ident.upper() in desc or ident.upper() in mfr:
                    return port.device, f"{port.device}: {port.description}"

        # Method 3: Single physical port
        if len(physical_ports) == 1:
            return physical_ports[0].device, f"{physical_ports[0].device}: {physical_ports[0].description} (satu-satunya port)"

        if not physical_ports:
            return None, "Tidak ada serial port fisik terdeteksi (hanya Bluetooth)"

        port_list = '\n'.join([f"  {p.device}: {p.description}" for p in physical_ports])
        return None, f"Beberapa port ditemukan:\n{port_list}\nGunakan: python run_dev.py <PORT>"

    except ImportError:
        return None, "pyserial belum terinstall (pip install pyserial)"
    except Exception as e:
        return None, f"Error: {e}"


def main():
    # Ensure working directory is raspberry-pi/
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    sys.path.insert(0, script_dir)

    parser = argparse.ArgumentParser(
        description='Solar Panel Cleaner - Development Mode (REAL hardware)',
        epilog='Contoh:\n'
               '  python run_dev.py              # Auto-detect ESP32\n'
               '  python run_dev.py COM5          # Windows manual port\n'
               '  python run_dev.py /dev/ttyUSB0  # Linux manual port\n',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('port', nargs='?', default=None,
                        help='Serial port ESP32 (auto-detect jika tidak diisi)')
    args = parser.parse_args()

    # Detect ESP32 port (Windows COM port bisa berubah; ini satu-satunya
    # bantuan khusus dev. Bila tidak ketemu, controller tetap jalan dan
    # ESP32Communicator akan auto-reconnect saat hardware muncul.)
    if args.port:
        serial_port = args.port
        print(f"\nUsing manual port: {serial_port}")
    else:
        print("\nAuto-detecting ESP32...")
        serial_port, info = auto_detect_esp32()
        if serial_port:
            print(f"  ESP32 ditemukan: {info}")
        else:
            print(f"  {info}")
            print("  Server tetap berjalan, ESP32 akan di-detect otomatis...")
            serial_port = None

    print_banner(serial_port)

    print("Checking environment...")
    check_python_version()
    check_dependencies()

    print("\nInitializing system...")
    try:
        from app.config import Config
        from app.controller import SolarPanelController
        from web.server import create_app

        config = Config()

        # Override serial port bila terdeteksi/manual (Windows COM port).
        if serial_port:
            config.set('serial.port', serial_port)

        # Pakai controller produksi yang SAMA dengan main.py — komponen real,
        # auto monitoring loop, auto cleaning, auto verification.
        controller = SolarPanelController(config)
        controller.start()
        print("  [OK] Monitoring loop started (auto capture + detection)")

        app = create_app(controller, config)

        print("\n  Server starting on http://localhost:5000/\n")
        app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)

    except KeyboardInterrupt:
        print("\n\nServer stopped")
        if 'controller' in locals():
            controller.stop()
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
