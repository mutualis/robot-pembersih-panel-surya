"""
Model Manager — kelola model YOLO (.pt) via web.

Fitur:
- Upload model .pt untuk stage tertentu (detection / classification)
- Daftar model tersedia per stage
- Pilih (aktifkan) model mana yang dipakai per stage
- Hapus model
- Deteksi otomatis jenis model (detection vs classification) dari isi .pt

Layout penyimpanan:
  models/
    detection/        *.pt  (Stage 1 — deteksi panel)
    classification/   *.pt  (Stage 2 — klasifikasi kekotoran)
    active.json       { "detection": "<file>", "classification": "<file>" }

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import os
import json
import shutil
import threading
from datetime import datetime
from typing import Dict, List, Optional


class ModelManager:
    STAGES = ("detection", "classification")

    def __init__(self, models_dir: str = "models"):
        self.models_dir = models_dir
        self.dirs = {
            "detection": os.path.join(models_dir, "detection"),
            "classification": os.path.join(models_dir, "classification"),
        }
        self.active_file = os.path.join(models_dir, "active.json")
        self._lock = threading.Lock()
        self._ensure_layout()

    # ------------------------------------------------------------------
    def _ensure_layout(self):
        """Buat folder per stage; migrasi model lama bila ada."""
        for d in self.dirs.values():
            os.makedirs(d, exist_ok=True)

        # Migrasi: salin model lama (flat) ke folder stage bila belum ada
        legacy = {
            "detection": os.path.join(self.models_dir, "panel_detection_best.pt"),
            "classification": os.path.join(self.models_dir, "dirt_classification_best.pt"),
        }
        active = self._read_active()
        for stage, legacy_path in legacy.items():
            if os.path.exists(legacy_path):
                dest = os.path.join(self.dirs[stage], os.path.basename(legacy_path))
                if not os.path.exists(dest):
                    try:
                        shutil.copy2(legacy_path, dest)
                    except Exception:
                        pass
                # Set sebagai aktif bila belum ada yang aktif
                if not active.get(stage):
                    active[stage] = os.path.basename(legacy_path)
        self._write_active(active)

    # ------------------------------------------------------------------
    def _read_active(self) -> Dict:
        try:
            with open(self.active_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write_active(self, data: Dict):
        try:
            with open(self.active_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[ModelManager] Gagal menulis active.json: {e}")

    @staticmethod
    def _safe_name(name: str) -> str:
        """Sanitasi nama file: hanya basename, hanya .pt, tanpa path traversal."""
        name = os.path.basename(name or "").strip()
        # buang karakter berbahaya
        name = "".join(c for c in name if c.isalnum() or c in "._- ")
        return name

    # ------------------------------------------------------------------
    def list_models(self) -> Dict:
        """Daftar semua model per stage + mana yang aktif."""
        active = self._read_active()
        result = {}
        for stage in self.STAGES:
            files = []
            d = self.dirs[stage]
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if not fn.lower().endswith(".pt"):
                        continue
                    fpath = os.path.join(d, fn)
                    try:
                        stat = os.stat(fpath)
                        size_mb = round(stat.st_size / (1024 * 1024), 2)
                        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                    except OSError:
                        size_mb, mtime = 0, "-"
                    files.append({
                        "name": fn,
                        "size_mb": size_mb,
                        "modified": mtime,
                        "active": fn == active.get(stage),
                    })
            result[stage] = {
                "models": files,
                "active": active.get(stage),
            }
        return {"success": True, "stages": result}

    def get_active_path(self, stage: str) -> Optional[str]:
        """Path absolut model aktif untuk stage, atau None."""
        if stage not in self.STAGES:
            return None
        active = self._read_active().get(stage)
        if not active:
            return None
        p = os.path.join(self.dirs[stage], active)
        return p if os.path.exists(p) else None

    # ------------------------------------------------------------------
    @staticmethod
    def detect_model_task(model_path: str) -> Optional[str]:
        """
        Deteksi jenis model dari isi file .pt: 'detection' atau 'classification'.
        Memuat model via ultralytics dan membaca atribut task.
        Return None bila gagal/ tidak dikenal.
        """
        try:
            from ultralytics import YOLO
            m = YOLO(model_path)
            task = getattr(m, "task", None)
            if task == "classify":
                return "classification"
            if task in ("detect", "segment", "pose", "obb"):
                return "detection"
            return None
        except Exception as e:
            print(f"[ModelManager] Gagal deteksi jenis model: {e}")
            return None

    def upload_model(self, stage: str, filename: str, tmp_path: str,
                     auto_detect: bool = True) -> Dict:
        """
        Simpan file model yang sudah diupload (ada di tmp_path) ke folder stage.

        - Validasi ekstensi .pt
        - Validasi isi: harus model YOLO valid; jenis dicocokkan dengan stage
        - Tidak menimpa diam-diam: bila nama sudah ada, beri akhiran timestamp
        Return: {success, message, name, detected_task}
        """
        if stage not in self.STAGES:
            return {"success": False, "message": f"Stage tidak valid: {stage}"}

        safe = self._safe_name(filename)
        if not safe.lower().endswith(".pt"):
            return {"success": False, "message": "File harus berekstensi .pt"}

        if not os.path.exists(tmp_path):
            return {"success": False, "message": "File upload tidak ditemukan"}

        # Validasi: coba muat sebagai model YOLO + deteksi jenis
        detected = self.detect_model_task(tmp_path)
        if detected is None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return {"success": False, "message": "File bukan model YOLO yang valid"}

        # Cek kecocokan jenis dengan stage yang dipilih
        if detected != stage:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return {
                "success": False,
                "message": f"Jenis model ({detected}) tidak cocok dengan stage "
                           f"yang dipilih ({stage}). Pilih stage yang benar.",
            }

        # Tentukan nama tujuan (hindari menimpa)
        dest = os.path.join(self.dirs[stage], safe)
        if os.path.exists(dest):
            base, ext = os.path.splitext(safe)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = f"{base}_{stamp}{ext}"
            dest = os.path.join(self.dirs[stage], safe)

        with self._lock:
            try:
                shutil.move(tmp_path, dest)
            except Exception as e:
                return {"success": False, "message": f"Gagal menyimpan model: {e}"}

        return {
            "success": True,
            "message": f"Model '{safe}' berhasil diupload untuk stage {stage}",
            "name": safe,
            "detected_task": detected,
        }

    def select_model(self, stage: str, name: str) -> Dict:
        """Aktifkan model tertentu untuk stage. Return path agar caller bisa reload."""
        if stage not in self.STAGES:
            return {"success": False, "message": f"Stage tidak valid: {stage}"}
        safe = self._safe_name(name)
        path = os.path.join(self.dirs[stage], safe)
        if not os.path.exists(path):
            return {"success": False, "message": f"Model '{safe}' tidak ditemukan"}

        with self._lock:
            active = self._read_active()
            active[stage] = safe
            self._write_active(active)

        return {
            "success": True,
            "message": f"Model aktif untuk {stage}: {safe}",
            "path": path,
            "stage": stage,
        }

    def delete_model(self, stage: str, name: str) -> Dict:
        """Hapus model. Tidak boleh menghapus model yang sedang aktif."""
        if stage not in self.STAGES:
            return {"success": False, "message": f"Stage tidak valid: {stage}"}
        safe = self._safe_name(name)
        path = os.path.join(self.dirs[stage], safe)
        if not os.path.exists(path):
            return {"success": False, "message": f"Model '{safe}' tidak ditemukan"}

        active = self._read_active()
        if active.get(stage) == safe:
            return {
                "success": False,
                "message": f"Tidak bisa menghapus model yang sedang aktif. "
                           f"Pilih model lain dulu sebagai aktif.",
            }

        with self._lock:
            try:
                os.unlink(path)
            except Exception as e:
                return {"success": False, "message": f"Gagal menghapus: {e}"}

        return {"success": True, "message": f"Model '{safe}' dihapus"}
