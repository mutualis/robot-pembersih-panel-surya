#!/usr/bin/env python3
"""
Main Entry Point - Solar Panel Cleaner

Production runner untuk Raspberry Pi.
Menggunakan SolarPanelController dengan auto-monitoring loop.

Penggunaan:
  python3 main.py

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import os
import sys

def main():
    # Ensure working directory is raspberry-pi/
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    sys.path.insert(0, script_dir)
    
    print("\n" + "=" * 60)
    print("  SOLAR PANEL CLEANER - Production Mode")
    print("=" * 60)
    print()
    
    try:
        from app.config import Config
        from app.controller import SolarPanelController
        from web.server import create_app
        
        # Load configuration
        config = Config()
        
        # Create controller with auto-monitoring
        controller = SolarPanelController(config)
        
        # Start monitoring loop (auto capture + detection)
        controller.start()
        print("[OK] Monitoring loop started (auto capture + detection)")
        
        # Create Flask app
        app = create_app(controller, config)
        
        # Get web server config
        host = config.get('web.host', '0.0.0.0')
        port = config.get('web.port', 5000)
        debug = config.get('web.debug', False)
        
        print(f"\nWeb interface: http://{host}:{port}/")
        print("  Dashboard:   http://{host}:{port}/")
        print("  Testing:     http://{host}:{port}/testing")
        print("  Performance: http://{host}:{port}/performance")
        print("  Report:      http://{host}:{port}/report")
        print()
        print("Press Ctrl+C to stop")
        print("=" * 60 + "\n")
        
        # Run Flask server
        app.run(host=host, port=port, debug=debug, use_reloader=False)
        
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
