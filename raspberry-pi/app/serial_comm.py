"""
Serial Communication with ESP32

Modul komunikasi serial antara Raspberry Pi dan ESP32
menggunakan protokol JSON melalui UART (/dev/serial0).

Fitur:
- Auto-reconnect saat koneksi terputus
- Retry mechanism (max 5 attempts)
- JSON command/response format
- Timeout handling

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import serial
import json
import time
from typing import Optional, Dict, List
import threading

class ESP32Communicator:
    def __init__(self, port: str = "/dev/serial0", baudrate: int = 115200, timeout: int = 1):
        # port bisa berupa path spesifik (mis. /dev/serial0, /dev/ttyUSB0, COM5)
        # atau "auto" untuk deteksi pintar lintas GPIO UART & USB-serial.
        self.configured_port = (port or "auto").strip()
        self.auto_mode = self.configured_port.lower() == "auto"
        # Port aktif: saat auto, mulai dari None sampai terdeteksi via handshake.
        self.port = None if self.auto_mode else self.configured_port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = None
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 2  # seconds
        self._lock = threading.Lock()  # Thread-safe serial access
        self._command_lock = threading.Lock()  # Prevent concurrent test/cleaning commands
        self._last_send_time = 0  # For retry backoff
        self._min_send_interval = 0.1  # 100ms minimum between commands
        self._reconnect_thread = None
        self._reconnect_running = False
        self._reconnect_lock = threading.Lock()  # Prevent duplicate reconnect threads
        # Liveness tracking: koneksi "hidup" hanya jika ESP32 benar-benar membalas.
        # Penting untuk UART hardware (/dev/ttyAMA*, /dev/serial0) yang port-nya
        # selalu bisa dibuka walau tidak ada ESP32 di ujung kabel RX/TX.
        self.last_response_time = 0.0      # waktu JSON valid terakhir diterima
        self.alive_window = 8.0            # detik: dianggap hidup jika balas < 8s lalu
        self._last_probe_time = 0.0        # throttle probe aktif
        self._probe_interval = 3.0         # detik: minimal jarak antar probe aktif
        self._last_alive_result = False
        self._connect()
        
        # Start background reconnect if initial connection failed
        if not self.connected:
            self._start_background_reconnect()
    
    # ------------------------------------------------------------------
    # Deteksi port adaptif (GPIO UART + USB-serial)
    # ------------------------------------------------------------------
    def _candidate_ports(self):
        """
        Daftar kandidat port untuk mode auto, terurut prioritas.

        Menggabungkan UART GPIO (Raspberry Pi) dan USB-serial (adapter ESP32 /
        Windows COM). Duplikat dibuang, urutan dipertahankan.
        """
        candidates = []

        # 1. USB-serial via VID:PID / deskripsi (paling spesifik → prioritas)
        try:
            import serial.tools.list_ports
            esp32_vid_pid = [
                (0x10C4, 0xEA60), (0x10C4, 0xEA70),  # CP210x
                (0x1A86, 0x7523), (0x1A86, 0x55D4),  # CH340 / CH9102
                (0x0403, 0x6001),                    # FT232RL
                (0x303A, 0x1001),                    # ESP32-S2/S3 native USB
            ]
            esp32_keywords = ['CP210', 'CH340', 'CH910', 'FTDI',
                              'USB SERIAL', 'USB-SERIAL', 'ESP32']
            ports = [p for p in serial.tools.list_ports.comports()
                     if 'bluetooth' not in (p.description or '').lower()]
            # match VID:PID dulu
            for p in ports:
                if p.vid and p.pid and (p.vid, p.pid) in esp32_vid_pid:
                    candidates.append(p.device)
            # lalu match deskripsi
            for p in ports:
                desc = (p.description or '').upper()
                if any(kw in desc for kw in esp32_keywords):
                    candidates.append(p.device)
        except Exception:
            pass

        # 2. UART GPIO Raspberry Pi (tidak punya VID:PID)
        candidates += ['/dev/serial0', '/dev/ttyAMA0', '/dev/ttyAMA10', '/dev/ttyS0']

        # 3. Sisa port USB generik (fallback terakhir)
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                dev = p.device
                if dev and ('USB' in dev or 'ACM' in dev or dev.startswith('COM')):
                    candidates.append(dev)
        except Exception:
            pass

        # Hapus duplikat, pertahankan urutan
        seen = set()
        ordered = []
        for c in candidates:
            if c and c not in seen:
                seen.add(c)
                ordered.append(c)
        return ordered

    def _probe_port(self, port: str) -> bool:
        """
        Buka port lalu handshake: kirim 'status', tunggu balasan JSON valid.

        Mengembalikan True hanya jika ada ESP32 yang benar-benar membalas —
        bukan sekadar port bisa dibuka (UART GPIO selalu bisa dibuka).
        """
        test = None
        try:
            test = serial.Serial(port=port, baudrate=self.baudrate,
                                 timeout=1, write_timeout=1)
            time.sleep(2)  # ESP32 boot/stabil + auto-reset USB
            test.reset_input_buffer()
            test.write((json.dumps({"cmd": "status"}) + "\n").encode())
            test.flush()
            deadline = time.time() + 2.5
            while time.time() < deadline:
                if test.in_waiting > 0:
                    line = test.readline().decode('utf-8', errors='ignore').strip()
                    if line.startswith('{'):
                        try:
                            obj = json.loads(line)
                            # Balasan ESP32 valid: ada 'status'/'state'/'ack'/'uptime'
                            if any(k in obj for k in ('status', 'state', 'ack', 'uptime')):
                                # Pegang koneksi ini agar tidak perlu buka ulang
                                self.serial = test
                                self.last_response_time = time.time()
                                return True
                        except json.JSONDecodeError:
                            pass
                else:
                    time.sleep(0.05)
            test.close()
        except Exception:
            try:
                if test and test.is_open:
                    test.close()
            except Exception:
                pass
        return False

    def _connect_auto(self) -> bool:
        """Mode auto: coba tiap kandidat port dengan handshake nyata."""
        candidates = self._candidate_ports()
        print(f"[Auto] Mendeteksi ESP32 pada kandidat: {candidates}")
        for cand in candidates:
            if self._probe_port(cand):
                self.port = cand
                self.connected = True
                self.reconnect_attempts = 0
                print(f"[OK] ESP32 terdeteksi (auto) pada {cand}")
                return True
        print("[Auto] ESP32 tidak ditemukan pada port manapun")
        self.connected = False
        return False
    
    def _connect(self):
        """Connect to ESP32. Mode auto memakai handshake lintas port."""
        if self.auto_mode:
            return self._connect_auto()
        return self._connect_fixed()
    
    def _connect_fixed(self):
        """Connect to ESP32 with retry mechanism"""
        for attempt in range(self.max_reconnect_attempts):
            try:
                if self.serial and self.serial.is_open:
                    self.serial.close()
                
                self.serial = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout,
                    write_timeout=self.timeout
                )
                time.sleep(2)  # Wait for connection to stabilize
                self.serial.reset_input_buffer()  # Flush stale data after reconnect
                self.connected = True
                self.reconnect_attempts = 0
                print(f"[OK] Connected to ESP32 on {self.port}")
                return True
            except serial.SerialException as e:
                self.connected = False
                self.reconnect_attempts += 1
                print(f"[!] Connection attempt {attempt + 1}/{self.max_reconnect_attempts} failed: {e}")
                if attempt < self.max_reconnect_attempts - 1:
                    time.sleep(self.reconnect_delay)
            except Exception as e:
                print(f"[X] Unexpected error connecting to ESP32: {e}")
                self.connected = False
                break
        
        print(f"[X] Failed to connect to ESP32 after {self.max_reconnect_attempts} attempts")
        return False
    
    def _ensure_connection(self) -> bool:
        """Ensure connection is active, reconnect if needed"""
        if self.connected and self.serial and self.serial.is_open:
            return True
        
        # If background reconnect is already running, don't block — just return False
        if self._reconnect_running:
            return False
        
        print("[!] Connection lost, attempting to reconnect...")
        success = self._connect()
        if not success:
            self._start_background_reconnect()
        return success
    
    def _start_background_reconnect(self):
        """Start background thread that periodically tries to reconnect"""
        with self._reconnect_lock:
            if self._reconnect_running:
                return
            self._reconnect_running = True
        self._reconnect_thread = threading.Thread(target=self._background_reconnect_loop, daemon=True)
        self._reconnect_thread.start()
        print("[!] Background auto-reconnect started (will retry every 5 seconds)")
    
    def _background_reconnect_loop(self):
        """Background loop that tries to reconnect every 5 seconds, with auto-detect"""
        while self._reconnect_running:
            time.sleep(5)
            
            # Exit if already connected and stable
            if self.connected:
                try:
                    if self.serial and self.serial.is_open:
                        self.serial.in_waiting  # Verify port is actually alive
                        break  # Truly connected, exit
                except Exception:
                    self.connected = False  # Port died, keep trying
            
            # Mode auto: cari ulang lewat handshake lintas kandidat port
            # (USB-serial bisa berganti nama, GPIO selalu /dev/serial0).
            if self.auto_mode:
                with self._lock:
                    try:
                        if self.serial and self.serial.is_open:
                            self.serial.close()
                    except Exception:
                        pass
                    self._connect_auto()
                continue
            
            # Mode port tetap. Auto-detect USB hanya bila port BUKAN GPIO UART
            # (port GPIO tidak punya VID:PID, jangan ditimpa perangkat USB lain).
            port_to_try = self.port
            _gpio_uart = ('serial0' in self.port or 'ttyAMA' in self.port
                          or 'ttyS' in self.port)
            if not _gpio_uart:
                try:
                    detected_port = self._auto_detect_port()
                    if detected_port:
                        port_to_try = detected_port
                except Exception:
                    pass
            
            with self._lock:
                try:
                    if self.serial and self.serial.is_open:
                        self.serial.close()
                    
                    self.serial = serial.Serial(
                        port=port_to_try,
                        baudrate=self.baudrate,
                        timeout=self.timeout,
                        write_timeout=self.timeout
                    )
                    time.sleep(1)
                    self.serial.reset_input_buffer()
                    self.connected = True
                    self.port = port_to_try  # Update port for future reconnects
                    self.reconnect_attempts = 0
                    print(f"[OK] Auto-reconnect successful! Connected to ESP32 on {port_to_try}")
                except serial.SerialException as e:
                    print(f"[!] Auto-reconnect failed on {port_to_try}: {e}")
                except Exception as e:
                    print(f"[!] Auto-reconnect error: {e}")
        
        self._reconnect_running = False
    
    @staticmethod
    def _auto_detect_port():
        """Auto-detect ESP32 serial port (CH340, CP2102, etc.)"""
        try:
            import serial.tools.list_ports
            
            esp32_vid_pid = [
                (0x10C4, 0xEA60), (0x10C4, 0xEA70),  # CP210x
                (0x1A86, 0x7523), (0x1A86, 0x55D4),  # CH340/CH9102
                (0x0403, 0x6001),                      # FT232RL
                (0x303A, 0x1001), (0x303A, 0x0002),   # ESP32 native USB
            ]
            esp32_keywords = ['CP210', 'CH340', 'CH910', 'FTDI', 'USB Serial', 'USB-SERIAL']
            
            ports = [p for p in serial.tools.list_ports.comports()
                     if 'bluetooth' not in (p.description or '').lower()]
            
            # Match by VID:PID
            for p in ports:
                if p.vid and p.pid:
                    for vid, pid in esp32_vid_pid:
                        if p.vid == vid and p.pid == pid:
                            return p.device
            
            # Match by description
            for p in ports:
                desc = (p.description or '').upper()
                for kw in esp32_keywords:
                    if kw.upper() in desc:
                        return p.device
            
            # Single physical port
            if len(ports) == 1:
                return ports[0].device
            
            return None
        except Exception:
            return None
    
    def send_command(self, command: str, **kwargs) -> bool:
        """Send command to ESP32 with auto-reconnect (thread-safe, with backoff)"""
        with self._lock:
            if not self._ensure_connection():
                return False
            
            try:
                # Backoff: enforce minimum interval between commands
                import time as _time
                elapsed = _time.time() - self._last_send_time
                if elapsed < self._min_send_interval:
                    _time.sleep(self._min_send_interval - elapsed)
                
                # Flush stale data before sending
                if self.serial and self.serial.in_waiting:
                    self.serial.reset_input_buffer()
                
                data = {"cmd": command, **kwargs}
                message = json.dumps(data) + "\n"
                self.serial.write(message.encode())
                self.serial.flush()
                self._last_send_time = _time.time()
                return True
            except serial.SerialException as e:
                print(f"[X] Serial error sending command: {e}")
                self.connected = False
                return False
            except Exception as e:
                print(f"[X] Error sending command: {e}")
                return False
    
    def trigger_cleaning_cycle(self, zone: int = 0, weighted_score: float = 0) -> bool:
        """Trigger single wiper cleaning cycle (adaptive based on score)
        
        For manual trigger (weighted_score=0), send score=100 to ensure ESP32 starts cleaning.
        ESP32 rejects score < 70 as "panel bersih" (clean panel).
        """
        # If manual trigger (score=0), use score=100 to trigger medium cleaning
        if weighted_score == 0:
            weighted_score = 100.0
        return self.send_command("siklus_pembersihan", zone=zone, score=weighted_score)
    
    def stop_cleaning(self) -> bool:
        """Stop cleaning mechanism"""
        return self.send_command("stop")
    
    def request_status(self) -> bool:
        """Request status from ESP32"""
        return self.send_command("status")
    
    def read_response(self, timeout: Optional[float] = None) -> Optional[Dict]:
        """Read JSON response from ESP32, skip non-JSON debug lines (thread-safe)"""
        with self._lock:
            if not self.connected or not self.serial:
                return None
            
            old_timeout = self.serial.timeout
            try:
                if timeout is not None:
                    self.serial.timeout = timeout
                
                import time as _time
                deadline = _time.time() + (timeout or self.timeout)
                
                while _time.time() < deadline:
                    if self.serial.in_waiting > 0:
                        line = self.serial.readline().decode('utf-8', errors='ignore').strip()
                        if line and line.startswith('{'):
                            try:
                                result = json.loads(line)
                                self.last_response_time = _time.time()  # tandai koneksi hidup
                                return result
                            except json.JSONDecodeError:
                                pass  # Not valid JSON, skip
                    else:
                        _time.sleep(0.05)
                    
            except serial.SerialException as e:
                print(f"[X] Serial error reading response: {e}")
                self.connected = False
            except Exception as e:
                print(f"[X] Error reading response: {e}")
            finally:
                try:
                    if self.serial:
                        self.serial.timeout = old_timeout
                except Exception:
                    pass
            
            return None
    
    def read_all_responses(self, max_lines: int = 40) -> list:
        """Drain SEMUA baris JSON yang sudah ada di buffer (NON-BLOCKING).

        ESP32 mengirim status 5Hz; loop pembaca lebih lambat → buffer menumpuk
        dan data jadi basi. Membaca semua sekaligus menjaga status tetap TERBARU
        sekaligus tidak melewatkan pesan penting (done/error/stopped) karena tiap
        baris dikembalikan berurutan untuk diproses. Hanya membaca yang sudah
        tersedia (in_waiting) — tidak menunggu.
        """
        import time as _time
        out = []
        with self._lock:
            if not self.connected or not self.serial:
                return out
            try:
                count = 0
                while self.serial.in_waiting > 0 and count < max_lines:
                    line = self.serial.readline().decode('utf-8', errors='ignore').strip()
                    count += 1
                    if line and line.startswith('{'):
                        try:
                            out.append(json.loads(line))
                            self.last_response_time = _time.time()  # tandai koneksi hidup
                        except json.JSONDecodeError:
                            pass  # baris non-JSON (debug) → skip
            except serial.SerialException as e:
                print(f"[X] Serial error draining responses: {e}")
                self.connected = False
            except Exception as e:
                print(f"[X] Error draining responses: {e}")
        return out
    
    def send_and_receive(self, command: str, timeout: float = 3.0, **kwargs) -> Optional[Dict]:
        """Send command and read response atomically (no interleaving, with backoff)"""
        with self._lock:
            if not self._ensure_connection():
                return None
            
            try:
                # Backoff: enforce minimum interval between commands
                import time as _time
                elapsed = _time.time() - self._last_send_time
                if elapsed < self._min_send_interval:
                    _time.sleep(self._min_send_interval - elapsed)
                
                # Flush stale data
                if self.serial and self.serial.in_waiting:
                    self.serial.reset_input_buffer()
                
                # Send
                data = {"cmd": command, **kwargs}
                message = json.dumps(data) + "\n"
                self.serial.write(message.encode())
                self.serial.flush()
                self._last_send_time = _time.time()
                
                # Read response
                import time as _time
                deadline = _time.time() + timeout
                old_timeout = self.serial.timeout
                self.serial.timeout = timeout
                
                while _time.time() < deadline:
                    if self.serial.in_waiting > 0:
                        line = self.serial.readline().decode('utf-8', errors='ignore').strip()
                        if line and line.startswith('{'):
                            try:
                                result = json.loads(line)
                                self.last_response_time = _time.time()  # tandai koneksi hidup
                                self.serial.timeout = old_timeout
                                return result
                            except json.JSONDecodeError:
                                pass
                    else:
                        _time.sleep(0.05)
                
                self.serial.timeout = old_timeout
                
            except serial.SerialException as e:
                print(f"[X] Serial error: {e}")
                self.connected = False
            except Exception as e:
                print(f"[X] Error: {e}")
            
            return None
    
    def get_status(self) -> Optional[Dict]:
        """Request and read status from ESP32 (atomic)"""
        return self.send_and_receive("status", timeout=2.0)
    
    def is_alive(self) -> bool:
        """
        Cek apakah ESP32 BENAR-BENAR terhubung (membalas), bukan sekadar
        port serial terbuka.

        Diperlukan karena UART hardware (/dev/ttyAMA*, /dev/serial0) selalu
        bisa dibuka meski tidak ada ESP32 di ujung kabel RX/TX — sehingga
        self.connected (port terbuka) bisa menipu.

        Logika:
        1. Jika port belum terbuka → tidak hidup.
        2. Jika baru saja menerima JSON valid (< alive_window detik) → hidup.
        3. Jika belum, lakukan probe aktif ber-throttle: kirim "status" dan
           tunggu balasan singkat. Hasil di-cache agar tidak membanjiri bus.
        """
        import time as _time
        # 1. Port harus terbuka
        if not (self.serial and getattr(self.serial, 'is_open', False)):
            self._last_alive_result = False
            return False

        # 2. Respons terakhir masih dalam jendela waktu → pasti hidup
        if (_time.time() - self.last_response_time) < self.alive_window:
            self._last_alive_result = True
            return True

        # 3. Throttle probe aktif: jangan probe terlalu sering
        if (_time.time() - self._last_probe_time) < self._probe_interval:
            return self._last_alive_result

        self._last_probe_time = _time.time()
        resp = self.send_and_receive("status", timeout=1.0)
        self._last_alive_result = resp is not None
        return self._last_alive_result
    
    def reliability_test(self, count: int = 100, interval: float = 0.2,
                         timeout: float = 2.0, progress_cb=None) -> Dict:
        """
        Uji keandalan komunikasi UART: kirim N perintah 'status' berturut-turut,
        ukur round-trip time (RTT) tiap perintah, hitung success rate + statistik.

        Args:
            count: jumlah perintah.
            interval: jeda antar perintah (detik).
            timeout: batas tunggu respons per perintah.
            progress_cb: callable(done, total) opsional.

        Return: dict statistik (success rate, RTT mean/min/max/stdev).
        """
        import time as _time
        import statistics

        rtts: List[float] = []
        success = 0
        for i in range(count):
            t0 = _time.perf_counter()
            resp = self.send_and_receive("status", timeout=timeout)
            dt_ms = (_time.perf_counter() - t0) * 1000.0
            if resp is not None:
                success += 1
                rtts.append(dt_ms)
            if progress_cb and ((i + 1) % 5 == 0 or i + 1 == count):
                try:
                    progress_cb(i + 1, count)
                except Exception:
                    pass
            if interval > 0:
                _time.sleep(interval)

        rtt_stats = None
        if rtts:
            rtt_stats = {
                "mean": round(statistics.mean(rtts), 2),
                "median": round(statistics.median(rtts), 2),
                "min": round(min(rtts), 2),
                "max": round(max(rtts), 2),
                "stdev": round(statistics.stdev(rtts), 2) if len(rtts) > 1 else 0.0,
            }
        return {
            "sent": count,
            "received": success,
            "success_rate": round(success / count * 100, 2) if count else 0.0,
            "rtt_ms": rtt_stats,
            "timestamp": _time.time(),
        }
    
    # ------------------------------------------------------------------
    # Manajemen port (untuk panel pengaturan web)
    # ------------------------------------------------------------------
    @staticmethod
    def list_available_ports() -> List[Dict]:
        """
        Daftar port serial yang tersedia di sistem, plus kandidat UART GPIO.

        Tiap item: {device, description, is_gpio, likely_esp32}.
        Dipakai dropdown pemilihan port di halaman Settings.
        """
        import os
        items = []
        seen = set()

        # USB-serial / COM ports
        try:
            import serial.tools.list_ports
            esp32_vid_pid = {
                (0x10C4, 0xEA60), (0x10C4, 0xEA70),
                (0x1A86, 0x7523), (0x1A86, 0x55D4),
                (0x0403, 0x6001), (0x303A, 0x1001),
            }
            esp32_kw = ('CP210', 'CH340', 'CH910', 'FTDI', 'USB SERIAL',
                        'USB-SERIAL', 'ESP32')
            for p in serial.tools.list_ports.comports():
                if 'bluetooth' in (p.description or '').lower():
                    continue
                desc = (p.description or '').upper()
                likely = bool((p.vid and p.pid and (p.vid, p.pid) in esp32_vid_pid)
                              or any(k in desc for k in esp32_kw))
                items.append({
                    "device": p.device,
                    "description": p.description or p.device,
                    "is_gpio": False,
                    "likely_esp32": likely,
                })
                seen.add(p.device)
        except Exception:
            pass

        # UART GPIO (Linux/Raspberry Pi) — hanya yang benar-benar ada
        for dev, label in [("/dev/serial0", "UART GPIO (pin 8/10)"),
                           ("/dev/ttyAMA0", "UART GPIO (ttyAMA0)"),
                           ("/dev/ttyAMA10", "UART GPIO (ttyAMA10)"),
                           ("/dev/ttyS0", "UART GPIO (ttyS0)")]:
            try:
                if dev not in seen and os.path.exists(dev):
                    items.append({
                        "device": dev,
                        "description": label,
                        "is_gpio": True,
                        "likely_esp32": dev == "/dev/serial0",
                    })
                    seen.add(dev)
            except Exception:
                pass

        return items

    def test_port(self, port: str, timeout: float = 2.5) -> Dict:
        """
        Uji satu port: buka + handshake 'status'. Tidak mengubah koneksi aktif
        bila port berbeda dari yang sedang dipakai.

        Return: {success, port, message, response?}
        """
        import serial as _pyserial
        # Bila menguji port yang sedang aktif & hidup, pakai jalur normal.
        if port == self.port and self.connected and self.serial and self.serial.is_open:
            resp = self.send_and_receive("status", timeout=timeout)
            if resp is not None:
                return {"success": True, "port": port,
                        "message": f"ESP32 merespons di {port}",
                        "response": resp}
            return {"success": False, "port": port,
                    "message": f"Port {port} aktif tapi ESP32 tidak merespons"}

        # Port lain: buka sementara, jangan ganggu koneksi aktif.
        test = None
        try:
            test = _pyserial.Serial(port=port, baudrate=self.baudrate,
                                    timeout=1, write_timeout=1)
            _t = __import__("time")
            _t.sleep(2)
            test.reset_input_buffer()
            test.write((json.dumps({"cmd": "status"}) + "\n").encode())
            test.flush()
            deadline = _t.time() + timeout
            while _t.time() < deadline:
                if test.in_waiting > 0:
                    line = test.readline().decode("utf-8", errors="ignore").strip()
                    if line.startswith("{"):
                        try:
                            obj = json.loads(line)
                            if any(k in obj for k in ("status", "state", "ack", "uptime")):
                                test.close()
                                return {"success": True, "port": port,
                                        "message": f"ESP32 merespons di {port}",
                                        "response": obj}
                        except json.JSONDecodeError:
                            pass
                else:
                    _t.sleep(0.05)
            test.close()
            return {"success": False, "port": port,
                    "message": f"Port {port} terbuka, tetapi ESP32 tidak merespons "
                               "(cek RX/TX, ESP32 menyala, baud 115200)"}
        except Exception as e:
            try:
                if test and test.is_open:
                    test.close()
            except Exception:
                pass
            return {"success": False, "port": port,
                    "message": f"Gagal membuka {port}: {e}"}

    def switch_port(self, port: str) -> Dict:
        """
        Pindah koneksi ke port baru saat runtime (tanpa restart aplikasi).

        port bisa path spesifik atau 'auto'. Mengembalikan status koneksi baru.
        """
        with self._lock:
            try:
                if self.serial and self.serial.is_open:
                    self.serial.close()
            except Exception:
                pass
            self.serial = None
            self.connected = False
            self.configured_port = (port or "auto").strip()
            self.auto_mode = self.configured_port.lower() == "auto"
            self.port = None if self.auto_mode else self.configured_port
            self.last_response_time = 0.0

        ok = self._connect()
        if not ok:
            self._start_background_reconnect()
        return {
            "success": ok,
            "auto_mode": self.auto_mode,
            "port": self.port,
            "message": (f"Terhubung ke ESP32 pada {self.port}" if ok
                        else "Belum terhubung — auto-reconnect berjalan di latar"),
        }
    
    def close(self):
        """Close serial connection"""
        self._reconnect_running = False  # Stop background reconnect
        if self.serial and self.serial.is_open:
            try:
                self.serial.close()
                self.connected = False
                print("[OK] ESP32 connection closed")
            except Exception as e:
                print(f"[!] Error closing connection: {e}")
    
    def __del__(self):
        """Destructor to ensure connection is closed"""
        self.close()
