import os
import uuid
import logging
import time
import json
import re
import cv2
import shutil
from pathlib import Path

from language_filter import enforce_language, clean_text
from image_processing import split_columns_simple, convert_pdf_to_images_safe

logger = logging.getLogger("BioManual")

class SystemOrchestrator:
    def __init__(self, vision_module, brain_module, architect_module, progress_tracker):
        self.vision = vision_module
        self.brain = brain_module
        self.architect = architect_module
        self.progress_tracker = progress_tracker
        self.output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_results")
        
        self.chapter_titles = {
            "BAB 1": "Tujuan Penggunaan & Keamanan",
            "BAB 2": "Instalasi",
            "BAB 3": "Panduan Operasional & Pemantauan Klinis",
            "BAB 4": "Perawatan, Pemeliharaan & Pembersihan",
            "BAB 5": "Pemecahan Masalah",
            "BAB 6": "Spesifikasi Teknis & Kepatuhan Standar",
            "BAB 7": "Garansi & Layanan",
            "Chapter 1": "Intended Use & Safety",
            "Chapter 2": "Installation",
            "Chapter 3": "Operation & Clinical Monitoring",
            "Chapter 4": "Maintenance, Care & Cleaning",
            "Chapter 5": "Troubleshooting",
            "Chapter 6": "Technical Specifications & Standards",
            "Chapter 7": "Warranty & Service"
        }

    def _remap_chapter(self, bab_id, target_lang):
        """Remap BAB -> Chapter or Chapter -> BAB based on target language."""
        if target_lang == 'en' and bab_id.startswith('BAB '):
            bab_num = bab_id.replace('BAB ', '')
            new_key = f"Chapter {bab_num}"
            if new_key in self.chapter_titles:
                return new_key
        elif target_lang == 'id' and bab_id.startswith('Chapter '):
            bab_num = bab_id.replace('Chapter ', '')
            new_key = f"BAB {bab_num}"
            if new_key in self.chapter_titles:
                return new_key
        return bab_id

    def _normalize_element(self, element, lang, direct_translate, text_corrector_hl):
        """Unified normalization and classification for an element."""
        if direct_translate:
            corrected = element['text']
            highlights = []
            normalized_result = {
                'original': corrected,
                'corrected': corrected,
                'typos': 0,
                'has_typo': False
            }
            bab_id = "Chapter 1" if lang == 'en' else "BAB 1"
        else:
            normalized_result = self.brain.normalize_text(element['text'], lang=lang)
            if text_corrector_hl:
                correction = text_corrector_hl(normalized_result['corrected'], lang=lang)
                corrected = correction['text']
                highlights = correction['highlights']
            else:
                corrected = normalized_result['corrected']
                highlights = []
            
            normalized_result['corrected'] = corrected
            
            # Semantic Mapping
            bab_id = element.get('chapter', '')
            if not bab_id or bab_id not in self.chapter_titles:
                bab_id, _ = self.brain.semantic_mapping(element)
        
        # Remap based on lang
        bab_id = self._remap_chapter(bab_id, lang)
        bab_title = self.chapter_titles.get(bab_id, "Unknown Chapter")
        
        # Enforce Language
        clean_orig = enforce_language(normalized_result['original'], lang=lang)
        clean_norm = enforce_language(normalized_result['corrected'], lang=lang)
        
        return {
            "chapter_id": bab_id,
            "chapter_title": bab_title,
            "type": element['type'],
            "original": clean_orig,
            "normalized": clean_norm,
            "typos": normalized_result.get('typos', 0),
            "has_typo": normalized_result.get('has_typo', False),
            "text_confidence": element.get('confidence', 1.0),
            "match_score": 100,
            "lang": element.get('lang', lang),
            "crop_url": element.get('crop_url'),
            "crop_local": element.get('crop_local'),
            "source_image_local": element.get('source_image_local'),
            "bbox": element.get('bbox'),
            "highlights": highlights,
            "_direct_read": element.get('_direct_read', False)
        }

    async def run_ocr_pipeline(self, images, filename, session_id, lang, direct_translate, text_corrector_hl):
        """Process scanned PDF or images using OCR."""
        self.brain.reset_context() 
        total_pages = len(images)
        structured_data = []
        clean_pages_urls = []
        
        print(f"\n  🚀  Processing {total_pages} pages...")
        for i, img_src in enumerate(images):
            current_page = i + 1
            pct = int((current_page / total_pages) * 100)
            
            # (Progress Tracker Updates...)
            self.progress_tracker[session_id].update({
                "current_page": current_page, "percentage": pct,
                "message": f"Processing page {current_page} of {total_pages}..."
            })
            
            # Print page progress to terminal
            print(f"      [ {pct:3d}% ] Reading Page {current_page}/{total_pages}...", end='\r')
            
            page_path = img_src
            if not isinstance(img_src, str):
                page_path = os.path.join(os.path.dirname(self.output_dir), f"page_{session_id}_{i}.png")
                img_src.save(page_path, "PNG")
            
            try:
                col_paths = split_columns_simple(page_path, f"{filename}_{i}", self.output_dir)
            except Exception as e:
                logger.warning(f"Column split failed: {e}")
                col_paths = [page_path]
                
            for col_idx, col_path in enumerate(col_paths):
                scan_result = self.vision.scan_document(
                    col_path, f"{filename}_{i}_c{col_idx}", lang=lang, direct_translate=direct_translate
                )
                
                layout_elements = scan_result if isinstance(scan_result, list) else scan_result.get('elements', [])
                if not isinstance(scan_result, list):
                    clean_path = scan_result.get('clean_image_path')
                    if clean_path and os.path.exists(clean_path):
                        from urllib.parse import quote
                        clean_pages_urls.append(f"http://127.0.0.1:8000/output/{quote(os.path.basename(clean_path))}")
                
                for element in layout_elements:
                    element['source_image_local'] = col_path
                    item = self._normalize_element(element, lang, direct_translate, text_corrector_hl)
                    structured_data.append(item)
            
            if not isinstance(img_src, str) and os.path.exists(page_path):
                try: os.remove(page_path)
                except: pass
        
        print(f"\n  ✅  Extraction Complete: {len(structured_data)} elements found.")
        
        # Print Chapter Summary
        chapters_found = sorted(list(set(item['chapter_id'] for item in structured_data)))
        print(f"  📊  Chapter Summary:")
        for ch in chapters_found:
            count = sum(1 for item in structured_data if item['chapter_id'] == ch)
            print(f"      - {ch}: {count} elements")
                
        return structured_data, clean_pages_urls

    async def run_hybrid_direct_pipeline(self, pdf_path, filename, session_id, lang, direct_translate, text_corrector_hl):
        """
        Ultimate Hybrid Pipeline: Surya Layout + Direct Text Extraction.
        """
        self.brain.reset_context() # MUST RESET
        import pdfplumber
        import numpy as np
        
        structured_data = []
        clean_pages_urls = []
        
        logger.info(f"🚀 Running Hybrid Direct Pipeline (Surya Layout + PDF Text) for {filename}")
        
        # 1. Convert to images for Surya
        images = convert_pdf_to_images_safe(pdf_path)
        total_pages = len(images)
        
        with pdfplumber.open(pdf_path) as pdf:
            for i, page_img in enumerate(images):
                current_page = i + 1
                pct = int((current_page / total_pages) * 100)
                
                self.progress_tracker[session_id].update({
                    "current_page": current_page, "percentage": pct,
                    "message": f"Analyzing layout (Surya) page {current_page}..."
                })
                print(f"      [ {pct:3d}% ] Hybrid Layout Page {current_page}/{total_pages}...", end='\r')
                
                # Save page image for preview
                page_fname = f"PREVIEW_{filename}_{i}.jpg"
                page_path = os.path.join(self.output_dir, page_fname)
                page_img.save(page_path, "JPEG", quality=90)
                
                from urllib.parse import quote
                clean_pages_urls.append(f"http://127.0.0.1:8000/output/{quote(page_fname)}")
                
                # Render for Surya layout (OpenCV format)
                img_cv = cv2.cvtColor(np.array(page_img), cv2.COLOR_RGB2BGR)
                ch, cw = img_cv.shape[:2]
                
                # 2. Run Surya Layout Detection (Visual Only)
                regions = self.vision._detect_layout(img_cv)
                visual_regions = [r for r in regions if r['type'] in ('table', 'figure', 'formula')]
                
                # 3. Process PDF Page with PDFPlumber (Text Only)
                pdf_page = pdf.pages[i]
                scale_x = cw / pdf_page.width
                scale_y = ch / pdf_page.height
                
                # Get text elements from PDFPlumber logic
                # We'll use a simplified version of the direct reader logic here for precision
                words = pdf_page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
                
                # Filter out words that fall within Surya's visual boxes
                filtered_words = []
                for w in words:
                    # Convert PDF points to Image pixels for comparison
                    wx1, wy1, wx2, wy2 = w['x0'] * scale_x, w['top'] * scale_y, w['x1'] * scale_x, w['bottom'] * scale_y
                    w_bbox = [wx1, wy1, wx2, wy2]
                    
                    is_inside_visual = False
                    for vr in visual_regions:
                        v_bbox = vr['bbox']
                        # Check overlap
                        ov_x1 = max(w_bbox[0], v_bbox[0])
                        ov_y1 = max(w_bbox[1], v_bbox[1])
                        ov_x2 = min(w_bbox[2], v_bbox[2])
                        ov_y2 = min(w_bbox[3], v_bbox[3])
                        if ov_x2 > ov_x1 and ov_y2 > ov_y1:
                            # Significant overlap?
                            ov_area = (ov_x2 - ov_x1) * (ov_y2 - ov_y1)
                            w_area = (w_bbox[2] - w_bbox[0]) * (w_bbox[3] - w_bbox[1])
                            if w_area > 0 and (ov_area / w_area) > 0.5:
                                is_inside_visual = True
                                break
                    
                    if not is_inside_visual:
                        filtered_words.append(w)
                
                # Group filtered words into paragraphs
                from direct_reader import _group_words_into_lines, _merge_lines_into_paragraphs
                lines = _group_words_into_lines(filtered_words, pdf_page.height)
                paragraphs = _merge_lines_into_paragraphs(lines, pdf_page.width, pdf_page.height)
                
                for para in paragraphs:
                    text = para['text'].strip()
                    if not text: continue
                    
                    etype = "paragraph"
                    # Heuristic for headings based on font size or bold
                    if para.get('avg_size', 11) > 13 or para.get('is_bold'):
                        etype = "heading"
                    
                    element = {
                        "type": etype,
                        "text": text,
                        "bbox": para['bbox'], # PDF Units
                        "source_image_local": page_path,
                        "confidence": 1.0,
                        "_direct_read": True
                    }
                    item = self._normalize_element(element, lang, direct_translate, text_corrector_hl)
                    structured_data.append(item)
                
                # 4. Add Surya's Visual Crops
                for idx, vr in enumerate(visual_regions):
                    vbox = vr['bbox']
                    rtype = vr['type']
                    
                    # CROP: Use image pixels
                    pad = 10
                    px1, py1 = max(0, int(vbox[0] - pad)), max(0, int(vbox[1] - pad))
                    px2, py2 = min(cw, int(vbox[2] + pad)), min(ch, int(vbox[3] + pad))
                    crop_visual = img_cv[py1:py2, px1:px2]
                    
                    if crop_visual.size > 0:
                        crop_fname = f"{filename}_p{i}_v{idx}_{rtype}.png"
                        crop_path = os.path.join(self.output_dir, crop_fname)
                        cv2.imwrite(crop_path, crop_visual)
                        
                        element = {
                            "type": rtype,
                            "text": f"[{rtype.upper()}]",
                            "bbox": vbox, # Image Pixels
                            "crop_url": f"http://127.0.0.1:8000/output/{quote(crop_fname)}",
                            "crop_local": crop_path,
                            "source_image_local": page_path,
                            "confidence": 1.0
                        }
                        item = self._normalize_element(element, lang, direct_translate, text_corrector_hl)
                        structured_data.append(item)

        print(f"\n  ✅  Hybrid Direct Extraction Complete: {len(structured_data)} elements.")
        return structured_data, clean_pages_urls

    def extract_cover_info(self, clean_pages_urls, lang, text_context=None):
        """Extract product info from first page using AI (Visual or Text)."""
        if not clean_pages_urls and not text_context:
            return None, None
            
        first_page_url = clean_pages_urls[0]
        # Resolve local path from URL
        from urllib.parse import unquote, urlparse
        parsed = urlparse(first_page_url)
        fname = unquote(parsed.path.split('/')[-1])
        local_path = os.path.join(self.output_dir, fname)
        
        if not os.path.exists(local_path):
            return None, None
            
        logger.info(f"🧠 AI: Extracting cover info from {fname}...")
        try:
            from openrouter_client import get_openrouter_client
            client = get_openrouter_client()
            
            # Read first page
            img_cv = cv2.imread(local_path)
            if img_cv is None: return None, None
            
            h, w = img_cv.shape[:2]
            if w > 1000:
                scale = 1000 / w
                img_cv = cv2.resize(img_cv, (1000, int(h * scale)))
            
            import base64
            _, buffer = cv2.imencode('.jpg', img_cv, [cv2.IMWRITE_JPEG_QUALITY, 80])
            img_b64 = base64.b64encode(buffer).decode('utf-8')
            
            lang_label = "Indonesia" if lang == 'id' else "English"
            prompt = f"""Look at this manual book cover page. Please extract:
1. "product_name": The main name of the medical device (usually big bold text).
2. "product_description": A short functional description of what the device does (e.g., "Infusion Pump", "Standard Wheelchair").
Respond in {lang_label} if possible.
Return ONLY JSON: {{"product_name": "...", "product_description": "..."}}"""

            response = client.call(prompt, image_base64=img_b64, timeout=30)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                payload = json.loads(json_match.group())
                return payload.get('product_name'), payload.get('product_description')
        except Exception as e:
            logger.warning(f"AI cover info extraction failed: {e}")
            
        return None, None
