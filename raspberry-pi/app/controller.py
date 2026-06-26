"""
Main Controller - Solar Panel Cleaning System

Controller utama yang mengatur alur kerja sistem:
1. Monitoring: Capture gambar -> Deteksi kotoran (YOLO two-stage)
2. Decision: Jika skor kotoran > threshold -> Trigger pembersihan
3. Cleaning: Kirim perintah ke ESP32 -> Tunggu selesai
4. Verification: Capture ulang -> Cek apakah sudah bersih
5. Repeat: Jika masih kotor, ulangi (max 5x)

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import time
import serial
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List
import threading
from collections import deque

from .camera import Camera
from .two_stage_detector import TwoStageDetector
from .serial_comm import ESP32Communicator
from .config import Config

class SolarPanelController:
    def __init__(self, config: Config):
        self.config = config
        self.running = False
        self.last_cleaning = None
        
        # Cooldown state: tracks interval between detection cycles
        self._last_detection_cycle = None  # When the last detection cycle completed
        self._cooldown_paused = False      # Paused during cleaning or hardware disconnect
        self._cooldown_pause_remaining = 0 # Remaining seconds when cooldown was paused
        self._active_cooldown_duration = 0 # Locked duration for current cooldown cycle
        
        # Cleaning state
        self.cleaning_in_progress = False
        self.cleaning_attempts = 0
        self.waiting_for_esp32 = False
        self._cleaning_is_test = False   # True = siklus dipicu dari demo Testing (jangan masuk log/report)
        self._esp32_cmd_sent_time = None
        self._esp32_last_status_time = None  # waktu terakhir terima status ESP32 saat cleaning
        self._last_verify_score = 0.0   # score hasil verifikasi terakhir (untuk logger)
        self._last_detect_time_s = 0.0  # durasi deteksi two-stage terakhir (untuk logger)
        # Pelacakan transisi koneksi ESP32 (untuk uji auto-reconnect serial)
        self._esp32_was_alive = None
        self._esp32_disconnect_time = None
        self._status_lock = threading.Lock()
        self._camera_lock = threading.Lock()  # Protect camera access across threads
        
        # Activity log (max 500 entries di memori) — DIPERSIST ke file agar
        # riwayat tetap ada setelah RPi mati/restart.
        self._activity_log_max = 500
        # Batas baris file persist: cegah file membengkak tak terbatas saat
        # operasi 24/7 (loop monitoring menulis tiap siklus). File di-trim
        # otomatis ke _activity_file_max baris terakhir.
        self._activity_file_max = 3000
        self._activity_write_count = 0
        self.activity_log: deque = deque(maxlen=self._activity_log_max)
        self._activity_log_dir = Path("logs/activity")
        self._activity_log_dir.mkdir(parents=True, exist_ok=True)
        self._activity_log_file = self._activity_log_dir / "activity_log.jsonl"
        self._activity_log_lock = threading.Lock()
        self._load_activity_log()
        
        # Cleaning session logger (riwayat siklus pembersihan untuk laporan)
        try:
            from app.cleaning_logger import CleaningSessionLogger
            self.cleaning_logger = CleaningSessionLogger()
        except Exception as _e:
            print(f"[Controller] CleaningSessionLogger tidak aktif: {_e}")
            self.cleaning_logger = None
        
        # Initialize components
        self.camera = None
        self._camera_config = {
            'device_id': config.get('camera.device_id', 0),
            'resolution': tuple(config.get('camera.resolution', [1920, 1080])),
            'auto_exposure': config.get('camera.auto_exposure', True),
            'brightness': config.get('camera.brightness', None),
            'gain': config.get('camera.gain', None),
            'exposure': config.get('camera.exposure', None)
        }
        self._camera_reconnect_running = False
        self._init_camera()
        
        # Start background camera reconnect if failed
        if self.camera is None:
            self._start_camera_reconnect()
        
        # Initialize two-stage detector
        # Path model: utamakan model AKTIF dari ModelManager (persist via web),
        # fallback ke path di settings.yaml.
        panel_path = config.get('detection.panel_model_path', 'models/panel_detection_best.pt')
        dirt_path = config.get('detection.dirt_model_path', 'models/dirt_classification_best.pt')
        try:
            from app.model_manager import ModelManager
            _mm = ModelManager(models_dir=config.get('models.dir', 'models'))
            _active_panel = _mm.get_active_path('detection')
            _active_dirt = _mm.get_active_path('classification')
            if _active_panel:
                panel_path = _active_panel
            if _active_dirt:
                dirt_path = _active_dirt
        except Exception as _e:
            print(f"[Controller] ModelManager tidak aktif, pakai path default: {_e}")
        
        self.detector = TwoStageDetector(
            panel_model_path=panel_path,
            dirt_model_path=dirt_path,
            panel_confidence=config.get('detection.panel_confidence', 0.7),
            dirt_confidence=config.get('detection.dirt_confidence', 0.7),
            enable_performance_logging=config.get('detection.enable_performance_logging', False)
        )
        print("[Controller] Using two-stage detection (Panel Detection -> Dirt Classification)")
        
        self.esp32 = ESP32Communicator(
            port=config.get('serial.port', '/dev/serial0'),
            baudrate=config.get('serial.baudrate', 115200)
        )
        
        self.preview_active = False  # Preview kamera ON/OFF dari dashboard
        self.preview_detection = False  # YOLO detection overlay pada preview
        
        self.current_status = {
            'running': False,
            'mode': 'monitoring',
            'last_capture': None,
            'last_detection': None,
            'cleaning_active': False,
            'cleaning_attempts': 0,
            'esp32_connected': self.esp32.connected,
            'last_cleaning': None,
            'cooldown_remaining': 0,
            'cooldown_start': None,
            'cooldown_duration': 0,
            'preview_active': False
        }
    
    def _init_camera(self):
        """Try to initialize camera, return True if successful"""
        try:
            self.camera = Camera(
                device_id=self._camera_config['device_id'],
                resolution=self._camera_config['resolution'],
                auto_exposure=self._camera_config['auto_exposure'],
                brightness=self._camera_config['brightness'],
                gain=self._camera_config['gain'],
                exposure=self._camera_config['exposure']
            )
            print("[Controller] Camera connected")
            return True
        except Exception as e:
            print(f"[Controller] Camera not available: {e}")
            self.camera = None
            return False
    
    def _start_camera_reconnect(self):
        """Start background thread to auto-reconnect camera"""
        if self._camera_reconnect_running:
            return
        self._camera_reconnect_running = True
        t = threading.Thread(target=self._camera_reconnect_loop, daemon=True)
        t.start()
        print("[Controller] Camera auto-reconnect started (retry every 10s)")
    
    def _camera_reconnect_loop(self):
        """Background loop that tries to reconnect camera every 10 seconds"""
        while self._camera_reconnect_running:
            if self.camera is not None:
                break
            time.sleep(10)
            if self.camera is not None:
                break
            if self._init_camera():
                break
        self._camera_reconnect_running = False
    
    def start(self):
        """Start monitoring loop"""
        if self.running:
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print("Solar panel monitoring started")
    
    def stop(self):
        """Stop monitoring loop and clean up resources"""
        self.running = False
        if hasattr(self, 'monitor_thread'):
            self.monitor_thread.join(timeout=5)
        if self.esp32:
            self.esp32.close()
        if self.camera:
            try:
                self.camera.release()
            except Exception:
                pass
        print("Solar panel monitoring stopped")
    
    def _within_working_hours(self) -> bool:
        """True jika waktu sekarang berada dalam jam kerja monitoring.

        Mengembalikan True bila fitur dinonaktifkan atau konfigurasi tidak valid
        (fail-safe: jangan memblokir operasi karena config rusak). Mendukung
        rentang yang melewati tengah malam (mis. 22:00-06:00).
        """
        if not self.config.get('monitoring.working_hours.enabled', True):
            return True
        start_s = str(self.config.get('monitoring.working_hours.start', '07:00'))
        stop_s = str(self.config.get('monitoring.working_hours.stop', '17:00'))
        try:
            from datetime import time as _time
            sh, sm = (int(x) for x in start_s.split(':')[:2])
            eh, em = (int(x) for x in stop_s.split(':')[:2])
            start_t = _time(sh, sm)
            stop_t = _time(eh, em)
        except Exception:
            return True
        now_t = datetime.now().time()
        if start_t <= stop_t:
            return start_t <= now_t <= stop_t
        # Rentang melewati tengah malam
        return now_t >= start_t or now_t <= stop_t

    def _monitor_loop(self):
        """Main monitoring loop with cleaning verification"""
        while self.running:
            try:
                # Read intervals fresh each iteration (config can change via dashboard)
                monitor_interval = self.config.get('cleaning.monitor_interval', 1)
                verify_interval = self.config.get('cleaning.verify_interval', 2)
                # === HARDWARE AVAILABILITY CHECK (fresh every iteration) ===
                camera_ready = self.camera is not None
                
                # Live ESP32 check: ESP32 dianggap siap HANYA jika benar-benar
                # membalas (handshake), bukan sekadar port serial terbuka.
                # Penting untuk UART hardware yang port-nya selalu terbuka walau
                # pin RX/TX tidak tersambung ke ESP32.
                esp32_ready = False
                try:
                    esp32_ready = self.esp32.is_alive()
                except (serial.SerialException, OSError, AttributeError):
                    esp32_ready = False
                if not esp32_ready:
                    self.esp32.connected = False
                    if not self.esp32._reconnect_running:
                        self.esp32._start_background_reconnect()

                # === LOG transisi koneksi ESP32 (uji auto-reconnect serial) ===
                # Catat saat PUTUS terdeteksi dan saat PULIH (+ durasi & attempt),
                # agar bisa dibaca dari activity log (halaman Report).
                if self._esp32_was_alive is None:
                    self._esp32_was_alive = esp32_ready
                if self._esp32_was_alive and not esp32_ready:
                    self._esp32_disconnect_time = datetime.now()
                    self._log_activity('esp32_disconnected',
                        'ESP32 terputus — memulai auto-reconnect',
                        {'disconnect_at': self._esp32_disconnect_time.isoformat()})
                elif (not self._esp32_was_alive) and esp32_ready:
                    dur = None
                    if self._esp32_disconnect_time is not None:
                        dur = round((datetime.now() - self._esp32_disconnect_time).total_seconds(), 2)
                    self._log_activity('esp32_reconnected',
                        (f'ESP32 pulih (durasi {dur} detik)' if dur is not None else 'ESP32 pulih'),
                        {'recovery_time_s': dur,
                         'reconnect_attempts': getattr(self.esp32, 'reconnect_attempts', None)})
                    self._esp32_disconnect_time = None
                self._esp32_was_alive = esp32_ready
                
                # Update mode based on hardware availability
                if not camera_ready:
                    # === Fase TREATMENT (ESP32 sedang bergerak): jangan abort ===
                    # Baca status ESP32 dan biarkan hardware selesai dulu.
                    # Fase VERIFIKASI (butuh kamera) baru dilewati setelah treatment selesai.
                    if self.waiting_for_esp32:
                        with self._status_lock:
                            self.current_status['mode'] = 'cleaning'
                        _nocam_silence_timeout = 30
                        if esp32_ready:
                            for response in self.esp32.read_all_responses():
                                self._handle_esp32_response(response)
                                if self.waiting_for_esp32:
                                    self._esp32_last_status_time = datetime.now()
                        if self.waiting_for_esp32:
                            if not esp32_ready:
                                self.waiting_for_esp32 = False
                                self._finish_cleaning(success=False)
                            else:
                                ref = self._esp32_last_status_time or self._esp32_cmd_sent_time
                                if ref and (datetime.now() - ref).total_seconds() > _nocam_silence_timeout:
                                    self.esp32.stop_cleaning()
                                    time.sleep(0.5)
                                    self.waiting_for_esp32 = False
                                    self._finish_cleaning(success=False)
                        time.sleep(0.1)
                        continue

                    # === Fase VERIFIKASI atau IDLE: kamera wajib ada ===
                    with self._status_lock:
                        self.current_status['mode'] = 'waiting_camera'
                        # Pause cooldown when camera disconnected
                        self.current_status['cooldown_start'] = None
                        self.current_status['cooldown_remaining'] = 0
                    # Abort hanya jika kamera hilang di fase verifikasi
                    if self.cleaning_in_progress:
                        print("[!] Camera tidak tersedia untuk verifikasi, akhiri siklus")
                        self._finish_cleaning(success=False)
                        # Don't start cooldown after camera-caused abort
                        self._last_detection_cycle = None
                        self._cooldown_paused = False
                    # Freeze cooldown — will resume from where it left off when camera returns
                    if self._last_detection_cycle and not self._cooldown_paused:
                        cd = self._active_cooldown_duration or self.config.get('cleaning.cooldown_after_success', 300)
                        self._cooldown_paused = True
                        self._cooldown_pause_remaining = max(0,
                            cd - (datetime.now() - self._last_detection_cycle).total_seconds())
                    if not self._camera_reconnect_running:
                        self._start_camera_reconnect()
                    time.sleep(2)
                    continue
                
                # Check ESP32 responses (even if ESP32 disconnected, drain buffer)
                esp32_silence_timeout = 30  # detik tanpa status ESP32 saat cleaning = dianggap hang
                if esp32_ready:
                    # Drain SEMUA status ESP32 yang menumpuk (ESP32 kirim 5Hz,
                    # loop lebih lambat) agar dashboard real-time & pesan penting
                    # (done/error/stopped) tidak terlewat.
                    for response in self.esp32.read_all_responses():
                        self._handle_esp32_response(response)
                        # Tiap respons = bukti ESP32 hidup → reset timer "diam".
                        if self.waiting_for_esp32:
                            self._esp32_last_status_time = datetime.now()
                
                # Check ESP32 timeout while waiting for cleaning to finish.
                # Pakai timeout berbasis "diam": selama ESP32 masih mengirim status
                # (10 Hz saat cleaning), siklus TIDAK di-abort — apa pun durasinya
                # (berat 2-pass ~120s pun aman). Abort hanya bila ESP32 benar-benar
                # senyap > esp32_silence_timeout (indikasi hang) atau terputus.
                if self.waiting_for_esp32:
                    if not esp32_ready:
                        # ESP32 disconnected during cleaning — abort
                        print("[!] ESP32 disconnected during cleaning, aborting")
                        self.waiting_for_esp32 = False
                        self._finish_cleaning(success=False)
                    else:
                        ref = self._esp32_last_status_time or self._esp32_cmd_sent_time
                        if ref:
                            silence = (datetime.now() - ref).total_seconds()
                            if silence > esp32_silence_timeout:
                                print(f"[!] ESP32 senyap {silence:.0f}s (>{esp32_silence_timeout}s), aborting cleaning", flush=True)
                                print(f"  → Sending STOP command to ESP32 to reset state", flush=True)
                                # Send stop command to reset ESP32 state back to IDLE
                                self.esp32.stop_cleaning()
                                time.sleep(0.5)  # Wait for ESP32 to process stop command
                                self.waiting_for_esp32 = False
                                self._finish_cleaning(success=False)
                    time.sleep(0.1)  # poll cepat saat cleaning agar status real-time (10Hz)
                    continue
                
                # Determine interval based on mode
                if self.cleaning_in_progress:
                    interval = verify_interval
                    with self._status_lock:
                        self.current_status['mode'] = 'verifying'
                else:
                    interval = monitor_interval
                    with self._status_lock:
                        if esp32_ready:
                            self.current_status['mode'] = 'monitoring'
                        else:
                            self.current_status['mode'] = 'detect_only'
                    
                    # === JAM KERJA MONITORING ===
                    # Di luar jam kerja, lewati deteksi/pembersihan (hemat daya & sesuai
                    # kondisi pencahayaan siang). Siklus pembersihan yang sedang berjalan
                    # tidak terpengaruh (ditangani di cabang verifying di atas).
                    if not self._within_working_hours():
                        wh_start = self.config.get('monitoring.working_hours.start', '07:00')
                        wh_stop = self.config.get('monitoring.working_hours.stop', '17:00')
                        with self._status_lock:
                            self.current_status['mode'] = 'off_hours'
                            self.current_status['working_hours'] = {
                                'start': wh_start, 'stop': wh_stop, 'active': False
                            }
                            self.current_status['cooldown_remaining'] = 0
                        time.sleep(30)
                        continue
                    else:
                        with self._status_lock:
                            self.current_status['working_hours'] = {
                                'start': self.config.get('monitoring.working_hours.start', '07:00'),
                                'stop': self.config.get('monitoring.working_hours.stop', '17:00'),
                                'active': True
                            }
                    
                    # === COOLDOWN CHECK (between detection cycles) ===
                    # Use locked duration for current cycle (changes apply next cycle)
                    cooldown = self._active_cooldown_duration or self.config.get('cleaning.cooldown_after_success', 300)
                    
                    # Pause cooldown when ESP32 disconnected
                    if not esp32_ready and self._last_detection_cycle and not self._cooldown_paused:
                        elapsed = (datetime.now() - self._last_detection_cycle).total_seconds()
                        self._cooldown_pause_remaining = max(0, cooldown - elapsed)
                        self._cooldown_paused = True
                        self._last_detection_cycle = None
                        print(f"[Cooldown] Paused with {self._cooldown_pause_remaining:.0f}s remaining")
                        with self._status_lock:
                            self.current_status['cooldown_start'] = None
                            self.current_status['cooldown_remaining'] = 0
                    
                    # While ESP32 disconnected and cooldown is paused, just wait
                    if not esp32_ready and self._cooldown_paused:
                        # Ensure reconnect thread is alive and running
                        if not self.esp32.connected:
                            reconnect_alive = (self.esp32._reconnect_thread is not None and 
                                             self.esp32._reconnect_thread.is_alive())
                            if not reconnect_alive:
                                self.esp32._reconnect_running = False  # Reset stale flag
                                self.esp32._start_background_reconnect()
                        time.sleep(1)
                        continue
                    
                    # Resume cooldown after hardware reconnect
                    if self._cooldown_paused and not self.cleaning_in_progress and camera_ready and esp32_ready:
                        if self._cooldown_pause_remaining > 0:
                            self._last_detection_cycle = datetime.now() - timedelta(
                                seconds=(cooldown - self._cooldown_pause_remaining))
                            with self._status_lock:
                                self.current_status['cooldown_start'] = self._last_detection_cycle.isoformat()
                                self.current_status['cooldown_duration'] = cooldown
                                self.current_status['cooldown_remaining'] = int(self._cooldown_pause_remaining)
                            print(f"[Cooldown] Resumed with {self._cooldown_pause_remaining:.0f}s remaining")
                        else:
                            self._last_detection_cycle = None
                            with self._status_lock:
                                self.current_status['cooldown_start'] = None
                                self.current_status['cooldown_remaining'] = 0
                        self._cooldown_paused = False
                        self._cooldown_pause_remaining = 0
                    
                    if self._last_detection_cycle and not self._cooldown_paused:
                        elapsed = (datetime.now() - self._last_detection_cycle).total_seconds()
                        remaining = max(0, cooldown - elapsed)
                        with self._status_lock:
                            self.current_status['cooldown_remaining'] = int(remaining)
                            self.current_status['cooldown_start'] = self._last_detection_cycle.isoformat()
                            self.current_status['cooldown_duration'] = cooldown
                        if remaining > 0:
                            time.sleep(1)
                            continue
                        # Cooldown finished — reset for next cycle
                        self._last_detection_cycle = None
                        self._active_cooldown_duration = 0
                        with self._status_lock:
                            self.current_status['cooldown_remaining'] = 0
                            self.current_status['cooldown_start'] = None
                    else:
                        with self._status_lock:
                            self.current_status['cooldown_remaining'] = 0
                            if self._cooldown_paused:
                                self.current_status['cooldown_start'] = None
                
                # === CAPTURE IMAGE (thread-safe) ===
                with self._camera_lock:
                    if self.camera is None:
                        time.sleep(interval)
                        continue
                    frame = self.camera.capture()
                
                if frame is None:
                    # Camera might have been unplugged
                    with self._camera_lock:
                        if self.camera is not None:
                            try:
                                if not self.camera.is_open:
                                    raise RuntimeError("Camera disconnected")
                            except Exception:
                                print("[Controller] Camera disconnected, releasing...")
                                try:
                                    self.camera.release()
                                except Exception:
                                    pass
                                self.camera = None
                                if not self._camera_reconnect_running:
                                    self._start_camera_reconnect()
                    time.sleep(interval)
                    continue
                
                with self._status_lock:
                    self.current_status['last_capture'] = datetime.now().isoformat()
                
                # Detect dirt (with None protection) — ukur durasi deteksi untuk logger
                zones = self.config.zones
                _detect_t0 = time.perf_counter()
                try:
                    if zones:
                        results = self.detector.detect_zones(frame, zones) or []
                    else:
                        result = self.detector.detect(frame)
                        results = [result] if result else []
                except Exception as e:
                    print(f"[Controller] Detection error: {e}")
                    results = []
                self._last_detect_time_s = round(time.perf_counter() - _detect_t0, 3)
                
                if not results:
                    time.sleep(interval)
                    continue
                
                with self._status_lock:
                    self.current_status['last_detection'] = {
                        'timestamp': datetime.now().isoformat(),
                        'results': results
                    }
                
                # Log detection result
                if results:
                    r = results[0]
                    self._log_activity('monitoring', 
                        f'Deteksi: {r.get("dirt_level", "unknown")} (score={r.get("weighted_score", 0):.1f})',
                        {
                            'panel_detected': r.get('panel_detected', False),
                            'category': r.get('dirt_level', 'unknown'),
                            'score': round(r.get('weighted_score', 0), 2),
                            'confidence': round(r.get('dirt_confidence', 0), 3),
                            'clean': r.get('clean', True)
                        }
                    )
                
                # Handle based on mode
                if self.cleaning_in_progress:
                    # Verifying cleaning result (needs ESP32 for next cycle)
                    if esp32_ready:
                        self._verify_cleaning_result(results)
                    else:
                        # ESP32 disconnected during verification — abort cleaning
                        print("[!] ESP32 disconnected, cannot verify cleaning")
                        self._finish_cleaning(success=False)
                else:
                    # Normal monitoring — only trigger cleaning if ESP32 is connected
                    if esp32_ready:
                        self._check_cleaning_trigger(results)
                    # else: detect_only mode — don't set cooldown (no point without ESP32)
                    
                    # If cooldown was just started, skip the long sleep
                    # and go straight to cooldown loop (1s updates)
                    if self._last_detection_cycle and not self._cooldown_paused:
                        cd = self._active_cooldown_duration or self.config.get('cleaning.cooldown_after_success', 300)
                        with self._status_lock:
                            self.current_status['cooldown_remaining'] = cd
                            self.current_status['cooldown_start'] = self._last_detection_cycle.isoformat()
                            self.current_status['cooldown_duration'] = cd
                        continue
                
            except Exception as e:
                print(f"Error in monitor loop: {e}")
            
            time.sleep(interval if not self.waiting_for_esp32 else 0.1)
    
    def _check_cleaning_trigger(self, results: list):
        """Check if cleaning should be triggered based on YOLO classification"""
        # Check each zone result — trigger if NOT clean
        any_dirty = False
        for result in results:
            is_clean = result.get('clean', True)
            weighted_score = result.get('weighted_score', 0)
            
            if not is_clean:
                any_dirty = True
                # Pause cooldown during cleaning process
                self._cooldown_paused = True
                
                # Start cleaning process
                zone_id = result.get('zone_id', 0)
                
                print(f"Dirt detected: score={weighted_score:.2f}")
                self._log_activity('detection', f'Kotoran terdeteksi: {result.get("dirt_level", "unknown")}', {
                    'score': round(weighted_score, 2),
                    'category': result.get('dirt_level', 'unknown'),
                    'confidence': round(result.get('dirt_confidence', 0), 3),
                    'panel_detected': result.get('panel_detected', False),
                    'clean': False
                })
                self._start_cleaning_cycle(zone_id, weighted_score)
                break
        
        if not any_dirty:
            # Panel is clean — start cooldown countdown from now
            self._last_detection_cycle = datetime.now()
            self._active_cooldown_duration = self.config.get('cleaning.cooldown_after_success', 300)
            self._cooldown_paused = False
    
    def _start_cleaning_cycle(self, zone: int, weighted_score: float, test: bool = False):
        """Start cleaning cycle — auto-stops PID logging if active to avoid motor conflict.

        test=True: siklus demo dari halaman Testing — treatment + verifikasi tetap
        berjalan, tetapi TIDAK dicatat ke activity log maupun cleaning report.
        """
        # Tandai mode uji lebih dulu agar seluruh _log_activity selama siklus di-skip.
        self._cleaning_is_test = bool(test)
        # Safety: stop PID logging first if active (PID uses wiper motor)
        if hasattr(self, 'pid_logger') and self.pid_logger is not None and self.pid_logger.is_logging:
            print("[Controller] PID logging aktif — menghentikan PID logger sebelum cleaning")
            self.esp32.send_and_receive("berhenti_wiper", timeout=1.0)
            report = self.pid_logger.stop_logging()
            self._log_activity('pid_interrupted', 'PID logging dihentikan otomatis karena cleaning cycle dimulai', {
                'data_points': report.get('data_points', 0) if report else 0
            })
        
        self.cleaning_in_progress = True
        self.cleaning_attempts = 0
        with self._status_lock:
            self.current_status['cleaning_active'] = True
            self.current_status['cleaning_attempts'] = 0
        
        # Mulai pencatatan sesi pembersihan (score awal disimpan untuk efektivitas).
        # Dilewati pada mode uji agar tidak masuk cleaning report.
        if self.cleaning_logger is not None and not test:
            try:
                self.cleaning_logger.start_session(weighted_score, detect_time_s=self._last_detect_time_s)
            except Exception as _e:
                print(f"[Controller] cleaning_logger.start_session gagal: {_e}")
        
        print(f"Starting cleaning cycle: zone={zone}, score={weighted_score:.2f}{' [TEST]' if test else ''}")
        self._log_activity('cleaning_start', f'Memulai pembersihan (score={weighted_score:.1f})', {
            'zone': zone, 'score': round(weighted_score, 2)
        })
        self._trigger_single_clean(zone, weighted_score)
    
    def _trigger_single_clean(self, zone: int, weighted_score: float):
        """Trigger single wiper cycle"""
        max_attempts = self.config.get('cleaning.cycles.max_attempts', 5)
        
        if self.cleaning_attempts >= max_attempts:
            print(f"Max cleaning attempts ({max_attempts}) reached. Stopping.", flush=True)
            self._finish_cleaning(success=False)
            return
        
        self.cleaning_attempts += 1
        with self._status_lock:
            self.current_status['cleaning_attempts'] = self.cleaning_attempts
        
        if self.cleaning_logger is not None:
            try:
                self.cleaning_logger.record_attempt()
            except Exception:
                pass
        
        self.waiting_for_esp32 = True
        self._esp32_cmd_sent_time = datetime.now()
        self._esp32_last_status_time = None  # reset timer diam; akan terisi saat status pertama tiba
        
        print(f"\n{'='*60}", flush=True)
        print(f"CLEANING ATTEMPT {self.cleaning_attempts}/{max_attempts}", flush=True)
        print(f"{'='*60}", flush=True)
        
        if self.esp32.trigger_cleaning_cycle(zone, weighted_score):
            print(f"✓ Command sent to ESP32: zone={zone}, score={weighted_score}", flush=True)
            print(f"  Waiting for ESP32 response...", flush=True)
        else:
            print("✗ Failed to send command to ESP32", flush=True)
            self.waiting_for_esp32 = False
            self._esp32_cmd_sent_time = None
    
    def _verify_cleaning_result(self, results: list):
        """Verify if cleaning was successful based on YOLO classification.
        Uses hysteresis: trigger at score >= 70, verify clean at score < 60
        to prevent oscillation around threshold."""
        max_attempts = self.config.get('cleaning.cycles.max_attempts', 5)
        # Verification threshold same as trigger (score gap between clean=0 and dirty≥91 is large enough)
        verify_clean_threshold = 70
        
        # Tandai mulai fase verifikasi (untuk ukur durasi verifikasi di logger)
        if self.cleaning_logger is not None:
            try:
                self.cleaning_logger.add_verify_time(self._last_detect_time_s)
            except Exception:
                pass
        
        # Guard: bila verifikasi TIDAK menemukan panel (results kosong, mis. karena
        # pencahayaan kurang / panel tak terdeteksi), JANGAN biarkan siklus
        # menggantung (cleaning_in_progress tetap true → UI terkunci selamanya).
        # Akhiri siklus dengan aman; monitoring akan mendeteksi ulang nanti.
        if not results:
            print("[Verify] Tidak ada panel terdeteksi saat verifikasi — akhiri siklus agar UI tidak terkunci.")
            self._log_activity('verification_no_panel',
                               'Verifikasi: panel tidak terdeteksi, siklus diakhiri')
            self._finish_cleaning(success=False)
            return
        
        for result in results:
            weighted_score = result.get('weighted_score', 0)
            is_verified_clean = weighted_score < verify_clean_threshold
            # Simpan score terakhir hasil verifikasi untuk pencatatan efektivitas
            self._last_verify_score = weighted_score
            
            print(f"Verification: score={weighted_score:.2f}, clean={is_verified_clean} (threshold<{verify_clean_threshold})")
            
            if is_verified_clean:
                print(f"Cleaning successful after {self.cleaning_attempts} attempts!")
                self._log_activity('verification_success', f'Panel bersih setelah {self.cleaning_attempts} percobaan', {
                    'score': round(weighted_score, 2), 'attempts': self.cleaning_attempts
                })
                self._finish_cleaning(success=True)
            else:
                # Still dirty — check if max attempts reached BEFORE triggering
                if self.cleaning_attempts >= max_attempts:
                    print(f"Max cleaning attempts ({max_attempts}) reached. Stopping.")
                    self._finish_cleaning(success=False)
                else:
                    # Trigger another cycle
                    zone_id = result.get('zone_id', 0)
                    print(f"Still dirty (score={weighted_score:.2f}), triggering another cycle...")
                    self._log_activity('verification_fail', f'Masih kotor (score={weighted_score:.1f}), ulangi pembersihan', {
                        'score': round(weighted_score, 2), 'attempt': self.cleaning_attempts
                    })
                    
                    # Wait a bit before next cycle
                    verify_delay = self.config.get('cleaning.cycles.verify_delay', 2)
                    time.sleep(verify_delay)
                    
                    self._trigger_single_clean(zone_id, weighted_score)
            
            break
    
    def _finish_cleaning(self, success: bool):
        """Finish cleaning process"""
        self.cleaning_in_progress = False
        self.waiting_for_esp32 = False
        self._esp32_cmd_sent_time = None
        
        # Catat sesi pembersihan ke logger (skenario + verifikasi + waktu siklus)
        if self.cleaning_logger is not None:
            try:
                max_attempts = self.config.get('cleaning.cycles.max_attempts', 5)
                rec = self.cleaning_logger.finish_session(
                    score_after=self._last_verify_score,
                    success=success,
                    max_attempts=max_attempts,
                )
                if rec:
                    self._log_activity('cleaning_session',
                        f"Sesi pembersihan {rec['level']} selesai "
                        f"({'berhasil' if success else 'gagal'}, "
                        f"{rec['attempts']}x, {rec['total_time_s']}s)", rec)
            except Exception as _e:
                print(f"[Controller] cleaning_logger.finish_session gagal: {_e}")
        
        with self._status_lock:
            self.current_status['cleaning_active'] = False
            self.current_status['mode'] = 'monitoring'
            # Reset ESP32 live fields
            self.current_status['progress'] = 0
            self.current_status['esp32_state'] = 'IDLE'  # Default to IDLE state
            self.current_status['wiper_rpm'] = 0
            self.current_status['brush_rpm'] = 0
            self.current_status['pump'] = False
        
        if success:
            self.last_cleaning = datetime.now()
            with self._status_lock:
                self.current_status['last_cleaning'] = self.last_cleaning.isoformat()
            print("Cleaning cycle completed successfully. Returning to monitoring mode.")
        else:
            print("Cleaning cycle failed. Returning to monitoring mode.")
        
        # Start cooldown after cleaning finishes (both success and fail)
        self._last_detection_cycle = datetime.now()
        self._active_cooldown_duration = self.config.get('cleaning.cooldown_after_success', 300)
        self._cooldown_paused = False

        # Selesai — matikan flag mode uji agar logging normal kembali aktif.
        self._cleaning_is_test = False
        
        # Reset attempts counter
        self.cleaning_attempts = 0
        with self._status_lock:
            self.current_status['cleaning_attempts'] = 0
    
    def _handle_esp32_response(self, response: Dict):
        """Handle response from ESP32"""
        status = response.get('status')
        
        # Log all ESP32 responses for debugging
        print(f"\n[ESP32 Response] {response}", flush=True)
        
        # Handle acknowledgment (ack field present)
        if 'ack' in response:
            print(f"  → ACK: {response['ack']}", flush=True)
            return
        
        # Merge ESP32 live data into current_status for dashboard
        # Accept ESP32 data if:
        # 1. Cleaning is active (cleaning_in_progress=True), OR
        # 2. Waiting for ESP32 response (waiting_for_esp32=True) - to handle initial status updates
        with self._status_lock:
            is_cleaning_active = self.current_status.get('cleaning_active', False)
            is_waiting_esp32 = self.waiting_for_esp32
            should_accept_data = is_cleaning_active or is_waiting_esp32
            
            # Always update these fields (hardware state, not cleaning-specific)
            for key in ['ls1', 'ls2', 'position']:
                if key in response:
                    self.current_status[key] = response[key]
                    print(f"  → {key}: {response[key]}", flush=True)
            
            # Update cleaning-related fields if we should accept ESP32 data
            if should_accept_data:
                for key in ['state', 'progress', 'wiper_rpm', 'wiper_target',
                            'brush_rpm', 'brush_target', 'pump',
                            'current_pass', 'total_passes', 'cleaning_level']:
                    if key in response:
                        dashboard_key = 'esp32_state' if key == 'state' else key
                        self.current_status[dashboard_key] = response[key]
                        print(f"  → {dashboard_key}: {response[key]}", flush=True)
            else:
                # Not waiting for ESP32 and cleaning not active - ignore stale data
                if 'progress' in response or 'state' in response:
                    print(f"  → Ignoring stale ESP32 data (not waiting, cleaning not active): progress={response.get('progress', 'N/A')}, state={response.get('state', 'N/A')}", flush=True)
            
            # Convert encoder position (pulses) to mm
            # Encoder quadrature: pulsa NEGATIF saat carriage TURUN dari home
            # (LS1 atas = 0). Faktor mm = KALIBRASI EMPIRIS dari pengukuran nyata:
            # full travel LS1->LS2 (~800 mm) = 19290 pulsa => 24,1 pulsa/mm.
            # (Gear ratio mekanis 1:100 per config.h; selisih dari nilai teoretis
            # 27,5 akibat glitch filter encoder membuang sebagian pulsa + toleransi
            # belt/pulley.) Tanda dibalik agar 0 mm = atas (home), ~800 mm di bawah.
            if 'position' in response:
                position_pulses = response['position']
                position_mm = max(0.0, -position_pulses / 24.1)  # 24,1 pulsa/mm (kalibrasi empiris)
                self.current_status['position_mm'] = round(position_mm, 1)
                print(f"  → position_mm: {position_mm:.1f} mm (from {position_pulses} pulses)", flush=True)
        
        if status == 'done':
            duration = response.get('duration', 0)
            print(f"ESP32: Wiper cycle completed ({duration}ms)")
            self._log_activity('esp32_done', f'ESP32 selesai ({duration}ms)', {'duration': duration})
            if self.cleaning_logger is not None:
                try:
                    self.cleaning_logger.record_cleaning_duration(float(duration))
                except Exception:
                    pass
            self.waiting_for_esp32 = False
            self._esp32_cmd_sent_time = None
            with self._status_lock:
                self.current_status['progress'] = 100
            
        elif status == 'cleaning':
            progress = response.get('progress', 0)
            state = response.get('state', '')
            print(f"ESP32: {state} ({progress}%)")
            
        elif status == 'error':
            error_code = response.get('error', 'unknown')
            error_msg = response.get('message', '')
            print(f"ESP32 error {error_code}: {error_msg}")
            self._log_activity('esp32_error', f'ESP32 error: {error_code} - {error_msg}')
            self.waiting_for_esp32 = False
            self._esp32_cmd_sent_time = None
            self._finish_cleaning(success=False)
        
        elif status == 'stopped':
            print("ESP32: Emergency stop executed, clearing cleaning state")
            self._log_activity('emergency_stop', 'Emergency stop dieksekusi oleh ESP32')
            self.waiting_for_esp32 = False
            self._esp32_cmd_sent_time = None
            self._finish_cleaning(success=False)
        
        elif status == 'idle':
            pass
    
    def get_status(self) -> Dict:
        """Get current system status (thread-safe)"""
        with self._status_lock:
            return self.current_status.copy()
    
    def _load_activity_log(self):
        """Muat ulang activity log dari file JSONL (riwayat lintas-restart).

        Hanya memuat hingga _activity_log_max entri terakhir agar ringan.
        """
        try:
            if not self._activity_log_file.exists():
                return
            with open(self._activity_log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # Ambil baris terakhir sebanyak kapasitas buffer
            for line in lines[-self._activity_log_max:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.activity_log.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            print(f"[Controller] Activity log dimuat: {len(self.activity_log)} entri")
        except Exception as e:
            print(f"[Controller] Gagal memuat activity log: {e}")

    def _log_activity(self, event_type: str, message: str, data: dict = None):
        """Add entry to activity log (in-memory + persist ke file JSONL)."""
        # Demo pembersihan dari halaman Testing: JANGAN catat ke activity log /
        # report monitoring. Selama siklus uji aktif, seluruh event di-skip
        # (loop monitoring sedang dijeda, jadi hanya event cleaning yang muncul).
        if getattr(self, '_cleaning_is_test', False):
            return
        entry = {
            'timestamp': datetime.now().isoformat(),
            'time': datetime.now().strftime('%H:%M:%S'),
            'type': event_type,
            'message': message,
        }
        if data:
            entry['data'] = data
        self.activity_log.append(entry)
        # Persist ke file (append 1 baris JSON). Best-effort, tidak memblokir.
        try:
            with self._activity_log_lock:
                with open(self._activity_log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                # Trim berkala agar file tidak membengkak tak terbatas (24/7).
                self._activity_write_count += 1
                if self._activity_write_count >= 500:
                    self._activity_write_count = 0
                    self._trim_activity_file()
        except Exception as e:
            print(f"[Controller] Gagal menulis activity log: {e}")

    def _trim_activity_file(self):
        """Pangkas file activity log ke _activity_file_max baris terakhir.

        Dipanggil di dalam _activity_log_lock. Mencegah file tumbuh tanpa batas
        pada operasi jangka panjang.
        """
        try:
            if not self._activity_log_file.exists():
                return
            with open(self._activity_log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) <= self._activity_file_max:
                return
            keep = lines[-self._activity_file_max:]
            tmp = self._activity_log_file.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(keep)
            tmp.replace(self._activity_log_file)
        except Exception as e:
            print(f"[Controller] Gagal trim activity log: {e}")
    
    def get_activity_log(self) -> List[Dict]:
        """Get activity log entries"""
        return list(self.activity_log)
    
    def clear_activity_log(self):
        """Kosongkan activity log di memori DAN file persist."""
        self.activity_log.clear()
        try:
            with self._activity_log_lock:
                if self._activity_log_file.exists():
                    self._activity_log_file.unlink()
        except OSError as e:
            print(f"[Controller] Gagal menghapus file activity log: {e}")
    
    def detect_and_clean(self) -> Dict:
        """Capture + deteksi YOLO, lalu picu pembersihan NYATA (dicatat ke logger)
        bila panel kotor (score >= threshold). Dipakai tombol 'Bersihkan Manual'
        dan pengambilan data: score_before = hasil deteksi asli. Melewati cooldown
        karena ini trigger langsung (bukan loop monitoring otomatis).
        """
        if getattr(self, 'cleaning_in_progress', False) or getattr(self, 'waiting_for_esp32', False):
            return {'success': False, 'message': 'Pembersihan sedang berjalan'}

        with self._camera_lock:
            if self.camera is None:
                return {'success': False, 'message': 'Kamera tidak tersedia'}
            frame = self.camera.capture()
        if frame is None:
            return {'success': False, 'message': 'Gagal mengambil gambar dari kamera'}

        zones = self.config.zones
        try:
            import time as _t
            _t0 = _t.perf_counter()
            if zones:
                results = self.detector.detect_zones(frame, zones) or []
            else:
                r = self.detector.detect(frame)
                results = [r] if r else []
            detect_time_s = round(_t.perf_counter() - _t0, 2)
        except Exception as e:
            return {'success': False, 'message': f'Deteksi gagal: {e}'}

        timestamp = datetime.now().isoformat()
        with self._status_lock:
            self.current_status['last_detection'] = {'timestamp': timestamp, 'results': results}
            self.current_status['last_capture'] = timestamp

        if not results:
            return {'success': True, 'cleaning': False, 'message': 'Panel tidak terdeteksi'}

        threshold = self.config.get('cleaning.trigger_threshold', 70)
        r0 = results[0]
        score = float(r0.get('weighted_score', 0) or 0)
        level = r0.get('dirt_level', 'unknown')

        # Catat event deteksi (trigger manual) agar statistik "Deteksi" mencerminkan
        # bahwa deteksi benar-benar dijalankan — baik hasilnya bersih maupun kotor.
        self._log_activity('detection',
            f'Deteksi manual: {level} (score {score:.1f})',
            {'score': round(score, 2), 'category': level,
             'detect_time_s': detect_time_s})

        if (not r0.get('clean', True)) and score >= threshold:
            zone_id = r0.get('zone_id', 0)
            # test=False → pembersihan NYATA, dicatat ke cleaning_logger
            self._start_cleaning_cycle(zone_id, score, test=False)
            return {'success': True, 'cleaning': True, 'score': round(score, 1),
                    'level': level,
                    'message': f'Kotor ({level}, score {score:.0f}) - pembersihan dimulai'}

        # Panel bersih → catat juga ke riwayat (adil: keputusan tidak membersihkan)
        if self.cleaning_logger is not None:
            try:
                max_attempts = self.config.get('cleaning.cycles.max_attempts', 5)
                rec = self.cleaning_logger.record_clean_detection(
                    score, detect_time_s=detect_time_s, max_attempts=max_attempts)
                if rec:
                    self._log_activity('cleaning_session',
                        f"Deteksi bersih dicatat (score {score:.0f}, tanpa pembersihan)", rec)
            except Exception as _e:
                print(f"[Controller] record_clean_detection gagal: {_e}")

        return {'success': True, 'cleaning': False, 'score': round(score, 1),
                'level': level,
                'message': f'Panel bersih (score {score:.0f}) - tidak perlu pembersihan'}

    def manual_capture(self) -> Optional[Dict]:
        """Manual capture, YOLO detection, update last_detection, return annotated image"""
        import cv2
        import base64
        import numpy as np

        with self._camera_lock:
            if self.camera is None:
                return None
            frame = self.camera.capture()
        
        if frame is None:
            return None

        zones = self.config.zones
        if zones:
            results = self.detector.detect_zones(frame, zones)
        else:
            results = [self.detector.detect(frame)]

        # Update last_detection in status so WebSocket reflects the new result
        timestamp = datetime.now().isoformat()
        with self._status_lock:
            self.current_status['last_detection'] = {
                'timestamp': timestamp,
                'results': results
            }
            self.current_status['last_capture'] = timestamp

        # Draw YOLO annotations on the captured frame
        annotated = frame.copy()
        for result in results:
            if result.get('panel_detected') and result.get('panel_bbox'):
                x1, y1, x2, y2 = result['panel_bbox']
                conf = result.get('panel_confidence', 0)
                dirt = result.get('dirt_level', 'unknown')
                dirt_conf = result.get('dirt_confidence', 0)
                score = result.get('weighted_score', 0)

                # Panel bounding box (hijau)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 3)

                # Satu label gabungan di sisi atas (1 baris): panel + dirt.
                # Border & background label hijau, teks putih. Digambar DI DALAM
                # kotak agar tidak keluar frame.
                if dirt != 'unknown':
                    label = f'Panel {conf*100:.0f}% | {dirt} {dirt_conf*100:.0f}% S:{score:.0f}'
                else:
                    label = f'Panel {conf*100:.0f}%'
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
                cv2.rectangle(annotated, (x1, y1), (x1 + tw + 10, y1 + th + 12), (0, 255, 0), -1)
                cv2.putText(annotated, label, (x1 + 5, y1 + th + 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
            else:
                # No panel detected — draw text
                cv2.putText(annotated, 'No panel detected', (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)

        # Encode annotated frame to base64 JPEG
        _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
        img_b64 = base64.b64encode(buffer).decode()

        return {
            'timestamp': timestamp,
            'results': results,
            'image': f'data:image/jpeg;base64,{img_b64}'
        }
