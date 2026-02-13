"""
HYBRID PIPELINE v2 - PPStructure + PaddleOCR + OpenRouter AI
Optimized for manual book processing
Updated: February 11, 2026 (OpenRouter Integration)
"""

import os
import cv2
import numpy as np
import logging
import google.generativeai as genai

import requests
from paddleocr import PaddleOCR, PPStructure
from pathlib import Path
from dotenv import load_dotenv

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure APIs
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Parse multiple models for fallback
raw_models = os.getenv("AI_MODEL", "google/gemini-2.0-flash-exp:free")
AI_MODELS = [m.strip() for m in raw_models.split(",") if m.strip()]

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

AI_AVAILABLE = False
DIRECT_GEMINI_AVAILABLE = False

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # Use a standard stable model for direct API
        logger.info("✓ Direct Google Gemini API: Active")
        DIRECT_GEMINI_AVAILABLE = True
        AI_AVAILABLE = True
    except Exception as e:
        logger.error(f"❌ Gemini API Config Failed: {e}")

if not DIRECT_GEMINI_AVAILABLE and OPENROUTER_API_KEY and OPENROUTER_API_KEY != "your_openrouter_key_here":
    logger.info(f"✓ OpenRouter API: Active (Models: {', '.join(AI_MODELS)})")
    AI_AVAILABLE = True
elif not AI_AVAILABLE:
    logger.warning("⚠️ No valid AI API Key found (OpenRouter or Gemini) - AI enhancement disabled")


class BioVisionHybrid:
    def __init__(self):
        """
        Triple-Engine Hybrid Pipeline:
        1. PPStructure → Detect & crop tables/figures
        2. PaddleOCR → Fast text extraction
        3. Gemini (Direct or OpenRouter) → Text quality enhancement
        """
        # 0. Initialize Gemini Direct Client (if available)
        self.gemini_model = None
        if DIRECT_GEMINI_AVAILABLE:
            # User specifically requested "Flash 2.5" (likely 2.5-flash-exp)
            self.gemini_model = genai.GenerativeModel('gemini-2.5-flash-exp')

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
            lang='id', # Use 'id' (Indonesian) which covers English too
            show_log=False
        )
        
        logger.info("✓ Hybrid Pipeline Ready (PPStructure + PaddleOCR + OpenRouter AI)")
        
    def remove_watermark(self, image):
        """
        Advanced Preprocessing: Red Channel Extraction (Tuned)
        - Extracts the Red channel where red ink appears white
        - Gentle thresholding to preserve faint text
        """
        try:
            if image is None: return None
            
            # 1. Extract Red Channel
            red_channel = image[:, :, 2]
            
            # 2. Adaptive Thresholding (Tuned for MAX CLEANING)
            # C=20 is very aggressive. It removes almost all noise/watermark.
            # BlockSize=21 is large to estimate background better.
            # AI will fix any broken text resulting from this aggressive cleaning.
            clean = cv2.adaptiveThreshold(
                red_channel, 
                255, 
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY, 
                21, 
                20 # INCREASED from 5 to 20 to kill stubborn watermarks
            )
            
            # 3. Convert back to BGR
            clean_bgr = cv2.cvtColor(clean, cv2.COLOR_GRAY2BGR)
            return clean_bgr
            
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
        Use OpenRouter AI to enhance PaddleOCR text quality
        - Tries multiple models (fallback mechanism)
        - Only returns original text if ALL models fail
        """
        if not AI_AVAILABLE or not raw_text.strip():
            return raw_text
            
        prompt = f"""You are a professional document digitizer.
The following text is raw OCR output from a technical manual (Bilingual: Indonesian & English). It has broken lines and scanner noise.

RAW OCR INPUT:
{raw_text}

YOUR TASK:
1. Fix broken lines (merge correctly).
2. Fix obvious OCR character errors (e.g. '1l' -> 'll').
3. DO NOT REWRITE OR SUMMARIZE. PROHIBITED.
4. DO NOT ADD INFORMATION not present in the text.
5. DO NOT REMOVE any content.
6. Output ONLY the restored text. Matches the original content exactly.

RESTORED TEXT:"""

        # PRIORITIZE DIRECT GEMINI API (It's free and reliable)
        if self.gemini_model:
            try:
                # logger.info("🤖 Enhancing text with Direct Google Gemini...")
                response = self.gemini_model.generate_content(prompt)
                enhanced = response.text.strip()
                logger.info(f"✓ AI enhanced text quality (Success with Direct Gemini)")
                return enhanced
            except Exception as e:
                logger.warning(f"Direct Gemini failed: {e}, falling back to OpenRouter...")

        # Fallback to OpenRouter
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "Manual Book Data Normalization"
        }

        # Try each model in sequence
        for model in AI_MODELS:
            try:
                # logger.info(f"🤖 Enhancing text with model: {model}...")
                
                data = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}]
                }
                
                response = requests.post(OPENROUTER_API_URL, headers=headers, json=data, timeout=30)
                
                if response.status_code != 200:
                    continue
                
                result = response.json()
                if 'choices' not in result or not result['choices']:
                    continue
                    
                enhanced = result['choices'][0]['message']['content'].strip()
                logger.info(f"✓ AI enhanced text quality (Success with {model})")
                return enhanced
                
            except Exception as e:
                continue
        
        return raw_text
    
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
                    crop_img = clean_img[y1:y2, x1:x2]
                    
                    # BRANCH A: Visual Elements (Table/Figure)
                    if rtype in ['table', 'figure']:
                        crop_fname = f"{filename_base}_crop_{rtype}_{idx}.png"
                        crop_path = os.path.join(output_dir, crop_fname)
                        cv2.imwrite(crop_path, crop_img)
                        
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
