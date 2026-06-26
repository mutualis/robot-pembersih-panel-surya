"""
Flask Web Server - Monitoring & Control Dashboard

Web server untuk monitoring dan kontrol sistem pembersihan panel surya.
Fitur:
- Dashboard: Preview kamera, status sistem, konfigurasi zona
- Testing: Test hardware ESP32 (motor, pump, limit switch, encoder)
- WebSocket: Real-time status update (dengan fallback ke HTTP polling)
- API: REST API untuk kontrol dan konfigurasi

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

from flask import Flask, render_template, jsonify, request, Response, send_from_directory, session, redirect, url_for
from flask_cors import CORS
from flask_sock import Sock
from werkzeug.security import check_password_hash
from functools import wraps
import cv2
import json
import base64
import numpy as np
import os
import serial
import threading
import time
from datetime import datetime, timedelta

def create_app(controller, config):
    app = Flask(__name__)
    CORS(app)
    
    # Initialize WebSocket support (native WebSocket, no Socket.IO)
    sock = Sock(app)
    
    # ===== AUTENTIKASI =====
    # Admin (login) bisa akses semua fitur. Pengunjung tanpa login hanya
    # bisa melihat (view-only). Proteksi diterapkan otomatis ke semua
    # request yang mengubah state (POST/PUT/DELETE/PATCH) via before_request.
    auth_enabled = config.get('auth.enabled', True)
    admin_username = config.get('auth.admin_username', 'admin')
    admin_password_hash = config.get('auth.admin_password_hash', '')
    session_hours = config.get('auth.session_hours', 12)
    app.secret_key = config.get('auth.secret_key') or os.urandom(32).hex()
    app.permanent_session_lifetime = timedelta(hours=session_hours)
    
    def is_admin():
        """True jika request berasal dari sesi admin yang login."""
        return bool(session.get('is_admin'))
    
    # Endpoint yang boleh diakses tanpa login meski memakai POST.
    # - login/logout: proses autentikasi itu sendiri.
    # - preview toggle: hanya mengontrol tampilan feed kamera (read-only),
    #   tidak menggerakkan hardware atau mengubah konfigurasi. Aman untuk viewer.
    AUTH_EXEMPT_PATHS = {
        '/api/login',
        '/api/logout',
        '/api/preview/toggle',
        '/api/preview/detection/toggle',
    }
    
    @app.before_request
    def _enforce_admin_for_writes():
        """
        Blokir semua aksi yang mengubah state untuk non-admin.
        GET/HEAD/OPTIONS tetap terbuka (view-only untuk semua).
        """
        if not auth_enabled:
            return None
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return None
        if request.path in AUTH_EXEMPT_PATHS:
            return None
        if is_admin():
            return None
        # Non-admin mencoba melakukan aksi → tolak
        return jsonify({
            'success': False,
            'auth_required': True,
            'message': 'Login sebagai admin diperlukan untuk melakukan aksi ini.'
        }), 401
    
    # WiFi manager (ganti WiFi client via web tanpa edit kode).
    # Aman bila nmcli tidak tersedia (mis. saat dev di Windows) — error
    # ditangani di tiap endpoint.
    try:
        from app.wifi_manager import WiFiManager
        wifi_client_iface = config.get('wifi.client_interface', 'wlan0')
        wifi_ap_iface = config.get('wifi.ap_interface', 'uap0')
        wifi_manager = WiFiManager(client_iface=wifi_client_iface, ap_iface=wifi_ap_iface)
    except Exception as _e:
        wifi_manager = None
        print(f"[WiFi] Manager tidak aktif: {_e}")
    
    # Model manager (upload/pilih/hapus model YOLO via web).
    try:
        from app.model_manager import ModelManager
        models_dir = config.get('models.dir', 'models')
        model_manager = ModelManager(models_dir=models_dir)
    except Exception as _e:
        model_manager = None
        print(f"[Model] Manager tidak aktif: {_e}")
    
    # Store active WebSocket connections and status thread
    class WebSocketState:
        def __init__(self):
            self.clients = set()
            self.status_thread = None
            self.status_thread_running = False
    
    ws_state = WebSocketState()
    
    def _enrich_status(status):
        """Add component info to status dict (shared by HTTP and WebSocket)"""
        # Camera: check if camera object exists and is actually working
        with controller._camera_lock:
            if controller.camera is not None:
                try:
                    if controller.camera.cap is not None and controller.camera.cap.grab():
                        status['camera_type'] = 'real'
                        status['camera_open'] = True
                    else:
                        raise RuntimeError("Camera grab failed")
                except Exception:
                    status['camera_type'] = 'none'
                    status['camera_open'] = False
                    try:
                        controller.camera.release()
                    except Exception:
                        pass
                    controller.camera = None
                    if not controller._camera_reconnect_running:
                        controller._start_camera_reconnect()
            else:
                status['camera_type'] = 'none'
                status['camera_open'] = False
        
        # Override mode if hardware is missing (monitor loop might be delayed)
        if status['camera_type'] == 'none' and not status.get('cleaning_active', False):
            status['mode'] = 'waiting_camera'
        
        det = controller.detector
        if det is not None and hasattr(det, 'panel_model') and det.panel_model:
            status['yolo_type'] = 'two_stage'
        else:
            status['yolo_type'] = 'none'
        
        # Port serial aktif. Mode auto: tampilkan "auto (mendeteksi…)" sampai
        # port nyata ditemukan via handshake.
        _active_port = getattr(controller.esp32, 'port', None)
        if _active_port:
            status['serial_port'] = _active_port
        elif getattr(controller.esp32, 'auto_mode', False):
            status['serial_port'] = 'auto (mendeteksi…)'
        else:
            status['serial_port'] = 'none'
        
        # Live connection check: ESP32 dianggap terhubung HANYA jika benar-benar
        # membalas (handshake), bukan sekadar port serial terbuka.
        # Ini penting untuk UART hardware (/dev/ttyAMA*, /dev/serial0) yang
        # port-nya selalu bisa dibuka walau pin RX/TX tidak tersambung ke ESP32.
        esp32_connected = False
        try:
            esp32_connected = controller.esp32.is_alive()
        except (serial.SerialException, OSError, AttributeError):
            esp32_connected = False

        # Bila port hilang total (mis. USB dicabut), picu reconnect.
        if not esp32_connected:
            try:
                port_open = bool(controller.esp32.serial and controller.esp32.serial.is_open)
            except Exception:
                port_open = False
            if not port_open and not controller.esp32._reconnect_running:
                controller.esp32.connected = False
                controller.esp32._start_background_reconnect()
        
        # Sync both statuses from the same live check result
        status['serial_open'] = esp32_connected
        status['esp32_connected'] = esp32_connected
        
        # Override mode based on actual hardware state (fixes race condition with monitor loop)
        if not status.get('cleaning_active', False):
            if status['camera_type'] == 'real' and not esp32_connected:
                status['mode'] = 'detect_only'
            elif status['camera_type'] == 'real' and esp32_connected and status.get('mode') == 'detect_only':
                status['mode'] = 'monitoring'
        
        # PID logging state (for frontend sync)
        status['pid_logging_active'] = (
            hasattr(controller, 'pid_logger') and 
            controller.pid_logger is not None and 
            controller.pid_logger.is_logging
        )
        
        return status
    
    def background_status_broadcast():
        """Background thread to broadcast status updates via WebSocket"""
        while ws_state.status_thread_running:
            try:
                # Stop broadcasting if no clients connected
                if not ws_state.clients:
                    time.sleep(1)
                    continue
                
                status = _enrich_status(controller.get_status())
                status_json = json.dumps(status)
                
                # Broadcast to all connected clients
                disconnected = set()
                for ws in ws_state.clients.copy():
                    try:
                        ws.send(status_json)
                    except Exception:
                        disconnected.add(ws)
                
                # Always remove dead clients
                if disconnected:
                    ws_state.clients.difference_update(disconnected)
                
                time.sleep(0.1)  # Update setiap 100ms (10Hz) — real-time
            except Exception as e:
                print(f"[WebSocket] Broadcast error: {e}")
                time.sleep(1)
    
    @sock.route('/ws')
    def websocket_handler(ws):
        """Handle WebSocket connections"""
        print('[WebSocket] Client connected')
        ws_state.clients.add(ws)
        
        # Start background thread if not running
        if ws_state.status_thread is None or not ws_state.status_thread.is_alive():
            ws_state.status_thread_running = True
            ws_state.status_thread = threading.Thread(target=background_status_broadcast, daemon=True)
            ws_state.status_thread.start()
        
        # Send initial status
        try:
            initial_status = _enrich_status(controller.get_status())
            ws.send(json.dumps(initial_status))
        except Exception as e:
            print(f"[WebSocket] Error sending initial status: {e}")
        
        # Keep connection alive and handle messages
        try:
            while True:
                message = ws.receive()
                if message:
                    try:
                        data = json.loads(message)
                        if data.get('type') == 'request_status':
                            # Send status immediately
                            status = _enrich_status(controller.get_status())
                            ws.send(json.dumps(status))
                    except json.JSONDecodeError:
                        print(f"[WebSocket] Invalid JSON: {message}")
        except Exception as e:
            print(f"[WebSocket] Connection closed: {e}")
        finally:
            ws_state.clients.discard(ws)
            print('[WebSocket] Client disconnected')
    
    @app.route('/static/<path:filename>')
    def static_files(filename):
        """Serve static files"""
        return send_from_directory('static', filename)

    @app.route('/sw.js')
    def service_worker():
        """Service worker disajikan di root agar scope-nya mencakup seluruh situs (/)."""
        resp = send_from_directory('static', 'sw.js', mimetype='application/javascript')
        resp.headers['Service-Worker-Allowed'] = '/'
        resp.headers['Cache-Control'] = 'no-cache'
        return resp
    
    @app.route('/')
    def index():
        """Main dashboard"""
        return render_template('dashboard.html', active_page='dashboard')
    
    # ===== AUTH ENDPOINTS =====
    @app.route('/api/login', methods=['POST'])
    def api_login():
        """Login admin. Body: {username, password}"""
        if not auth_enabled:
            return jsonify({'success': True, 'is_admin': True, 'message': 'Auth dinonaktifkan'})
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = data.get('password') or ''
        
        valid = (
            username == admin_username
            and admin_password_hash
            and check_password_hash(admin_password_hash, password)
        )
        if valid:
            session.permanent = True
            session['is_admin'] = True
            session['username'] = username
            return jsonify({'success': True, 'is_admin': True, 'username': username,
                            'message': f'Selamat datang, {username}'})
        return jsonify({'success': False, 'message': 'Username atau password salah'}), 401
    
    @app.route('/api/logout', methods=['POST'])
    def api_logout():
        """Logout admin → kembali ke mode view-only."""
        session.clear()
        return jsonify({'success': True, 'message': 'Anda telah logout'})
    
    @app.route('/api/auth/status')
    def api_auth_status():
        """Status auth saat ini (untuk frontend menyesuaikan UI)."""
        return jsonify({
            'auth_enabled': auth_enabled,
            'is_admin': is_admin(),
            'username': session.get('username'),
        })
    
    @app.route('/testing')
    def testing():
        """System testing page (admin-only)"""
        if auth_enabled and not is_admin():
            return redirect(url_for('index'))
        return render_template('testing.html', active_page='testing')
    
    @app.route('/performance')
    def performance():
        """Performance monitoring page"""
        return render_template('performance.html', active_page='performance')
    
    @app.route('/report')
    def report():
        """Activity report page"""
        return render_template('report.html', active_page='report')
    
    @app.route('/settings')
    def settings():
        """Settings page (WiFi configuration, dll) — admin-only"""
        if auth_enabled and not is_admin():
            return redirect(url_for('index'))
        return render_template('settings.html', active_page='settings')
    
    @app.route('/api/status')
    def get_status():
        """Get system status"""
        status = _enrich_status(controller.get_status())
        return jsonify(status)
    
    @app.route('/api/capture', methods=['POST'])
    def manual_capture():
        """Manual capture, YOLO detection, and update last_detection status"""
        try:
            result = controller.manual_capture()
            if result:
                return jsonify(result)
            return jsonify({'error': 'Capture gagal — kamera tidak tersedia'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/zones', methods=['GET'])
    def get_zones():
        """Get configured zones"""
        return jsonify(config.zones)
    
    @app.route('/api/zones', methods=['POST'])
    def save_zones():
        """Save zone configuration"""
        zones = request.json
        if config.save_zones(zones):
            return jsonify({'success': True})
        return jsonify({'error': 'Failed to save zones'}), 500
    
    @app.route('/api/config', methods=['GET'])
    def get_config():
        """Get cleaning + monitoring configuration"""
        return jsonify({
            'max_attempts': config.get('cleaning.cycles.max_attempts', 5),
            'cooldown': config.get('cleaning.cooldown_after_success', 300),
            'working_hours': {
                'enabled': bool(config.get('monitoring.working_hours.enabled', True)),
                'start': str(config.get('monitoring.working_hours.start', '07:00')),
                'stop': str(config.get('monitoring.working_hours.stop', '17:00')),
            }
        })
    
    @app.route('/api/config', methods=['POST'])
    def save_config():
        """Save cleaning + monitoring configuration"""
        data = request.json or {}
        
        try:
            if 'max_attempts' in data:
                config.set('cleaning.cycles.max_attempts', data.get('max_attempts', 5))
            if 'cooldown' in data:
                config.set('cleaning.cooldown_after_success', data.get('cooldown', 300))
            
            # Jam kerja monitoring (opsional). Format "HH:MM" 24 jam.
            wh = data.get('working_hours')
            if isinstance(wh, dict):
                import re as _re
                def _valid_hhmm(s):
                    return bool(_re.match(r'^([01]?\d|2[0-3]):[0-5]\d$', str(s)))
                if 'enabled' in wh:
                    config.set('monitoring.working_hours.enabled', bool(wh.get('enabled')))
                if wh.get('start') is not None:
                    if not _valid_hhmm(wh.get('start')):
                        return jsonify({'error': 'Format jam mulai harus HH:MM (00:00-23:59)'}), 400
                    config.set('monitoring.working_hours.start', str(wh.get('start')))
                if wh.get('stop') is not None:
                    if not _valid_hhmm(wh.get('stop')):
                        return jsonify({'error': 'Format jam selesai harus HH:MM (00:00-23:59)'}), 400
                    config.set('monitoring.working_hours.stop', str(wh.get('stop')))
            
            if config.save():
                return jsonify({'success': True})
            else:
                return jsonify({'error': 'Failed to save config'}), 500
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # ===== WIFI MANAGEMENT API =====
    # Memungkinkan ganti WiFi client (wlan0) lewat web tanpa edit kode.
    # Akses tetap aman karena WiFi AP (uap0) tidak terputus saat ganti.
    
    def _wifi_unavailable():
        return jsonify({
            'success': False,
            'message': 'Manajemen WiFi tidak tersedia (nmcli/NetworkManager tidak ada). '
                       'Fitur ini hanya berjalan di Raspberry Pi.'
        }), 503
    
    @app.route('/api/wifi/status')
    def wifi_status():
        """Status koneksi WiFi client saat ini (SSID, sinyal, IP)."""
        if wifi_manager is None:
            return _wifi_unavailable()
        return jsonify(wifi_manager.status())
    
    @app.route('/api/wifi/scan')
    def wifi_scan():
        """Scan daftar WiFi yang tersedia."""
        if wifi_manager is None:
            return _wifi_unavailable()
        return jsonify(wifi_manager.scan())
    
    @app.route('/api/wifi/connect', methods=['POST'])
    def wifi_connect():
        """Sambungkan ke WiFi baru. Body: {ssid, password?, username?, auth_type?}"""
        if wifi_manager is None:
            return _wifi_unavailable()
        data = request.get_json(silent=True) or {}
        ssid      = data.get('ssid', '')
        password  = data.get('password')
        username  = data.get('username')   # untuk WPA2-Enterprise
        auth_type = data.get('auth_type')  # 'psk' | 'enterprise' | 'open'
        result = wifi_manager.connect(ssid, password, username=username, auth_type=auth_type)
        return jsonify(result), (200 if result.get('success') else 400)
    
    @app.route('/api/wifi/saved')
    def wifi_saved():
        """Daftar profil WiFi tersimpan."""
        if wifi_manager is None:
            return _wifi_unavailable()
        return jsonify(wifi_manager.saved_networks())
    
    @app.route('/api/wifi/forget', methods=['POST'])
    def wifi_forget():
        """Hapus profil WiFi tersimpan. Body: {ssid}"""
        if wifi_manager is None:
            return _wifi_unavailable()
        data = request.get_json(silent=True) or {}
        result = wifi_manager.forget(data.get('ssid', ''))
        return jsonify(result), (200 if result.get('success') else 400)
    
    @app.route('/api/wifi/connectivity')
    def wifi_connectivity():
        """Deteksi koneksi Pi: WiFi / LAN / keduanya."""
        if wifi_manager is None:
            return _wifi_unavailable()
        lan_iface = config.get('wifi.lan_interface', 'eth0')
        return jsonify(wifi_manager.connectivity(lan_iface=lan_iface))
    
    @app.route('/api/wifi/access')
    def wifi_access():
        """Daftar alamat URL untuk mengakses web (AP, WiFi lokal, LAN)."""
        if wifi_manager is None:
            return _wifi_unavailable()
        web_port = config.get('web.port', 5000)
        ap_ip = config.get('wifi.ap_ip', '192.168.50.1')
        lan_iface = config.get('wifi.lan_interface', 'eth0')
        return jsonify(wifi_manager.access_addresses(
            web_port=web_port, ap_ip=ap_ip, lan_iface=lan_iface))
    
    @app.route('/api/wifi/ap', methods=['GET'])
    def wifi_ap_get():
        """Baca konfigurasi WiFi AP saat ini (SSID, password, channel)."""
        if wifi_manager is None:
            return _wifi_unavailable()
        return jsonify(wifi_manager.get_ap_config())
    
    @app.route('/api/wifi/ap', methods=['POST'])
    def wifi_ap_set():
        """Ubah SSID/password WiFi AP. Body: {ssid?, password?}"""
        if wifi_manager is None:
            return _wifi_unavailable()
        data = request.get_json(silent=True) or {}
        result = wifi_manager.set_ap_config(
            ssid=data.get('ssid'),
            password=data.get('password'),
        )
        return jsonify(result), (200 if result.get('success') else 400)
    
    @app.route('/api/wifi/captive', methods=['GET'])
    def wifi_captive_get():
        """Baca konfigurasi captive portal tersimpan."""
        return jsonify({
            'success': True,
            'enabled':        config.get('captive_portal.enabled', False),
            'url':            config.get('captive_portal.url', ''),
            'username_field': config.get('captive_portal.username_field', 'username'),
            'password_field': config.get('captive_portal.password_field', 'password'),
            'username':       config.get('captive_portal.username', ''),
            'password':       config.get('captive_portal.password', ''),
            'auto_login':     config.get('captive_portal.auto_login', False),
        })

    @app.route('/api/wifi/captive', methods=['POST'])
    def wifi_captive_save():
        """Simpan konfigurasi captive portal. Body: {url, username_field, password_field, username, password, enabled, auto_login}"""
        data = request.get_json(silent=True) or {}
        fields = {
            'captive_portal.enabled':        bool(data.get('enabled', False)),
            'captive_portal.url':            str(data.get('url', '')).strip(),
            'captive_portal.username_field': str(data.get('username_field', 'username')).strip() or 'username',
            'captive_portal.password_field': str(data.get('password_field', 'password')).strip() or 'password',
            'captive_portal.username':       str(data.get('username', '')).strip(),
            'captive_portal.password':       str(data.get('password', '')),
            'captive_portal.auto_login':     bool(data.get('auto_login', False)),
        }
        for k, v in fields.items():
            config.set(k, v)
        ok = config.save()
        if ok:
            return jsonify({'success': True, 'message': 'Konfigurasi captive portal disimpan'})
        return jsonify({'success': False, 'message': 'Gagal menyimpan konfigurasi'}), 500

    @app.route('/api/wifi/captive/login', methods=['POST'])
    def wifi_captive_login():
        """Coba login ke captive portal dengan konfigurasi tersimpan (atau override dari body)."""
        if wifi_manager is None:
            return _wifi_unavailable()
        data = request.get_json(silent=True) or {}
        url            = data.get('url')            or config.get('captive_portal.url', '')
        username_field = data.get('username_field') or config.get('captive_portal.username_field', 'username')
        password_field = data.get('password_field') or config.get('captive_portal.password_field', 'password')
        username       = data.get('username')       or config.get('captive_portal.username', '')
        password       = data.get('password')       or config.get('captive_portal.password', '')
        result = wifi_manager.captive_login(url, username_field, password_field, username, password)
        return jsonify(result), (200 if result.get('success') else 400)

    @app.route('/api/wifi/captive/check', methods=['GET'])
    def wifi_captive_check():
        """
        Cek apakah internet sudah bisa diakses dan deteksi URL captive portal
        secara otomatis (seperti Windows/macOS).
        """
        if wifi_manager is None:
            return _wifi_unavailable()
        ok = wifi_manager.check_internet()
        if ok:
            return jsonify({
                'success': True,
                'internet': True,
                'portal_url': None,
                'message': 'Internet aktif',
            })
        # Internet belum aktif — coba deteksi URL portal otomatis
        portal_url = wifi_manager.detect_captive_portal_url()
        return jsonify({
            'success': True,
            'internet': False,
            'portal_url': portal_url,
            'message': (
                f'Captive portal terdeteksi: {portal_url}'
                if portal_url else
                'Captive portal terdeteksi (URL tidak dapat dideteksi otomatis)'
            ),
        })

    # ===== MODEL MANAGEMENT API (upload/pilih/hapus model YOLO) =====
    def _model_unavailable():
        return jsonify({
            'success': False,
            'message': 'Manajemen model tidak tersedia.'
        }), 503
    
    def _reject_model_op_if_cleaning():
        """Tolak operasi model (upload/select) saat pembersihan aktif.
        Memuat model YOLO menyita CPU sesaat — hindari saat siklus berjalan
        agar timing verifikasi pembersihan tidak terganggu."""
        busy = (getattr(controller, 'cleaning_in_progress', False)
                or getattr(controller, 'waiting_for_esp32', False))
        if busy:
            return jsonify({
                'success': False,
                'blocked': True,
                'message': 'Pembersihan sedang berlangsung. Tunggu hingga selesai '
                           'sebelum mengubah model (mencegah gangguan timing).'
            }), 423
        return None
    
    @app.route('/api/models')
    def models_list():
        """Daftar model per stage + status aktif."""
        if model_manager is None:
            return _model_unavailable()
        return jsonify(model_manager.list_models())
    
    @app.route('/api/models/upload', methods=['POST'])
    def models_upload():
        """
        Upload model .pt. Form-data: file=<.pt>, stage=detection|classification.
        Memvalidasi isi file sebagai model YOLO dan mencocokkan jenis dgn stage.
        """
        if model_manager is None:
            return _model_unavailable()
        blocked = _reject_model_op_if_cleaning()
        if blocked:
            return blocked
        stage = request.form.get('stage', '')
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'Tidak ada file diunggah'}), 400
        f = request.files['file']
        if not f or not f.filename:
            return jsonify({'success': False, 'message': 'Nama file kosong'}), 400
        if not f.filename.lower().endswith('.pt'):
            return jsonify({'success': False, 'message': 'File harus .pt'}), 400
        
        # Simpan ke file sementara dulu
        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(suffix='.pt')
        try:
            os.close(tmp_fd)
            f.save(tmp_path)
            result = model_manager.upload_model(stage, f.filename, tmp_path)
            return jsonify(result), (200 if result.get('success') else 400)
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
        finally:
            if os.path.exists(tmp_path):
                try: os.unlink(tmp_path)
                except OSError: pass
    
    @app.route('/api/models/select', methods=['POST'])
    def models_select():
        """Aktifkan model untuk stage + reload detector tanpa restart.
        Body: {stage, name}"""
        if model_manager is None:
            return _model_unavailable()
        blocked = _reject_model_op_if_cleaning()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        stage = data.get('stage', '')
        name = data.get('name', '')
        result = model_manager.select_model(stage, name)
        if not result.get('success'):
            return jsonify(result), 400
        
        # Reload model di detector (panel = detection, dirt = classification)
        det = getattr(controller, 'detector', None)
        if det is not None and hasattr(det, 'reload_model'):
            det_stage = 'panel' if stage == 'detection' else 'dirt'
            reload_res = det.reload_model(det_stage, result['path'])
            if not reload_res.get('success'):
                return jsonify({
                    'success': False,
                    'message': f"Model dipilih tapi gagal di-reload: {reload_res.get('message')}"
                }), 500
        return jsonify({'success': True, 'message': result['message']})
    
    @app.route('/api/models/delete', methods=['POST'])
    def models_delete():
        """Hapus model. Body: {stage, name}"""
        if model_manager is None:
            return _model_unavailable()
        data = request.get_json(silent=True) or {}
        result = model_manager.delete_model(data.get('stage', ''), data.get('name', ''))
        return jsonify(result), (200 if result.get('success') else 400)
    
    # ===== SYSTEM CONTROL API (restart aplikasi / reboot Raspberry Pi) =====
    def _verify_admin_password(password):
        """Verifikasi ulang password admin untuk aksi berisiko tinggi."""
        if not auth_enabled:
            return True
        return bool(admin_password_hash) and check_password_hash(admin_password_hash, password or '')
    
    def _reject_system_op_if_cleaning():
        """Tolak restart/reboot saat pembersihan aktif (motor/pompa bisa
        tertinggal di posisi tengah / menyala)."""
        busy = (getattr(controller, 'cleaning_in_progress', False)
                or getattr(controller, 'waiting_for_esp32', False))
        if busy:
            return jsonify({
                'success': False,
                'blocked': True,
                'message': 'Pembersihan sedang berlangsung. Tunggu hingga selesai '
                           'sebelum restart/reboot (mencegah aktuator berhenti di tengah siklus).'
            }), 423
        return None
    
    def _safe_stop_actuators():
        """Kirim perintah stop ke ESP32 agar motor & pompa mati sebelum
        aplikasi/sistem dimatikan. Best-effort (abaikan bila gagal)."""
        try:
            controller.esp32.send_and_receive("stop", timeout=1.5)
        except Exception:
            pass
    
    def _delayed_system_command(cmd_args, delay=1.5):
        """Jalankan perintah sistem setelah jeda singkat di thread terpisah,
        agar respons HTTP sempat terkirim ke browser lebih dulu."""
        import subprocess as _sp
        def _run():
            import time as _t
            _t.sleep(delay)
            try:
                _sp.run(cmd_args, capture_output=True, text=True, timeout=15, check=False)
            except Exception as e:
                print(f"[System] Gagal menjalankan {cmd_args}: {e}")
        threading.Thread(target=_run, daemon=True).start()
    
    @app.route('/api/system/restart_app', methods=['POST'])
    def system_restart_app():
        """Restart service aplikasi (solar-panel-cleaner). Body: {password}"""
        data = request.get_json(silent=True) or {}
        if not _verify_admin_password(data.get('password')):
            return jsonify({'success': False, 'message': 'Password salah'}), 401
        blocked = _reject_system_op_if_cleaning()
        if blocked:
            return blocked
        _safe_stop_actuators()
        # Restart service via systemctl (perlu izin sudoers)
        _delayed_system_command(['sudo', '-n', 'systemctl', 'restart', 'solar-panel-cleaner'])
        return jsonify({
            'success': True,
            'message': 'Aplikasi akan restart dalam beberapa detik. Halaman akan '
                       'terputus sebentar lalu sambungkan kembali.'
        })
    
    @app.route('/api/system/reboot', methods=['POST'])
    def system_reboot():
        """Reboot Raspberry Pi (OS penuh). Body: {password}"""
        data = request.get_json(silent=True) or {}
        if not _verify_admin_password(data.get('password')):
            return jsonify({'success': False, 'message': 'Password salah'}), 401
        blocked = _reject_system_op_if_cleaning()
        if blocked:
            return blocked
        _safe_stop_actuators()
        _delayed_system_command(['sudo', '-n', 'reboot'])
        return jsonify({
            'success': True,
            'message': 'Raspberry Pi sedang reboot. Tunggu ~1 menit lalu '
                       'sambungkan kembali ke jaringan robot.'
        })
    
    @app.route('/api/trigger', methods=['POST'])
    def trigger_cleaning():
        """Manual trigger cleaning"""
        # Block if already cleaning
        if _is_cleaning_active():
            return jsonify({'success': False, 'message': 'Pembersihan sudah berjalan'}), 423
        
        # Block if PID logging active
        if hasattr(controller, 'pid_logger') and controller.pid_logger.is_logging:
            return jsonify({'success': False, 'message': 'PID logging aktif — hentikan dulu'}), 423
        
        data = request.json
        zone = data.get('zone', 0)
        # Default score 100 -> CLEAN_LIGHT (wiper + brush, tanpa semprot, 1 pass)
        # Score < 70 will be rejected by ESP32 as "panel bersih"
        # User can override via request body
        weighted_score = data.get('weighted_score', 100)
        is_test = bool(data.get('test', False))  # True = demo dari Testing (tidak masuk log/report)
        
        print(f"[DEBUG] /api/trigger received: zone={zone}, weighted_score={weighted_score}, test={is_test}", flush=True)
        
        try:
            controller._start_cleaning_cycle(zone, weighted_score, test=is_test)
            return jsonify({'success': True, 'message': f'Pembersihan dimulai (score={weighted_score})'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/stop', methods=['POST'])
    def stop_cleaning():
        """Stop cleaning"""
        controller.esp32.stop_cleaning()
        return jsonify({'success': True})

    @app.route('/api/detect_and_clean', methods=['POST'])
    def detect_and_clean():
        """Tangkap gambar -> deteksi YOLO -> bersihkan NYATA (dicatat) bila kotor.

        Untuk tombol 'Bersihkan Manual': score_before = hasil deteksi asli, dan
        level pembersihan ditentukan deteksi (bukan dipaksa). Melewati cooldown.
        """
        if _is_cleaning_active():
            return jsonify({'success': False, 'message': 'Pembersihan sudah berjalan'}), 423
        if hasattr(controller, 'pid_logger') and controller.pid_logger.is_logging:
            return jsonify({'success': False, 'message': 'PID logging aktif - hentikan dulu'}), 423
        if not controller.esp32.is_alive():
            return jsonify({'success': False, 'message': 'ESP32 tidak terhubung'}), 423
        try:
            result = controller.detect_and_clean()
            code = 200 if result.get('success') else 400
            return jsonify(result), code
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    
    @app.route('/api/preview/stream')
    def preview_stream():
        """
        MJPEG stream endpoint — browser opens ONE persistent HTTP connection,
        server pushes frames continuously. Replaces polling /api/preview every 2s.
        Usage: <img src="/api/preview/stream">
        """
        def generate():
            while True:
                if not controller.preview_active:
                    # Send a blank/placeholder frame when preview is off
                    time.sleep(0.5)
                    continue

                # Check if camera is available
                if controller.camera is None:
                    # Generate "No Camera" placeholder frame
                    placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                    placeholder[:] = (40, 40, 40)  # Dark gray background
                    cv2.putText(placeholder, 'NO CAMERA', (150, 250),
                                cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 200), 3)
                    _, buffer = cv2.imencode('.jpg', placeholder)
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'
                    )
                    time.sleep(2)  # Slow refresh when no camera
                    continue

                with controller._camera_lock:
                    if controller.camera is None:
                        time.sleep(0.5)
                        continue
                    frame = controller.camera.capture()
                if frame is None:
                    # Camera might have disconnected — will be caught by _enrich_status
                    time.sleep(0.5)
                    continue

                # Draw YOLO overlay if detection mode is on
                if getattr(controller, 'preview_detection', False) and \
                        controller.detector.panel_model is not None:
                    try:
                        result = controller.detector.detect(frame)
                        if result.get('panel_detected') and result.get('panel_bbox'):
                            x1, y1, x2, y2 = result['panel_bbox']
                            conf      = result.get('panel_confidence', 0)
                            dirt      = result.get('dirt_level', 'unknown')
                            dirt_conf = result.get('dirt_confidence', 0)
                            score     = result.get('weighted_score', 0)

                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 3)
                            # Satu label gabungan di sisi atas (1 baris): panel + dirt
                            if dirt != 'unknown':
                                label = f'Panel {conf*100:.0f}% | {dirt} {dirt_conf*100:.0f}% S:{score:.0f}'
                            else:
                                label = f'Panel {conf*100:.0f}%'
                            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                            # Label DI DALAM kotak (di bawah garis atas) agar tidak keluar frame
                            cv2.rectangle(frame, (x1, y1), (x1 + tw + 10, y1 + th + 12), (0, 255, 0), -1)
                            cv2.putText(frame, label, (x1 + 5, y1 + th + 6),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
                        else:
                            cv2.putText(frame, 'No panel detected', (20, 40),
                                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    except Exception as e:
                        print(f"Stream detection error: {e}")

                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                frame_bytes = buffer.tobytes()

                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n'
                )

                time.sleep(0.1)  # ~10 FPS max — enough for monitoring

        return Response(
            generate(),
            mimetype='multipart/x-mixed-replace; boundary=frame'
        )

    @app.route('/api/preview')
    def preview():
        """
        Single-frame preview (JSON + base64) — kept for compatibility.
        For live preview use /api/preview/stream (MJPEG).
        """
        if not controller.preview_active:
            return jsonify({'image': None, 'preview_active': False})

        if controller.camera is None:
            return jsonify({'image': None, 'error': 'Kamera tidak terdeteksi', 'preview_active': True})

        frame = controller.camera.capture()
        if frame is None:
            return jsonify({'error': 'Tidak ada frame'}), 500

        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        img_base64 = base64.b64encode(buffer).decode()
        return jsonify({
            'image': f'data:image/jpeg;base64,{img_base64}',
            'preview_active': True
        })
    
    @app.route('/api/preview/toggle', methods=['POST'])
    def toggle_preview():
        """Toggle camera preview ON/OFF (controls streaming, not hardware)"""
        controller.preview_active = not controller.preview_active
        with controller._status_lock:
            controller.current_status['preview_active'] = controller.preview_active
        return jsonify({
            'success': True,
            'preview_active': controller.preview_active
        })
    
    @app.route('/api/preview/detection/toggle', methods=['POST'])
    def toggle_preview_detection():
        """Toggle YOLO detection overlay on preview"""
        current = getattr(controller, 'preview_detection', False)
        controller.preview_detection = not current
        return jsonify({
            'success': True,
            'preview_detection': controller.preview_detection
        })
    
    # ===== TESTING API ENDPOINTS =====
    
    # Global test lock — prevents concurrent test commands
    _test_lock = threading.Lock()
    
    def _is_cleaning_active():
        """Check if automatic cleaning is in progress"""
        return getattr(controller, 'cleaning_in_progress', False) or getattr(controller, 'waiting_for_esp32', False)
    
    def _reject_if_cleaning():
        """Return error response if cleaning is active, None otherwise"""
        if _is_cleaning_active():
            return jsonify({
                'success': False, 
                'blocked': True,
                'message': 'Pembersihan otomatis sedang berlangsung. Testing tidak dapat dilakukan hingga selesai.'
            }), 423  # 423 Locked
        return None
    
    def _reject_if_busy():
        """Reject if cleaning active OR another test is running"""
        blocked = _reject_if_cleaning()
        if blocked:
            return blocked
        if _test_lock.locked():
            return jsonify({
                'success': False,
                'blocked': True,
                'message': 'Test lain sedang berjalan. Tunggu hingga selesai.'
            }), 423
        return None
    
    @app.route('/api/test/cleaning_lock')
    def check_cleaning_lock():
        """Check if testing is locked due to active cleaning"""
        return jsonify({
            'locked': _is_cleaning_active(),
            'cleaning_active': getattr(controller, 'cleaning_in_progress', False),
            'waiting_esp32': getattr(controller, 'waiting_for_esp32', False),
            'attempts': getattr(controller, 'cleaning_attempts', 0)
        })
    
    @app.route('/api/test/esp32/connection')
    def test_esp32_connection():
        """Test ESP32 connection"""
        try:
            # Check serial port is open
            if not controller.esp32.serial or not controller.esp32.serial.is_open:
                return jsonify({
                    'success': False,
                    'message': 'Serial port not open'
                })
            
            # Atomic send + receive (no collision)
            response = controller.esp32.send_and_receive("status", timeout=2.0)
            
            if response:
                return jsonify({
                    'success': True,
                    'message': f'ESP32 connected on {controller.esp32.port}',
                    'esp32_state': response.get('state', 'unknown')
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'ESP32 not responding (no JSON response)'
                })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/esp32/motor_wiper', methods=['POST'])
    def test_motor_wiper():
        """Test motor wiper — mode naik/turun dengan proteksi limit switch.

        Pengaman utama ada di firmware ESP32 (checkSafety, loop 100Hz): wiper
        berhenti otomatis saat menyentuh LS sesuai arah (naik->LS1, turun->LS2).
        Polling di sini hanya cadangan + untuk pesan status ke UI.
        """
        blocked = _reject_if_busy()
        if blocked: return blocked
        try:
            import time
            data = request.get_json(silent=True) or {}
            arah = str(data.get('direction', 'naik')).strip().lower()
            going_up = arah in ('naik', 'up', '1')
            direction = 1 if going_up else 0  # 1=naik (LS1), 0/-1=turun (LS2)
            speed = float(data.get('speed', 40))
            target_ls = 'ls1' if going_up else 'ls2'
            which_label = 'LS1 (atas)' if going_up else 'LS2 (bawah)'
            arah_label = 'naik' if going_up else 'turun'

            # Jangan gerakkan bila sudah di ujung tujuan
            st0 = controller.esp32.send_and_receive("status", timeout=1.0)
            if st0 and st0.get(target_ls, False):
                return jsonify({
                    'success': True,
                    'message': f'Wiper sudah di {which_label} - tidak digerakkan'
                })

            # Start wiper sesuai arah
            ack = controller.esp32.send_and_receive(
                "mulai_wiper", timeout=2.0, speed=speed, direction=direction)
            if not ack:
                return jsonify({'success': False, 'message': 'ESP32 not responding'})

            # Poll: berhenti saat LS tujuan aktif (cadangan; firmware sudah jaga)
            MAX_DURATION = 6.0   # cukup untuk full travel ~80 cm
            POLL_INTERVAL = 0.1
            start = time.time()
            ls_triggered = False

            while time.time() - start < MAX_DURATION:
                time.sleep(POLL_INTERVAL)
                status = controller.esp32.send_and_receive("status", timeout=0.5)
                if status and status.get(target_ls, False):
                    ls_triggered = True
                    print(f"[TestWiper] {which_label} aktif - menghentikan motor")
                    break

            # Stop motor (firmware mungkin sudah stop di LS; ini memastikan)
            controller.esp32.send_and_receive("berhenti_wiper", timeout=1.0)

            if ls_triggered:
                return jsonify({
                    'success': True,
                    'message': f'Wiper {arah_label} selesai - berhenti di {which_label}'
                })
            else:
                return jsonify({
                    'success': True,
                    'message': f'Wiper {arah_label} selesai ({MAX_DURATION:.0f} detik, LS belum tercapai)'
                })
        except Exception as e:
            # Safety: pastikan motor berhenti meski ada error
            try: controller.esp32.send_and_receive("berhenti_wiper", timeout=1.0)
            except: pass
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/esp32/homing', methods=['POST'])
    def test_homing():
        """Homing wiper ke posisi atas (LS1 = home).

        Menggerakkan wiper NAIK sampai menyentuh LS1. Pengaman LS di firmware
        (checkSafety) menghentikan motor otomatis di LS1. Berguna untuk
        mengembalikan carriage ke titik acuan sebelum/sesudah pengujian.
        """
        blocked = _reject_if_busy()
        if blocked: return blocked
        try:
            import time
            speed = 45.0  # kecepatan transit homing

            # Sudah di atas (LS1)? tidak perlu gerak
            st0 = controller.esp32.send_and_receive("status", timeout=1.0)
            if st0 and st0.get('ls1', False):
                return jsonify({'success': True, 'message': 'Sudah di posisi home (LS1 atas)'})

            ack = controller.esp32.send_and_receive(
                "mulai_wiper", timeout=2.0, speed=speed, direction=1)  # 1 = naik
            if not ack:
                return jsonify({'success': False, 'message': 'ESP32 not responding'})

            MAX_DURATION = 8.0   # cukup untuk full travel dari bawah
            POLL_INTERVAL = 0.1
            start = time.time()
            reached = False
            while time.time() - start < MAX_DURATION:
                time.sleep(POLL_INTERVAL)
                status = controller.esp32.send_and_receive("status", timeout=0.5)
                if status and status.get('ls1', False):
                    reached = True
                    break

            controller.esp32.send_and_receive("berhenti_wiper", timeout=1.0)

            if reached:
                return jsonify({'success': True, 'message': 'Homing selesai - wiper di posisi home (LS1 atas)'})
            return jsonify({'success': True, 'message': 'Homing selesai (8 detik, LS1 belum tercapai - cek limit switch)'})
        except Exception as e:
            try: controller.esp32.send_and_receive("berhenti_wiper", timeout=1.0)
            except: pass
            return jsonify({'success': False, 'message': str(e)})

    @app.route('/api/test/esp32/motor_brush', methods=['POST'])
    def test_motor_brush():
        """Test motor brush — putar singkat (open-loop, tanpa LS)."""
        blocked = _reject_if_busy()
        if blocked: return blocked
        try:
            data = request.get_json(silent=True) or {}
            # Default 150 RPM agar jelas berputar (50 RPM kadang tak cukup
            # menembus gesekan statis sikat). Bisa di-override dari request.
            speed = float(data.get('speed', 150))
            ack = controller.esp32.send_and_receive("mulai_sikat", timeout=2.0, speed=speed)

            if not ack:
                return jsonify({'success': False, 'message': 'ESP32 not responding'})

            import time
            time.sleep(3)

            controller.esp32.send_and_receive("berhenti_sikat", timeout=1.0)

            return jsonify({
                'success': True,
                'message': f'Motor sikat test selesai ({speed:.0f} RPM, 3 detik)'
            })
        except Exception as e:
            try: controller.esp32.send_and_receive("berhenti_sikat", timeout=1.0)
            except: pass
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/esp32/pump', methods=['POST'])
    def test_pump():
        """Test water pump — send pump_on with duration, ESP32 handles auto-off"""
        blocked = _reject_if_busy()
        if blocked: return blocked
        try:
            data = request.get_json(silent=True) or {}
            duration = data.get('duration', 3000)  # Default 3 seconds
            
            ack = controller.esp32.send_and_receive("pompa_nyala", timeout=2.0, duration=duration)
            
            if ack:
                return jsonify({
                    'success': True,
                    'message': f'Pompa menyala {duration/1000:.0f} detik (auto-off oleh ESP32)',
                    'duration': duration
                })
            else:
                return jsonify({'success': False, 'message': 'ESP32 tidak merespons'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/esp32/limit_switches')
    def test_limit_switches():
        """Test limit switches"""
        try:
            status = controller.esp32.send_and_receive("status", timeout=2.0)
            if status and 'ls1' in status:
                return jsonify({
                    'success': True,
                    'ls1': status.get('ls1', False),
                    'ls2': status.get('ls2', False)
                })
            else:
                return jsonify({'success': False, 'message': 'ESP32 not responding'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/esp32/encoder')
    def test_encoder():
        """Test encoder — sample for 2 seconds server-side, return best reading"""
        try:
            import time as _time
            DURATION = 2.0
            INTERVAL = 0.2
            best_rpm = 0
            last_pulses = 0
            start = _time.time()
            
            while _time.time() - start < DURATION:
                status = controller.esp32.send_and_receive("status", timeout=1.0)
                if status and 'wiper_rpm' in status:
                    rpm = status.get('wiper_rpm', 0)
                    if rpm > best_rpm:
                        best_rpm = rpm
                    last_pulses = status.get('position', 0)
                _time.sleep(INTERVAL)
            
            return jsonify({
                'success': True,
                'rpm': best_rpm,
                'pulses': last_pulses
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/esp32/cleaning_cycle', methods=['POST'])
    def test_cleaning_cycle():
        """Start full cleaning cycle test — score=100 (CLEAN_LIGHT: wiper + brush, tanpa semprot)"""
        blocked = _reject_if_busy()
        if blocked: return blocked
        try:
            # score=100 -> CLEAN_LIGHT: wiper + brush, 1 pass, tanpa semprot (sikat kering).
            # ESP32 menolak score < 70 sebagai panel bersih.
            # Aman untuk verifikasi mekanik tanpa menyemprotkan air.
            ack = controller.esp32.send_and_receive(
                "siklus_pembersihan", timeout=3.0,
                zone=0, score=100.0
            )
            
            if ack:
                return jsonify({
                    'success': True,
                    'message': 'Cleaning cycle started (ringan, score=100: wiper + brush 1 pass, tanpa semprot)'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'ESP32 not responding'
                })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/esp32/cleaning_status')
    def test_cleaning_status():
        """Poll ESP32 cleaning progress — returns state, progress, and whether done/error"""
        try:
            status = controller.esp32.send_and_receive("status", timeout=2.0)
            
            if not status:
                return jsonify({'success': False, 'message': 'ESP32 not responding'})
            
            raw_status = status.get('status', 'idle')
            state      = status.get('state', 'IDLE')
            progress   = status.get('progress', 0)
            
            # ESP32 sends "done" once via sendCompletion, then immediately returns to IDLE.
            # By the time we poll, it may already be "idle" with progress=100 or progress=0.
            # Treat idle+progress=100 as done, and idle+progress=0 only as done if
            # the state name is SELESAI (DONE state before transitioning back to IDLE).
            is_done = (
                raw_status == 'done' or
                (raw_status == 'idle' and progress >= 100) or
                (raw_status == 'idle' and state in ('SELESAI', 'DONE'))
            )
            
            return jsonify({
                'success': True,
                'state': state,
                'progress': progress,
                'esp32_status': 'done' if is_done else raw_status,
                'wiper_rpm': status.get('wiper_rpm', 0),
                'brush_rpm': status.get('brush_rpm', 0),
                'pump': status.get('pump', False),
                'ls1': status.get('ls1', False),
                'ls2': status.get('ls2', False),
                'error': status.get('error'),
                'message': status.get('message')
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/camera')
    def test_camera():
        """Test camera"""
        try:
            frame = controller.camera.capture()
            if frame is not None:
                height, width = frame.shape[:2]
                return jsonify({
                    'success': True,
                    'width': width,
                    'height': height
                })
            else:
                return jsonify({'success': False, 'message': 'Cannot capture frame'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/yolo')
    def test_yolo():
        """Test YOLO model"""
        try:
            detector = controller.detector
            if hasattr(detector, 'panel_model') and detector.panel_model:
                return jsonify({
                    'success': True,
                    'type': 'two_stage',
                    'panel_model': detector.panel_model_path,
                    'dirt_model': detector.dirt_model_path
                })
            else:
                return jsonify({'success': False, 'message': 'Model not loaded'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/detection', methods=['POST'])
    def test_detection():
        """Test detection — capture frame, run two-stage YOLO, return annotated image"""
        try:
            # Reuse manual_capture which: captures, runs two-stage YOLO,
            # draws bounding boxes, updates last_detection, returns base64 image
            result = controller.manual_capture()
            if result is None:
                return jsonify({'success': False, 'message': 'Kamera tidak tersedia atau gagal capture'})
            
            # Pick first zone result (or the single result)
            results = result.get('results', [])
            if not results:
                return jsonify({'success': False, 'message': 'Tidak ada hasil deteksi'})
            
            r = results[0]
            return jsonify({
                'success': True,
                'panel_detected':  r.get('panel_detected', False),
                'dirt_level':      r.get('dirt_level', 'unknown'),
                'dirt_confidence': r.get('dirt_confidence', 0.0),
                'weighted_score':  r.get('weighted_score', 0.0),
                'clean':           r.get('clean', True),
                'image':           result.get('image')   # base64 annotated frame
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/serial')
    def test_serial():
        """Test serial communication — verifikasi ESP32 benar-benar membalas,
        bukan sekadar port serial terbuka (penting untuk UART hardware yang
        port-nya selalu terbuka walau pin RX/TX tidak tersambung)."""
        try:
            # Port harus terbuka dulu
            if not (controller.esp32.serial and controller.esp32.serial.is_open):
                return jsonify({'success': False, 'message': 'Serial port tidak terbuka'})

            # Verifikasi handshake: kirim status, harus ada balasan JSON
            response = controller.esp32.send_and_receive("status", timeout=2.0)
            if response:
                return jsonify({
                    'success': True,
                    'port': controller.esp32.port,
                    'baudrate': controller.esp32.baudrate,
                    'message': f'Komunikasi serial OK pada {controller.esp32.port}'
                })
            else:
                return jsonify({
                    'success': False,
                    'port': controller.esp32.port,
                    'message': f'Port {controller.esp32.port} terbuka, tetapi ESP32 tidak merespons '
                               '(periksa kabel RX/TX atau ESP32 belum menyala)'
                })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/test/config')
    def test_config():
        """Test configuration — show all key system parameters"""
        try:
            return jsonify({
                'success': True,
                'zones': len(config.zones),
                'trigger_threshold': config.get('cleaning.trigger_threshold', 70),
                'monitor_interval': config.get('cleaning.monitor_interval', 300),
                'cooldown': config.get('cleaning.cooldown_after_success', 300),
                'max_attempts': config.get('cleaning.cycles.max_attempts', 5),
                'verify_delay': config.get('cleaning.cycles.verify_delay', 2),
                'panel_confidence': config.get('detection.panel_confidence', 0.7),
                'dirt_confidence': config.get('detection.dirt_confidence', 0.7),
                'panel_model': config.get('detection.panel_model_path', 'N/A'),
                'dirt_model': config.get('detection.dirt_model_path', 'N/A'),
                'camera_device': config.get('camera.device_id', 0),
                'camera_resolution': config.get('camera.resolution', [1920, 1080]),
                'serial_port': config.get('serial.port', '/dev/serial0'),
                'serial_baudrate': config.get('serial.baudrate', 115200)
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    # ===== ACTIVITY LOG / REPORT API =====
    
    @app.route('/api/report/log')
    def get_activity_log():
        """Get activity log for report page"""
        try:
            log = controller.get_activity_log()
            return jsonify({'success': True, 'log': log, 'count': len(log)})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/report/clear', methods=['POST'])
    def clear_activity_log():
        """Clear activity log (memori + file persist)"""
        try:
            if hasattr(controller, 'clear_activity_log'):
                controller.clear_activity_log()
            else:
                controller.activity_log.clear()
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    # ===== CLEANING SESSION LOG (riwayat siklus pembersihan) =====
    
    @app.route('/api/cleaning/sessions')
    def get_cleaning_sessions():
        """Daftar sesi pembersihan + ringkasan agregat per level."""
        try:
            cl = getattr(controller, 'cleaning_logger', None)
            if cl is None:
                return jsonify({'success': False, 'message': 'Cleaning logger tidak aktif'})
            return jsonify({
                'success': True,
                'sessions': cl.get_sessions(),
                'summary': cl.get_summary(),
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/cleaning/export', methods=['POST'])
    def export_cleaning_report():
        """Ekspor laporan siklus pembersihan (CSV/JSON/TXT)."""
        try:
            cl = getattr(controller, 'cleaning_logger', None)
            if cl is None:
                return jsonify({'success': False, 'message': 'Cleaning logger tidak aktif'})
            files = cl.export_report()
            return jsonify({'success': True, 'files': files})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/cleaning/clear', methods=['POST'])
    def clear_cleaning_sessions():
        """Kosongkan riwayat sesi pembersihan."""
        try:
            cl = getattr(controller, 'cleaning_logger', None)
            if cl is None:
                return jsonify({'success': False, 'message': 'Cleaning logger tidak aktif'})
            n = cl.clear()
            return jsonify({'success': True, 'removed': n})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/cleaning/download/<path:filepath>')
    def cleaning_download(filepath):
        """Unduh file laporan pembersihan (aman: dibatasi folder)."""
        from flask import send_file, abort
        file_path = os.path.abspath(filepath)
        allowed_dirs = [
            os.path.abspath('analysis_output/cleaning'),
            os.path.abspath('logs/cleaning'),
        ]
        if not any(file_path.startswith(d) for d in allowed_dirs):
            abort(403, 'Access denied')
        if not os.path.isfile(file_path):
            abort(404, 'File tidak ditemukan')
        return send_file(file_path, as_attachment=True)
    
    # ===== UJI KEANDALAN KOMUNIKASI SERIAL UART =====
    
    if not hasattr(controller, '_uart_test_state'):
        controller._uart_test_state = {
            'running': False, 'done': 0, 'total': 0,
            'result': None, 'error': None,
        }
    _uart_test_lock = threading.Lock()
    
    def _run_uart_test_thread(count, interval):
        st = controller._uart_test_state
        try:
            def _cb(done, total):
                st['done'] = done
                st['total'] = total
            result = controller.esp32.reliability_test(
                count=count, interval=interval, progress_cb=_cb,
            )
            st['result'] = result
            st['error'] = None
        except Exception as e:
            st['error'] = str(e)
        finally:
            st['running'] = False
    
    @app.route('/api/serial/reliability/start', methods=['POST'])
    def serial_reliability_start():
        """Mulai uji keandalan UART (background). Diblokir saat cleaning."""
        blocked = _reject_if_busy()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        try:
            count = int(data.get('count', 100))
            interval = float(data.get('interval', 0.2))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Parameter tidak valid'})
        count = max(10, min(count, 1000))
        interval = max(0.0, min(interval, 2.0))
        
        # Wajib ESP32 hidup
        if not controller.esp32.is_alive():
            return jsonify({'success': False,
                            'message': 'ESP32 tidak terhubung — uji dibatalkan'})
        
        with _uart_test_lock:
            if controller._uart_test_state.get('running'):
                return jsonify({'success': False, 'message': 'Uji sedang berjalan'})
            controller._uart_test_state = {
                'running': True, 'done': 0, 'total': count,
                'result': None, 'error': None,
            }
            t = threading.Thread(target=_run_uart_test_thread,
                                 args=(count, interval), daemon=True)
            t.start()
        return jsonify({'success': True, 'message': f'Uji UART dimulai ({count} perintah)'})
    
    @app.route('/api/serial/reliability/status')
    def serial_reliability_status():
        """Status uji keandalan UART + hasil bila selesai."""
        st = controller._uart_test_state
        resp = {
            'success': True,
            'running': st.get('running', False),
            'done': st.get('done', 0),
            'total': st.get('total', 0),
            'error': st.get('error'),
        }
        if not st.get('running') and st.get('result'):
            resp['result'] = st['result']
        return jsonify(resp)

    # ===== UJI SISTEM KOMUNIKASI JARINGAN (latensi, beban, uptime) =====
    def _net_build_targets(data):
        """Bangun target ping per mode dari body request + auto-detect gateway."""
        from app.network_test import default_gateway
        targets = {}
        gw = default_gateway()
        if gw:
            targets["WiFi Client (gateway)"] = gw
        ap_client = (data.get('ap_client') or '').strip()
        if ap_client:
            targets["WiFi AP (klien)"] = ap_client
        cf = (data.get('cloudflare_host') or config.get('network.cloudflare_host', '') or '').strip()
        if cf:
            cf = cf.replace('https://', '').replace('http://', '').split('/')[0]
            targets["Cloudflare"] = cf
        return targets

    if not hasattr(controller, '_net_test_state'):
        controller._net_test_state = {'running': False, 'done': 0, 'total': 0,
                                      'result': None, 'error': None}
    _net_test_lock = threading.Lock()

    def _run_net_test_thread(count, targets, urls):
        st = controller._net_test_state
        try:
            from app.network_test import NetworkTester
            nt = NetworkTester(targets)

            def _cb(d, t):
                st['done'] = d
                st['total'] = t
            lat = nt.latency_test(count=count, progress_cb=_cb)
            load = nt.http_load_test(urls)
            files = nt.generate_report(latency=lat, load=load, prefix="network_latency")
            st['result'] = {'latency': lat, 'load': load, 'files': files}
            st['error'] = None
        except Exception as e:
            st['error'] = str(e)
        finally:
            st['running'] = False

    @app.route('/api/network/test/start', methods=['POST'])
    def network_test_start():
        """Mulai uji latensi + waktu muat (background). Diblokir saat cleaning."""
        blocked = _reject_if_busy()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        try:
            count = int(data.get('count', 30))
        except (ValueError, TypeError):
            count = 30
        count = max(5, min(count, 200))
        targets = _net_build_targets(data)
        if not targets:
            return jsonify({'success': False,
                            'message': 'Tidak ada target. Isi cloudflare_host / ap_client, '
                                       'atau pastikan gateway terdeteksi.'})
        web_port = config.get('web.port', 5000)
        urls = {'Dashboard lokal': f'http://127.0.0.1:{web_port}/'}
        cf_url = (data.get('cloudflare_url') or '').strip()
        if cf_url:
            urls['Dashboard Cloudflare'] = cf_url
        with _net_test_lock:
            if controller._net_test_state.get('running'):
                return jsonify({'success': False, 'message': 'Uji jaringan sedang berjalan'})
            controller._net_test_state = {'running': True, 'done': 0,
                                          'total': count * len(targets),
                                          'result': None, 'error': None}
            threading.Thread(target=_run_net_test_thread,
                             args=(count, targets, urls), daemon=True).start()
        return jsonify({'success': True,
                        'message': f'Uji jaringan dimulai ({len(targets)} target x {count} ping)',
                        'targets': list(targets.keys())})

    @app.route('/api/network/test/status')
    def network_test_status():
        st = controller._net_test_state
        resp = {'success': True, 'running': st.get('running', False),
                'done': st.get('done', 0), 'total': st.get('total', 0),
                'error': st.get('error')}
        if not st.get('running') and st.get('result'):
            resp['result'] = st['result']
        return jsonify(resp)

    if not hasattr(controller, '_net_uptime_state'):
        controller._net_uptime_state = {'running': False, 'elapsed': 0, 'duration': 0,
                                        'result': None, 'error': None, 'stop': False}
    _net_uptime_lock = threading.Lock()

    def _run_net_uptime_thread(duration_sec, interval_sec, targets):
        st = controller._net_uptime_state
        try:
            from app.network_test import NetworkTester
            nt = NetworkTester(targets)

            def _cb(e, t):
                st['elapsed'] = e
                st['duration'] = t
            res = nt.uptime_monitor(duration_sec, interval_sec=interval_sec,
                                    progress_cb=_cb, stop_flag=lambda: st.get('stop'))
            files = nt.generate_report(uptime=res, prefix="network_uptime")
            st['result'] = {'uptime': res, 'files': files}
            st['error'] = None
        except Exception as e:
            st['error'] = str(e)
        finally:
            st['running'] = False

    @app.route('/api/network/uptime/start', methods=['POST'])
    def network_uptime_start():
        """Mulai monitor uptime/downtime (background, durasi menit)."""
        data = request.get_json(silent=True) or {}
        try:
            duration_min = float(data.get('duration_min', 60))
            interval_sec = float(data.get('interval_sec', 60))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Parameter tidak valid'})
        duration_min = max(1, min(duration_min, 1440))   # maks 24 jam
        interval_sec = max(5, min(interval_sec, 300))
        targets = _net_build_targets(data)
        if not targets:
            return jsonify({'success': False, 'message': 'Tidak ada target jaringan.'})
        with _net_uptime_lock:
            if controller._net_uptime_state.get('running'):
                return jsonify({'success': False, 'message': 'Monitor uptime sedang berjalan'})
            controller._net_uptime_state = {'running': True, 'elapsed': 0,
                                            'duration': int(duration_min * 60),
                                            'result': None, 'error': None, 'stop': False}
            threading.Thread(target=_run_net_uptime_thread,
                             args=(int(duration_min * 60), interval_sec, targets),
                             daemon=True).start()
        return jsonify({'success': True,
                        'message': f'Monitor uptime dimulai ({duration_min:.0f} menit)',
                        'targets': list(targets.keys())})

    @app.route('/api/network/uptime/status')
    def network_uptime_status():
        st = controller._net_uptime_state
        resp = {'success': True, 'running': st.get('running', False),
                'elapsed': st.get('elapsed', 0), 'duration': st.get('duration', 0),
                'error': st.get('error')}
        if not st.get('running') and st.get('result'):
            resp['result'] = st['result']
        return jsonify(resp)

    @app.route('/api/network/uptime/stop', methods=['POST'])
    def network_uptime_stop():
        controller._net_uptime_state['stop'] = True
        return jsonify({'success': True, 'message': 'Monitor uptime dihentikan'})

    @app.route('/api/ping')
    def api_ping():
        """Endpoint super-ringan untuk ukur latensi round-trip dari browser klien."""
        return jsonify({'ok': True})

    @app.route('/api/network/browser_latency', methods=['POST'])
    def network_browser_latency():
        """Simpan hasil latensi yang diukur dari browser klien (per mode akses)."""
        data = request.get_json(silent=True) or {}
        mode = str(data.get('mode', 'akses'))[:50]
        stats = data.get('stats') or {}
        from app.network_test import OUT_DIR
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        p = OUT_DIR / f'network_browser_latency_{ts}.txt'
        lines = [
            '=' * 56,
            'LATENSI AKSES (diukur dari BROWSER klien, round-trip HTTP)',
            '=' * 56,
            f'Timestamp : {ts}',
            f'Mode      : {mode}',
            '',
            f"Mean : {stats.get('mean', '-')} ms",
            f"Min  : {stats.get('min', '-')} ms",
            f"Max  : {stats.get('max', '-')} ms",
            f"Std  : {stats.get('std', '-')} ms",
            f"N    : {stats.get('n', '-')}",
            '',
            f"Baris LaTeX: Latensi {mode}: {stats.get('mean', '-')} ms",
            '=' * 56,
        ]
        p.write_text('\n'.join(lines), encoding='utf-8')
        return jsonify({'success': True, 'files': {'txt': str(p)}})

    # ===== MANAJEMEN PORT SERIAL (Settings) =====
    
    @app.route('/api/serial/ports')
    def serial_list_ports():
        """Daftar port serial tersedia + port aktif & mode saat ini."""
        try:
            ports = controller.esp32.list_available_ports()
            return jsonify({
                'success': True,
                'ports': ports,
                'active_port': getattr(controller.esp32, 'port', None),
                'configured': getattr(controller.esp32, 'configured_port', 'auto'),
                'auto_mode': getattr(controller.esp32, 'auto_mode', False),
                'alive': controller.esp32.is_alive(),
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/serial/test_port', methods=['POST'])
    def serial_test_port():
        """Uji satu port (handshake) tanpa mengganggu koneksi aktif."""
        blocked = _reject_if_busy()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        port = (data.get('port') or '').strip()
        if not port:
            return jsonify({'success': False, 'message': 'Port wajib diisi'})
        try:
            result = controller.esp32.test_port(port)
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/serial/set_port', methods=['POST'])
    def serial_set_port():
        """Pindah & simpan port serial (persist ke settings.yaml). Diblokir saat cleaning."""
        blocked = _reject_if_busy()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        port = (data.get('port') or '').strip()
        if not port:
            return jsonify({'success': False, 'message': 'Port wajib diisi'})
        try:
            # Pindah koneksi runtime
            result = controller.esp32.switch_port(port)
            # Persist ke config
            config.set('serial.port', port)
            config.save()
            result['saved'] = True
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    # ===== PERFORMANCE MONITORING API =====
    
    @app.route('/api/performance/stats')
    def get_performance_stats():
        """Get real-time performance statistics"""
        try:
            stats = controller.detector.get_performance_stats()
            if stats:
                return jsonify({'success': True, 'stats': stats})
            else:
                return jsonify({'success': False, 'message': 'Performance logging not enabled'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/system/info')
    def get_system_info_endpoint():
        """
        Info sistem Raspberry Pi (uptime, suhu, RAM, CPU, throttling).
        Selalu tersedia walau performance logging belum aktif / belum ada deteksi.
        """
        try:
            from app.performance_logger import get_system_info
            return jsonify({'success': True, 'system': get_system_info()})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    def _rel_download_path(abs_or_rel_path):
        """Ubah path file hasil menjadi path relatif (forward slash) untuk
        endpoint /api/performance/download. Mengembalikan None bila gagal."""
        try:
            if not abs_or_rel_path:
                return None
            rel = os.path.relpath(os.path.abspath(abs_or_rel_path), os.path.abspath('.'))
            return rel.replace('\\', '/')
        except Exception:
            return None

    @app.route('/api/performance/report', methods=['POST'])
    def generate_performance_report():
        """Generate comprehensive performance report"""
        try:
            report = controller.detector.generate_performance_report()
            if not report:
                return jsonify({'success': False, 'message': 'Performance logging belum aktif'})
            # generate_summary_report() mengembalikan {'error': ...} bila belum ada data
            if isinstance(report, dict) and report.get('error'):
                return jsonify({'success': False, 'message': report['error']})
            # Path file JSON report agar bisa diunduh langsung dari browser (remote)
            json_path = (report.get('files') or {}).get('json') if isinstance(report, dict) else None
            return jsonify({
                'success': True,
                'report': report,
                'download_path': _rel_download_path(json_path),
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/performance/export', methods=['POST'])
    def export_performance_data():
        """Export performance data"""
        try:
            result = controller.detector.export_performance_for_bab4()
            if not result:
                return jsonify({'success': False, 'message': 'Performance logging belum aktif / belum ada data deteksi'})
            # File laporan teks (LaTeX-friendly) sebagai unduhan utama
            latex_path = result.get('latex_file') if isinstance(result, dict) else None
            return jsonify({
                'success': True,
                'files': result,
                'download_path': _rel_download_path(latex_path),
            })
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    # ===== BENCHMARK INFERENSI (via web) =====
    
    # State benchmark disimpan di controller agar lintas-request
    if not hasattr(controller, '_benchmark_state'):
        controller._benchmark_state = {
            'running': False, 'done': 0, 'total': 0,
            'result': None, 'error': None, 'started_at': None,
        }
    _benchmark_lock = threading.Lock()
    
    def _run_benchmark_thread(runs, warmup):
        """Worker benchmark di background thread."""
        import numpy as np
        from app.performance_logger import run_inference_benchmark
        st = controller._benchmark_state
        try:
            # Ambil 1 frame dari kamera (thread-safe), fallback dummy
            frame = None
            source = "synthetic 1920x1080 (dummy)"
            try:
                with controller._camera_lock:
                    if controller.camera is not None:
                        frame = controller.camera.capture()
                        if frame is not None:
                            source = f"kamera ({frame.shape[1]}x{frame.shape[0]})"
            except Exception:
                frame = None
            if frame is None:
                frame = (np.random.rand(1080, 1920, 3) * 255).astype('uint8')
            
            def _cb(done, total):
                st['done'] = done
                st['total'] = total
            
            payload = run_inference_benchmark(
                controller.detector, frame, runs=runs, warmup=warmup,
                source=source, progress_cb=_cb,
            )
            st['result'] = payload
            st['error'] = None
        except Exception as e:
            st['error'] = str(e)
        finally:
            st['running'] = False
    
    @app.route('/api/performance/benchmark/start', methods=['POST'])
    def benchmark_start():
        """Mulai benchmark inferensi (background). Diblokir saat cleaning."""
        blocked = _reject_if_busy()
        if blocked:
            return blocked
        data = request.get_json(silent=True) or {}
        try:
            runs = int(data.get('runs', 100))
            warmup = int(data.get('warmup', 5))
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'runs/warmup harus angka'})
        runs = max(10, min(runs, 500))      # batasi 10-500
        warmup = max(0, min(warmup, 50))
        
        with _benchmark_lock:
            if controller._benchmark_state.get('running'):
                return jsonify({'success': False, 'message': 'Benchmark sedang berjalan'})
            if controller.detector.panel_model is None or controller.detector.dirt_model is None:
                return jsonify({'success': False, 'message': 'Model belum dimuat'})
            controller._benchmark_state = {
                'running': True, 'done': 0, 'total': runs,
                'result': None, 'error': None, 'started_at': time.time(),
            }
            t = threading.Thread(target=_run_benchmark_thread,
                                 args=(runs, warmup), daemon=True)
            t.start()
        return jsonify({'success': True, 'message': f'Benchmark dimulai ({runs} iterasi)'})
    
    @app.route('/api/performance/benchmark/status')
    def benchmark_status():
        """Status benchmark + hasil bila selesai."""
        st = controller._benchmark_state
        resp = {
            'success': True,
            'running': st.get('running', False),
            'done': st.get('done', 0),
            'total': st.get('total', 0),
            'error': st.get('error'),
        }
        if not st.get('running') and st.get('result'):
            resp['result'] = st['result']
        return jsonify(resp)
    
    # ===== DAFTAR & DOWNLOAD FILE HASIL (performance) =====
    
    @app.route('/api/performance/files')
    def performance_files():
        """Daftar file hasil performance & benchmark untuk diunduh dari web."""
        import glob
        items = []
        empty_count = 0
        search_dirs = ['analysis_output/performance', 'logs/performance', 'analysis_output/network']
        for d in search_dirs:
            base = os.path.abspath(d)
            if not os.path.isdir(base):
                continue
            for path in glob.glob(os.path.join(base, '*')):
                if not os.path.isfile(path):
                    continue
                try:
                    stat = os.stat(path)
                    rel = os.path.relpath(path, os.path.abspath('.'))
                    name = os.path.basename(path)
                    # Kategori untuk filter di UI
                    if name.startswith('inference_benchmark'):
                        category = 'benchmark'
                    elif name.startswith('network_'):
                        category = 'network'
                    elif name.startswith('session') or name.startswith('performance_report'):
                        category = 'report'
                    else:
                        category = 'metrics'
                    is_empty = name.startswith('metrics_') and stat.st_size < 200
                    if is_empty:
                        empty_count += 1
                    items.append({
                        'name': name,
                        'path': rel.replace('\\', '/'),
                        'size_kb': round(stat.st_size / 1024, 1),
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        'category': category,
                        'empty': is_empty,
                    })
                except OSError:
                    continue
        items.sort(key=lambda x: x['modified'], reverse=True)
        return jsonify({'success': True, 'files': items, 'empty_count': empty_count})
    
    @app.route('/api/performance/download/<path:filepath>')
    def performance_download(filepath):
        """Unduh file hasil performance/benchmark (aman: dibatasi folder)."""
        from flask import send_file, abort
        file_path = os.path.abspath(filepath)
        allowed_dirs = [
            os.path.abspath('analysis_output/performance'),
            os.path.abspath('logs/performance'),
            os.path.abspath('analysis_output/network'),
        ]
        if not any(file_path.startswith(d) for d in allowed_dirs):
            abort(403, 'Access denied — file di luar direktori yang diizinkan')
        if not os.path.isfile(file_path):
            abort(404, 'File tidak ditemukan')
        return send_file(file_path, as_attachment=True)
    
    @app.route('/api/performance/files/delete', methods=['POST'])
    def performance_delete_file():
        """Hapus file hasil (aman: dibatasi folder). Admin-only via before_request."""
        data = request.get_json(silent=True) or {}
        rel = data.get('path', '')
        action = data.get('action', 'one')
        allowed_dirs = [
            os.path.abspath('analysis_output/performance'),
            os.path.abspath('logs/performance'),
            os.path.abspath('analysis_output/network'),
        ]
        
        # Hapus banyak file kosong sekaligus (metrics CSV header-only)
        if action == 'empty':
            import glob
            removed = 0
            for d in allowed_dirs:
                for path in glob.glob(os.path.join(d, 'metrics_*.csv')):
                    try:
                        # CSV "kosong" = hanya header (≤ 1 baris) atau < 200 byte
                        if os.path.getsize(path) < 200:
                            os.remove(path)
                            removed += 1
                    except OSError:
                        continue
            return jsonify({'success': True, 'removed': removed,
                            'message': f'{removed} file kosong dihapus'})
        
        # Hapus SEMUA file hasil (opsional difilter per kategori sesuai dropdown)
        if action == 'all':
            import glob
            category = (data.get('category') or 'all').lower()

            def _cat(name):
                if name.startswith('inference_benchmark'):
                    return 'benchmark'
                if name.startswith('network_'):
                    return 'network'
                if name.startswith('session') or name.startswith('performance_report'):
                    return 'report'
                return 'metrics'

            removed = 0
            for d in allowed_dirs:
                if not os.path.isdir(d):
                    continue
                for path in glob.glob(os.path.join(d, '*')):
                    if not os.path.isfile(path):
                        continue
                    if category not in ('all', '') and _cat(os.path.basename(path)) != category:
                        continue
                    try:
                        os.remove(path)
                        removed += 1
                    except OSError:
                        continue
            return jsonify({'success': True, 'removed': removed,
                            'message': f'{removed} file dihapus'})

        # Hapus satu file
        file_path = os.path.abspath(rel)
        if not any(file_path.startswith(d) for d in allowed_dirs):
            return jsonify({'success': False, 'message': 'Akses ditolak'}), 403
        if not os.path.isfile(file_path):
            return jsonify({'success': False, 'message': 'File tidak ditemukan'}), 404
        try:
            os.remove(file_path)
            return jsonify({'success': True, 'message': 'File dihapus'})
        except OSError as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/emergency_stop', methods=['POST'])
    def emergency_stop():
        """Emergency stop — stop ESP32, skip verification, return to monitoring"""
        try:
            # 1. Reset controller cleaning state LEBIH DULU. Ini WAJIB jalan walau
            #    pengiriman serial ke ESP32 gagal/lambat — supaya UI tidak terkunci.
            controller.cleaning_in_progress = False
            controller.waiting_for_esp32 = False
            controller._esp32_cmd_sent_time = None
            controller.cleaning_attempts = 0
            controller._cleaning_is_test = False  # matikan flag mode uji demo
            
            # Reset cooldown — start fresh after emergency stop
            controller._last_detection_cycle = datetime.now()
            controller._cooldown_paused = False
            
            with controller._status_lock:
                controller.current_status['cleaning_active'] = False
                controller.current_status['cleaning_attempts'] = 0
                controller.current_status['mode'] = 'monitoring'
                controller.current_status['progress'] = 0
                controller.current_status['esp32_state'] = 'IDLE'  # Default to IDLE state
                controller.current_status['wiper_rpm'] = 0
                controller.current_status['brush_rpm'] = 0
                controller.current_status['pump'] = False
            
            # 2. Kirim stop ke ESP32 (best-effort — kegagalan tidak boleh
            #    membatalkan reset state di atas).
            try:
                controller.esp32.stop_cleaning()
            except Exception as _e:
                print(f"[emergency_stop] gagal kirim stop ke ESP32: {_e}", flush=True)
            
            # 3. Log emergency stop
            if hasattr(controller, '_log_activity'):
                controller._log_activity('emergency_stop', 'EMERGENCY STOP — pembersihan dibatalkan, kembali ke monitoring')
            
            return jsonify({'success': True, 'message': 'Emergency stop executed. Kembali ke mode monitoring.'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    # ===== PID LOGGING API (HTTP fallback — prefer /ws/pid WebSocket) =====
    
    @app.route('/api/pid/start', methods=['POST'])
    def pid_start_logging():
        """Start PID data logging + start wiper motor at setpoint RPM"""
        blocked = _reject_if_busy()
        if blocked: return blocked
        try:
            data = request.json
            setpoint = data.get('setpoint', 30)
            test_name = data.get('test_name', 'step_response')
            
            # Initialize PID logger if not exists
            if not hasattr(controller, 'pid_logger'):
                from app.pid_logger import PIDLogger
                controller.pid_logger = PIDLogger()
            
            # Start wiper motor at setpoint RPM
            ack = controller.esp32.send_and_receive(
                "mulai_wiper", timeout=2.0, speed=setpoint, direction=1
            )
            if not ack:
                return jsonify({'success': False, 'message': 'ESP32 tidak merespons — motor tidak bisa dinyalakan'})
            
            # Start logging
            controller.pid_logger.start_logging(setpoint, test_name)
            
            return jsonify({'success': True, 'message': f'Motor started + logging @ {setpoint} RPM'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/pid/log', methods=['POST'])
    def pid_log_data():
        """Log a single PID data point"""
        try:
            data = request.json
            rpm = data.get('rpm', 0)
            pwm = data.get('pwm', 0)
            
            if hasattr(controller, 'pid_logger') and controller.pid_logger.is_logging:
                controller.pid_logger.log_data_point(rpm, pwm)
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'message': 'Logging not started'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/pid/stop', methods=['POST'])
    def pid_stop_logging():
        """Stop PID logging, stop wiper motor, and generate report"""
        try:
            # Stop wiper motor first
            controller.esp32.send_and_receive("berhenti_wiper", timeout=1.0)
            
            if hasattr(controller, 'pid_logger'):
                report = controller.pid_logger.stop_logging()
                if report:
                    return jsonify({'success': True, 'report': report})
                else:
                    return jsonify({'success': False, 'message': 'No active logging session'})
            else:
                return jsonify({'success': False, 'message': 'PID logger not initialized'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/pid/status')
    def pid_get_status():
        """Get PID logging status"""
        try:
            if hasattr(controller, 'pid_logger'):
                status = controller.pid_logger.get_status()
                return jsonify({'success': True, 'status': status})
            else:
                return jsonify({'success': True, 'status': {'is_logging': False}})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/pid/data')
    def pid_get_data():
        """Get current PID data buffer"""
        try:
            if hasattr(controller, 'pid_logger'):
                data = controller.pid_logger.get_current_data()
                return jsonify({'success': True, 'data': data})
            else:
                return jsonify({'success': True, 'data': []})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/pid/export', methods=['POST'])
    def pid_export():
        """Export PID data for report"""
        try:
            if hasattr(controller, 'pid_logger'):
                result = controller.pid_logger.export_for_report()
                if result:
                    return jsonify({'success': True, 'files': result})
                else:
                    return jsonify({'success': False, 'message': 'No data to export'})
            else:
                return jsonify({'success': False, 'message': 'PID logger not initialized'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    
    @app.route('/api/pid/download/<path:filepath>')
    def pid_download_file(filepath):
        """Download a PID export file (CSV, JSON, or TXT report)"""
        from flask import send_file, abort
        
        # Resolve relative to app working directory
        file_path = os.path.abspath(filepath)
        
        # Security: only allow files under logs/pid or analysis_output/pid
        allowed_dirs = [
            os.path.abspath('logs/pid'),
            os.path.abspath('analysis_output/pid'),
        ]
        if not any(file_path.startswith(d) for d in allowed_dirs):
            abort(403, 'Access denied — file outside allowed directories')
        
        if not os.path.isfile(file_path):
            abort(404, 'File not found')
        
        return send_file(file_path, as_attachment=True)
    
    # ===== PERFORMANCE WEBSOCKET (replaces GET /api/performance/stats polling) =====
    
    @sock.route('/ws/performance')
    def performance_websocket_handler(ws):
        """
        Push performance stats every 2s via WebSocket.
        Replaces setInterval(updateStats, 2000) in performance.html.
        Info sistem RPi selalu dikirim walau logging belum aktif.
        """
        print('[WebSocket/Performance] Client connected')
        from app.performance_logger import get_system_info
        try:
            while True:
                try:
                    stats = controller.detector.get_performance_stats()
                    if stats:
                        # stats sudah memuat 'system' dari get_realtime_stats
                        ws.send(json.dumps({'success': True, 'stats': stats}))
                    else:
                        # Logging belum aktif (belum ada deteksi) — tetap kirim
                        # info sistem agar kartu RPi di halaman tetap hidup.
                        ws.send(json.dumps({
                            'success': False,
                            'message': 'Performance logging not enabled',
                            'system': get_system_info(),
                        }))
                except Exception as e:
                    ws.send(json.dumps({'success': False, 'message': str(e)}))
                time.sleep(2.0)
        except Exception as e:
            print(f'[WebSocket/Performance] Connection closed: {e}')
        finally:
            print('[WebSocket/Performance] Client disconnected')
    
    # ===== PID WEBSOCKET (real-time, replaces HTTP polling) =====
    
    @sock.route('/ws/pid')
    def pid_websocket_handler(ws):
        """
        WebSocket endpoint for PID data logging.
        
        Replaces 4x HTTP polling (encoder + pid/log + pid/data + pid/status)
        with a single persistent connection. A background thread reads encoder,
        logs data, and pushes updates to the client at ~200ms intervals.
        
        Client messages (JSON):
          { "type": "start", "setpoint": 30, "test_name": "step_response" }
          { "type": "stop" }
          { "type": "export" }
          { "type": "get_data" }
        
        Server pushes (JSON):
          { "type": "started", "success": true, "message": "..." }
          { "type": "stopped", "success": true, "report": {...} }
          { "type": "pid_data", "data_point": {...}, "status": {...} }
          { "type": "exported", "success": true, "files": {...} }
          { "type": "error", "message": "..." }
        """
        print('[WebSocket/PID] Client connected')
        
        # Shared state between main thread and data-push thread
        pid_active = threading.Event()
        pid_stop_requested = threading.Event()
        connection_alive = threading.Event()
        connection_alive.set()
        
        def _send_json(data):
            """Thread-safe JSON send"""
            try:
                ws.send(json.dumps(data))
            except Exception:
                connection_alive.clear()
        
        def pid_data_loop():
            """Background thread: read encoder -> log -> push data at 200ms"""
            while connection_alive.is_set() and pid_active.is_set():
                try:
                    # 1. Read encoder from ESP32
                    esp32_status = controller.esp32.send_and_receive("status", timeout=1.0)
                    current_rpm = 0
                    if esp32_status and 'wiper_rpm' in esp32_status:
                        current_rpm = esp32_status.get('wiper_rpm', 0)
                    
                    # 2. Log data point
                    if hasattr(controller, 'pid_logger') and controller.pid_logger.is_logging:
                        controller.pid_logger.log_data_point(current_rpm, 0)
                        
                        # 3. Push latest data point + status
                        buf = controller.pid_logger.data_buffer
                        latest = buf[-1] if buf else None
                        status = controller.pid_logger.get_status()
                        
                        _send_json({
                            'type': 'pid_data',
                            'data_point': latest,
                            'total_points': len(buf),
                            'status': status
                        })
                    else:
                        # Logging was stopped externally
                        pid_active.clear()
                        _send_json({
                            'type': 'stopped',
                            'success': True,
                            'report': None,
                            'message': 'Logging stopped externally'
                        })
                        break
                    
                    time.sleep(0.2)  # 200ms interval (5Hz)
                    
                except Exception as e:
                    print(f'[WebSocket/PID] Data loop error: {e}')
                    _send_json({'type': 'error', 'message': str(e)})
                    time.sleep(0.5)
            
            print('[WebSocket/PID] Data loop ended')
        
        data_thread = None
        
        try:
            while True:
                # Blocking receive — waits for client commands
                message = ws.receive()
                if message is None:
                    break
                
                try:
                    data = json.loads(message)
                    msg_type = data.get('type', '')
                    
                    if msg_type == 'start':
                        # ---- START PID LOGGING ----
                        setpoint = data.get('setpoint', 30)
                        test_name = data.get('test_name', 'step_response')
                        
                        # Initialize PID logger if needed
                        if not hasattr(controller, 'pid_logger'):
                            from app.pid_logger import PIDLogger
                            controller.pid_logger = PIDLogger()
                        
                        # Start wiper motor
                        ack = controller.esp32.send_and_receive(
                            "mulai_wiper", timeout=2.0, speed=setpoint, direction=1
                        )
                        if not ack:
                            _send_json({
                                'type': 'started',
                                'success': False,
                                'message': 'ESP32 tidak merespons — motor tidak bisa dinyalakan'
                            })
                            continue
                        
                        # Start logging
                        controller.pid_logger.start_logging(setpoint, test_name)
                        
                        # Start background data push thread
                        pid_active.set()
                        pid_stop_requested.clear()
                        data_thread = threading.Thread(target=pid_data_loop, daemon=True)
                        data_thread.start()
                        
                        _send_json({
                            'type': 'started',
                            'success': True,
                            'message': f'Motor started + logging @ {setpoint} RPM'
                        })
                    
                    elif msg_type == 'stop':
                        # ---- STOP PID LOGGING ----
                        pid_active.clear()
                        
                        # Wait for data thread to finish
                        if data_thread and data_thread.is_alive():
                            data_thread.join(timeout=2.0)
                        
                        # Stop wiper motor
                        controller.esp32.send_and_receive("berhenti_wiper", timeout=1.0)
                        
                        report = None
                        if hasattr(controller, 'pid_logger'):
                            report = controller.pid_logger.stop_logging()
                        
                        _send_json({
                            'type': 'stopped',
                            'success': True,
                            'report': report,
                            'message': 'Logging stopped'
                        })
                    
                    elif msg_type == 'export':
                        # ---- EXPORT DATA ----
                        if hasattr(controller, 'pid_logger'):
                            result = controller.pid_logger.export_for_report()
                            if result:
                                _send_json({
                                    'type': 'exported',
                                    'success': True,
                                    'files': result
                                })
                            else:
                                _send_json({
                                    'type': 'exported',
                                    'success': False,
                                    'message': 'No data to export'
                                })
                        else:
                            _send_json({
                                'type': 'exported',
                                'success': False,
                                'message': 'PID logger not initialized'
                            })
                    
                    elif msg_type == 'get_data':
                        # ---- GET FULL BUFFER (one-time fetch for chart init) ----
                        if hasattr(controller, 'pid_logger'):
                            buf = controller.pid_logger.get_current_data()
                            status = controller.pid_logger.get_status()
                            _send_json({
                                'type': 'full_data',
                                'success': True,
                                'data': buf,
                                'status': status
                            })
                        else:
                            _send_json({
                                'type': 'full_data',
                                'success': True,
                                'data': [],
                                'status': {'is_logging': False}
                            })
                
                except json.JSONDecodeError:
                    _send_json({'type': 'error', 'message': 'Invalid JSON'})
        
        except Exception as e:
            print(f'[WebSocket/PID] Connection closed: {e}')
        finally:
            # Cleanup: stop data thread and motor if client disconnects mid-session
            connection_alive.clear()
            if pid_active.is_set():
                pid_active.clear()
                print('[WebSocket/PID] Client disconnected during logging — stopping motor')
                try:
                    controller.esp32.send_and_receive("berhenti_wiper", timeout=1.0)
                    if hasattr(controller, 'pid_logger') and controller.pid_logger.is_logging:
                        controller.pid_logger.stop_logging()
                except Exception:
                    pass
            if data_thread and data_thread.is_alive():
                data_thread.join(timeout=2.0)
            print('[WebSocket/PID] Client disconnected')
    
    return app  # Return only app (no socketio)
