"""
Configuration Management

Modul untuk mengelola konfigurasi sistem dari file YAML.
Mendukung dot notation untuk akses nested config.

Author: Muhammad Ridho Assidiqi
Institution: Universitas Gadjah Mada
"""

import yaml
import json
import os
from pathlib import Path
from typing import Dict, Any, List

class Config:
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = config_path
        self.zones_path = "config/zones.json"
        self.config = self._load_yaml()
        self.zones = self._load_zones()
    
    def _load_yaml(self) -> Dict[str, Any]:
        """Load YAML configuration"""
        try:
            with open(self.config_path, 'r') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"Config file not found: {self.config_path}")
            return self._default_config()
    
    def _load_zones(self) -> List[Dict]:
        """Load zone configuration"""
        try:
            with open(self.zones_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return []
    
    def save_zones(self, zones: List[Dict]) -> bool:
        """Save zone configuration"""
        try:
            os.makedirs(os.path.dirname(self.zones_path), exist_ok=True)
            with open(self.zones_path, 'w') as f:
                json.dump(zones, f, indent=2)
            self.zones = zones
            return True
        except Exception as e:
            print(f"Error saving zones: {e}")
            return False
    
    def get(self, key: str, default=None):
        """Baca nilai konfigurasi dengan dot notation (mis. 'cleaning.monitor_interval').

        Traversal berhenti dan mengembalikan `default` jika salah satu segmen
        key tidak ada, bukan dict, atau nilainya None.
        """
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def set(self, key: str, value: Any):
        """Tulis nilai konfigurasi dengan dot notation.

        Dict perantara dibuat otomatis bila belum ada — aman untuk key nested
        yang belum pernah di-set sebelumnya (mis. 'baru.seksi.nilai').
        Perubahan hanya ada di memori sampai save() dipanggil.
        """
        keys = key.split('.')
        config = self.config

        # Navigate to the parent dict
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        # Set the value
        config[keys[-1]] = value

    def save(self) -> bool:
        """Save configuration to YAML file"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, sort_keys=False)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def _default_config(self) -> Dict[str, Any]:
        """Konfigurasi bawaan — dikembalikan bila settings.yaml tidak ditemukan atau gagal di-parse.

        Nilai di sini harus bisa membuat sistem berjalan minimal (deteksi, web server)
        tanpa membutuhkan file konfigurasi manual. Setelah berjalan, simpan via save()
        agar settings.yaml terbentuk dan bisa diedit.
        """
        return {
            'camera': {
                'resolution': [1920, 1080],
                'fps': 30,
                'device_id': 0
            },
            'detection': {
                'confidence_threshold': 0.5,
                'interval_seconds': 1
            },
            'cleaning': {
                'trigger_threshold': 70,
                'cooldown_after_success': 300,
                'cycles': {
                    'max_attempts': 5,
                    'verify_delay': 2,
                    'success_threshold': 70
                },
                'monitor_interval': 1,
                'verify_interval': 2
            },
            'monitoring': {
                'working_hours': {
                    'enabled': True,
                    'start': '07:00',
                    'stop': '17:00'
                }
            },
            'serial': {
                'port': '/dev/serial0',
                'baudrate': 115200,
                'timeout': 1
            },
            'web': {
                'host': '0.0.0.0',
                'port': 5000
            }
        }
