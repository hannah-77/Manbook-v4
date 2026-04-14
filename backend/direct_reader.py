"""
DIRECT READER — Text-based PDF & DOCX Extraction (No OCR!)
============================================================

Handles documents that already contain embedded text:
  - DOCX → python-docx (100% accurate, preserves styles)
  - PDF  → pdfplumber  (100% accurate for text-based PDFs)

Falls back gracefully when the document is scanned/image-only.

Updated: March 2026
"""

import os
import re
import cv2
import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger("BioManual.DirectReader")


# ═══════════════════════════════════════════════════════════════
# 1. PDF TYPE DETECTION — is it text-based or scanned?
# ═══════════════════════════════════════════════════════════════

def is_text_pdf(pdf_path: str, sample_pages: int = 5) -> dict:
    """
    Detect whether a PDF contains real embedded text or is scanned (image-only).
    
    Returns:
        {
            "is_text_based": bool,
            "text_ratio": float,      # 0.0-1.0 — ratio of pages with text
            "avg_chars_per_page": int, # Average characters per page
            "total_pages": int,
            "sample_text": str,       # First ~500 chars for language detection
        }
    """
    try:
        import PyPDF2
        
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            total_pages = len(reader.pages)
            check_pages = min(total_pages, sample_pages)
            
            text_pages = 0
            total_chars = 0
            sample_text_parts = []
            
            for i in range(check_pages):
                try:
                    text = reader.pages[i].extract_text() or ""
                    text = text.strip()
                    chars = len(text)
                    total_chars += chars
                    
                    # A page is "text-based" if it has at least 50 chars
                    if chars > 50:
                        text_pages += 1
                    
                    if len(' '.join(sample_text_parts)) < 500:
                        sample_text_parts.append(text)
                except Exception:
                    pass
            
            text_ratio = text_pages / max(check_pages, 1)
            avg_chars = total_chars // max(check_pages, 1)
            
            result = {
                "is_text_based": text_ratio >= 0.5 and avg_chars >= 80,
                "text_ratio": round(text_ratio, 2),
                "avg_chars_per_page": avg_chars,
                "total_pages": total_pages,
                "sample_text": ' '.join(sample_text_parts)[:500],
            }
            
            logger.info(
                f"📄 PDF Type Detection: {'TEXT-BASED' if result['is_text_based'] else 'SCANNED'} "
                f"(ratio={result['text_ratio']}, avg_chars={result['avg_chars_per_page']}, "
                f"pages={total_pages})"
            )
            return result
    
    except Exception as e:
        logger.warning(f"PDF type detection failed: {e}")
        return {
            "is_text_based": False,
            "text_ratio": 0.0,
            "avg_chars_per_page": 0,
            "total_pages": 0,
            "sample_text": "",
        }


# ═══════════════════════════════════════════════════════════════
# 2. DOCX DIRECT READER — 100% accurate text extraction
# ═══════════════════════════════════════════════════════════════

