"""
UNIFIED VISION PIPELINE v4 — Single AI Call per Page
Optimized for speed: 1 API call extracts ALL text + detects ALL tables/figures per page.
PPStructure + PaddleOCR kept as fallback when AI is unavailable.
Updated: February 2026
"""

import os
import cv2
import numpy as np
import logging
import base64
import json
import re

from paddleocr import PaddleOCR, PPStructure
from pathlib import Path
from dotenv import load_dotenv

# Import OpenRouter Smart Client
from openrouter_client import get_openrouter_client

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inisialisasi OpenRouter Client (satu-satunya AI provider)
openrouter = get_openrouter_client()
AI_AVAILABLE = openrouter.is_available

if AI_AVAILABLE:
    logger.info("✓ OpenRouter Client: Active")
else:
    logger.warning("⚠️ OpenRouter tidak tersedia — AI enhancement dinonaktifkan")


class BioVisionHybrid:
    def __init__(self):
        """
        Unified Pipeline:
        1. AI Vision (primary) → Single call: layout + text + visual detection
        2. PPStructure + PaddleOCR (fallback) → When AI unavailable
        """
        # Fallback: PPStructure for layout analysis
        logger.info("Initializing PPStructure (fallback)...")
        self.layout_engine = PPStructure(
            show_log=False,
            image_orientation=False,
            layout=True,
            table=True,
            ocr=False,
            recovery=False
        )
        
        # Fallback: PaddleOCR for text extraction
        logger.info("Initializing PaddleOCR (fallback)...")
        self.ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang='id',
            show_log=False
        )
        
        logger.info("✓ Unified Vision Pipeline Ready")

    # ─────────────────────────────────────────────────────────────
    # CORE: Single AI Call — Layout + OCR in One Shot
    # ─────────────────────────────────────────────────────────────
    def _unified_ai_scan(self, image_cv):
        """
        ONE API call that does EVERYTHING:
        - Extracts all text content
        - Detects tables/figures with bounding boxes
        - Classifies each element into the correct chapter (BAB 1-7)
        - Returns structured JSON in reading order
        """
        if not AI_AVAILABLE:
            return None

        h, w = image_cv.shape[:2]
        _, buffer = cv2.imencode('.jpg', image_cv, [cv2.IMWRITE_JPEG_QUALITY, 85])
        img_base64 = base64.b64encode(buffer).decode('utf-8')

        vision_model = os.getenv("AI_VISION_MODEL", "google/gemini-2.0-flash-001")

        prompt = """Analyze this document page from a medical device manual. Extract ALL content in reading order.

CRITICAL RULES:
1. NEVER translate any text. Output text EXACTLY in its original language.
2. IGNORE the original chapter/bab numbering in the document. You MUST reclassify every element into our STANDARDIZED structure based on the CONTENT MEANING, NOT the original number.

For example: if the document says "Bab 1: Spesifikasi Teknis", you must classify it as "BAB 6" (Technical Specifications), NOT "BAB 1". The original numbering is irrelevant.

For each element, return a JSON object with:
- "type": one of "heading", "paragraph", "table", "figure"
- "text": the EXACT text as written. DO NOT translate.
- "bbox": bounding box in SCALE 0-1000. Format: [x1, y1, x2, y2].
- "lang": "id" for Indonesian, "en" for English
- "chapter": REMAP into our standardized structure based on CONTENT MEANING:

    STANDARDIZED CHAPTER MAPPING (classify by content, NOT by original number):
    
    "BAB 1" / "Chapter 1" = SAFETY & PURPOSE
        → intended use, purpose, safety warnings, caution, danger, contraindications, patient safety, introduction, overview
    
    "BAB 2" / "Chapter 2" = INSTALLATION
        → installation, setup, mounting, assembly, connecting cables, power supply, unboxing, unpacking, placement
    
    "BAB 3" / "Chapter 3" = OPERATION
        → how to use, operation guide, buttons, display, screen, controls, monitoring, clinical use, measurement, alarms, modes
    
    "BAB 4" / "Chapter 4" = MAINTENANCE & CLEANING
        → maintenance, cleaning, disinfection, sterilization, battery replacement, routine care, filter replacement, calibration, storage
    
    "BAB 5" / "Chapter 5" = TROUBLESHOOTING
        → troubleshooting, error codes, problems, solutions, FAQ, common issues, alarm messages
    
    "BAB 6" / "Chapter 6" = TECHNICAL SPECIFICATIONS
        → specifications, technical data, dimensions, weight, power requirements, accuracy, standards, ISO, IEC, EMC, electrical safety
    
    "BAB 7" / "Chapter 7" = WARRANTY & SERVICE
        → warranty, guarantee, service center, contact info, support, spare parts, returns

Use "BAB X" for Indonesian documents, "Chapter X" for English documents.

Additional rules:
- Cover pages and table of contents → "BAB 1" / "Chapter 1"
- For tables: type="table", text="[TABLE]"
- For figures/images: type="figure", text="[FIGURE]"
- Output ONLY a valid JSON array. No markdown, no commentary.

Example — Original doc says "Bab 1 Spesifikasi Teknis" but we REMAP it:
[
  {"type": "heading", "text": "Bab 1 Spesifikasi Teknis", "bbox": [50, 30, 950, 80], "chapter": "BAB 6", "lang": "id"},
  {"type": "paragraph", "text": "Tegangan: 220V AC, Frekuensi: 50Hz", "bbox": [50, 90, 950, 150], "chapter": "BAB 6", "lang": "id"},
  {"type": "heading", "text": "Bab 2 Peringatan Pengamanan", "bbox": [50, 200, 950, 250], "chapter": "BAB 1", "lang": "id"},
  {"type": "paragraph", "text": "Jauhkan unit dari api.", "bbox": [50, 260, 950, 300], "chapter": "BAB 1", "lang": "id"}
]"""

        logger.info(f"🤖 Unified AI Scan: {vision_model} (1 call: text+layout+chapter)")

        old_model = openrouter.model
        openrouter.model = vision_model
        try:
            response = openrouter.call(prompt, image_base64=img_base64, timeout=60)
            if not response:
                logger.warning("AI returned empty response")
                return None

            # Extract JSON array from response
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if not json_match:
                logger.warning(f"No JSON found in AI response: {response[:200]}")
                return None

            raw_results = json.loads(json_match.group())
            
            # Scale bboxes from 0-1000 to actual pixels
            elements = []
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                
                rtype = item.get('type', 'paragraph').lower()
                text = item.get('text', '').strip()
                bbox = item.get('bbox', [0, 0, 1000, 1000])
                chapter = item.get('chapter', 'BAB 1')
                lang = item.get('lang', 'id')
                
                # Validate chapter format (accept both "BAB X" and "Chapter X")
                valid_chapters = [f"BAB {i}" for i in range(1, 8)] + [f"Chapter {i}" for i in range(1, 8)]
                if chapter not in valid_chapters:
                    chapter = 'BAB 1' if lang == 'id' else 'Chapter 1'
                
                # Scale to pixels
                x1 = int((bbox[0] / 1000) * w)
                y1 = int((bbox[1] / 1000) * h)
                x2 = int((bbox[2] / 1000) * w)
                y2 = int((bbox[3] / 1000) * h)
                
                # Clamp
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                
                if x2 <= x1 or y2 <= y1:
                    continue
                
                # Normalize type
                if rtype in ('title', 'header', 'heading'):
                    rtype = 'heading'
                elif rtype in ('text', 'body', 'paragraph'):
                    rtype = 'paragraph'
                elif 'table' in rtype:
                    rtype = 'table'
                elif rtype in ('figure', 'image', 'picture', 'diagram', 'photo'):
                    rtype = 'figure'
                
                elements.append({
                    'type': rtype,
                    'text': text,
                    'bbox': [x1, y1, x2, y2],
                    'chapter': chapter,
                    'lang': lang
                })
            
            logger.info(f"✓ AI extracted {len(elements)} elements in single call")
            return elements

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI JSON: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unified AI scan failed: {e}")
            return None
        finally:
            openrouter.model = old_model

    # ─────────────────────────────────────────────────────────────
    # FALLBACK: PPStructure + PaddleOCR (when AI unavailable)
    # ─────────────────────────────────────────────────────────────
    def _fallback_paddle_scan(self, image_cv):
        """
        Fallback pipeline using PPStructure for layout + PaddleOCR for text.
        Used when AI is unavailable or fails.
        """
        h, w = image_cv.shape[:2]
        elements = []

        try:
            # Layout detection
            paddle_results = self.layout_engine(image_cv)
            if not paddle_results:
                return []

            # Sort by Y coordinate
            paddle_results.sort(key=lambda x: x['bbox'][1])

            for region in paddle_results:
                region.pop('img', None)
                bbox = region['bbox']
                rtype = region['type'].lower()
                
                x1, y1, x2, y2 = [int(v) for v in bbox]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                
                text = ""
                if rtype in ('table', 'figure'):
                    text = f"[{rtype.upper()}]"
                else:
                    crop = image_cv[y1:y2, x1:x2]
                    ocr_result = self.ocr_engine.ocr(crop, cls=False)
                    if ocr_result and ocr_result[0]:
                        text = "\n".join([line[1][0] for line in ocr_result[0]])
                
                if text:
                    if rtype == 'title':
                        rtype = 'heading'
                    elif rtype not in ('table', 'figure'):
                        rtype = 'paragraph'
                    
                    elements.append({
                        'type': rtype,
                        'text': text,
                        'bbox': [x1, y1, x2, y2]
                    })

            logger.info(f"✓ Paddle fallback: {len(elements)} elements")
            return elements

        except Exception as e:
            logger.error(f"Paddle fallback failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────────
    # MAIN: scan_document (entry point)
    # ─────────────────────────────────────────────────────────────
    def scan_document(self, image_path, filename_base, session_id=None):
        logger.info(f"🔍 Scanning: {os.path.basename(image_path)}")

        # Setup
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(backend_dir, "output_results")
        os.makedirs(output_dir, exist_ok=True)

        # Load image
        original_img = cv2.imread(image_path)
        if original_img is None:
            logger.error(f"Failed to load image: {image_path}")
            return {"elements": [], "clean_image_path": None}

        h, w = original_img.shape[:2]

        # Save preview (original image for user)
        preview_fname = f"PREVIEW_{filename_base}.jpg"
        preview_path = os.path.join(output_dir, preview_fname)
        cv2.imwrite(preview_path, original_img)

        # ── STRATEGY: Try AI first, fallback to Paddle ──
        ai_ocr_enabled = os.getenv("AI_VISION_OCR_ENABLED", "false").lower() in ("true", "1", "yes", "on")
        
        raw_elements = None
        if ai_ocr_enabled:
            raw_elements = self._unified_ai_scan(original_img)
        
        if raw_elements is None:
            logger.info("⚠️ AI unavailable or failed → Using PaddleOCR fallback")
            raw_elements = self._fallback_paddle_scan(original_img)

        # ── POST-PROCESS: Crop visual elements ──
        final_elements = []
        for idx, elem in enumerate(raw_elements):
            rtype = elem['type']
            text = elem['text']
            bbox = elem['bbox']
            x1, y1, x2, y2 = bbox

            crop_url = None
            crop_local = None

            if rtype in ('table', 'figure'):
                # Crop from ORIGINAL image with safety padding
                pad = 20
                px1, py1 = max(0, x1 - pad), max(0, y1 - pad)
                px2, py2 = min(w, x2 + pad), min(h, y2 + pad)
                crop_visual = original_img[py1:py2, px1:px2]

                crop_fname = f"{filename_base}_crop_{rtype}_{idx}.png"
                crop_path = os.path.join(output_dir, crop_fname)
                cv2.imwrite(crop_path, crop_visual)

                from urllib.parse import quote
                crop_url = f"http://127.0.0.1:8000/output/{quote(crop_fname)}"
                crop_local = crop_path
                logger.info(f"📸 Saved {rtype} crop: {crop_fname}")

            final_elements.append({
                "type": rtype,
                "text": text,
                "confidence": 0.95,
                "bbox": bbox,
                "crop_url": crop_url,
                "crop_local": crop_local
            })

        logger.info(f"✅ Total: {len(final_elements)} elements")
        return {
            "elements": final_elements,
            "clean_image_path": preview_path
        }

    # ─────────────────────────────────────────────────────────────
    # UTILITY: Generate missing chapter content
    # ─────────────────────────────────────────────────────────────
    def generate_chapter_content(self, topic, context=""):
        """Generate konten untuk chapter yang hilang."""
        if not AI_AVAILABLE:
            return (
                f"[AI GENERATION FAILED] Tidak ada API Key AI yang aktif. "
                f"Tambahkan OPENROUTER_API_KEY di .env untuk generate {topic}."
            )

        prompt = f"""You are a professional technical writer for medical device manuals.
The user's manual is missing '{topic}'.

PRODUCT CONTEXT (From other chapters):
{context}

YOUR TASK:
1. Write a comprehensive, professional '{topic}' section for THIS SPECIFIC PRODUCT.
2. Include detailed steps, warnings, and best practices.
3. If the product context is vague, write a high-quality standard guide for this type of medical equipment.
4. Use standard technical language (Indonesian).
5. Format with clear headings and bullet points.
6. Do NOT mention that this is AI-generated. Write it as if it belongs in the original manual.
"""

        logger.info(f"🤖 Generating missing chapter: {topic}")

        if openrouter.is_available:
            result = openrouter.call(prompt, timeout=60)
            if result:
                return result

        return f"[GENERATION FAILED] Tidak bisa generate {topic}. Periksa OPENROUTER_API_KEY di .env."


# Factory Function
def create_vision_engine(**kwargs):
    return BioVisionHybrid()
