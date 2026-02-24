"""
HYBRID PIPELINE v3 - PPStructure + PaddleOCR + OpenRouter AI
Optimized for manual book processing
Updated: February 2026 (Full OpenRouter — no Gemini)
"""

import os
import cv2
import numpy as np
import logging

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
        Hybrid Pipeline:
        1. PPStructure → Detect & crop tables/figures
        2. PaddleOCR → Fast text extraction
        3. OpenRouter AI → Text quality enhancement
        """
        # 1. PPStructure for layout analysis (tables/figures)
        logger.info("Initializing PPStructure for table/figure detection...")
        self.layout_engine = PPStructure(
            show_log=False,
            image_orientation=False,
            layout=True,
            table=True,
            ocr=False,
            recovery=False
        )
        
        # 2. PaddleOCR for text extraction
        logger.info("Initializing PaddleOCR for text extraction...")
        self.ocr_engine = PaddleOCR(
            use_angle_cls=True,
            lang='id',
            show_log=False
        )
        
        logger.info("✓ Hybrid Pipeline Ready (PPStructure + PaddleOCR + OpenRouter AI)")
        
    def remove_watermark(self, image):
        """
        Advanced Preprocessing: HSV Color Filtering
        - Identifies Red/Pink watermarks using HSV color space
        - Turns them WHITE before thresholding to avoid 'black line' artifacts
        """
        try:
            if image is None: return None
            
            # 1. Convert to HSV
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            
            # 2. Define Red Color Ranges (Red wraps around 0/180)
            # Range 1: 0-10 (Red)
            lower_red1 = np.array([0, 30, 30])
            upper_red1 = np.array([10, 255, 255])
            
            # Range 2: 170-180 (Red/Pink)
            lower_red2 = np.array([170, 30, 30])
            upper_red2 = np.array([180, 255, 255])
            
            # 3. Create Masks
            mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
            mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
            watermark_mask = mask1 + mask2
            
            # 4. Dilate mask to cover anti-aliased edges (The "Black Line" killer)
            kernel = np.ones((3,3), np.uint8)
            dilated_mask = cv2.dilate(watermark_mask, kernel, iterations=1)
            
            # 5. Inpaint / Turn White
            # We copy the image to avoid modifying the original source
            clean_color = image.copy()
            # Set watermark pixels to pure white
            clean_color[dilated_mask > 0] = (255, 255, 255)
            
            # 6. Convert to Grayscale & Threshold (for OCR)
            gray = cv2.cvtColor(clean_color, cv2.COLOR_BGR2GRAY)
            
            # Gentle Threshold to preserve text
            clean_binary = cv2.adaptiveThreshold(
                gray, 
                255, 
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY, 
                15, # Block size
                10  # Constant
            )
            
            # Return as BGR (3 channels) for consistency
            return cv2.cvtColor(clean_binary, cv2.COLOR_GRAY2BGR)
            
        except Exception as e:
            logger.warning(f"Preprocessing failed: {e}")
            return image

    def _smart_sort_regions(self, regions):
        """
        Sort regions using Y-clustering to handle multiple columns.
        1. Sort by Y-coordinate.
        2. Cluster regions that are roughly on the same line (within tolerance).
        3. Sort clusters by X-coordinate (Left-to-Right).
        """
        if not regions: return []
        
        # Initial sort by Y
        regions.sort(key=lambda x: x['bbox'][1])
        
        sorted_regions = []
        current_row = [regions[0]]
        row_y = regions[0]['bbox'][1]
        tolerance = 20 # pixels
        
        for region in regions[1:]:
            y = region['bbox'][1]
            if abs(y - row_y) < tolerance:
                # Same row
                current_row.append(region)
            else:
                # New row
                # Sort current row by X
                current_row.sort(key=lambda x: x['bbox'][0])
                sorted_regions.extend(current_row)
                
                # Start new row
                current_row = [region]
                row_y = y
        
        # Append last row
        if current_row:
            current_row.sort(key=lambda x: x['bbox'][0])
            sorted_regions.extend(current_row)
            
        return sorted_regions
    
    def enhance_text_with_gemini(self, raw_text):
        """
        Gunakan OpenRouter untuk enhance kualitas teks OCR.
        Timeout pendek agar tidak hang. Fallback ke teks mentah jika gagal.
        """
        if not AI_AVAILABLE or not raw_text.strip():
            return raw_text

        # Skip enhance jika teks terlalu pendek (tidak worth API call)
        if len(raw_text.strip()) < 50:
            return raw_text

        # Batasi panjang teks yang dikirim (max 3000 char) agar respons cepat
        text_to_enhance = raw_text.strip()[:3000]
        if len(raw_text.strip()) > 3000:
            tail = raw_text.strip()[3000:]
        else:
            tail = ""

        # Timeout dari .env, default 20 detik
        enhance_timeout = int(os.getenv("AI_ENHANCE_TIMEOUT", "20"))

        prompt = f"""Fix OCR errors in this technical manual text (Indonesian/English). 
