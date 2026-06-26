"""
Two-Stage Dirt Detector
Stage 1: Panel Detection
Stage 2: Dirt Classification

Author: Muhammad Ridho Assidiqi
"""

import cv2
import numpy as np
from typing import Dict, List, Optional
import os
import time

# Lazy import — ultralytics mungkin tidak tersedia di semua environment
YOLO = None
def _ensure_yolo():
    global YOLO
    if YOLO is None:
        from ultralytics import YOLO as _YOLO
        YOLO = _YOLO


class TwoStageDetector:
    """Two-stage detection: Panel detection -> Dirt classification"""
    
    def __init__(
        self,
        panel_model_path: str,
        dirt_model_path: str,
        panel_confidence: float = 0.5,
        dirt_confidence: float = 0.7,
        enable_performance_logging: bool = False
    ):
        self.panel_model_path = panel_model_path
        self.dirt_model_path = dirt_model_path
        self.panel_confidence = panel_confidence
        self.dirt_confidence = dirt_confidence
        
        self.panel_model = None
        self.dirt_model = None
        
        # Lock agar reload model tidak bentrok dengan inferensi yang berjalan
        import threading as _threading
        self._model_lock = _threading.Lock()
        
        # Performance logging
        self.enable_performance_logging = enable_performance_logging
        self.performance_logger = None
        
        if self.enable_performance_logging:
            try:
                from app.performance_logger import PerformanceLogger
                self.performance_logger = PerformanceLogger()
                print("[TwoStageDetector] Performance logging enabled")
            except ImportError:
                print("[TwoStageDetector] Warning: performance_logger not found")
                self.enable_performance_logging = False
        
        self._load_models()
    
    def _load_models(self):
        """Load both models"""
        try:
            _ensure_yolo()
        except ImportError:
            print("[!] ultralytics tidak terinstall — model YOLO tidak dapat di-load")
            print("  Gunakan: pip install ultralytics  (atau jalankan dengan venv yang benar)")
            return
        
        # Load Stage 1: Panel Detection
        if os.path.exists(self.panel_model_path):
            try:
                self.panel_model = YOLO(self.panel_model_path)
                print(f"[OK] Panel detection model loaded: {self.panel_model_path}")
            except Exception as e:
                print(f"[X] Error loading panel model: {e}")
                self.panel_model = None
        else:
            print(f"[X] Panel model not found: {self.panel_model_path}")
            self.panel_model = None
        
        # Load Stage 2: Dirt Classification
        if os.path.exists(self.dirt_model_path):
            try:
                self.dirt_model = YOLO(self.dirt_model_path)
                print(f"[OK] Dirt classification model loaded: {self.dirt_model_path}")
            except Exception as e:
                print(f"[X] Error loading dirt model: {e}")
                self.dirt_model = None
        else:
            print(f"[X] Dirt model not found: {self.dirt_model_path}")
            self.dirt_model = None
    
    def reload_model(self, stage: str, model_path: str) -> dict:
        """
        Muat ulang model untuk satu stage tanpa restart aplikasi.

        stage: 'panel' (deteksi) atau 'dirt' (klasifikasi).
        model_path: path ke file .pt yang akan dipakai.

        Thread-safe: inferensi yang sedang berjalan akan menunggu lock.
        Return: {success, message}
        """
        if stage not in ("panel", "dirt"):
            return {"success": False, "message": f"Stage tidak valid: {stage}"}
        if not os.path.exists(model_path):
            return {"success": False, "message": f"File model tidak ditemukan: {model_path}"}
        try:
            _ensure_yolo()
        except ImportError:
            return {"success": False, "message": "ultralytics tidak terinstall"}

        # Muat model baru DULU (di luar lock) supaya error tidak mengganggu model lama
        try:
            new_model = YOLO(model_path)
        except Exception as e:
            return {"success": False, "message": f"Gagal memuat model: {e}"}

        with self._model_lock:
            if stage == "panel":
                self.panel_model = new_model
                self.panel_model_path = model_path
            else:
                self.dirt_model = new_model
                self.dirt_model_path = model_path

        print(f"[OK] Model {stage} di-reload: {model_path}")
        return {"success": True, "message": f"Model {stage} aktif: {os.path.basename(model_path)}"}

    def detect(self, image: np.ndarray) -> Dict:
        """
        Two-stage detection pipeline
        
        Returns:
            {
                'panel_detected': bool,
                'panel_bbox': [x1, y1, x2, y2] or None,
                'panel_confidence': float,
                'dirt_level': str,
                'dirt_confidence': float,
                'weighted_score': float,
                'clean': bool,
                'detections': list,
                'stage1_time_ms': float (if logging enabled),
                'stage2_time_ms': float (if logging enabled),
                'total_time_ms': float (if logging enabled)
            }
        """
        # Stage 1: Detect panel (with timing)
        stage1_start = time.perf_counter()
        panel_result = self._detect_panel(image)
        stage1_time = time.perf_counter() - stage1_start
        
        if not panel_result['detected']:
            # No panel detected
            result = {
                'panel_detected': False,
                'panel_bbox': None,
                'panel_confidence': 0.0,
                'dirt_level': 'unknown',
                'dirt_confidence': 0.0,
                'weighted_score': 0.0,
                'clean': True,
                'detections': [],
                'message': 'No solar panel detected in image'
            }
            
            if self.enable_performance_logging:
                result['stage1_time_ms'] = round(stage1_time * 1000, 2)
                result['stage2_time_ms'] = 0.0
                result['total_time_ms'] = round(stage1_time * 1000, 2)
                
                # Log to performance logger even when no panel detected
                if self.performance_logger:
                    self.performance_logger.log_detection(
                        stage1_time=stage1_time,
                        stage2_time=0.0,
                        panel_detected=False,
                        panel_confidence=0.0,
                        dirt_level='unknown',
                        dirt_confidence=0.0,
                        weighted_score=0.0
                    )
            
            return result
        
        # Stage 2: Classify dirt level on detected panel (with timing)
        panel_bbox = panel_result['bbox']
        panel_roi = self._crop_panel(image, panel_bbox)
        
        stage2_start = time.perf_counter()
        dirt_result = self._classify_dirt(panel_roi)
        stage2_time = time.perf_counter() - stage2_start
        
        # Combine results
        result = {
            'panel_detected': True,
            'panel_bbox': panel_bbox,
            'panel_confidence': panel_result['confidence'],
            'dirt_level': dirt_result['category'],
            'dirt_confidence': dirt_result['confidence'],
            'weighted_score': dirt_result['weighted_score'],
            'clean': dirt_result['clean'],
            'detections': dirt_result['detections'],
            'category_counts': dirt_result.get('category_counts', {}),
            'dominant_category': dirt_result.get('dominant_category', 'unknown')
        }
        
        # Add timing info
        if self.enable_performance_logging:
            result['stage1_time_ms'] = round(stage1_time * 1000, 2)
            result['stage2_time_ms'] = round(stage2_time * 1000, 2)
            result['total_time_ms'] = round((stage1_time + stage2_time) * 1000, 2)
            
            # Log to performance logger
            if self.performance_logger:
                self.performance_logger.log_detection(
                    stage1_time=stage1_time,
                    stage2_time=stage2_time,
                    panel_detected=True,
                    panel_confidence=panel_result['confidence'],
                    dirt_level=dirt_result['category'],
                    dirt_confidence=dirt_result['confidence'],
                    weighted_score=dirt_result['weighted_score']
                )
        
        return result
    
    def detect_zones(self, image: np.ndarray, zones: list) -> list:
        """Jalankan deteksi dua-tahap pada gambar penuh, lalu tandai hasil dengan info zona.

        Model bekerja pada frame lengkap (bukan crop per zona) karena kamera
        sudah diarahkan ke satu panel. Zona hanya metadata (id, nama) yang
        diteruskan ke controller untuk identifikasi area. Jika zones kosong,
        kembalikan satu hasil tanpa metadata zona.
        """
        # Two-stage detection works on full image (panel detection + dirt classification)
        # Zone info is metadata only — the model handles the full frame
        result = self.detect(image)
        results = []
        if zones:
            for i, zone in enumerate(zones):
                zone_result = result.copy()
                zone_result['zone_id'] = zone.get('id', i)
                zone_result['zone_name'] = zone.get('name', f'Zone {i+1}')
                results.append(zone_result)
        else:
            results.append(result)
        return results
    
    def _detect_panel(self, image: np.ndarray) -> Dict:
        """
        Stage 1: Detect solar panel in image
        
        Returns:
            {
                'detected': bool,
                'bbox': [x1, y1, x2, y2] or None,
                'confidence': float
            }
        """
        # Ambil referensi lokal (snapshot) agar aman bila reload_model menukar
        # self.panel_model di tengah inferensi — kita tetap pakai model yang
        # konsisten untuk frame ini.
        model = self.panel_model
        if model is None:
            # Model not loaded — cannot detect panel
            return {
                'detected': False,
                'bbox': None,
                'confidence': 0.0,
                'message': 'Panel detection model not loaded'
            }
        
        # Run detection
        results = model(image, conf=self.panel_confidence, verbose=False)
        
        # Get best detection (highest confidence)
        best_detection = None
        best_conf = 0.0
        
        for result in results:
            boxes = result.boxes
            for box in boxes:
                conf = float(box.conf[0])
                if conf > best_conf:
                    best_conf = conf
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    best_detection = [int(x1), int(y1), int(x2), int(y2)]
        
        if best_detection is None:
            return {
                'detected': False,
                'bbox': None,
                'confidence': 0.0
            }
        
        return {
            'detected': True,
            'bbox': best_detection,
            'confidence': best_conf
        }
    
    def _crop_panel(self, image: np.ndarray, bbox: List[int]) -> np.ndarray:
        """Crop panel region from image"""
        x1, y1, x2, y2 = bbox
        
        # Add padding (10% of bbox size)
        w = x2 - x1
        h = y2 - y1
        pad_w = int(w * 0.1)
        pad_h = int(h * 0.1)
        
        # Expand bbox with padding
        x1 = max(0, x1 - pad_w)
        y1 = max(0, y1 - pad_h)
        x2 = min(image.shape[1], x2 + pad_w)
        y2 = min(image.shape[0], y2 + pad_h)
        
        # Crop
        panel_roi = image[y1:y2, x1:x2]
        
        return panel_roi
    
    def _classify_dirt(self, panel_image: np.ndarray) -> Dict:
        """
        Stage 2: Classify dirt level on panel
        
        Returns:
            {
                'category': str,
                'confidence': float,
                'weighted_score': float,
                'clean': bool,
                'detections': list
            }
        """
        # Snapshot referensi model (aman terhadap reload di tengah inferensi)
        model = self.dirt_model
        if model is None:
            # Model not loaded — cannot classify
            return {
                'category': 'unknown',
                'confidence': 0.0,
                'weighted_score': 0.0,
                'clean': True,
                'detections': [],
                'category_counts': {},
                'dominant_category': 'unknown',
                'message': 'Dirt classification model not loaded'
            }
        
        # Run classification
        results = model(panel_image, conf=self.dirt_confidence, verbose=False)
        
        # Bobot kategori berbasis NAMA kelas (bukan indeks).
        category_weights = {
            'bersih': 0,
            'kotor_ringan': 1.0,
            'kotor_sedang': 2.0,
            'kotor_berat': 3.0
        }
        
        # Get prediction
        detections = []
        weighted_score = 0.0
        category_counts = {'bersih': 0, 'kotor_ringan': 0, 'kotor_sedang': 0, 'kotor_berat': 0}
        
        for result in results:
            # Get top prediction
            probs = result.probs
            top1_idx = int(probs.top1)
            top1_conf = float(probs.top1conf)
            
            # PENTING: pakai pemetaan kelas milik model (result.names), BUKAN list
            # hardcoded. YOLO-cls mengurutkan kelas sesuai folder dataset (alfabetis:
            # bersih, kotor_berat, kotor_ringan, kotor_sedang) sehingga indeks TIDAK
            # sama dengan urutan logis bersih->ringan->sedang->berat. Hardcoding membuat
            # kelas salah label (mis. kotor_ringan terbaca kotor_sedang).
            names = result.names
            if hasattr(names, 'get'):
                category = names.get(top1_idx, 'unknown')
            else:
                category = names[top1_idx] if top1_idx < len(names) else 'unknown'
            
            if category not in category_counts:
                category_counts[category] = 0
            # Di-set ke 1 (bukan +=1) karena tiap inferensi hanya menghasilkan
            # SATU prediksi top-1 — hitungan per kategori adalah 0 atau 1.
            category_counts[category] = 1
            
            # Calculate weighted score with confidence modulation (hybrid formula)
            # Formula: S = 100 * w * (0.7 + 0.3 * conf)
            weight = category_weights.get(category, 0)
            weighted_score = 100 * weight * (0.7 + 0.3 * top1_conf)
            
            detections.append({
                'class': top1_idx,
                'category': category,
                'confidence': top1_conf,
                'area_percentage': 100.0
            })
        
        dominant_category = max(category_counts, key=category_counts.get) if detections else 'bersih'
        
        return {
            'category': dominant_category,
            'confidence': detections[0]['confidence'] if detections else 0.0,
            'weighted_score': round(weighted_score, 2),
            'clean': weighted_score < 70,
            'detections': detections,
            'category_counts': category_counts,
            'dominant_category': dominant_category
        }
    
    def _fallback_classify(self, image: np.ndarray) -> Dict:
        """Klasifikasi cadangan berbasis kecerahan OpenCV — dipakai bila model YOLO tidak tersedia.

        Heuristik sederhana: rata-rata kecerahan grayscale dibandingkan threshold
        untuk menentukan kategori. Akurasi jauh di bawah model YOLO (tidak melihat
        jenis kotoran), tetapi mencegah sistem mati total bila model belum diload.
        Dipanggil secara manual; pipeline utama tidak memanggil ini otomatis.
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Calculate average brightness
        avg_brightness = np.mean(gray)
        
        # Simple threshold-based classification
        if avg_brightness > 150:
            category = 'bersih'
            weighted_score = 5.0
        elif avg_brightness > 120:
            category = 'kotor_ringan'
            weighted_score = 20.0
        elif avg_brightness > 90:
            category = 'kotor_sedang'
            weighted_score = 50.0
        else:
            category = 'kotor_berat'
            weighted_score = 80.0
        
        return {
            'category': category,
            'confidence': 0.8,
            'weighted_score': weighted_score,
            'clean': weighted_score < 70,
            'detections': [{
                'class': 0,
                'category': category,
                'confidence': 0.8,
                'area_percentage': 100.0
            }],
            'category_counts': {category: 1},
            'dominant_category': category,
            'method': 'fallback_opencv'
        }
    
    def get_performance_stats(self) -> Optional[Dict]:
        """Get real-time performance statistics"""
        if self.performance_logger:
            return self.performance_logger.get_realtime_stats()
        return None
    
    def generate_performance_report(self) -> Optional[Dict]:
        """Generate comprehensive performance report"""
        if self.performance_logger:
            return self.performance_logger.generate_summary_report()
        return None
    
    def export_performance_for_bab4(self, output_dir: str = "analysis_output/performance"):
        """Export performance data for analysis"""
        if self.performance_logger:
            return self.performance_logger.export_for_bab4(output_dir)
        return None
