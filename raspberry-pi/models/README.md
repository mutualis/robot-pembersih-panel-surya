# Models Directory

Letakkan YOLO model hasil training di sini.

## Two-Stage Detection (Recommended)

### File yang diperlukan:

**Stage 1: Panel Detection**
- `panel_detection.onnx` - YOLO11 Detection model untuk mendeteksi lokasi panel
- `panel_detection.pt` - PyTorch version (optional, untuk re-training)

**Stage 2: Dirt Classification**
- `dirt_classification.onnx` - YOLO11 Classification model untuk klasifikasi tingkat kotoran
- `dirt_classification.pt` - PyTorch version (optional, untuk re-training)

**Fallback: Single-Stage**
- `yolo11n_solar.onnx` - Single-stage model (backward compatible)

## Download Pretrained Model:

Jika belum training sendiri, download pretrained YOLO11:

```bash
# YOLO11 nano detection (untuk Stage 1)
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt

# YOLO11 nano classification (untuk Stage 2)
wget https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-cls.pt
```

## Training Models:

### Stage 1: Panel Detection

```bash
cd ../training
python app.py
# Pilih: "Stage 1 Saja (Deteksi Panel)"
# Epochs: 50-100
# Image size: 640
# Batch size: 16

# Output: runs/detect/panel_detection_yolo11_v1/weights/best.pt
```

### Stage 2: Dirt Classification

```bash
cd ../training
python app.py
# Pilih: "Stage 2 Saja (Klasifikasi Kotoran)"
# Epochs: 50-100
# Image size: 224
# Batch size: 16

# Output: runs/classify/dirt_classification_yolo11_v1/weights/best.pt
```

## Export ke ONNX:

### Stage 1: Panel Detection

```python
from ultralytics import YOLO

# Load trained model
model = YOLO('runs/detect/panel_detection_yolo11_v1/weights/best.pt')

# Export to ONNX
model.export(format='onnx', simplify=True)

# Output: runs/detect/panel_detection_yolo11_v1/weights/best.onnx
```

### Stage 2: Dirt Classification

```python
from ultralytics import YOLO

# Load trained model
model = YOLO('runs/classify/dirt_classification_yolo11_v1/weights/best.pt')

# Export to ONNX
model.export(format='onnx', simplify=True)

# Output: runs/classify/dirt_classification_yolo11_v1/weights/best.onnx
```

## Deploy ke Raspberry Pi:

```bash
# Copy Stage 1 model
scp runs/detect/panel_detection_yolo11_v1/weights/best.onnx \
    pi@raspberrypi.local:~/raspberry-pi/models/panel_detection.onnx

# Copy Stage 2 model
scp runs/classify/dirt_classification_yolo11_v1/weights/best.onnx \
    pi@raspberrypi.local:~/raspberry-pi/models/dirt_classification.onnx
```

## Model Structure:

```
models/
├── panel_detection.onnx       # Stage 1: Detect panel location
├── dirt_classification.onnx   # Stage 2: Classify dirt level
└── yolo11n_solar.onnx         # Fallback: Single-stage (optional)
```

## Performance Expectations:

### Two-Stage Detection:
- **Stage 1 (Panel Detection):** ~58ms, mAP@0.5 > 90%
- **Stage 2 (Dirt Classification):** ~28ms, Accuracy 85-95%
- **Total:** ~86ms (11.6 FPS)

### Single-Stage Detection:
- **Total:** ~50ms (20 FPS)
- **Accuracy:** 75-80%

**Recommendation:** Use two-stage for better accuracy!
