"""
Camera Capture Module

Modul untuk menangkap gambar dari kamera USB atau Pi Camera.
Mendukung pengaturan resolusi dan crop zona tertentu.
Timeout protection agar tidak hang jika kamera tidak tersedia.

Kamera dibuka saat startup dan tetap standby.
Penghematan dilakukan di sisi streaming (preview ON/OFF),
bukan buka-tutup hardware (USB camera butuh 10-17s untuk init).

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import cv2
import numpy as np
from typing import Optional, Tuple
import time
import threading
import platform
import shutil
import subprocess


class Camera:
    def __init__(self, device_id: int = 0, resolution: Tuple[int, int] = (1920, 1080), timeout: float = 25.0,
                 auto_exposure: bool = True, brightness: Optional[float] = None,
                 gain: Optional[float] = None, exposure: Optional[float] = None):
        self.device_id = device_id
        self.resolution = resolution
        self._timeout = timeout
        # Pengaturan pencahayaan kamera. Di Linux (V4L2/Raspberry Pi) OpenCV TIDAK
        # mengaktifkan auto-exposure secara default sehingga gambar gelap, padahal
        # di Windows driver kamera otomatis melakukannya. auto_exposure=True memaksa
        # mode auto agar konsisten terang di RPi.
        self.auto_exposure = auto_exposure
        self.brightness = brightness      # opsional, 0-255 (None = biarkan default driver)
        self.gain = gain                  # opsional (None = default)
        self.exposure = exposure          # opsional, hanya dipakai bila auto_exposure=False
        self.cap = None
        self._lock = threading.Lock()
        self._available = False
        self._initialize()

    @property
    def is_open(self) -> bool:
        """Check if camera is currently open"""
        return self.cap is not None and self.cap.isOpened()

    @property
    def available(self) -> bool:
        """Check if camera was successfully opened"""
        return self._available

    def _configure_camera(self, cap):
        """Atur exposure/gain/white-balance agar tidak gelap di Linux (V4L2).

        Konvensi nilai CAP_PROP_AUTO_EXPOSURE berbeda antar backend:
        - V4L2 (Linux/Raspberry Pi): 3 = auto, 1 = manual
        - DSHOW/MSMF (Windows): 0.75 = auto, 0.25 = manual
        Tiap set dibungkus try/except karena tidak semua kamera mendukung
        properti tertentu (gagal di-set tidak boleh menghentikan init).
        """
        is_linux = platform.system() == 'Linux'
        try:
            if self.auto_exposure:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3 if is_linux else 0.75)
            else:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1 if is_linux else 0.25)
                if self.exposure is not None:
                    cap.set(cv2.CAP_PROP_EXPOSURE, self.exposure)
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_AUTO_WB, 1)  # auto white balance
        except Exception:
            pass
        if self.brightness is not None:
            try:
                cap.set(cv2.CAP_PROP_BRIGHTNESS, self.brightness)
            except Exception:
                pass
        if self.gain is not None:
            try:
                cap.set(cv2.CAP_PROP_GAIN, self.gain)
            except Exception:
                pass
        # Linux: properti OpenCV sering diabaikan kamera UVC. Terapkan juga lewat
        # v4l2-ctl yang jauh lebih andal di Raspberry Pi.
        self._apply_v4l2_controls()

    def _apply_v4l2_controls(self):
        """Set kontrol kamera lewat v4l2-ctl (Linux) — lebih andal dari properti OpenCV.

        Nama kontrol berbeda antar versi kernel/UVC, jadi tiap varian dicoba dan
        kegagalan diabaikan. Tujuan: memastikan exposure/gain/brightness benar-benar
        terpasang sehingga preview tidak gelap di Raspberry Pi.
        """
        if platform.system() != 'Linux' or not shutil.which('v4l2-ctl'):
            return
        dev = f"/dev/video{self.device_id}" if isinstance(self.device_id, int) else str(self.device_id)

        def setctrl(*candidates):
            for pair in candidates:
                try:
                    subprocess.run(['v4l2-ctl', '-d', dev, '--set-ctrl', pair],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                except Exception:
                    pass

        if self.auto_exposure:
            # 3 = aperture priority (auto). Matikan dulu auto-priority agar FPS stabil.
            setctrl('exposure_auto=3', 'auto_exposure=3')
            setctrl('white_balance_temperature_auto=1', 'white_balance_automatic=1')
        else:
            # 1 = manual. Set exposure absolut bila diberikan.
            setctrl('exposure_auto=1', 'auto_exposure=1')
            if self.exposure is not None:
                setctrl(f'exposure_absolute={int(self.exposure)}',
                        f'exposure_time_absolute={int(self.exposure)}')
        if self.brightness is not None:
            setctrl(f'brightness={int(self.brightness)}')
        if self.gain is not None:
            setctrl(f'gain={int(self.gain)}')

    def _initialize(self):
        """Initialize camera with timeout (tidak hang jika kamera tidak ada)"""
        result = [None]
        error = [None]

        def _open():
            try:
                cap = cv2.VideoCapture(self.device_id)
                if cap.isOpened():
                    # Set resolution BEFORE first read
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                    # Aktifkan auto-exposure/WB sebelum membaca frame
                    self._configure_camera(cap)
                    ret, _ = cap.read()
                    if ret:
                        result[0] = cap
                        return
                cap.release()
                error[0] = f"Cannot open camera {self.device_id}"
            except Exception as e:
                error[0] = str(e)

        thread = threading.Thread(target=_open, daemon=True)
        thread.start()
        thread.join(timeout=self._timeout)

        if result[0] is None:
            msg = error[0] or f"Camera {self.device_id} timeout ({self._timeout}s)"
            self._available = False
            raise RuntimeError(msg)

        self.cap = result[0]
        self._available = True

        # Warm up lebih lama agar auto-exposure/auto-gain sempat konvergen
        # (mencegah frame pertama gelap di Raspberry Pi). ~15 frame dengan jeda.
        for _ in range(15):
            self.cap.read()
            time.sleep(0.03)

    def open(self):
        """Re-open camera if it was closed"""
        with self._lock:
            if not self.is_open:
                self._initialize()

    def close(self):
        """Close camera and release resources"""
        with self._lock:
            if self.cap:
                self.cap.release()
                self.cap = None
                self._available = False

    def capture(self) -> Optional[np.ndarray]:
        """Capture a single frame"""
        with self._lock:
            if not self.is_open:
                try:
                    self._initialize()
                except RuntimeError:
                    return None

            ret, frame = self.cap.read()
            if not ret:
                return None
            return frame

    def capture_zone(self, zone: dict) -> Optional[np.ndarray]:
        """Capture and crop to specific zone"""
        frame = self.capture()
        if frame is None:
            return None
        x, y, w, h = zone['x'], zone['y'], zone['width'], zone['height']
        return frame[y:y+h, x:x+w]

    def release(self):
        """Release camera resources"""
        self.close()

    def __del__(self):
        self.release()
