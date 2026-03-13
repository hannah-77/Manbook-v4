import traceback
import sys

print(f"Python: {sys.version}")

try:
    from surya.foundation import FoundationPredictor
    print("✓ surya.foundation OK")
except Exception:
    traceback.print_exc()
    print("✗ surya.foundation FAILED")

try:
    from surya.layout import LayoutPredictor
    print("✓ surya.layout OK")
except Exception:
    traceback.print_exc()
    print("✗ surya.layout FAILED")

try:
    from surya.settings import settings
    print(f"✓ surya.settings OK - LAYOUT_MODEL_CHECKPOINT: {settings.LAYOUT_MODEL_CHECKPOINT}")
except Exception:
    traceback.print_exc()
    print("✗ surya.settings FAILED")

print("\nDone.")
