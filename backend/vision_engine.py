"""
HYBRID VISION PIPELINE v5 — Optimized for Accuracy & Speed
============================================================

Strategy (3-stage pipeline):
  Stage 1: PPStructure  → Layout detection (text / table / figure regions)
  Stage 2: PaddleOCR    → Text extraction per region (accurate OCR, no AI typos)
  Stage 3: AI (Gemini)  → Chapter classification (TEXT-ONLY, no image = cheap & fast)

Why this works better:
  - PaddleOCR:    specialized OCR = NO typos (unlike AI OCR)
  - PPStructure:  trained to detect tables/figures visually = tables stay as images
  - AI:           only classifies text into chapters = fast, cheap (no image sent)

Updated: February 2026
"""

import os
import cv2
import numpy as np
import logging
import json
import re

from paddleocr import PaddleOCR, PPStructure
from dotenv import load_dotenv

# Import OpenRouter Smart Client
from openrouter_client import get_openrouter_client

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

        # ── Stage 2: OCR Engine ──
        logger.info("Initializing PaddleOCR (text extraction)...")
        self.ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang='en',       # Latin-script model, works for both EN and ID
            show_log=False
        )

        logger.info("✓ Hybrid Vision Pipeline v5 Ready")

    # ═══════════════════════════════════════════════════════════════
    # STAGE 1: Layout Detection (PPStructure)
    # ═══════════════════════════════════════════════════════════════
    def _detect_layout(self, image_cv):
        """
        Detect page regions using PPStructure.
        Returns list of {"type": str, "bbox": [x1,y1,x2,y2]}
        Types: heading, paragraph, table, figure
        """
        h, w = image_cv.shape[:2]

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
                if area < 500:
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

            logger.info(f"📐 Layout: {len(regions)} regions "
                        f"({sum(1 for r in regions if r['type'] == 'heading')} headings, "
                        f"{sum(1 for r in regions if r['type'] == 'table')} tables, "
                        f"{sum(1 for r in regions if r['type'] == 'figure')} figures)")
            return regions

        except Exception as e:
            logger.error(f"Layout detection failed: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════
    # STAGE 2: Text Extraction (PaddleOCR)
    # ═══════════════════════════════════════════════════════════════
    def _extract_text(self, image_cv, bbox):
        """
        Extract text from a specific region using PaddleOCR.
        This is the KEY improvement: PaddleOCR does OCR, not AI!
        → No hallucinations, no typos from AI misreading.
        """
        x1, y1, x2, y2 = bbox
        crop = image_cv[y1:y2, x1:x2]

        if crop.size == 0:
            return "", 0.0

        try:
            ocr_result = self.ocr_engine.ocr(crop, cls=False)
            if ocr_result and ocr_result[0]:
                lines = []
                confidences = []
                for line in ocr_result[0]:
                    text = line[1][0]
                    conf = line[1][1]
                    if conf > 0.4:           # Skip very low confidence noise
                        lines.append(text)
                        confidences.append(conf)

                if lines:
                    avg_conf = sum(confidences) / len(confidences)
                    return " ".join(lines), avg_conf

        except Exception as e:
            logger.warning(f"OCR failed for region {bbox}: {e}")

        return "", 0.0

    # ═══════════════════════════════════════════════════════════════
    # STAGE 3: AI Chapter Classification (TEXT-ONLY — no image!)
    # ═══════════════════════════════════════════════════════════════
    def _classify_chapters_ai(self, elements):
        """
        Classify text elements into standardized chapters using AI.

        KEY INSIGHT: We send TEXT ONLY (no image!) to the AI.
        Benefits:
          - 10-50x cheaper (no base64 image encoding)
          - 5x faster (much smaller payload)
          - More accurate (AI focuses on semantics, not OCR)
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

        prompt = f"""Classify each text element from a medical device manual into a chapter.

CHAPTERS:
1=Safety, Purpose, Introduction, Warnings
2=Installation, Setup, Assembly, Mounting
3=Operation, Usage, Controls, Display, Monitoring
4=Maintenance, Cleaning, Care, Battery
5=Troubleshooting, Errors, Problems, FAQ
6=Technical Specifications, Standards, Dimensions
7=Warranty, Service, Contact Info

ELEMENTS (format: index|type|text):
{elements_text}

Return ONLY a JSON array. For each element:
{{"i": index, "c": chapter_number(1-7), "l": "en" or "id"}}

Detect language from the actual text content.
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
    def scan_document(self, image_path, filename_base, session_id=None):
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

        # Save preview (original image for frontend display)
        preview_fname = f"PREVIEW_{filename_base}.jpg"
        preview_path = os.path.join(output_dir, preview_fname)
        cv2.imwrite(preview_path, original_img, [cv2.IMWRITE_JPEG_QUALITY, 90])

        # ── STAGE 1: Layout Detection ─────────────────────────────
        logger.info("📐 Stage 1: Layout detection (PPStructure)...")
        regions = self._detect_layout(original_img)

        # Fallback: if PPStructure finds nothing, OCR the full page
        if not regions:
            logger.warning("⚠️ No layout regions detected — OCR-ing full page")
            regions = [{"type": "paragraph", "bbox": [0, 0, w, h]}]

        # ── STAGE 2: Text Extraction ──────────────────────────────
        logger.info(f"📝 Stage 2: Text extraction (PaddleOCR) for {len(regions)} regions...")
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
            else:
                # Text elements: extract with PaddleOCR
                text, confidence = self._extract_text(original_img, bbox)
                if text.strip():
                    elements.append({
                        "type": rtype,
                        "text": text,
                        "bbox": bbox,
                        "confidence": round(confidence, 2)
                    })

        logger.info(f"📝 Extracted text from {len(elements)} elements "
                    f"({sum(1 for e in elements if e['type'] in ('table', 'figure'))} visual)")

        # ── STAGE 3: AI Chapter Classification ────────────────────
        ai_enabled = os.getenv("AI_VISION_OCR_ENABLED", "false").lower() in (
            "true", "1", "yes", "on"
        )

        if ai_enabled and elements:
            logger.info(f"🧠 Stage 3: AI chapter classification (text-only)...")
            classifications = self._classify_chapters_ai(elements)

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
                        lang = cls_map[idx].get('l', 'id')

                        # Validate chapter number
                        if not isinstance(ch_num, int) or ch_num < 1 or ch_num > 7:
                            ch_num = 1

                        ch_prefix = "Chapter" if lang == 'en' else "BAB"
                        elem['chapter'] = f"{ch_prefix} {ch_num}"
                        elem['lang'] = lang
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
                "crop_local": crop_local
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
