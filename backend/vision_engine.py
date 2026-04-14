"""
HYBRID VISION PIPELINE v7 — Surya + Tesseract + AI
============================================================

Strategy (3-stage pipeline):
  Stage 1: Surya           → Layout detection (text / table / figure / heading regions)
  Stage 2: PaddleOCR       → English text extraction (PRIMARY for English)
           Tesseract OCR   → Indonesian text extraction (PRIMARY for Indonesian, lang pack 'ind')
           Each falls back to the other if the primary engine fails
  Stage 3: AI (Gemini)     → Chapter classification (TEXT-ONLY, no image = cheap & fast)

Why Surya (replaces PPStructure):
  - More accurate layout classification (Section-header, Text, Table, Figure, etc.)
  - Better at distinguishing tables vs figures vs text
  - Provides reading order detection
  - Supports 90+ languages

Why Tesseract:
  - Has dedicated Indonesian language pack (`ind`) = far fewer typos
  - Has dedicated English language pack (`eng`) = proven accuracy
  - Industry standard OCR used by Google, Adobe, Microsoft
  - Fast and reliable for printed text

Updated: March 2026
"""

import os
import cv2
import numpy as np
import logging
import json
import re
import base64

# ── NumPy 2.0 compatibility shim ──
# PaddleOCR uses np.sctypes which was removed in NumPy 2.0.
# Monkey-patch it back so PaddleOCR can import without errors.
if not hasattr(np, 'sctypes'):
    np.sctypes = {
        'int':     [np.int8, np.int16, np.int32, np.int64],
        'uint':    [np.uint8, np.uint16, np.uint32, np.uint64],
        'float':   [np.float16, np.float32, np.float64],
        'complex': [np.complex64, np.complex128],
        'others':  [bool, object, bytes, str, np.void],
    }

# ⚠️ CRITICAL: Import torch/surya BEFORE paddleocr on Windows to prevent DLL Hell (WinError 127)
# Surya Layout Detection (replaces PPStructure)
try:
    import torch  # Pre-load torch DLLs safely
    from PIL import Image as PILImage
    from surya.foundation import FoundationPredictor
    from surya.layout import LayoutPredictor
    from surya.settings import settings as surya_settings
    SURYA_AVAILABLE = True
except ImportError as _surya_err:
    SURYA_AVAILABLE = False
    logging.warning(f"⚠️ Surya not available: {_surya_err}. Layout detection will be limited.")

from paddleocr import PaddleOCR
from dotenv import load_dotenv

# Tesseract OCR (PRIMARY)
try:
    import pytesseract
    from PIL import Image

    # Auto-detect Tesseract path on Windows
    tesseract_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join("C:\\Users", os.getenv('USERNAME', ''), "AppData", "Local", "Tesseract-OCR", "tesseract.exe"),
    ]
    TESSERACT_AVAILABLE = False
    for tpath in tesseract_paths:
        if os.path.exists(tpath):
            pytesseract.pytesseract.tesseract_cmd = tpath
            TESSERACT_AVAILABLE = True
            break

    # Check if tesseract is in PATH
    if not TESSERACT_AVAILABLE:
        import shutil
        if shutil.which('tesseract'):
            TESSERACT_AVAILABLE = True

    if TESSERACT_AVAILABLE:
        # Verify it works
        ver = pytesseract.get_tesseract_version()
        logging.info(f"✓ Tesseract OCR v{ver} found")
    else:
        logging.warning("⚠️ Tesseract OCR not found — will use PaddleOCR fallback")

except ImportError:
    TESSERACT_AVAILABLE = False
    logging.warning("⚠️ pytesseract not installed — will use PaddleOCR fallback")

# Import OpenRouter Smart Client
from openrouter_client import get_openrouter_client

# Import Language Filter (enforce target language on all output)
from language_filter import enforce_language, get_language_instruction, clean_text

# Import Text Corrector (OCR post-processor)
try:
    from text_corrector import correct_ocr_text
    TEXT_CORRECTOR_AVAILABLE = True
except ImportError:
    TEXT_CORRECTOR_AVAILABLE = False
    logger.warning("⚠️ text_corrector not available — OCR correction disabled")

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize OpenRouter (for chapter classification only)
openrouter = get_openrouter_client()
AI_AVAILABLE = openrouter.is_available

if AI_AVAILABLE:
    logger.info("✓ OpenRouter Client: Active (chapter classification)")
else:
    logger.warning("⚠️ OpenRouter unavailable — will use keyword-based fallback")


