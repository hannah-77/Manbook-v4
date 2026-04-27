import os
import uuid
import logging
import time
import json
import re
import cv2
import shutil
import asyncio
import base64
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

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
            
        # Semantic Mapping (Universal for both modes)
        bab_id = element.get('chapter', '')
        
        # If no chapter from vision engine, or it's unsure, run mapping
        if not bab_id or bab_id not in self.chapter_titles:
            # 1. Rule-based mapping first
            bab_id, _ = self.brain.semantic_mapping(element)
            
            # 2. AI Fallback: If it's a heading, we want high accuracy
            # Or if it's the beginning of the document and we're still in BAB 1
            is_heading = element.get('type') in ('title', 'heading')
            ai_enabled = os.getenv("AI_VISION_OCR_ENABLED", "false").lower() in ("true", "1", "yes")
            
            if ai_enabled and is_heading:
                logger.info(f"🧠 AI: Classifying heading: '{element['text'][:50]}...'")
                ai_bab = self.brain.classify_chapter_ai(element['text'], self.brain.current_context, lang=lang)
                if ai_bab:
                    logger.info(f"   ↳ AI Result: {ai_bab}")
                    bab_id = ai_bab
                    self.brain.current_context = bab_id # Sync context
        
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
            
            # ── Add column crops (or full page) to Layout Preview ──
            page_has_columns = len(col_paths) > 1 and col_paths[0] != page_path
            if page_has_columns:
                # Multi-column: each column crop is already saved in output_dir by split_columns_simple
                for col_path in col_paths:
                    col_basename = os.path.basename(col_path)
                    clean_pages_urls.append(f"http://127.0.0.1:8000/output/{quote(col_basename)}")
                logger.info(f"📐 OCR Preview: Page {current_page} → {len(col_paths)} column crops")
            else:
                # Single column: save full page image to output_dir for preview
                preview_fname = f"OCR_PREVIEW_{filename}_{i}.png"
                preview_path = os.path.join(self.output_dir, preview_fname)
                import shutil as _shutil
                try:
                    _shutil.copy2(page_path, preview_path)
                except Exception:
                    preview_path = page_path  # fallback
                clean_pages_urls.append(f"http://127.0.0.1:8000/output/{quote(preview_fname)}")
                
            for col_idx, col_path in enumerate(col_paths):
                scan_result = self.vision.scan_document(
                    col_path, f"{filename}_{i}_c{col_idx}", lang=lang, direct_translate=direct_translate
                )
                
                layout_elements = scan_result if isinstance(scan_result, list) else scan_result.get('elements', [])
                
                for element in layout_elements:
                    element['source_image_local'] = col_path
                    item = self._normalize_element(element, lang, direct_translate, text_corrector_hl)
                    structured_data.append(item)
            
            if not isinstance(img_src, str) and os.path.exists(page_path):
                try: os.remove(page_path)
                except: pass
        
        print(f"\n  ✅  Extraction Complete: {len(structured_data)} elements found.")
        
        # ─── Global Classification Refinement (NEW) ───
        structured_data = await self.refine_classification(structured_data, lang)
        
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
                
                # Save page image for Surya layout analysis
                page_fname = f"PREVIEW_{filename}_{i}.jpg"
                page_path = os.path.join(self.output_dir, page_fname)
                page_img.save(page_path, "JPEG", quality=90)
                
                # NOTE: We do NOT add the full page to clean_pages_urls here.
                # If columns are detected, only column crops will be added.
                # If no columns are detected (single column), we add it below.
                full_page_url = f"http://127.0.0.1:8000/output/{quote(page_fname)}"
                
                # Render for Surya layout (OpenCV format)
                img_cv = cv2.cvtColor(np.array(page_img), cv2.COLOR_RGB2BGR)
                ch, cw = img_cv.shape[:2]
                
                # Run Surya Layout Detection (Visual Only) once per page
                regions = self.vision._detect_layout(img_cv)
                visual_regions = [r for r in regions if r['type'] in ('table', 'figure', 'formula')]
                
                # Scale factors for coordinate conversion
                scale_y = ch / pdf.pages[i].height if pdf.pages[i].height > 0 else 1.0
                
                # 2. Column Detection (Visual projection)
                # This ensures we extract text in the correct reading order for multi-column manuals
                col_boundaries = [0, cw]
                try:
                    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
                    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
                    
                    # Vertical projection on 84% of page (ignore headers/footers)
                    h_start = int(ch * 0.08)
                    h_end = int(ch * 0.92)
                    roi = binary[h_start:h_end, :]
                    white_ratio = np.mean(roi == 255, axis=0)
                    
                    # Robust smoothing — 1% of page width
                    k_size = max(7, int(cw * 0.01))
                    white_smooth = np.convolve(white_ratio, np.ones(k_size)/k_size, mode='same')
                    
                    # Strict cover page logic if it's the first page
                    if current_page == 1:
                        is_gap = white_smooth > 0.98
                        min_gap_width = int(cw * 0.05)
                        
                        gaps = []
                        in_gap = False
                        gap_start = 0
                        for x in range(cw):
                            if is_gap[x] and not in_gap:
                                gap_start = x
                                in_gap = True
                            elif not is_gap[x] and in_gap:
                                gap_w = x - gap_start
                                if gap_w >= min_gap_width:
                                    gc = gap_start + gap_w // 2
                                    if cw * 0.05 < gc < cw * 0.95:
                                        gaps.append(gc)
                                in_gap = False
                    else:
                        # Multi-pass gap detection: strict → lenient
                        gaps = []
                        pass_configs = [
                            (0.95, 0.02),   # Real column gutters
                            (0.90, 0.015),  # Slightly less strict
                            (0.85, 0.012),  # More tolerant
                        ]
                        
                        for pass_thresh, pass_min_pct in pass_configs:
                            is_gap_pass = white_smooth > pass_thresh
                            min_gap_w = max(10, int(cw * pass_min_pct))
                            
                            pass_gaps = []
                            in_gap = False
                            gap_start = 0
                            for x in range(cw):
                                if is_gap_pass[x] and not in_gap:
                                    gap_start = x
                                    in_gap = True
                                elif not is_gap_pass[x] and in_gap:
                                    gap_w = x - gap_start
                                    if gap_w >= min_gap_w:
                                        gc = gap_start + gap_w // 2
                                        if cw * 0.05 < gc < cw * 0.95:
                                            pass_gaps.append(gc)
                                    in_gap = False
                            
                            if pass_gaps:
                                pass_gaps.sort()
                                filtered = [pass_gaps[0]]
                                for g in pass_gaps[1:]:
                                    if g - filtered[-1] > cw * 0.15:
                                        filtered.append(g)
                                
                                num_found = len(filtered) + 1
                                if 2 <= num_found <= 4:
                                    gaps = filtered
                                    logger.info(f"   Hybrid col detection (thresh={pass_thresh}): {num_found} cols, gaps={gaps}")
                                    break
                    
                    # Filter gaps too close to each other (safety)
                    filtered_gaps = []
                    if gaps:
                        gaps.sort()
                        filtered_gaps.append(gaps[0])
                        for g in gaps[1:]:
                            if g - filtered_gaps[-1] > cw * 0.15:
                                filtered_gaps.append(g)
                                
                    gaps = filtered_gaps
                    col_boundaries = [0] + sorted(gaps) + [cw]
                    num_cols = len(col_boundaries) - 1
                    
                    # Validate columns: wide enough and balanced
                    if num_cols > 1:
                        col_widths = []
                        valid_cols = []
                        for c_idx in range(num_cols):
                            c_w = col_boundaries[c_idx+1] - col_boundaries[c_idx]
                            col_widths.append(c_w)
                            if c_w > cw * 0.10:
                                valid_cols.append(c_idx)
                        if len(valid_cols) < 2:
                            col_boundaries = [0, cw]
                        else:
                            # Balance check
                            valid_widths = [col_widths[i] for i in valid_cols]
                            if max(valid_widths) > 3 * min(valid_widths):
                                logger.info(f"Hybrid: unbalanced column widths {[int(c) for c in col_widths]}, using single column")
                                col_boundaries = [0, cw]
                            
                    if len(col_boundaries) - 1 > 4:
                        logger.warning(f"Too many columns ({len(col_boundaries)-1}), capping at 4")
                        gaps = gaps[:3]
                        col_boundaries = [0] + sorted(gaps) + [cw]
                        
                    if len(col_boundaries) - 1 > 1:
                        logger.info(f"Hybrid Page {current_page}: detected {len(col_boundaries)-1} columns")
                except Exception as e_col:
                    logger.warning(f"Hybrid column detection failed: {e_col}")

                # 3. Process each column individually
                num_cols = len(col_boundaries) - 1
                page_has_columns = num_cols > 1
                
                # If single column, add the full page to preview
                if not page_has_columns:
                    clean_pages_urls.append(full_page_url)
                    logger.info(f"📐 Hybrid Preview: Page {current_page} → Single Column")
                else:
                    logger.info(f"📐 Hybrid Preview: Page {current_page} → {num_cols} Columns")
                
                for col_idx in range(num_cols):
                    cx1, cx2 = col_boundaries[col_idx], col_boundaries[col_idx+1]
                    
                    # CROP: Separate image for each column in preview (User Request!)
                    col_pad_px = 5
                    cpx1, cpx2 = max(0, int(cx1 - col_pad_px)), min(cw, int(cx2 + col_pad_px))
                    col_img_cv = img_cv[0:ch, cpx1:cpx2]
                    
                    col_fname = f"PREVIEW_{filename}_p{i}_c{col_idx+1}.jpg"
                    col_path = os.path.join(self.output_dir, col_fname)
                    cv2.imwrite(col_path, col_img_cv, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    
                    # Only add column crops to preview when multi-column is detected
                    if page_has_columns:
                        clean_pages_urls.append(f"http://127.0.0.1:8000/output/{quote(col_fname)}")
                    
                    # 4. Surya Regions in this column
                    # Convert pixel boundaries to Surya/Image coordinates (same here as it's the full page)
                    col_regions = []
                    for vr in visual_regions:
                        vbox = vr['bbox']
                        # Check if region center is within column boundaries
                        v_center_x = (vbox[0] + vbox[2]) / 2
                        if cx1 <= v_center_x <= cx2:
                            col_regions.append(vr)
                            
                    # 5. Extract PDF Words in this column
                    pdf_page = pdf.pages[i]
                    # Convert pixel boundaries back to PDF units for extraction
                    scale_to_pdf = pdf_page.width / cw
                    pcx1, pcx2 = cx1 * scale_to_pdf, cx2 * scale_to_pdf
                    
                    # Narrow extraction zone to this column
                    col_words = pdf_page.crop((max(0, pcx1 - 5), 0, min(pdf_page.width, pcx2 + 5), pdf_page.height)).extract_words(
                        x_tolerance=3, y_tolerance=3, keep_blank_chars=False, extra_attrs=['fontname', 'size']
                    )
                    
                    # Filter out words that fall within visual boxes
                    filtered_words = []
                    for w in col_words:
                        # wx1, wy1, wx2, wy2 in PDF units
                        # But Surya bboxes are in pixels, need to convert word to pixels or Surya to PDF
                        w_pixels = [w['x0'] / scale_to_pdf, w['top'] * scale_y, w['x1'] / scale_to_pdf, w['bottom'] * scale_y]
                        
                        is_inside_visual = False
                        for vr in col_regions:
                            v_bbox = vr['bbox']
                            # Check overlap in pixels
                            ov_x1 = max(w_pixels[0], v_bbox[0])
                            ov_y1 = max(w_pixels[1], v_bbox[1])
                            ov_x2 = min(w_pixels[2], v_bbox[2])
                            ov_y2 = min(w_pixels[3], v_bbox[3])
                            if ov_x2 > ov_x1 and ov_y2 > ov_y1:
                                ov_area = (ov_x2 - ov_x1) * (ov_y2 - ov_y1)
                                w_area = (w_pixels[2] - w_pixels[0]) * (w_pixels[3] - w_pixels[1])
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
                        if para.get('avg_size', 11) > 13 or para.get('is_bold'):
                            etype = "heading"
                        
                        element = {
                            "type": etype,
                            "text": text,
                            "bbox": para['bbox'],
                            "source_image_local": col_path,
                            "confidence": 1.0,
                            "_direct_read": True
                        }
                        item = self._normalize_element(element, lang, direct_translate, text_corrector_hl)
                        structured_data.append(item)
                    
                    # 6. Add Visual Crops for this column
                    for idx, vr in enumerate(col_regions):
                        vbox = vr['bbox']
                        rtype = vr['type']
                        
                        pad = 10
                        px1, py1 = max(0, int(vbox[0] - pad)), max(0, int(vbox[1] - pad))
                        px2, py2 = min(cw, int(vbox[2] + pad)), min(ch, int(vbox[3] + pad))
                        crop_visual = img_cv[py1:py2, px1:px2]
                        
                        if crop_visual.size > 0:
                            crop_fname = f"{filename}_p{i}_c{col_idx+1}_v{idx}_{rtype}.png"
                            crop_path = os.path.join(self.output_dir, crop_fname)
                            cv2.imwrite(crop_path, crop_visual)
                            
                            element = {
                                "type": rtype,
                                "text": f"[{rtype.upper()}]",
                                "bbox": vbox,
                                "crop_url": f"http://127.0.0.1:8000/output/{quote(crop_fname)}",
                                "crop_local": crop_path,
                                "source_image_local": col_path,
                                "confidence": 1.0
                            }
                            item = self._normalize_element(element, lang, direct_translate, text_corrector_hl)
                            structured_data.append(item)

        print(f"\n  ✅  Hybrid Direct Extraction Complete: {len(structured_data)} elements.")
        
        # ─── Global Classification Refinement (NEW) ───
        structured_data = await self.refine_classification(structured_data, lang)
        
        return structured_data, clean_pages_urls

    def extract_cover_info(self, clean_pages_urls, lang, text_context=None):
        """Extract product info from first page using AI (Visual or Text)."""
        if not clean_pages_urls and not text_context:
            return None, None
            
        if not clean_pages_urls:
            logger.warning("extract_cover_info: No clean_pages_urls provided")
            return None, None
            
        first_page_url = clean_pages_urls[0]
        # Resolve local path from URL
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
            
            _, buffer = cv2.imencode('.jpg', img_cv, [cv2.IMWRITE_JPEG_QUALITY, 80])
            img_b64 = base64.b64encode(buffer).decode('utf-8')
            
            lang_label = "Indonesia" if lang == 'id' else "English"
            prompt = f"""Look at this manual book cover page. Please extract:
1. "product_name": The main name of the medical device (usually big bold text).
2. "product_description": A VERY SHORT functional description (MAX 10 WORDS). Example: "Infusion Pump", "Standard Wheelchair". 

CRITICAL:
- IGNORE legal notices, FCC statements, user notifications, or long paragraphs. 
- If no short description is found, leave it EMPTY. 
- Respond in {lang_label}.
Return ONLY JSON: {{"product_name": "...", "product_description": "..."}}"""

            response = client.call(prompt, image_base64=img_b64, timeout=30)
            if response:
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    payload = json.loads(json_match.group())
                    return payload.get('product_name'), payload.get('product_description')
        except Exception as e:
            logger.warning(f"AI cover info extraction failed: {e}")
            
        return None, None

    async def refine_classification(self, structured_data, lang):
        """
        Global Refinement: Collect all headings and re-classify them as a sequence.
        This provides context that isolated classification lacks.
        """
        if not structured_data: return structured_data
        
        headings_idx = [i for i, item in enumerate(structured_data) if item['type'] in ('title', 'heading')]
        if not headings_idx: return structured_data
        
        logger.info(f"🧠 AI: Refining classification for {len(headings_idx)} headings...")
        
        # Build heading map for AI
        heading_list = []
        for idx in headings_idx:
            heading_list.append({
                "id": idx,
                "text": structured_data[idx]['normalized'][:150]
            })
            
        try:
            from openrouter_client import get_openrouter_client
            client = get_openrouter_client()
            if not client: return structured_data
            
            # Use current chapter titles for prompt
            chapters_summary = "\n".join([f"BAB {i}: {self.chapter_titles[f'BAB {i}']}" for i in range(1, 8)])
            
            prompt = f"""You are a medical document structure expert.
Classify these headings into the 7 standard chapters.

CHAPTERS:
{chapters_summary}

HEADINGS (in document order):
{json.dumps(heading_list, indent=2)}

GOAL:
- Assign each heading to a BAB (1-7).
- Content must follow a logical flow.
- If a heading is ambiguous, consider its position relative to others.
- Return ONLY a JSON object: {{"results": [{{"id": index, "bab": 1}}, ...]}}"""

            response = client.call(prompt, timeout=25)
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                refinement = json.loads(json_match.group())
                results = refinement.get("results", [])
                
                # Apply refined BABs to headings
                overrides = {r['id']: f"BAB {r['bab']}" for r in results}
                
                # Propagate refined BABs to following paragraphs
                # Start with the chapter of the first element
                current_bab = structured_data[0]['chapter_id']
                for i in range(len(structured_data)):
                    if i in overrides:
                        current_bab = overrides[i]
                    
                    # Update item
                    structured_data[i]['chapter_id'] = current_bab
                    # Sync Chapter/BAB naming based on language
                    structured_data[i]['chapter_id'] = self._remap_chapter(current_bab, lang)
                    structured_data[i]['chapter_title'] = self.chapter_titles.get(structured_data[i]['chapter_id'], "Unknown")

                logger.info(f"✅ Global Refinement Complete: Applied {len(results)} overrides.")
        except Exception as e:
            logger.warning(f"Global refinement failed: {e}")
            
        return structured_data
