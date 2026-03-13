"""
OCR Engines Integration Test
Tests: Tesseract (Indonesian + English) & PaddleOCR (English fallback)
Validates each engine independently on a real image crop.
"""
import sys
import os
import time
import traceback
import glob
import numpy as np

log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ocr_test_result.txt")

with open(log_path, "w", encoding="utf-8") as f:
    def log(msg):
        print(msg)
        f.write(msg + "\n")

    log(f"Python: {sys.version}")
    log("=" * 60)

    # ── Step 1: Check Tesseract availability ──
    log("\n[1/6] Checking Tesseract OCR...")
    TESSERACT_OK = False
    try:
        import pytesseract
        from PIL import Image

        tesseract_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.join("C:\\Users", os.getenv('USERNAME', ''), "AppData", "Local", "Tesseract-OCR", "tesseract.exe"),
        ]
        for tpath in tesseract_paths:
            if os.path.exists(tpath):
                pytesseract.pytesseract.tesseract_cmd = tpath
                TESSERACT_OK = True
                log(f"  OK Tesseract found at: {tpath}")
                break

        if not TESSERACT_OK:
            import shutil
            if shutil.which('tesseract'):
                TESSERACT_OK = True
                log(f"  OK Tesseract found in PATH")

        if TESSERACT_OK:
            ver = pytesseract.get_tesseract_version()
            log(f"  OK Tesseract version: {ver}")

            # Check available languages
            langs = pytesseract.get_languages()
            log(f"  Installed language packs: {langs}")
            has_ind = 'ind' in langs
            has_eng = 'eng' in langs
            log(f"  Indonesian (ind): {'OK' if has_ind else 'MISSING'}")
            log(f"  English (eng): {'OK' if has_eng else 'MISSING'}")
        else:
            log("  WARNING Tesseract not found on system")

    except ImportError:
        log("  WARNING pytesseract package not installed")
    except Exception as e:
        log(f"  WARNING Tesseract check error: {e}")

    # ── Step 2: Check PaddleOCR availability ──
    log("\n[2/6] Checking PaddleOCR...")
    PADDLE_OK = False
    try:
        # NumPy 2.0 compat shim
        if not hasattr(np, 'sctypes'):
            np.sctypes = {
                'int':     [np.int8, np.int16, np.int32, np.int64],
                'uint':    [np.uint8, np.uint16, np.uint32, np.uint64],
                'float':   [np.float16, np.float32, np.float64],
                'complex': [np.complex64, np.complex128],
                'others':  [bool, object, bytes, str, np.void],
            }
        from paddleocr import PaddleOCR
        PADDLE_OK = True
        log("  OK PaddleOCR imported successfully")
    except ImportError as e:
        log(f"  WARNING PaddleOCR not available: {e}")
    except Exception as e:
        log(f"  WARNING PaddleOCR import error: {e}")

    # ── Step 3: Load a test image ──
    log("\n[3/6] Loading test image...")
    import cv2

    preview_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_results")
    preview_images = glob.glob(os.path.join(preview_dir, "PREVIEW_*.jpg"))
    if not preview_images:
        preview_images = glob.glob(os.path.join(preview_dir, "*.jpg"))

    if not preview_images:
        log("  FAILED No test images found!")
        sys.exit(1)

    test_image = preview_images[0]
    log(f"  Using: {os.path.basename(test_image)}")

    img_cv = cv2.imread(test_image)
    if img_cv is None:
        log(f"  FAILED Cannot read image: {test_image}")
        sys.exit(1)

    h, w = img_cv.shape[:2]
    log(f"  OK Image loaded: {w}x{h}")

    # Crop a text region from the page (upper-middle area, likely has text)
    # Use top ~20% of the page as test crop (usually contains headings/text)
    crop_y1, crop_y2 = int(h * 0.05), int(h * 0.25)
    crop_x1, crop_x2 = int(w * 0.03), int(w * 0.95)
    text_crop = img_cv[crop_y1:crop_y2, crop_x1:crop_x2]
    log(f"  Test crop region: ({crop_x1},{crop_y1}) to ({crop_x2},{crop_y2}) = {crop_x2-crop_x1}x{crop_y2-crop_y1} px")

    # ── Step 4: Test Tesseract OCR (English) ──
    log("\n[4/6] Testing Tesseract OCR (English - eng)...")
    if TESSERACT_OK:
        t0 = time.time()
        try:
            rgb = cv2.cvtColor(text_crop, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            data = pytesseract.image_to_data(
                pil_img, lang='eng', config='--oem 3 --psm 6',
                output_type=pytesseract.Output.DICT
            )

            words = []
            confidences = []
            for i, txt in enumerate(data['text']):
                txt = txt.strip()
                conf = int(data['conf'][i])
                if txt and conf > 25:
                    words.append(txt)
                    confidences.append(conf / 100.0)

            elapsed = time.time() - t0
            if words:
                avg_conf = sum(confidences) / len(confidences)
                text_result = ' '.join(words)
                log(f"  OK Tesseract (eng) extracted {len(words)} words in {elapsed:.1f}s")
                log(f"  Avg confidence: {avg_conf:.2f}")
                log(f"  Text preview: {text_result[:200]}...")
            else:
                log(f"  WARNING Tesseract (eng) found no text ({elapsed:.1f}s)")
        except Exception as e:
            log(f"  FAILED Tesseract (eng) error: {e}")
            traceback.print_exc()
    else:
        log("  SKIPPED (Tesseract not available)")

    # ── Step 5: Test Tesseract OCR (Indonesian) ──
    log("\n[5/6] Testing Tesseract OCR (Indonesian - ind)...")
    if TESSERACT_OK and has_ind:
        t0 = time.time()
        try:
            rgb = cv2.cvtColor(text_crop, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            data = pytesseract.image_to_data(
                pil_img, lang='ind', config='--oem 3 --psm 6',
                output_type=pytesseract.Output.DICT
            )

            words = []
            confidences = []
            for i, txt in enumerate(data['text']):
                txt = txt.strip()
                conf = int(data['conf'][i])
                if txt and conf > 25:
                    words.append(txt)
                    confidences.append(conf / 100.0)

            elapsed = time.time() - t0
            if words:
                avg_conf = sum(confidences) / len(confidences)
                text_result = ' '.join(words)
                log(f"  OK Tesseract (ind) extracted {len(words)} words in {elapsed:.1f}s")
                log(f"  Avg confidence: {avg_conf:.2f}")
                log(f"  Text preview: {text_result[:200]}...")
            else:
                log(f"  WARNING Tesseract (ind) found no text ({elapsed:.1f}s)")
        except Exception as e:
            log(f"  FAILED Tesseract (ind) error: {e}")
            traceback.print_exc()
    elif TESSERACT_OK and not has_ind:
        log("  SKIPPED (Indonesian lang pack not installed)")
    else:
        log("  SKIPPED (Tesseract not available)")

    # ── Step 6: Test PaddleOCR (English) ──
    log("\n[6/6] Testing PaddleOCR (English)...")
    if PADDLE_OK:
        t0 = time.time()
        try:
            ocr_engine = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
            init_time = time.time() - t0
            log(f"  OK PaddleOCR initialized ({init_time:.1f}s)")

            t1 = time.time()
            ocr_result = ocr_engine.ocr(text_crop, cls=False)
            ocr_time = time.time() - t1

            if ocr_result and ocr_result[0]:
                lines = []
                confidences = []
                for line in ocr_result[0]:
                    text = line[1][0]
                    conf = line[1][1]
                    if conf > 0.35:
                        lines.append(text)
                        confidences.append(conf)

                if lines:
                    avg_conf = sum(confidences) / len(confidences)
                    text_result = ' '.join(lines)
                    log(f"  OK PaddleOCR extracted {len(lines)} lines in {ocr_time:.1f}s")
                    log(f"  Avg confidence: {avg_conf:.2f}")
                    log(f"  Text preview: {text_result[:200]}...")
                else:
                    log(f"  WARNING PaddleOCR found no high-confidence text ({ocr_time:.1f}s)")
            else:
                log(f"  WARNING PaddleOCR returned empty result ({ocr_time:.1f}s)")
        except Exception as e:
            log(f"  FAILED PaddleOCR error: {e}")
            traceback.print_exc()
    else:
        log("  SKIPPED (PaddleOCR not available)")

    # ── Summary ──
    log("\n" + "=" * 60)
    log("SUMMARY")
    log("=" * 60)
    log(f"  Tesseract OCR:  {'OK' if TESSERACT_OK else 'NOT AVAILABLE'}")
    if TESSERACT_OK:
        log(f"    - English (eng):    {'OK' if has_eng else 'MISSING'}")
        log(f"    - Indonesian (ind): {'OK' if has_ind else 'MISSING'}")
    log(f"  PaddleOCR:      {'OK' if PADDLE_OK else 'NOT AVAILABLE'}")
    log("=" * 60)
    log(f"\nResults saved to: {log_path}")