Rules: fix broken lines, fix character errors (l→1, O→0 in numbers). DO NOT add/remove content.
Output ONLY the fixed text.

TEXT:
{text_to_enhance}

FIXED TEXT:"""

        # OpenRouter only
        if openrouter.is_available:
            result = openrouter.call(prompt, timeout=enhance_timeout)
            if result:
                return result + ("\n" + tail if tail else "")

        # Fallback: return raw OCR text (no Gemini)
        logger.info("OpenRouter unavailable — using raw OCR text")
        return raw_text
    
    def generate_chapter_content(self, topic, context=""):
        """
        Generate konten untuk chapter yang hilang (e.g. BAB 4 Maintenance).
        Gunakan mode smart untuk output yang lebih berkualitas.
        """
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

        logger.info(f"🤖 Generating missing chapter: {topic} (mode=smart, context={len(context)} chars)")

        # OpenRouter only
        if openrouter.is_available:
            result = openrouter.call(prompt, timeout=60)
            if result:
                return result

        return f"[GENERATION FAILED] Tidak bisa generate {topic}. Periksa OPENROUTER_API_KEY di .env."
    
    def scan_document(self, image_path, filename_base, session_id=None):
        logger.info(f"🔍 Scanning (Hybrid Mode): {os.path.basename(image_path)}")
        
        # Setup
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(backend_dir, "output_results")
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. Preprocess
        original_img = cv2.imread(image_path)
        if original_img is None:
            logger.error(f"Failed to load image: {image_path}")
            return {"elements": [], "clean_image_path": None}
            
        clean_img = self.remove_watermark(original_img)
        h, w, _ = clean_img.shape
        
        # Save preview
        preview_fname = f"PREVIEW_{filename_base}.jpg"
        preview_path = os.path.join(output_dir, preview_fname)
        cv2.imwrite(preview_path, clean_img)
        
        # 2. Layout Analysis (PPStructure)
        # This is CRITICAL for multi-column documents to get reading order right
        logger.info("📐 Analyzing Layout (Regions)...")
        visual_regions = []
        raw_text_accumulated = []
        
        try:
            layout_results = self.layout_engine(clean_img)
            
            # Use Smart Sort (Row-Major) instead of simple Y-sort
            # This handles multi-column layouts correctly
            layout_results = self._smart_sort_regions(layout_results)
            
            has_regions = len(layout_results) > 0
            
            if has_regions:
                logger.info(f"✓ Found {len(layout_results)} layout regions (processing individually)")
                
                for idx, region in enumerate(layout_results):
                    rtype = region.get('type', 'text')
                    bbox = region.get('bbox', [0,0,0,0])
                    x1, y1, x2, y2 = [int(v) for v in bbox]
                    
                    # Clamp coordinates
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    
                    if x2 <= x1 or y2 <= y1: continue
                    
                    # Create crop for this region
                    # DEFAULT: Use clean image for OCR (Text)
                    crop_img = clean_img[y1:y2, x1:x2]
                    
                    # BRANCH A: Visual Elements (Table/Figure)
                    if rtype in ['table', 'figure']:
                        # Add SAFETY PADDING (20px) to capture borders/headers
                        pad = 20
                        px1 = max(0, x1 - pad)
                        py1 = max(0, y1 - pad)
                        px2 = min(w, x2 + pad)
                        py2 = min(h, y2 + pad)
                        
                        # Use ORIGINAL IMAGE for visuals (preserve color)
                        # We use the original_img (before thresholding)
                        crop_visual = original_img[py1:py2, px1:px2]
                        
                        crop_fname = f"{filename_base}_crop_{rtype}_{idx}.png"
                        crop_path = os.path.join(output_dir, crop_fname)
                        cv2.imwrite(crop_path, crop_visual)
                        
                        visual_regions.append({
                            "type": rtype,
                            "bbox": [x1, y1, x2, y2],
                            "crop_url": f"http://127.0.0.1:8000/output/{crop_fname}",
                            "crop_local": crop_path
                        })
                    
                    # BRANCH B: Text Elements (Text, Title, List, Header, Footer)
                    else:
                        # Region-based OCR
                        # Optimization: cls=False for speed (assume text is upright in regions)
                        try:
                            # Show progress in terminal
                            print(f"    Processing region {idx+1}/{len(layout_results)}...", end='\r')
                            
                            # Run OCR on the crop
                            # cls=False saves ~300ms per region
                            block_ocr = self.ocr_engine.ocr(crop_img, cls=False)
                            
                            if block_ocr and block_ocr[0]:
                                for line in block_ocr[0]:
                                    text = line[1][0]
                                    conf = line[1][1]
                                    
                                    # Append text directly. We trust the region sort order.
                                    raw_text_accumulated.append(text)
                                    
                        except Exception as e_ocr:
                            logger.warning(f"Region OCR failed: {e_ocr}")

            else:
                logger.warning("No layout regions found. Falling back to global OCR.")
                # Fallback: Global OCR (old behavior)
                ocr_results = self.ocr_engine.ocr(clean_img)
                if ocr_results and ocr_results[0]:
                    lines = sorted(ocr_results[0], key=lambda x: x[0][0][1]) # Sort by Y
                    for line in lines:
                        raw_text_accumulated.append(line[1][0])

        except Exception as e:
            logger.error(f"Layout analysis failed: {e}")
            # Fallback on crash
            ocr_results = self.ocr_engine.ocr(clean_img)
            if ocr_results and ocr_results[0]:
                for line in ocr_results[0]:
                    raw_text_accumulated.append(line[1][0])
            
        
        # 3. Concatenate Text
        raw_text = "\n".join(raw_text_accumulated)
        
        # 4. AI: Enhance text quality
        logger.info("🤖 AI enhancing text quality...")
        enhanced_text = self.enhance_text_with_gemini(raw_text)
        
        # 5. Build final elements
        final_elements = []
        
        # Add enhanced text as paragraphs
        if enhanced_text:
            paragraphs = [p.strip() for p in enhanced_text.split('\n\n') if p.strip()]
            for para in paragraphs:
                is_heading = (
                    len(para) < 100 and
                    (para.isupper() or
                     para.startswith(('BAB', 'CHAPTER', 'SECTION')) or
                     any(para.startswith(f'{i}.') for i in range(1, 10)))
                )
                
                final_elements.append({
                    "type": "heading" if is_heading else "paragraph",
                    "text": para,
                    "confidence": 0.95,
                    "bbox": [0, 0, w, h], # Global bbox for now
                    "crop_url": None,
                    "crop_local": None
                })
        
        # Add visual elements
        for visual in visual_regions:
            final_elements.append({
                "type": visual['type'],
                "text": f"[{visual['type'].upper()}]",
                "confidence": 0.95,
                "bbox": visual['bbox'],
                "crop_url": visual['crop_url'],
                "crop_local": visual['crop_local']
            })
        
        logger.info(f"✅ Total: {len(final_elements)} elements ({len(visual_regions)} visuals)")
        
        return {
            "elements": final_elements,
            "clean_image_path": preview_path
        }

# Factory Function
def create_vision_engine(**kwargs):
    return BioVisionHybrid()
