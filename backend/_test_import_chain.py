"""Test the full import chain as vision_engine.py does it."""
import numpy as np

# NumPy 2.0 compat shim (same as vision_engine.py)
if not hasattr(np, 'sctypes'):
    np.sctypes = {
        'int':     [np.int8, np.int16, np.int32, np.int64],
        'uint':    [np.uint8, np.uint16, np.uint32, np.uint64],
        'float':   [np.float16, np.float32, np.float64],
        'complex': [np.complex64, np.complex128],
        'others':  [bool, object, bytes, str, np.void],
    }

print(f"numpy {np.__version__}")

try:
    import torch
    print(f"torch {torch.__version__} — device: {'cuda' if torch.cuda.is_available() else 'cpu'}")
except ImportError as e:
    print(f"FAILED torch: {e}")

try:
    from PIL import Image as PILImage
    print("PIL OK")
except ImportError as e:
    print(f"FAILED PIL: {e}")

try:
    from surya.foundation import FoundationPredictor
    print("surya.foundation OK")
except ImportError as e:
    print(f"FAILED surya.foundation: {e}")

try:
    from surya.layout import LayoutPredictor
    print("surya.layout OK")
except ImportError as e:
    print(f"FAILED surya.layout: {e}")

try:
    from surya.settings import settings as surya_settings
    print(f"surya.settings OK — LAYOUT_MODEL_CHECKPOINT: {surya_settings.LAYOUT_MODEL_CHECKPOINT}")
except ImportError as e:
    print(f"FAILED surya.settings: {e}")

try:
    from paddleocr import PaddleOCR
    print("paddleocr OK")
except ImportError as e:
    print(f"FAILED paddleocr: {e}")

print("\n=== ALL IMPORTS TESTED ===")
