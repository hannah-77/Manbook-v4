"""
Full Surya Integration Test — writes results to file
"""
import sys
import time
import traceback
import os
import glob

log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_surya_test_result.txt")

with open(log_path, "w", encoding="utf-8") as f:
    def log(msg):
        print(msg)
        f.write(msg + "\n")
    
    log(f"Python: {sys.version}")
    log("=" * 60)

    # Step 1: Import
    log("\n[1/4] Importing Surya modules...")
    t0 = time.time()
    try:
        from PIL import Image as PILImage
        from surya.foundation import FoundationPredictor
        from surya.layout import LayoutPredictor
        from surya.settings import settings as surya_settings
        log(f"  OK All Surya imports ({time.time()-t0:.1f}s)")
        log(f"  LAYOUT_MODEL_CHECKPOINT: {surya_settings.LAYOUT_MODEL_CHECKPOINT}")
    except Exception:
        log(traceback.format_exc())
        log("  FAILED Surya import")
        sys.exit(1)

    # Step 2: Init model
    log("\n[2/4] Initializing Surya model...")
    t1 = time.time()
    try:
        foundation = FoundationPredictor(
            checkpoint=surya_settings.LAYOUT_MODEL_CHECKPOINT
        )
        layout_predictor = LayoutPredictor(foundation)
        log(f"  OK Model initialized ({time.time()-t1:.1f}s)")
    except Exception:
        log(traceback.format_exc())
        log("  FAILED Model initialization")
        sys.exit(1)

    # Step 3: Load image
    log("\n[3/4] Loading test image...")
    preview_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_results")
    preview_images = glob.glob(os.path.join(preview_dir, "PREVIEW_*.jpg"))
    if not preview_images:
        preview_images = glob.glob(os.path.join(preview_dir, "*.jpg"))
    if not preview_images:
        lh = os.path.join(os.path.dirname(os.path.abspath(__file__)), "letterhead.png")
        if os.path.exists(lh):
            preview_images = [lh]
    
    if not preview_images:
        log("  FAILED No test images found!")
        sys.exit(1)

    test_image = preview_images[0]
    log(f"  Using: {os.path.basename(test_image)}")
    
    try:
        pil_img = PILImage.open(test_image).convert("RGB")
        log(f"  OK Image loaded: {pil_img.size[0]}x{pil_img.size[1]}")
    except Exception:
        log(traceback.format_exc())
        log("  FAILED Image load")
        sys.exit(1)

    # Step 4: Run layout detection
    log("\n[4/4] Running Surya layout detection...")
    t2 = time.time()
    try:
        predictions = layout_predictor([pil_img])
        elapsed = time.time() - t2

        if not predictions:
            log("  FAILED No predictions returned!")
            sys.exit(1)

        page_pred = predictions[0]
        bboxes = page_pred.bboxes if hasattr(page_pred, 'bboxes') else []

        log(f"  OK Layout detection ({elapsed:.1f}s)")
        log(f"  Found {len(bboxes)} layout elements")

        label_counts = {}
        for item in bboxes:
            label = (item.label if hasattr(item, 'label') else 'unknown').lower()
            bbox = item.bbox if hasattr(item, 'bbox') else [0,0,0,0]
            position = item.position if hasattr(item, 'position') else -1
            
            label_counts[label] = label_counts.get(label, 0) + 1

            x1, y1, x2, y2 = [int(v) for v in bbox]
            w = x2 - x1
            h = y2 - y1
            log(f"    [{position:2d}] {label:20s}  bbox=({x1},{y1},{x2},{y2})  size={w}x{h}")

        log(f"\n  Summary: {dict(sorted(label_counts.items()))}")
    except Exception:
        log(traceback.format_exc())
        log("  FAILED Layout detection")
        sys.exit(1)

    log("\n" + "=" * 60)
    log("ALL TESTS PASSED — Surya is fully functional!")
    log("=" * 60)
    log(f"\nResults saved to: {log_path}")
