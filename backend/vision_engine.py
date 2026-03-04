"""
HYBRID VISION PIPELINE v6 — Tesseract + PPStructure + AI
============================================================

Strategy (3-stage pipeline):
  Stage 1: PPStructure    → Layout detection (text / table / figure regions)
  Stage 2: Tesseract OCR  → Text extraction per region (PRIMARY, with lang packs)
           PaddleOCR      → Fallback if Tesseract unavailable
  Stage 3: AI (Gemini)    → Chapter classification (TEXT-ONLY, no image = cheap & fast)

Why Tesseract:
  - Has dedicated Indonesian language pack (`ind`) = far fewer typos
  - Has dedicated English language pack (`eng`) = proven accuracy
  - Industry standard OCR used by Google, Adobe, Microsoft
  - Fast and reliable for printed text

Updated: February 2026
"""

import os
import cv2
import numpy as np
import logging
import json
import re
import base64

from paddleocr import PaddleOCR, PPStructure
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
        1. PPStructure  → layout detection
        2. PaddleOCR    → text extraction
        3. AI           → chapter classification (text-only)
        """
        # ── Stage 1: Layout Engine ──
        logger.info("Initializing PPStructure (layout detection)...")
        self.layout_engine = PPStructure(
            show_log=False,
            image_orientation=False,
            layout=True,
            table=True,
            ocr=False,       # We do OCR separately with PaddleOCR
            recovery=False
        )

        # ── Stage 2: OCR Engines ──
        # INDONESIAN: Tesseract OCR (lang pack 'ind')
        if TESSERACT_AVAILABLE:
            logger.info("✓ Tesseract OCR: Ready (Indonesian)")
        else:
            logger.info("⚠️ Tesseract unavailable — PaddleOCR will be used as fallback for Indonesian")

        # ENGLISH: PaddleOCR (lang 'en')
        logger.info("Initializing PaddleOCR: Ready (English)...")
        self.ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang='en',
            show_log=False
        )

        logger.info("✓ Hybrid Vision Pipeline v6 Ready")

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

    # ═══════════════════════════════════════════════════════════════
    # STAGE 1: Layout Detection (PPStructure + bordered-box detection)
    # ═══════════════════════════════════════════════════════════════
    def _detect_layout(self, image_cv):
        """
        Detect page regions using PPStructure.
        Before handing off to PPStructure, we first detect bordered rectangles
        (letterheads, company boxes) via OpenCV — those are marked as 'table'
        type so they get cropped as images, not OCR'd line by line.

        Returns list of {"type": str, "bbox": [x1,y1,x2,y2]}
        Types: heading, paragraph, table, figure
        """
        h, w = image_cv.shape[:2]

        # ── PRE-PASS: Detect bordered boxes with OpenCV ──────────
        bordered_boxes = self._detect_bordered_boxes(image_cv)
        # We'll use these to override PPStructure results later

        try:
            results = self.layout_engine(image_cv)
            if not results:
                return []

            # Sort top-to-bottom (reading order)
            results.sort(key=lambda x: x['bbox'][1])

            regions = []
            for r in results:
                r.pop('img', None)    # Free memory
                bbox = r['bbox']
                rtype = r['type'].lower()

                x1, y1, x2, y2 = [int(v) for v in bbox]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)

                if x2 <= x1 or y2 <= y1:
                    continue

                # Skip tiny regions (likely noise)
                area = (x2 - x1) * (y2 - y1)
                if area < 200:
                    continue

                # Normalize PPStructure types to our standard types
                if rtype in ('title', 'header'):
                    rtype = 'heading'
                elif rtype in ('text', 'reference', 'list'):
                    rtype = 'paragraph'
                elif rtype == 'table':
                    rtype = 'table'
                elif rtype in ('figure', 'equation'):
                    rtype = 'figure'
                else:
                    rtype = 'paragraph'

                regions.append({
                    "type": rtype,
                    "bbox": [x1, y1, x2, y2]
                })

            # ── OVERRIDE: Merge PPStructure sub-regions inside bordered boxes ──
            # If OpenCV detected a bordered rectangle (e.g. company letterhead),
            # any PPStructure regions that fall inside it are REMOVED and replaced
            # by the single bordered box as a 'table' type (will be cropped as image).
            if bordered_boxes:
                # For each bordered box, check which PPStructure regions it contains
                final_regions = []
                covered_indices = set()

                for bx1, by1, bx2, by2 in bordered_boxes:
                    # Find all PPStructure regions that overlap significantly
                    # with this border box
                    inside = []
                    for idx, region in enumerate(regions):
                        rx1, ry1, rx2, ry2 = region['bbox']
                        # Compute overlap
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
                        # Replace all sub-regions with one bordered box region
                        for idx in inside:
                            covered_indices.add(idx)
                        final_regions.append({"type": "table", "bbox": [bx1, by1, bx2, by2]})
                        logger.info(
                            f"📦 BorderBox override: merged {len(inside)} sub-regions "
                            f"at y={by1}-{by2} → single 'table' crop"
                        )

                # Add remaining PPStructure regions not inside any border
                for idx, region in enumerate(regions):
                    if idx not in covered_indices:
                        final_regions.append(region)

                # Sort by vertical position
                final_regions.sort(key=lambda r: r['bbox'][1])
                regions = final_regions

            # ── Aspect-ratio heuristic (secondary pass) ──────────────────
            # Catches wide/short text regions that still look like boxes
            # but don't have a visible border OpenCV could detect.
            for region in regions:
                if region['type'] in ('table', 'figure'):
                    continue
                rx1, ry1, rx2, ry2 = region['bbox']
                rw = rx2 - rx1
                rh = ry2 - ry1
                if rh == 0:
                    continue
                aspect    = rw / rh
                width_pct = rw / w
                top_pct   = ry1 / h

                if aspect >= 4.0 and width_pct >= 0.5 and top_pct <= 0.40:
                    region['type'] = 'table'
                    logger.info(f"📦 AspectHeuristic: promoted region y={ry1} "
                                f"to 'table' (aspect={aspect:.1f}, w={width_pct:.0%})")

            logger.info(f"📐 Layout: {len(regions)} regions "
                        f"({sum(1 for r in regions if r['type'] == 'heading')} headings, "
                        f"{sum(1 for r in regions if r['type'] == 'table')} tables, "
                        f"{sum(1 for r in regions if r['type'] == 'figure')} figures)")
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
        OCR engine is selected STRICTLY based on language:
          'id' → Tesseract OCR (Indonesian lang pack 'ind')
                 Fallback to PaddleOCR if Tesseract not installed
          'en' → PaddleOCR ONLY (English model)

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
        # INDONESIAN → Tesseract OCR (lang pack 'ind')
        # ════════════════════════════════════════════════════
        if lang == 'id':
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
                        # Threshold: 25 (balanced — was 30 original, then 20 too low)
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
                            logger.debug(f"PSM 11 rescue: found {len(words2)} words")
                            return ' '.join(words2), avg_conf

                    return "", 0.0

                except Exception as e:
                    logger.warning(f"Tesseract (ind) failed: {e}")
                    # Fall through to PaddleOCR

            else:
                logger.warning("⚠️ Tesseract not available — using PaddleOCR as fallback for Indonesian")

            # Fallback: PaddleOCR for Indonesian
            try:
                ocr_result = self.ocr_engine.ocr(clean_crop, cls=False)
                if ocr_result and ocr_result[0]:
                    lines, confidences = [], []
                    for line in ocr_result[0]:
                        text = line[1][0]
                        conf = line[1][1]
                        if conf > 0.35:   # balanced (was 0.4 original, 0.3 too low)
                            lines.append(text)
                            confidences.append(conf)
                    if lines:
                        avg_conf = sum(confidences) / len(confidences)
                        return " ".join(lines), avg_conf
            except Exception as e:
                logger.warning(f"PaddleOCR fallback (id) failed: {e}")

            return "", 0.0

        # ════════════════════════════════════════════════════
        # ENGLISH → PaddleOCR ONLY (lang model 'en')
        # ════════════════════════════════════════════════════
        else:  # lang == 'en'
            try:
                ocr_result = self.ocr_engine.ocr(clean_crop, cls=False)
                if ocr_result and ocr_result[0]:
                    lines = []
                    confidences = []
                    for line in ocr_result[0]:
                        text = line[1][0]
                        conf = line[1][1]
                        if conf > 0.35:   # balanced (was 0.4 original, 0.3 too low)
                            lines.append(text)
                            confidences.append(conf)

                    if lines:
                        avg_conf = sum(confidences) / len(confidences)
                        return " ".join(lines), avg_conf

            except Exception as e:
                logger.warning(f"PaddleOCR (en) failed: {e}")

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
    def scan_document(self, image_path, filename_base, session_id=None, lang='id'):
        """
        Main entry point for the hybrid pipeline.

        Pipeline:
          1. PPStructure → detect layout regions
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
        # Upscale 2x jika lebar < 1500px (threshold untuk teks 10pt terbaca baik)
        ocr_img = original_img   # Gambar yang dipakai untuk OCR (bisa berbeda dari preview)
        ocr_scale = 1.0
        if w < 1500:
            scale_factor = min(2.0, 1500 / w)   # max 2x upscale
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
        logger.info("\ud83d\udcd0 Stage 1: Layout detection (PPStructure)...")
        regions = self._detect_layout(ocr_img)   # Gunakan ocr_img (sudah upscale jika perlu)

        # Scale-down bbox jika gambar di-upscale agar bbox sesuai original_img
        if ocr_scale != 1.0:
            for r in regions:
                r['bbox'] = [int(v / ocr_scale) for v in r['bbox']]

        # Fallback: if PPStructure finds nothing, OCR the full page
        if not regions:
            logger.warning("⚠️ No layout regions detected — OCR-ing full page")
            regions = [{"type": "paragraph", "bbox": [0, 0, w, h]}]

        # NOTE: Visual-box heuristic is applied inside _detect_layout()


        # ── STAGE 2: Text Extraction ────────────────────────────────────
        ocr_engine_name = "Tesseract (ind)" if (lang == 'id' and TESSERACT_AVAILABLE) else "PaddleOCR (en)"
        logger.info(f"📝 Stage 2: Text extraction [{ocr_engine_name}] for {len(regions)} regions...")
        elements = []

        for region in regions:
            rtype = region['type']
            bbox = region['bbox']

            if rtype in ('table', 'figure'):
                # Visual elements: keep as-is, will be cropped in Stage 4
                elements.append({
                    "type": rtype,
                    "text": f"[{rtype.upper()}]",
                    "bbox": bbox,
                    "confidence": 0.95
                })
                # ALSO try OCR on table/figure regions — some are actually
                # highlighted text boxes (gray bg) that PPStructure misclassifies.
                # If readable text is found, add it as a separate paragraph.
                try:
                    text, confidence = self._extract_text(original_img, bbox, lang=lang)
                    if text.strip() and confidence > 0.55 and len(text.strip()) > 10:
                        elements.append({
                            "type": "paragraph",
                            "text": text,
                            "bbox": bbox,
                            "confidence": round(confidence, 2),
                            "_from_visual_region": True
                        })
                        logger.info(f"📖 Also extracted text from {rtype} region: "
                                    f"'{text[:50]}...' (conf={confidence:.2f})")
                except Exception:
                    pass  # Non-fatal: we still have the crop
            else:
                # Text elements: extract with PaddleOCR
                text, confidence = self._extract_text(original_img, bbox, lang=lang)
                if text.strip():
                    elements.append({
                        "type": rtype,
                        "text": text,
                        "bbox": bbox,
                        "confidence": round(confidence, 2)
                    })

        logger.info(f"📝 Extracted text from {len(elements)} elements "
                    f"({sum(1 for e in elements if e['type'] in ('table', 'figure'))} visual)")

        # ── STAGE 2.5: Orphan Text Recovery ──────────────────────────
        # Run full-page PaddleOCR and find text lines that PPStructure missed.
        # Any text not covered by an existing region is added as a new element.
        try:
            logger.info("🔎 Stage 2.5: Orphan text recovery (full-page OCR)...")
            full_page_result = self.ocr_engine.ocr(original_img, cls=False)

            orphan_count = 0
            if full_page_result and full_page_result[0]:
                # Collect bboxes of TEXT elements ONLY.
                # IMPORTANT: table/figure regions are NOT included because they were
                # only cropped as images — their text was never OCR'd.
                # If we included them, text near/inside table crops would be wrongly
                # considered "covered" and lost forever.
                existing_bboxes = [
                    e['bbox'] for e in elements
                    if e.get('type') not in ('table', 'figure')
                ]

                for line in full_page_result[0]:
                    # PaddleOCR returns [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], text, conf
                    points = line[0]
                    text   = line[1][0].strip()
                    conf   = line[1][1]

                    # Threshold: 0.30 — balanced (was 0.35 original, 0.25 too low)
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

                    # Check overlap with existing regions
                    is_covered = False
                    for ex1, ey1, ex2, ey2 in existing_bboxes:
                        # Compute intersection
                        ox1 = max(lx1, ex1)
                        oy1 = max(ly1, ey1)
                        ox2 = min(lx2, ex2)
                        oy2 = min(ly2, ey2)
                        if ox2 > ox1 and oy2 > oy1:
                            overlap_area = (ox2 - ox1) * (oy2 - oy1)
                            line_area    = (lx2 - lx1) * (ly2 - ly1) or 1
                            # If >40% of the orphan line is inside an existing region, skip
                            if overlap_area / line_area > 0.40:
                                is_covered = True
                                break

                    if not is_covered:
                        elements.append({
                            "type": "paragraph",
                            "text": text,
                            "bbox": [lx1, ly1, lx2, ly2],
                            "confidence": round(conf, 2),
                            "_orphan": True   # Tag for debugging
                        })
                        # Add this bbox to existing so subsequent orphans don't duplicate
                        existing_bboxes.append([lx1, ly1, lx2, ly2])
                        orphan_count += 1

            if orphan_count > 0:
                logger.info(f"🆕 Recovered {orphan_count} orphan text line(s) missed by PPStructure")

                # ── Merge nearby orphan lines into paragraphs ─────────
                # PaddleOCR returns line-by-line; merge adjacent orphans
                # vertically close to each other (same paragraph).
                orphans = [e for e in elements if e.get('_orphan')]
                non_orphans = [e for e in elements if not e.get('_orphan')]

                if len(orphans) > 1:
                    orphans.sort(key=lambda e: e['bbox'][1])  # sort top-to-bottom
                    merged = [orphans[0]]

                    for orph in orphans[1:]:
                        prev = merged[-1]
                        pb = prev['bbox']   # [x1,y1,x2,y2]
                        ob = orph['bbox']

                        vertical_gap = ob[1] - pb[3]  # top of new - bottom of prev
                        x_overlap = min(pb[2], ob[2]) - max(pb[0], ob[0])
                        min_width = min(pb[2] - pb[0], ob[2] - ob[0]) or 1

                        # Merge if: vertically close (<25px, was 15px) AND X overlaps >20%
                        # The relaxed threshold handles documents with inconsistent line spacing
                        if 0 <= vertical_gap < 25 and x_overlap / min_width > 0.20:
                            # Merge text and expand bbox
                            prev['text'] = prev['text'] + ' ' + orph['text']
                            prev['bbox'] = [
                                min(pb[0], ob[0]),
                                min(pb[1], ob[1]),
                                max(pb[2], ob[2]),
                                max(pb[3], ob[3])
                            ]
                            prev['confidence'] = round(
                                (prev['confidence'] + orph['confidence']) / 2, 2
                            )
                        else:
                            merged.append(orph)

                    elements = non_orphans + merged
                    logger.info(f"📦 Merged {orphan_count} orphan lines → {len(merged)} paragraph(s)")

                # Re-sort all elements top-to-bottom after adding orphans
                elements.sort(key=lambda e: e['bbox'][1])
            else:
                logger.info("✓ No orphan text found — PPStructure covered everything")

        except Exception as e:
            logger.warning(f"⚠️ Orphan text recovery failed (non-fatal): {e}")

        # ── STAGE 2.55: Tesseract Full-Page Pass (Indonesia only) ────────────
        # Khusus dokumen ID: jalankan Tesseract pada seluruh halaman dengan PSM 3
        # (auto page segmentation) untuk menangkap teks yang PaddleOCR miss.
        # Ini sangat efektif untuk: footnote, watermark teks, header/footer,
        # teks di area yang PPStructure classify salah sebagai figure.
        if lang == 'id' and TESSERACT_AVAILABLE:
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

        if ai_enabled and elements:
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