def extract_docx_direct(docx_path: str, lang: str = 'id') -> list[dict]:
    """
    Extract content directly from DOCX using python-docx.
    
    Returns list of elements in the same format as vision_engine.scan_document():
    [
        {"type": "heading", "text": "...", "confidence": 1.0, "bbox": [...], ...},
        {"type": "paragraph", "text": "...", "confidence": 1.0, "bbox": [...], ...},
        {"type": "table", "text": "[TABLE]", "confidence": 1.0, "bbox": [...], 
         "table_data": [[...], ...], ...},
        {"type": "figure", "text": "[FIGURE]", "confidence": 1.0, "bbox": [...], ...},
    ]
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    
    doc = Document(docx_path)
    elements = []
    y_position = 0  # Simulated vertical position for ordering
    LINE_HEIGHT = 30  # Simulated line height in pixels
    
    logger.info(f"📝 DOCX Direct Reader: {len(doc.paragraphs)} paragraphs, {len(doc.tables)} tables")
    
    # ── Track which paragraphs are inside tables (to skip them) ──
    # python-docx iterates body elements in order, including tables
    table_set = set()
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    table_set.add(id(para))
    
    # ── Iterate body elements in document order ──
    # doc.element.body contains all elements (paragraphs + tables) in order
    for child in doc.element.body:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        
        if tag == 'p':
            # This is a paragraph element — find matching paragraph object
            para = None
            for p in doc.paragraphs:
                if p._element is child:
                    para = p
                    break
            
            if para is None or id(para) in table_set:
                continue
            
            text = para.text.strip()
            import re
            
            # Find inline shapes and extract their embedded relationship ID (rId)
            # This completely ignores <wp:anchor> which are floating decorations like header waves
            xml_str = para._element.xml
            inline_xmls = re.findall(r'<wp:inline.*?</wp:inline>', xml_str, re.DOTALL)
            
            rIds = []
            for ix in inline_xmls:
                match = re.search(r'r:embed="([^"]+)"', ix)
                if match:
                    rIds.append(match.group(1))
            
            # Determine type: heading vs paragraph
            style_name = (para.style.name or "").lower()
            elem_type = "paragraph"
            
            # Heading detection strategies:
            # 1. Word heading style (Heading 1, Heading 2, etc.)
            if 'heading' in style_name or 'title' in style_name:
                elem_type = "heading"
            # 2. All caps short text (common manual heading pattern)
            elif text.isupper() and len(text) < 80:
                elem_type = "heading"
            # 3. Bold text that is short (common heading pattern)
            elif len(text) < 80:
                runs = para.runs
                if runs and all(run.bold for run in runs if run.text.strip()):
                    elem_type = "heading"
            # 4. Large font size (relative to body text)
            if elem_type == "paragraph" and len(text) < 100:
                runs = para.runs
                if runs:
                    font_sizes = [run.font.size for run in runs if run.font.size]
                    if font_sizes:
                        max_size = max(font_sizes)
                        # Pt(14) = 177800 EMUs — typical heading threshold
                        if max_size and max_size >= 177800:
                            elem_type = "heading"
            
            # Prior to recording text, record any leading figures (optional: order isn't perfect, but appending them is fine)
            
            # Estimate bbox based on text length
            text_height = max(LINE_HEIGHT, (len(text) // 80 + 1) * LINE_HEIGHT)
            bbox = [50, y_position, 750, y_position + text_height]
            
            if text:
                elements.append({
                    "type": elem_type,
                    "text": text,
                    "confidence": 1.0,
                    "bbox": bbox,
                })
                y_position += text_height + 5
            
            # Add the mapped inline image elements found in this paragraph
            for rId in rIds:
                elements.append({
                    "type": "figure",
                    "text": "[FIGURE]",
                    "confidence": 1.0,
                    "bbox": [50, y_position, 750, y_position + 200],
                    "rId": rId  # Explicit mapping for exact image extraction
                })
                y_position += 200
        
        elif tag == 'tbl':
            # This is a table element — find matching table object
            table = None
            for t in doc.tables:
                if t._element is child:
                    table = t
                    break
            
            if table is None:
                continue
            
            # Extract table data as 2D array
            table_data = []
            table_text_parts = []
            for row in table.rows:
                row_data = []
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    row_data.append(cell_text)
                    if cell_text:
                        table_text_parts.append(cell_text)
                table_data.append(row_data)
            
            if not table_text_parts:
                continue
            
            # Create markdown representation of table
            table_md = _table_to_markdown(table_data)
            
            # Generate fake crop image for the UI preview
            crop_fname = f"{base_name}_table_{len(elements)}_preview_only.png"
            crop_path = os.path.join(output_dir, crop_fname)
            
            try:
                from PIL import Image, ImageDraw, ImageFont
                col_widths = []
                for c in range(len(table_data[0])):
                    max_w = max([len(str(row[c])) for row in table_data if c < len(row)] + [5])
                    col_widths.append(min(max_w * 7 + 20, 300))  # cap column width
                    
                row_height = 25
                img_w = min(sum(col_widths) + 20, 1500)
                img_h = min(len(table_data) * row_height + 20, 2000)
                
                img = Image.new('RGB', (img_w, img_h), color=(250, 250, 250))
                d = ImageDraw.Draw(img)
                y_c = 10
                for r_idx, row in enumerate(table_data):
                    x_c = 10
                    for c_idx, cell in enumerate(row):
                        if c_idx >= len(col_widths): break
                        w = col_widths[c_idx]
                        d.rectangle([x_c, y_c, x_c+w, y_c+row_height], outline=(200, 200, 200))
                        txt = str(cell).replace('\n', ' ')
                        max_chars = (w - 10) // 6
                        if len(txt) > max_chars: txt = txt[:max_chars-3] + "..."
                        color = (50,50,50) if r_idx > 0 else (0,0,120)
                        d.text((x_c+5, y_c+5), txt, fill=color)
                        x_c += w
                    y_c += row_height
                    if y_c > img_h - row_height: break
                    
                img.save(crop_path)
                from urllib.parse import quote
                crop_url = f"http://127.0.0.1:8000/output/{quote(crop_fname)}"
            except Exception as e:
                logger.warning(f"PIL table generation failed: {e}")
                crop_path = None
                crop_url = None
            
            table_height = max(100, len(table_data) * LINE_HEIGHT)
            elements.append({
                "type": "table",
                "text": table_md if table_md else "[TABLE]",
                "confidence": 1.0,
                "bbox": [50, y_position, 750, y_position + table_height],
                "table_data": table_data,
                "crop_local": crop_path,
                "crop_url": crop_url
            })
            y_position += table_height + 10
    
    # ── Extract embedded images ──
    # Check for images that are standalone (not already captured)
    _extract_docx_images(doc, docx_path, elements)
    
    # ── Merge consecutive elements of the same type ──
    merged_elements = []
    for el in elements:
        if not merged_elements:
            merged_elements.append(el)
            continue
        
        last_el = merged_elements[-1]
        
        # Merge if both are text elements of the same type (heading or paragraph)
        if last_el['type'] == el['type'] and el['type'] in ('heading', 'paragraph'):
            # Merge text with newline
            last_el['text'] = last_el['text'] + "\n" + el['text']
            
            # Combine bounding boxes (min x, min y, max x, max y)
            bb1 = last_el.get('bbox', [0, 0, 0, 0])
            bb2 = el.get('bbox', [0, 0, 0, 0])
            last_el['bbox'] = [
                min(bb1[0], bb2[0]),
                min(bb1[1], bb2[1]),
                max(bb1[2], bb2[2]),
                max(bb1[3], bb2[3])
            ]
        else:
            merged_elements.append(el)
            
    elements = merged_elements
    
    logger.info(
        f"✅ DOCX Direct Reader: {len(elements)} elements "
        f"({sum(1 for e in elements if e['type'] == 'heading')} headings, "
        f"{sum(1 for e in elements if e['type'] == 'paragraph')} paragraphs, "
        f"{sum(1 for e in elements if e['type'] == 'table')} tables, "
        f"{sum(1 for e in elements if e['type'] == 'figure')} figures)"
    )
    
    return elements


def _table_to_markdown(table_data: list[list[str]]) -> str:
    """Convert 2D table data to markdown table string."""
    if not table_data or not table_data[0]:
        return ""
    
    # Header row
    header = table_data[0]
    md = "| " + " | ".join(h or " " for h in header) + " |\n"
    md += "| " + " | ".join("---" for _ in header) + " |\n"
    
    # Data rows
    for row in table_data[1:]:
        # Pad row to match header length
        padded = row + [""] * (len(header) - len(row))
        md += "| " + " | ".join(c or " " for c in padded[:len(header)]) + " |\n"
    
    return md.strip()


def _extract_docx_images(doc, docx_path: str, elements: list):
    """
    Extract embedded images from DOCX and save them to output_results/.
    Only extracts images related to the main document body (`document.xml`),
    automatically filtering out headers, footers, and page backgrounds.
    Updates figure elements with crop_url and crop_local paths.
    """
    try:
        from PIL import Image
        import io
        
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(backend_dir, "output_results")
        os.makedirs(output_dir, exist_ok=True)
        
        base_name = os.path.splitext(os.path.basename(docx_path))[0]
        
        img_idx = 0
        figure_elements = [e for e in elements if e['type'] == 'figure']
        
        # Iterate over only elements related to the main document body!
        # This completely skips header1.xml, footer1.xml and background images
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                image_part = rel.target_part
                ext = image_part.content_type.split('/')[-1].lower()
                
                # Skip invalid extensions
                if ext not in ('png', 'jpg', 'jpeg', 'bmp', 'gif', 'tiff'):
                    continue
                
                try:
                    img_data = image_part.blob
                    
                    # Save to output_results
                    crop_fname = f"{base_name}_direct_img_{img_idx}.{ext}"
                    crop_path = os.path.join(output_dir, crop_fname)
                    
                    with open(crop_path, 'wb') as f:
                        f.write(img_data)
                    
                    from urllib.parse import quote
                    crop_url = f"http://127.0.0.1:8000/output/{quote(crop_fname)}"
                    
                    # Match with figure elements
                    if img_idx < len(figure_elements):
                        figure_elements[img_idx]['crop_url'] = crop_url
                        figure_elements[img_idx]['crop_local'] = crop_path
                    
                    img_idx += 1
                except Exception as e:
                    logger.warning(f"Failed to extract body image {image_part.partname}: {e}")
                    
        logger.info(f"📸 Extracted {img_idx} body images from DOCX (Headers/Footers skipped)")
    
    except Exception as e:
        logger.warning(f"DOCX image extraction error: {e}")


# ═══════════════════════════════════════════════════════════════
# 3. PDF DIRECT READER — text extraction via pdfplumber
# ═══════════════════════════════════════════════════════════════

def extract_pdf_direct(pdf_path: str, lang: str = 'id') -> dict:
    """
    Extract content directly from a text-based PDF using pdfplumber.
    
    Returns dict per page:
    {
        "pages": [
            {
                "page_num": int,
                "elements": [...],     # Same format as vision_engine elements
                "page_image_path": str # Path to page image (for preview & figure crops)
            }
        ]
    }
    """
    import pdfplumber
    
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(backend_dir, "output_results")
    os.makedirs(output_dir, exist_ok=True)
    
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    
    pages_result = []
    
    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        logger.info(f"📄 PDF Direct Reader: {total_pages} pages")
        
        for page_idx, page in enumerate(pdf.pages):
            # ── Column Detection (Visual) ──
            # Render page to detect gaps visually (more reliable for manuals)
            # This allows us to handle 2, 3, or even 4 column layouts without interleaving text.
            col_boundaries = [0, page.width]
            try:
                # Render low-res for speed
                render = page.to_image(resolution=72)
                img_cv = cv2.cvtColor(np.array(render.original), cv2.COLOR_RGB2BGR)
                h_cv, w_cv = img_cv.shape[:2]
                
                # Grayscale + Threshold
                gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
                _, binary = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
                
                # Vertical projection (percentage of white pixels)
                margin_y = int(h_cv * 0.1) # Ignore header/footer for column detection
                roi = binary[margin_y:h_cv-margin_y, :]
                white_ratio = np.mean(roi == 255, axis=0) # shape (w_cv,)
                
                # Smooth
                kernel = np.ones(max(3, w_cv // 80)) / max(3, w_cv // 80)
                white_smooth = np.convolve(white_ratio, kernel, mode='same')
                
                # Identify gaps (> 95% white)
                is_gap = white_smooth > 0.95
                min_gap_w = max(5, int(w_cv * 0.012))
                
                gaps = []
                in_gap = False
                gs = 0
                for x in range(w_cv):
                    if is_gap[x] and not in_gap:
                        gs = x
                        in_gap = True
                    elif not is_gap[x] and in_gap:
                        gw = x - gs
                        if gw >= min_gap_w:
                            gc = gs + gw // 2
                            # Ignore edges (10% margin)
                            if w_cv * 0.1 < gc < w_cv * 0.9:
                                gaps.append(gc * (page.width / w_cv))
                        in_gap = False
                
                if gaps:
                    col_boundaries = sorted([0] + gaps + [page.width])
                    logger.info(f"📊 Page {page_idx+1}: detected {len(col_boundaries)-1} columns")
            except Exception as e:
                logger.warning(f"Visual column detection failed for page {page_idx+1}: {e}")

            # ── Extract text & elements for EACH column ────────────
            for col_idx in range(len(col_boundaries) - 1):
                cx1, cx2 = col_boundaries[col_idx], col_boundaries[col_idx+1]
                
                # Buffer for overlap
                pad = 2
                crop_bbox = (max(0, cx1 - pad), 0, min(page.width, cx2 + pad), page.height)
                col_page = page.crop(crop_bbox)
                
                col_elements = []
                
                # 1. Extract words in THIS column
                raw_words = col_page.extract_words(
                    x_tolerance=3, y_tolerance=3, keep_blank_chars=False,
                    extra_attrs=['fontname', 'size']
                )
                
                # Filter margins
                header_margin = min(60, page.height * 0.08)
                footer_margin = max(page.height - 60, page.height * 0.92)
                words = [w for w in raw_words if header_margin < ((w['top']+w['bottom'])/2) < footer_margin]
                
                if words:
                    # Group words into lines (per column)
                    lines = _group_words_into_lines(words, page.height)
                    
                    # Merge lines into paragraphs
                    paragraphs = _merge_lines_into_paragraphs(lines, page.width, page.height)
                    
                    # Detect headings
                    avg_fs = np.mean([p['avg_size'] for p in paragraphs if p.get('avg_size')]) if paragraphs else 11
                    for para in paragraphs:
                        text = para['text'].strip()
                        if not text: continue
                        
                        etype = "paragraph"
                        fs = para.get('avg_size', avg_fs)
                        if fs > avg_fs * 1.2 and len(text) < 100: etype = "heading"
                        elif text.isupper() and len(text) < 80: etype = "heading"
                        elif para.get('is_bold') and len(text) < 80: etype = "heading"
                        
                        col_elements.append({
                            "type": etype,
                            "text": text,
                            "confidence": 1.0,
                            "bbox": para['bbox'], # Relative to page
                        })

                # 2. Extract tables in THIS column
                # Use a tighter strategy to avoid capturing partial tables from other columns
                tables = col_page.extract_tables({
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                })
                table_finder = col_page.find_tables({
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                })
                
                if tables:
                    for t_idx, table_data in enumerate(tables):
                        if not table_data or not any(any(c for c in r if c) for r in table_data): continue
                        
                        clean_table = [[(c or "").strip() for c in r] for r in table_data]
                        table_md = _table_to_markdown(clean_table)
                        
                        if t_idx < len(table_finder):
                            tb = table_finder[t_idx].bbox
                            # Important: convert back to full-page coordinates
                            # col_page is already cropped, so x-coords are local.
                            # But pdfplumber crop() maintains coordinates relative to original page usually, 
                            # however let's be safe.
                            bbox = [int(tb[0]), int(tb[1]), int(tb[2]), int(tb[3])]
                        else:
                            bbox = [int(cx1), 0, int(cx2), 100]
                        
                        # Filter overlap
                        col_elements = [e for e in col_elements if not _bbox_overlap(e['bbox'], bbox, threshold=0.5)]
                        col_elements.append({
                            "type": "table",
                            "text": table_md or "[TABLE]",
                            "confidence": 1.0,
                            "bbox": bbox,
                            "table_data": clean_table,
                        })

                # 3. Extract images in THIS column
                if hasattr(page, 'images') and page.images:
                    for img in page.images:
                        # Only check x center
                        ix0, ix1 = img.get('x0', 0), img.get('x1', 0)
                        ic = (ix0 + ix1) / 2
                        if cx1 < ic < cx2:
                            iw, ih = ix1 - ix0, img.get('bottom', 0) - img.get('top', 0)
                            if iw > 50 and ih > 50:
                                col_elements.append({
                                    "type": "figure", "text": "[FIGURE]",
                                    "confidence": 1.0,
                                    "bbox": [int(ix0), int(img.get('top',0)), int(ix1), int(img.get('bottom',0))]
                                })

                if col_elements:
                    col_elements.sort(key=lambda e: (e['bbox'][1], e['bbox'][0]))
                    # Add to results as a separate "page" if multi-column
                    pages_result.append({
                        "page_num": page_idx,
                        "column_num": col_idx + 1,
                        "total_columns": len(col_boundaries) - 1,
                        "elements": col_elements,
                        "column_bbox": [int(cx1), 0, int(cx2), int(page.height)]
                    })
            
            # ── Extract tables ──
            tables = page.extract_tables({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
            })
            
            if tables:
                # Also get table bounding boxes
                table_finder = page.find_tables({
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                })
                
                for t_idx, table_data in enumerate(tables):
                    if not table_data or not any(any(cell for cell in row if cell) for row in table_data):
                        continue
                    
                    # Clean table data
                    clean_table = []
                    for row in table_data:
                        clean_row = [(cell or "").strip() for cell in row]
                        clean_table.append(clean_row)
                    
                    table_md = _table_to_markdown(clean_table)
                    
                    # Get table bbox
                    if t_idx < len(table_finder):
                        tb = table_finder[t_idx].bbox
                        bbox = [int(tb[0]), int(tb[1]), int(tb[2]), int(tb[3])]
                    else:
                        bbox = [0, 0, int(page.width), 100]
                    
                    # Remove paragraph elements that overlap with this table
                    elements = [
                        e for e in elements
                        if not _bbox_overlap(e['bbox'], bbox, threshold=0.5)
                    ]
                    
                    elements.append({
                        "type": "table",
                        "text": table_md if table_md else "[TABLE]",
                        "confidence": 1.0,
                        "bbox": bbox,
                        "table_data": clean_table,
                    })
            
            # ── Extract images ──
            if hasattr(page, 'images') and page.images:
                for img_info in page.images:
                    img_bbox = [
                        int(img_info.get('x0', 0)),
                        int(img_info.get('top', 0)),
                        int(img_info.get('x1', 100)),
                        int(img_info.get('bottom', 100)),
                    ]
                    # Only add if above a minimum size
                    img_w = img_bbox[2] - img_bbox[0]
                    img_h = img_bbox[3] - img_bbox[1]
                    if img_w > 50 and img_h > 50:
                        elements.append({
                            "type": "figure",
                            "text": "[FIGURE]",
                            "confidence": 1.0,
                            "bbox": img_bbox,
                        })
            
            # Sort elements by vertical position (reading order)
            elements.sort(key=lambda e: (e['bbox'][1], e['bbox'][0]))
            
            pages_result.append({
                "page_num": page_idx,
                "elements": elements,
                "is_empty": len(elements) == 0,
            })
    
    logger.info(
        f"✅ PDF Direct Reader: {len(pages_result)} pages, "
        f"{sum(len(p['elements']) for p in pages_result)} total elements"
    )
    
    return {"pages": pages_result}


def _group_words_into_lines(words: list, page_height: float) -> list:
    """Group words into lines based on Y position proximity."""
    if not words:
        return []
    
    # Sort by Y then X
    sorted_words = sorted(words, key=lambda w: (round(w['top'], 1), w['x0']))
    
    lines = []
    current_line = {
        'words': [sorted_words[0]],
        'top': sorted_words[0]['top'],
        'bottom': sorted_words[0]['bottom'],
    }
    
    for word in sorted_words[1:]:
        # Same line if Y is close (within 3 units)
        if abs(word['top'] - current_line['top']) < 3:
            current_line['words'].append(word)
            current_line['bottom'] = max(current_line['bottom'], word['bottom'])
        else:
            lines.append(current_line)
            current_line = {
                'words': [word],
                'top': word['top'],
                'bottom': word['bottom'],
            }
    
    lines.append(current_line)
    return lines


def _merge_lines_into_paragraphs(lines: list, page_width: float, page_height: float) -> list:
    """Merge adjacent lines into paragraphs based on spacing and indentation."""
    if not lines:
        return []
    
    paragraphs = []
    
    current_para = {
        'lines': [lines[0]],
        'text_parts': [' '.join(w['text'] for w in lines[0]['words'])],
        'top': lines[0]['top'],
        'bottom': lines[0]['bottom'],
        'sizes': [w.get('size', 11) for w in lines[0]['words'] if w.get('size')],
        'fonts': [w.get('fontname', '') for w in lines[0]['words'] if w.get('fontname')],
    }
    
    for line in lines[1:]:
        line_text = ' '.join(w['text'] for w in line['words'])
        line_top = line['top']
        prev_bottom = current_para['bottom']
        
        # Gap between this line and previous paragraph bottom
        gap = line_top - prev_bottom
        
        # Average line height in current paragraph
        avg_line_h = (current_para['bottom'] - current_para['top']) / max(len(current_para['lines']), 1)
        if avg_line_h < 5:
            avg_line_h = 12  # Default
        
        # Merge if gap is small (< 1.5x line height = same paragraph)
        if gap < avg_line_h * 1.5 and gap >= -2:
            current_para['lines'].append(line)
            current_para['text_parts'].append(line_text)
            current_para['bottom'] = line['bottom']
            current_para['sizes'].extend(w.get('size', 11) for w in line['words'] if w.get('size'))
            current_para['fonts'].extend(w.get('fontname', '') for w in line['words'] if w.get('fontname'))
        else:
            # Finalize current paragraph
            _finalize_paragraph(current_para, paragraphs, page_width)
            
            current_para = {
                'lines': [line],
                'text_parts': [line_text],
                'top': line['top'],
                'bottom': line['bottom'],
                'sizes': [w.get('size', 11) for w in line['words'] if w.get('size')],
                'fonts': [w.get('fontname', '') for w in line['words'] if w.get('fontname')],
            }
    
    # Finalize last paragraph
    _finalize_paragraph(current_para, paragraphs, page_width)
    
    return paragraphs


def _finalize_paragraph(para_data: dict, paragraphs: list, page_width: float):
    """Finalize a paragraph data structure."""
    text = ' '.join(para_data['text_parts']).strip()
    if not text:
        return
    
    # Calculate bounding box
    all_words = []
    for line in para_data['lines']:
        all_words.extend(line['words'])
    
    if not all_words:
        return
    
    x0 = min(w['x0'] for w in all_words)
    x1 = max(w['x1'] for w in all_words)
    
    bbox = [int(x0), int(para_data['top']), int(x1), int(para_data['bottom'])]
    
    avg_size = np.mean(para_data['sizes']) if para_data['sizes'] else 11
    
    # Detect if bold font (heuristic: font name contains "Bold")
    is_bold = any('bold' in f.lower() for f in para_data['fonts'] if f)
    
    paragraphs.append({
        'text': text,
        'bbox': bbox,
        'avg_size': float(avg_size),
        'is_bold': is_bold,
    })


def _bbox_overlap(bbox1, bbox2, threshold=0.5) -> bool:
    """Check if two bboxes overlap significantly."""
    x1 = max(bbox1[0], bbox2[0])
    y1 = max(bbox1[1], bbox2[1])
    x2 = min(bbox1[2], bbox2[2])
    y2 = min(bbox1[3], bbox2[3])
    
    if x2 <= x1 or y2 <= y1:
        return False
    
    overlap_area = (x2 - x1) * (y2 - y1)
    area1 = max((bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1]), 1)
    
    return overlap_area / area1 > threshold