class BioVisionHybrid:
    def __init__(self):
        """
        Initialize the 3-stage hybrid pipeline:
        1. Surya         → layout detection (replaces PPStructure)
        2. PaddleOCR     → text extraction
        3. AI            → chapter classification (text-only)
        """
        # ── Stage 1: Surya Layout Engine ──
        if SURYA_AVAILABLE:
            logger.info("Initializing Surya Layout Predictor...")
            self._surya_foundation = FoundationPredictor(
                checkpoint=surya_settings.LAYOUT_MODEL_CHECKPOINT
            )
            self.layout_engine = LayoutPredictor(self._surya_foundation)
            logger.info("✓ Surya Layout Predictor: Ready")
        else:
            logger.warning("⚠️ Surya not available — layout detection will be limited")
            self.layout_engine = None

        # ── Stage 2: OCR Engines ──
        # INDONESIAN: Tesseract OCR (lang pack 'ind')
        if TESSERACT_AVAILABLE:
            logger.info("✓ Tesseract OCR: Ready (Indonesian)")
        else:
            logger.info("⚠️ Tesseract unavailable — PaddleOCR will be used as fallback for Indonesian")

        # ENGLISH: PaddleOCR (lang 'en')
        logger.info("Initializing PaddleOCR: Ready (English)...")
        self.ocr_engine = PaddleOCR(
            use_angle_cls=False,  # Matikan untuk menghemat waktu (overhead berkurang signifikan)
            lang='en',
            use_gpu=True,         # Gunakan GPU jika tersedia, fallback ke CPU secara otomatis
            show_log=False
        )

        logger.info("✓ Hybrid Vision Pipeline v7 (Surya + Tesseract/PaddleOCR) Ready")

    # ═══════════════════════════════════════════════════════════════
    # HELPER: Detect Bordered Boxes (letterheads, company headers)
    # ═══════════════════════════════════════════════════════════════
    def _detect_bordered_boxes(self, image_cv):
        """
        Detect rectangular regions with visible borders using OpenCV contours.
        Catches company letterheads and framed tables that PPStructure would
        break into individual text line regions.

        Returns list of [x1, y1, x2, y2].
        """
        h, w = image_cv.shape[:2]
        gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)

        # Threshold: dark lines on white — finds borders/outlines
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        bordered = []
        min_area = (w * h) * 0.008   # minimum 0.8% of page
        max_area = (w * h) * 0.65    # maximum 65% of page

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue

            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.03 * peri, True)

            # Accept 3-6 corner shapes (rectangles, slight distortions)
            if not (3 <= len(approx) <= 6):
                continue

            x, y, bw, bh = cv2.boundingRect(cnt)
            if bw < w * 0.25 or bh < 10:
                continue

            # Fill ratio: border boxes have low fill (hollow inside)
            rect_area = bw * bh
            fill_ratio = area / rect_area if rect_area > 0 else 0
            if fill_ratio > 0.50:
                continue  # Solid block, not a border

            pad = 8
            bordered.append([
                max(0, x - pad), max(0, y - pad),
                min(w, x + bw + pad), min(h, y + bh + pad)
            ])
            logger.info(f"\U0001f4e6 Border detected at y={y}-{y+bh}, "
                        f"size={bw}x{bh}, fill={fill_ratio:.2f}")

        return bordered

    def _has_grid_lines(self, image_cv, bbox):
        """
        Check if a region contains table-like grid lines (horizontal + vertical).
        Uses morphological operations to isolate line structures.
        Returns True if the region looks like a table.
        """
        try:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            h_img, w_img = image_cv.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w_img, x2), min(h_img, y2)

            crop = image_cv[y1:y2, x1:x2]
            if crop.size == 0:
                return False

            ch, cw = crop.shape[:2]
            if ch < 20 or cw < 20:
                return False

            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

            # Detect horizontal lines (long horizontal structures)
            h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(30, cw // 4), 1))
            h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)
            h_line_pixels = cv2.countNonZero(h_lines)

            # Detect vertical lines (long vertical structures)
            v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(15, ch // 6)))
            v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)
            v_line_pixels = cv2.countNonZero(v_lines)

            total_pixels = ch * cw or 1
            h_ratio = h_line_pixels / total_pixels
            v_ratio = v_line_pixels / total_pixels

            # Table = has both horizontal AND vertical lines (grid)
            # OR has strong horizontal lines (borderless tables with row separators)
            has_h = h_ratio > 0.005  # at least 0.5% of pixels are horizontal lines
            has_v = v_ratio > 0.003  # at least 0.3% are vertical lines

            # Count distinct horizontal lines (by projecting)
            h_projection = np.sum(h_lines > 0, axis=1)  # per row
            h_line_rows = np.sum(h_projection > cw * 0.15)  # rows with significant horizontal line

            is_table = (has_h and has_v) or (h_line_rows >= 3)

            logger.debug(
                f"GridCheck bbox={bbox}: h_ratio={h_ratio:.4f}, v_ratio={v_ratio:.4f}, "
                f"h_lines={h_line_rows}, is_table={is_table}"
            )
            return is_table

        except Exception as e:
            logger.warning(f"Grid line detection error: {e}")
            return False

    def _is_visual_content(self, image_cv, bbox):
        """
        Check if a region contains visual content (images, diagrams, photos)
        vs just text on white background.
        Uses edge density and color variance analysis.
        Returns True if the region looks like an image/diagram.
        """
        try:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            h_img, w_img = image_cv.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w_img, x2), min(h_img, y2)

            crop = image_cv[y1:y2, x1:x2]
            if crop.size == 0:
                return False

            ch, cw = crop.shape[:2]
            if ch < 20 or cw < 20:
                return False

            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

            # 1. Edge density: images/diagrams have many edges scattered around
            edges = cv2.Canny(gray, 50, 150)
            edge_ratio = cv2.countNonZero(edges) / (ch * cw)

            # 2. Color variance: photos/diagrams have high color variance,
            #    plain text on white has low variance
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            s_channel = hsv[:, :, 1]  # Saturation
            color_var = float(np.std(s_channel))

            # 3. White ratio: text pages are mostly white (>60%)
            white_pixels = np.sum(gray > 220)
            white_ratio = white_pixels / (ch * cw)

            # Visual content: high edges + either colorful or not mostly white
            is_visual = (
                (edge_ratio > 0.08 and white_ratio < 0.65)  # Dense edges, not plain text
                or (color_var > 30)                           # Colorful content
                or (edge_ratio > 0.12)                        # Very high edge density (diagrams)
            )

            logger.debug(
                f"VisualCheck bbox={bbox}: edge_ratio={edge_ratio:.3f}, "
                f"color_var={color_var:.1f}, white_ratio={white_ratio:.2f}, "
                f"is_visual={is_visual}"
            )
            return is_visual

        except Exception as e:
            logger.warning(f"Visual content detection error: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════
    # STAGE 1: Layout Detection (Surya + bordered-box detection)
    # ═══════════════════════════════════════════════════════════════

    # Mapping from Surya labels to our internal types
    SURYA_LABEL_MAP = {
        # → heading
        'section-header': 'heading',
        'title':          'heading',
        # → paragraph
        'text':           'paragraph',
        'text-inline-math': 'paragraph',
        'list-item':      'paragraph',
        'caption':        'paragraph',
        'footnote':       'paragraph',
        'handwriting':    'paragraph',
        'form':           'paragraph',
        # → table
        'table':          'table',
        'table-of-contents': 'table',
        # → figure
        'figure':         'figure',
        'picture':        'figure',
        'formula':        'figure',
        # → skip (not useful for manual book content)
        'page-header':    '_skip',
        'page-footer':    '_skip',
    }

    def _detect_layout(self, image_cv):
        """
        Detect page regions using Surya Layout Predictor.
        Surya provides richer labels and more accurate classification than PPStructure.

        Falls back to bordered-box detection + full-page if Surya not available.

        Returns list of {"type": str, "bbox": [x1,y1,x2,y2], "position": int}
        Types: heading, paragraph, table, figure
        """
        h, w = image_cv.shape[:2]

        if not SURYA_AVAILABLE or self.layout_engine is None:
            logger.warning("⚠️ Surya not available — returning full-page as single region")
            return [{"type": "paragraph", "bbox": [0, 0, w, h], "position": 0}]

        try:
            # Convert cv2 (BGR numpy) → PIL Image (RGB) for Surya
            rgb = cv2.cvtColor(image_cv, cv2.COLOR_BGR2RGB)
            pil_img = PILImage.fromarray(rgb)

            # Run Surya layout prediction
            predictions = self.layout_engine([pil_img])

            if not predictions or len(predictions) == 0:
                logger.warning("⚠️ Surya returned no predictions")
                return []

            page_pred = predictions[0]  # First (only) image
            bboxes = page_pred.bboxes if hasattr(page_pred, 'bboxes') else []

            if not bboxes:
                logger.warning("⚠️ Surya found no layout elements")
                return []

            regions = []
            label_counts = {}  # For logging

            for item in bboxes:
                # Surya bbox: item.bbox = [x1, y1, x2, y2]
                bbox = item.bbox if hasattr(item, 'bbox') else None
                label = (item.label if hasattr(item, 'label') else 'text').lower()
                position = item.position if hasattr(item, 'position') else 0

                if bbox is None:
                    continue

                x1, y1, x2, y2 = [int(v) for v in bbox]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)

                if x2 <= x1 or y2 <= y1:
                    continue

                # Skip tiny regions (noise)
                area = (x2 - x1) * (y2 - y1)
                if area < 200:
                    continue

                # Map Surya label to our internal type
                rtype = self.SURYA_LABEL_MAP.get(label, 'paragraph')

                # Skip page headers/footers (not relevant for manual book content)
                if rtype == '_skip':
                    continue

                # Track label counts for logging
                label_counts[label] = label_counts.get(label, 0) + 1

                # Validate: if Surya says 'figure', check if it's actually visual content
                # Many false positives: Surya labels caption text ("Figure 11") as 'figure'
                if rtype == 'figure':
                    region_w = x2 - x1
                    region_h = y2 - y1
                    # Too small to be a real figure (likely caption text)
                    if region_w < 80 or region_h < 80:
                        logger.debug(
                            f"Figure too small ({region_w}x{region_h}), reclassifying as paragraph: "
                            f"bbox=[{x1},{y1},{x2},{y2}]"
                        )
                        rtype = 'paragraph'
                    # Check if region has actual visual content (not just text on white)
                    elif not self._is_visual_content(image_cv, [x1, y1, x2, y2]):
                        logger.debug(
                            f"Figure region has no visual content, reclassifying as paragraph: "
                            f"bbox=[{x1},{y1},{x2},{y2}]"
                        )
                        rtype = 'paragraph'

                regions.append({
                    "type": rtype,
                    "bbox": [x1, y1, x2, y2],
                    "position": position,
                    "surya_label": label,  # Keep original for debugging
                })

            # Sort by Surya's reading order (position), fallback to top-to-bottom
            regions.sort(key=lambda r: (r.get('position', 0), r['bbox'][1]))

            # ── PRE-PASS: Detect bordered boxes with OpenCV ──────────
            bordered_boxes = self._detect_bordered_boxes(image_cv)

            # ── OVERRIDE: Bordered boxes → table if has grid lines ──
            if bordered_boxes:
                final_regions = []
                covered_indices = set()

                for bx1, by1, bx2, by2 in bordered_boxes:
                    inside = []
                    for idx, region in enumerate(regions):
                        rx1, ry1, rx2, ry2 = region['bbox']
                        ox1 = max(bx1, rx1)
                        oy1 = max(by1, ry1)
                        ox2 = min(bx2, rx2)
                        oy2 = min(by2, ry2)
                        if ox2 > ox1 and oy2 > oy1:
                            overlap_area = (ox2 - ox1) * (oy2 - oy1)
                            region_area  = (rx2 - rx1) * (ry2 - ry1) or 1
                            if overlap_area / region_area > 0.40:
                                inside.append(idx)

                    if inside:
                        is_real_table = self._has_grid_lines(
                            image_cv, [bx1, by1, bx2, by2]
                        )
                        if is_real_table:
                            for idx in inside:
                                covered_indices.add(idx)
                            final_regions.append({
                                "type": "table", "bbox": [bx1, by1, bx2, by2],
                                "position": 0, "surya_label": "bordered-table"
                            })
                            logger.info(
                                f"📦 BorderBox → TABLE at y={by1}-{by2} "
                                f"(grid lines confirmed)"
                            )

                for idx, region in enumerate(regions):
                    if idx not in covered_indices:
                        final_regions.append(region)

                final_regions.sort(key=lambda r: (r.get('position', 0), r['bbox'][1]))
                regions = final_regions

            # Log summary
            surya_labels_str = ', '.join(f"{k}={v}" for k, v in sorted(label_counts.items()))
            logger.info(
                f"📐 Surya Layout: {len(regions)} regions "
                f"({sum(1 for r in regions if r['type'] == 'heading')} headings, "
                f"{sum(1 for r in regions if r['type'] == 'table')} tables, "
                f"{sum(1 for r in regions if r['type'] == 'figure')} figures) "
                f"[Surya labels: {surya_labels_str}]"
            )
            return regions

        except Exception as e:
            logger.error(f"Layout detection failed: {e}")
            return []


    # ═══════════════════════════════════════════════════════════════
    # PREPROCESSING: Watermark Removal + Denoising (for OCR)
    # ═══════════════════════════════════════════════════════════════
    def _preprocess_for_ocr(self, crop, region_type: str = 'paragraph'):
        """
        Clean an image crop before OCR:
        1. Remove red/pink watermarks (common in medical device manuals)
        2. CLAHE contrast enhancement (adaptive — better than flat sharpen)
        3. Gentle unsharp mask for edge crispness WITHOUT destroying thin strokes
        4. Deskew: straighten slightly-rotated text (common in scanned docs)
        """
        if crop is None or crop.size == 0:
            return crop

        try:
            h, w = crop.shape[:2]

            # 1. Remove red/pink watermarks using HSV color masking
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            mask1 = cv2.inRange(hsv, np.array([0,  30,  30]), np.array([10,  255, 255]))
            mask2 = cv2.inRange(hsv, np.array([160, 30, 30]), np.array([180, 255, 255]))
            mask3 = cv2.inRange(hsv, np.array([10,  50, 50]), np.array([25,  255, 255]))
            watermark_mask = mask1 + mask2 + mask3
            kernel = np.ones((3, 3), np.uint8)
            watermark_mask = cv2.dilate(watermark_mask, kernel, iterations=2)
            clean = crop.copy()
            clean[watermark_mask > 0] = (255, 255, 255)

            # 2. Denoise (bilateral: preserves edges, removes noise)
            clean = cv2.bilateralFilter(clean, 7, 50, 50)

            # 3. CLAHE contrast enhancement (adaptive histogram eq. per tile)
            #    Works much better than flat sharpen for low-contrast / faded text
            lab = cv2.cvtColor(clean, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            l = clahe.apply(l)
            lab = cv2.merge([l, a, b])
            clean = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

            # 4. Gentle unsharp mask (SAFER than hard sharpen kernel)
            #    gaussian_blur subtracted from original = sharpened edges only
            blur = cv2.GaussianBlur(clean, (0, 0), sigmaX=1.5)
            clean = cv2.addWeighted(clean, 1.5, blur, -0.5, 0)

            # 5. Deskew — straighten slight text rotation (scanned docs)
            #    Only applied if crop is wide enough to measure skew reliably
            if w > 80 and h > 20:
                try:
                    gray_d = cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY)
                    _, binary_d = cv2.threshold(
                        gray_d, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
                    )
                    coords = np.column_stack(np.where(binary_d > 0))
                    if len(coords) > 50:
                        angle = cv2.minAreaRect(coords)[-1]
                        # minAreaRect returns angle in [-90, 0]
                        if angle < -45:
                            angle = 90 + angle
                        # Only correct small angles (< 5°) to avoid false deskew
                        if abs(angle) < 5.0 and abs(angle) > 0.3:
                            M = cv2.getRotationMatrix2D(
                                (w // 2, h // 2), angle, 1.0
                            )
                            clean = cv2.warpAffine(
                                clean, M, (w, h),
                                flags=cv2.INTER_CUBIC,
                                borderMode=cv2.BORDER_REPLICATE
                            )
                except Exception:
                    pass  # Deskew is best-effort

            return clean
        except Exception as e:
            logger.warning(f"Preprocessing failed, using original: {e}")
            return crop

    # ═══════════════════════════════════════════════════════════════
    # STAGE 2: Text Extraction
    #   Indonesian → Tesseract OCR (lang pack 'ind')
    #   English    → PaddleOCR (lang 'en')
    # ═══════════════════════════════════════════════════════════════
    def _extract_text(self, image_cv, bbox, lang='en'):
        """
        Extract text from a specific region.
        OCR engine is selected STRICTLY based on language (NO fallback):
          'en' → PaddleOCR (English model)
          'id' → Tesseract OCR (Indonesian lang pack 'ind')

        Region is padded slightly on all sides before OCR to catch
        characters at the very edge of the detected bbox.
        """
        x1, y1, x2, y2 = bbox
        h_img, w_img = image_cv.shape[:2]

        # ── Pad bbox slightly to avoid clipping edge characters ──────
        pad_x = max(4, int((x2 - x1) * 0.02))   # 2% of region width
        pad_y = max(4, int((y2 - y1) * 0.05))   # 5% of region height
        x1p = max(0, x1 - pad_x)
        y1p = max(0, y1 - pad_y)
        x2p = min(w_img, x2 + pad_x)
        y2p = min(h_img, y2 + pad_y)

        crop = image_cv[y1p:y2p, x1p:x2p]

        if crop.size == 0:
            return "", 0.0

        # Preprocess: clean watermark + CLAHE + deskew
        clean_crop = self._preprocess_for_ocr(crop)

        # Determine best Tesseract PSM based on region shape
        region_h = y2p - y1p
        region_w = x2p - x1p
        aspect = region_w / max(region_h, 1)
        if region_h < 40:               # Single line (very short region)
            psm = 7
        elif aspect > 5 and region_h < 80:
            psm = 7                     # Single short wide line
        elif aspect > 3:
            psm = 6                     # Uniform text block (wide paragraph)
        else:
            psm = 4                     # Multi-column / mixed layout

        # ════════════════════════════════════════════════════
        # ENGLISH → PaddleOCR (STRICT)
        # ════════════════════════════════════════════════════
        if lang == 'en':
            try:
                ocr_result = self.ocr_engine.ocr(clean_crop, cls=False)
                if ocr_result and ocr_result[0]:
                    lines, confidences = [], []
                    for line in ocr_result[0]:
                        text = clean_text(line[1][0])  # Enforce Latin-only
                        conf = line[1][1]
                        if conf > 0.35 and text:   # balanced threshold
                            lines.append(text)
                            confidences.append(conf)
                    if lines:
                        avg_conf = sum(confidences) / len(confidences)
                        return " ".join(lines), avg_conf
            except Exception as e:
                logger.warning(f"PaddleOCR (en) failed: {e}")

            return "", 0.0

        # ════════════════════════════════════════════════════
        # INDONESIAN → Tesseract OCR (STRICT, lang pack 'ind')
        # ════════════════════════════════════════════════════
        if TESSERACT_AVAILABLE:
            try:
                rgb = cv2.cvtColor(clean_crop, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb)

                config = f'--oem 3 --psm {psm}'
                data = pytesseract.image_to_data(
                    pil_img, lang='ind', config=config,
                    output_type=pytesseract.Output.DICT
                )

                words = []
                confidences = []
                for i, txt in enumerate(data['text']):
                    txt = txt.strip()
                    conf = int(data['conf'][i])
                    # Threshold: 25 (balanced)
                    if txt and conf > 25:
                        words.append(txt)
                        confidences.append(conf / 100.0)

                if words:
                    avg_conf = sum(confidences) / len(confidences)
                    return ' '.join(words), avg_conf

                # Tesseract found nothing with PSM N → retry with PSM 11
                # (sparse text — finds individual words anywhere)
                if psm != 11:
                    data2 = pytesseract.image_to_data(
                        pil_img, lang='ind',
                        config='--oem 3 --psm 11',
                        output_type=pytesseract.Output.DICT
                    )
                    words2, confs2 = [], []
                    for i, txt in enumerate(data2['text']):
                        txt = txt.strip()
                        conf = int(data2['conf'][i])
                        if txt and conf > 25:
                            words2.append(txt)
                            confs2.append(conf / 100.0)
                    if words2:
                        avg_conf = sum(confs2) / len(confs2)
                        logger.debug(f"PSM 11 rescue (ind): found {len(words2)} words")
                        return ' '.join(words2), avg_conf

            except Exception as e:
                logger.warning(f"Tesseract (ind) failed: {e}")
        else:
            logger.warning("⚠️ Tesseract not available for Indonesian")

        return "", 0.0

    # ═══════════════════════════════════════════════════════════════
    # STAGE 3: AI Chapter Classification (TEXT-ONLY — no image!)
    # ═══════════════════════════════════════════════════════════════
    def _classify_chapters_ai(self, elements, lang='id'):
        """
        Classify text elements into standardized chapters using AI.
        Uses language-appropriate chapter names.
        """
        if not AI_AVAILABLE:
            return None

        # Build compact element summary for AI
        items = []
        for i, elem in enumerate(elements):
            # Truncate long text to save tokens
            text_preview = elem['text'][:200].replace('\n', ' ').strip()
            if text_preview:
                items.append(f"{i}|{elem['type']}|{text_preview}")

        if not items:
            return None

        elements_text = "\n".join(items)

        # ── Language-adaptive prompt ──
        ch_prefix = "Chapter" if lang == 'en' else "BAB"
        lang_note = "This is an ENGLISH document." if lang == 'en' else "This is an INDONESIAN document."

        prompt = f"""Classify each text element from a medical device manual into a chapter.
{lang_note}

CHAPTERS (use "{ch_prefix} N" format):
{ch_prefix} 1 = Safety, Purpose, Introduction, Warnings
{ch_prefix} 2 = Installation, Setup, Assembly, Mounting
{ch_prefix} 3 = Operation, Usage, Controls, Display, Monitoring
{ch_prefix} 4 = Maintenance, Cleaning, Care, Battery
{ch_prefix} 5 = Troubleshooting, Errors, Problems, FAQ
{ch_prefix} 6 = Technical Specifications, Standards, Dimensions
{ch_prefix} 7 = Warranty, Service, Contact Info

ELEMENTS (format: index|type|text):
{elements_text}

Return ONLY a JSON array. For each element:
{{"i": index, "c": chapter_number(1-7), "l": "{lang}"}}

Output ONLY the JSON array, nothing else."""

        vision_model = os.getenv("AI_VISION_MODEL", "google/gemini-2.0-flash-001")
        old_model = openrouter.model
        openrouter.model = vision_model

        try:
            # TEXT-ONLY call — no image_base64!
            response = openrouter.call(prompt, timeout=30)
            if not response:
                return None

            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if not json_match:
                logger.warning("AI classification: no JSON array found in response")
                return None

            results = json.loads(json_match.group())
            logger.info(f"🧠 AI classified {len(results)} elements into chapters")
            return results

        except json.JSONDecodeError as e:
            logger.warning(f"AI classification JSON parse error: {e}")
            return None
        except Exception as e:
            logger.warning(f"AI classification failed: {e}")
            return None
        finally:
            openrouter.model = old_model

    # ═══════════════════════════════════════════════════════════════
    # MAIN ENTRY POINT: scan_document
    # ═══════════════════════════════════════════════════════════════
    def scan_document(self, image_path, filename_base, session_id=None, lang='id', direct_translate=False, fast_mode=True):
        """
        Main entry point for the hybrid pipeline.

        Pipeline:
          1. Surya        → detect layout regions
          2. PaddleOCR   → extract text from each text region
          3. AI (optional) → classify text into chapters
          4. Post-process → crop tables/figures from original image

        Returns:
          {"elements": [...], "clean_image_path": str}
        """
        logger.info(f"🔍 Scanning: {os.path.basename(image_path)}")

        # Setup output directory
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(backend_dir, "output_results")
        os.makedirs(output_dir, exist_ok=True)

        # Load image
        original_img = cv2.imread(image_path)
        if original_img is None:
            logger.error(f"Failed to load image: {image_path}")
            return {"elements": [], "clean_image_path": None}

        h, w = original_img.shape[:2]

        # ── Auto-upscale: jika resolusi gambar terlalu kecil, OCR akan sulit ──
        # Dokumen yang di-scan dengan resolusi rendah sering menghasilkan
        # teks blur yang tidak bisa dibaca oleh OCR manapun.
        # ── Auto-upscale: jika resolusi gambar terlalu kecil, OCR akan sulit ──
        # Diturunkan ambang batasnya menjadi 1200, atau dimatikan sebagian jika fast_mode
        ocr_img = original_img   # Gambar yang dipakai untuk OCR (bisa berbeda dari preview)
        ocr_scale = 1.0
        upscale_threshold = 1000 if fast_mode else 1200
        
        if w < upscale_threshold:
            scale_factor = min(2.0, upscale_threshold / w)   # max 2x upscale
            new_w = int(w * scale_factor)
            new_h = int(h * scale_factor)
            ocr_img = cv2.resize(
                original_img, (new_w, new_h),
                interpolation=cv2.INTER_CUBIC   # CUBIC = terbaik untuk teks
            )
            ocr_scale = scale_factor
            logger.info(f"🔍 Auto-upscale: {w}x{h} → {new_w}x{new_h} (scale={scale_factor:.1f}x)")
        else:
            logger.info(f"✓ Resolusi OK: {w}x{h} — tidak perlu upscale")

        # Save preview (original image for frontend display)
        preview_fname = f"PREVIEW_{filename_base}.jpg"
        preview_path = os.path.join(output_dir, preview_fname)
        cv2.imwrite(preview_path, original_img, [cv2.IMWRITE_JPEG_QUALITY, 90])

        # ── STAGE 1: Layout Detection ─────────────────────────────
        logger.info("📐 Stage 1: Layout detection (Surya)...")
        regions = self._detect_layout(ocr_img)   # Gunakan ocr_img (sudah upscale jika perlu)

        # Scale-down bbox jika gambar di-upscale agar bbox sesuai original_img
        if ocr_scale != 1.0:
            for r in regions:
                r['bbox'] = [int(v / ocr_scale) for v in r['bbox']]

        # Fallback: if Surya finds nothing, OCR the full page
        if not regions:
            logger.warning("⚠️ No layout regions detected — OCR-ing full page")
            regions = [{"type": "paragraph", "bbox": [0, 0, w, h]}]

        # NOTE: Visual-box heuristic is applied inside _detect_layout()


        # ── STAGE 2: Text Extraction ──
        elements = []
        if direct_translate:
            logger.info("🧠 DIRECT TRANSLATE MODE: Extracting text from image regions with AI...")
            import base64
            
            vision_model = os.getenv("AI_VISION_MODEL", "google/gemini-2.0-flash-001")
            old_model = openrouter.model
            old_prov = getattr(openrouter, 'provider', '')
            
            try:
                openrouter.model = vision_model
                openrouter.provider = ""  # Clear provider restraint to auto-route for image models
                
                for region in regions:
                    rtype = region['type']
                    bbox = region['bbox']
                    if rtype in ('table', 'figure'):
                        elements.append({
                            "type": rtype,
                            "text": f"[{rtype.upper()}]",
                            "bbox": bbox,
                            "confidence": 0.95
                        })
                        continue
                    
                    # Direct Translate Region
                    x1, y1, x2, y2 = bbox
                    pad = 10
                    px1, py1 = max(0, x1 - pad), max(0, y1 - pad)
                    px2, py2 = min(w, x2 + pad), min(h, y2 + pad)
                    crop_visual = original_img[py1:py2, px1:px2]
                    
                    if crop_visual.size > 0:
                        _, buffer = cv2.imencode('.jpg', crop_visual)
                        b64_img = base64.b64encode(buffer).decode('utf-8')
                        # Build language-aware prompt
                        target_lang_name = "Bahasa Indonesia" if lang == 'id' else "English"
                        lang_rules = get_language_instruction(lang)
                        prompt = (
                            f"Extract and translate ALL text in this image region to {target_lang_name}. "
                            f"Keep formatting/newlines if possible. Output ONLY the translated text, "
                            f"do not add markdown or explanations.\n\n{lang_rules}"
                        )
                        try:
                            res = openrouter.call(prompt, image_base64=b64_img, timeout=45)
                            if res:
                                # Enforce target language: strip non-Latin scripts
                                clean_res = enforce_language(res, lang=lang)
                                if clean_res:
                                    elements.append({
                                        "type": rtype,
                                        "text": clean_res,
                                        "bbox": bbox,
                                        "confidence": 0.99
                                    })
                        except Exception as e:
                            logger.warning(f"Direct translate failed for region: {e}")
            finally:
                openrouter.model = old_model
                openrouter.provider = old_prov
        else:
            # Surya is used for layout detection (table/figure/text/heading regions).
            # We collect table/figure bboxes, and run PaddleOCR on the
            # full page to capture ALL text lines, then filter out those inside table/figure areas.
            logger.info(f"📝 Stage 2: Extracting tables/figures from Surya + full-page OCR for text...")
            
            # ── 2A: Collect table/figure regions from Surya ──
            visual_bboxes = []  # bboxes of table/figure regions (to exclude from text)
            for region in regions:
                rtype = region['type']
                bbox = region['bbox']

                if rtype in ('table', 'figure'):
                    elements.append({
                        "type": rtype,
                        "text": f"[{rtype.upper()}]",
                        "bbox": bbox,
                        "confidence": 0.95
                    })
                    visual_bboxes.append(bbox)
                    logger.info(f"📦 Surya {rtype}: bbox={bbox}")

            logger.info(f"📐 Found {len(visual_bboxes)} table/figure regions from Surya")

            # ── 2B: Full-page OCR for ALL text ──
            # This replaces both the old per-region OCR (Stage 2) and orphan recovery (Stage 2.5)
            text_line_count = 0
            try:
                full_page_result = self.ocr_engine.ocr(original_img, cls=False)

                if full_page_result and full_page_result[0]:
                    # Collect all text lines with their positions
                    raw_lines = []
                    for line in full_page_result[0]:
                        points = line[0]
                        text   = clean_text(line[1][0].strip())  # Enforce Latin-only
                        conf   = line[1][1]

                        if not text or conf < 0.30 or len(text) < 2:
                            continue

                        # Convert polygon to axis-aligned bbox
                        xs = [p[0] for p in points]
                        ys = [p[1] for p in points]
                        lx1, ly1 = int(min(xs)), int(min(ys))
                        lx2, ly2 = int(max(xs)), int(max(ys))

                        # Skip tiny fragments
                        if (lx2 - lx1) < 10 or (ly2 - ly1) < 5:
                            continue

                        # Check if this text line is INSIDE a table/figure region
                        is_inside_visual = False
                        for vx1, vy1, vx2, vy2 in visual_bboxes:
                            # Compute overlap
                            ox1 = max(lx1, vx1)
                            oy1 = max(ly1, vy1)
                            ox2 = min(lx2, vx2)
                            oy2 = min(ly2, vy2)
                            if ox2 > ox1 and oy2 > oy1:
                                overlap_area = (ox2 - ox1) * (oy2 - oy1)
                                line_area = (lx2 - lx1) * (ly2 - ly1) or 1
                                if overlap_area / line_area > 0.40:
                                    is_inside_visual = True
                                    break

                        if not is_inside_visual:
                            raw_lines.append({
                                "text": text,
                                "bbox": [lx1, ly1, lx2, ly2],
                                "confidence": round(conf, 2),
                            })

                    # ── Merge adjacent text lines into paragraphs ──
                    # PaddleOCR returns line-by-line; merge vertically close lines
                    # using line-height-relative threshold (adaptive to font size/DPI)
                    if raw_lines:
                        raw_lines.sort(key=lambda e: e['bbox'][1])  # sort top-to-bottom

                        # Calculate average line height for adaptive merge threshold
                        line_heights = [e['bbox'][3] - e['bbox'][1] for e in raw_lines]
                        avg_lh = sum(line_heights) / max(len(line_heights), 1)
                        # Merge threshold: 1.8x avg line height (covers normal line spacing)
                        merge_gap = max(25, int(avg_lh * 1.8))

                        merged = [dict(raw_lines[0])]

                        for line in raw_lines[1:]:
                            prev = merged[-1]
                            pb = prev['bbox']
                            lb = line['bbox']

                            vertical_gap = lb[1] - pb[3]  # top of new - bottom of prev
                            x_overlap = min(pb[2], lb[2]) - max(pb[0], lb[0])
                            min_width = min(pb[2] - pb[0], lb[2] - lb[0]) or 1

                            # Merge if vertically close AND horizontally overlapping (>20%)
                            if 0 <= vertical_gap < merge_gap and x_overlap / min_width > 0.20:
                                prev['text'] = prev['text'] + ' ' + line['text']
                                prev['bbox'] = [
                                    min(pb[0], lb[0]),
                                    min(pb[1], lb[1]),
                                    max(pb[2], lb[2]),
                                    max(pb[3], lb[3])
                                ]
                                prev['confidence'] = round(
                                    (prev['confidence'] + line['confidence']) / 2, 2
                                )
                            else:
                                merged.append(dict(line))

                        # ── Determine type (heading vs paragraph) ──
                        # Use font size heuristic: tall text relative to page = heading
                        avg_line_height = sum(
                            m['bbox'][3] - m['bbox'][1] for m in merged
                        ) / max(len(merged), 1)

                        for m in merged:
                            line_h = m['bbox'][3] - m['bbox'][1]
                            text_len = len(m['text'])

                            # Heading heuristic: short text + tall font OR all caps
                            is_heading = (
                                (line_h > avg_line_height * 1.3 and text_len < 80)
                                or (m['text'].isupper() and text_len < 60)
                                or (text_len < 50 and line_h > 30)
                            )

                            elements.append({
                                "type": "heading" if is_heading else "paragraph",
                                "text": m['text'],
                                "bbox": m['bbox'],
                                "confidence": m['confidence'],
                            })
                            text_line_count += 1

                        logger.info(
                            f"📝 Full-page OCR: {len(raw_lines)} lines → "
                            f"{len(merged)} paragraphs ({text_line_count} text elements)"
                        )

            except Exception as e:
                logger.error(f"Full-page OCR failed: {e}")

            # ── Auto-filter Headers and Footers ──
            # Ignore elements whose center is in the top 6% or bottom 6% of the image (typical header/footer zones)
            filtered_elements = []
            header_margin = h * 0.06
            footer_margin = h * 0.94
            for e in elements:
                y_center = (e['bbox'][1] + e['bbox'][3]) / 2
                if header_margin < y_center < footer_margin:
                    filtered_elements.append(e)
            
            elements = filtered_elements

            # Sort all elements by vertical position (reading order)
            elements.sort(key=lambda e: e['bbox'][1])




            # ── STAGE 2.55: Tesseract Full-Page Pass (Indonesia only) ────────────
            # Khusus dokumen ID: jalankan Tesseract pada seluruh halaman untuk menangkap
            # teks yang PaddleOCR miss. Ini sangat efektif tapi lambat.
            # Pada mode fast_mode, kita skip langkah tesseract ini untuk menghemat waktu besar.
            if lang == 'id' and TESSERACT_AVAILABLE and not fast_mode:
                try:
                    logger.info("🔎 Stage 2.55: Tesseract full-page Indonesian pass (PSM 3)...")
                    from PIL import Image as PILImage

                    # Gunakan ocr_img (sudah upscale) untuk Tesseract juga
                    rgb_full = cv2.cvtColor(ocr_img, cv2.COLOR_BGR2RGB)
                    pil_full = PILImage.fromarray(rgb_full)

                    data_full = pytesseract.image_to_data(
                        pil_full, lang='ind',
                        config='--oem 3 --psm 3',
                        output_type=pytesseract.Output.DICT
                    )

                    # Collect bboxes dari elemen yang sudah ada (untuk overlap check)
                    existing_bboxes_t = [
                        e['bbox'] for e in elements
                        if e.get('type') not in ('table', 'figure')
                    ]

                    tess_orphan_count = 0
                    # Kelompokkan per block_num — setiap block = satu area teks Tesseract
                    from itertools import groupby
                    indices = range(len(data_full['text']))
                    block_map = {}
                    for i in indices:
                        txt  = data_full['text'][i].strip()
                        conf = int(data_full['conf'][i])
                        bn   = data_full['block_num'][i]
                        if not txt or conf < 25:
                            continue
                        lx1 = data_full['left'][i]
                        ly1 = data_full['top'][i]
                        lx2 = lx1 + data_full['width'][i]
                        ly2 = ly1 + data_full['height'][i]

                        # Scale bbox kembali ke koordinat original_img
                        if ocr_scale != 1.0:
                            lx1 = int(lx1 / ocr_scale)
                            ly1 = int(ly1 / ocr_scale)
                            lx2 = int(lx2 / ocr_scale)
                            ly2 = int(ly2 / ocr_scale)

                        if bn not in block_map:
                            block_map[bn] = {'texts': [], 'confs': [], 'x1': lx1, 'y1': ly1, 'x2': lx2, 'y2': ly2}
                        block_map[bn]['texts'].append(txt)
                        block_map[bn]['confs'].append(conf)
                        block_map[bn]['x1'] = min(block_map[bn]['x1'], lx1)
                        block_map[bn]['y1'] = min(block_map[bn]['y1'], ly1)
                        block_map[bn]['x2'] = max(block_map[bn]['x2'], lx2)
                        block_map[bn]['y2'] = max(block_map[bn]['y2'], ly2)

                    for bn, blk in block_map.items():
                        text_out = ' '.join(blk['texts'])
                        if len(text_out.strip()) < 3:
                            continue
                        avg_conf = sum(blk['confs']) / len(blk['confs']) / 100.0
                        bx1, by1, bx2, by2 = blk['x1'], blk['y1'], blk['x2'], blk['y2']

                        # Cek overlap dengan elemen yang sudah ada
                        is_covered = False
                        for ex1, ey1, ex2, ey2 in existing_bboxes_t:
                            ox1 = max(bx1, ex1)
                            oy1 = max(by1, ey1)
                            ox2 = min(bx2, ex2)
                            oy2 = min(by2, ey2)
                            if ox2 > ox1 and oy2 > oy1:
                                overlap_area = (ox2 - ox1) * (oy2 - oy1)
                                blk_area = (bx2 - bx1) * (by2 - by1) or 1
                                if overlap_area / blk_area > 0.40:
                                    is_covered = True
                                    break

                        if not is_covered:
                            elements.append({
                                'type': 'paragraph',
                                'text': text_out,
                                'bbox': [bx1, by1, bx2, by2],
                                'confidence': round(avg_conf, 2),
                                '_tess_recovery': True
                            })
                            existing_bboxes_t.append([bx1, by1, bx2, by2])
                            tess_orphan_count += 1

                    if tess_orphan_count > 0:
                        logger.info(f"🌟 Tesseract recovery: +{tess_orphan_count} blok teks baru")
                        # Re-sort setelah penambahan
                        elements.sort(key=lambda e: e['bbox'][1])
                    else:
                        logger.info("✓ Tesseract full-page: tidak ada teks tambahan")

                except Exception as e:
                    logger.warning(f"⚠️ Stage 2.55 Tesseract recovery gagal (non-fatal): {e}")

            # ── STAGE 2.6: Text Correction (SymSpell + Context + Entity) ──
            if TEXT_CORRECTOR_AVAILABLE:
                try:
                    logger.info(f"✏️ Stage 2.6: OCR text correction (lang={lang})...")
                    corrected_count = 0
                    for elem in elements:
                        # Only correct text elements (skip tables/figures)
                        if elem.get('type') not in ('table', 'figure') and elem.get('text'):
                            original_text = elem['text']
                            elem['text'] = correct_ocr_text(elem['text'], lang=lang)
                            if elem['text'] != original_text:
                                corrected_count += 1
                    logger.info(f"✅ Text correction: {corrected_count}/{len(elements)} element(s) diperbaiki")
                except Exception as e:
                    logger.warning(f"⚠️ Stage 2.6 text correction failed (non-fatal): {e}")
            else:
                logger.info("ℹ️ Text corrector tidak tersedia — melewati Stage 2.6")

        # ── STAGE 3: AI Chapter Classification ────────────────────
        ai_enabled = os.getenv("AI_VISION_OCR_ENABLED", "false").lower() in (
            "true", "1", "yes", "on"
        )

        if not direct_translate and ai_enabled and elements:
            logger.info(f"🧠 Stage 3: AI chapter classification (text-only, lang={lang})...")
            classifications = self._classify_chapters_ai(elements, lang=lang)

            if classifications:
                # Build lookup map
                cls_map = {}
                for c in classifications:
                    if isinstance(c, dict) and 'i' in c:
                        cls_map[c['i']] = c

                # Apply classifications
                classified_count = 0
                for idx, elem in enumerate(elements):
                    if idx in cls_map:
                        ch_num = cls_map[idx].get('c', 1)
                        # IMPORTANT: use the function's lang parameter, NOT AI's response
                        # (AI might return wrong lang; user already selected it)

                        # Validate chapter number
                        if not isinstance(ch_num, int) or ch_num < 1 or ch_num > 7:
                            ch_num = 1

                        ch_prefix = "Chapter" if lang == 'en' else "BAB"
                        elem['chapter'] = f"{ch_prefix} {ch_num}"
                        elem['lang'] = lang  # Always use user-selected language
                        classified_count += 1

                logger.info(f"✓ Classified {classified_count}/{len(elements)} elements")
            else:
                logger.info("⚠️ AI classification unavailable — BioBrain keyword fallback will be used")
        else:
            if not ai_enabled:
                logger.info("ℹ️ AI classification disabled (AI_VISION_OCR_ENABLED=false)")

        # ── STAGE 4: Crop Visual Elements ─────────────────────────
        final_elements = []
        for idx, elem in enumerate(elements):
            crop_url = None
            crop_local = None

            if elem['type'] in ('table', 'figure'):
                x1, y1, x2, y2 = elem['bbox']
                pad = 20
                px1, py1 = max(0, x1 - pad), max(0, y1 - pad)
                px2, py2 = min(w, x2 + pad), min(h, y2 + pad)
                crop_visual = original_img[py1:py2, px1:px2]

                if crop_visual.size > 0:
                    crop_fname = f"{filename_base}_crop_{elem['type']}_{idx}.png"
                    crop_path = os.path.join(output_dir, crop_fname)
                    cv2.imwrite(crop_path, crop_visual)

                    from urllib.parse import quote
                    crop_url = f"http://127.0.0.1:8000/output/{quote(crop_fname)}"
                    crop_local = crop_path
                    logger.info(f"📸 Cropped {elem['type']}: {crop_fname}")

            final_elements.append({
                "type": elem['type'],
                "text": elem['text'],
                "confidence": elem.get('confidence', 0.95),
                "bbox": elem['bbox'],
                "chapter": elem.get('chapter'),
                "lang": elem.get('lang'),
                "crop_url": crop_url,
                "crop_local": crop_local,
                "source_image_local": preview_path
            })

        logger.info(f"✅ Hybrid scan complete: {len(final_elements)} elements")
        return {
            "elements": final_elements,
            "clean_image_path": preview_path
        }

    # ═══════════════════════════════════════════════════════════════
    # UTILITY: Generate missing chapter content
    # ═══════════════════════════════════════════════════════════════
    def generate_chapter_content(self, topic, context=""):
        """Generate content for a missing chapter using AI."""
        if not AI_AVAILABLE:
            return (
                f"[AI GENERATION FAILED] No AI API key. "
                f"Add OPENROUTER_API_KEY to .env to generate {topic}."
            )

        prompt = f"""You are a professional technical writer for medical device manuals.
Write a comprehensive '{topic}' section for this product.

PRODUCT CONTEXT:
{context}

Requirements:
1. Professional technical language
2. Include detailed steps, warnings, best practices
3. Format with clear headings and bullet points
4. Do NOT mention AI-generated. Write as if from the original manual."""

        logger.info(f"🤖 Generating missing chapter: {topic}")

        if openrouter.is_available:
            result = openrouter.call(prompt, timeout=60)
            if result:
                return result

        return f"[GENERATION FAILED] Cannot generate {topic}. Check OPENROUTER_API_KEY."


# Factory Function
def create_vision_engine(**kwargs):
    return BioVisionHybrid()
