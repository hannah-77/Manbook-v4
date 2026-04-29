import os
import cv2
import numpy as np
import logging
import uuid
import shutil
import re
from pathlib import Path

logger = logging.getLogger("BioManual")

_WATERMARK_PATTERNS = [
    r'(?i)draft', r'(?i)confidential', r'(?i)strictly confidential',
    r'(?i)internal use', r'(?i)preview', r'(?i)watermark', 
    r'(?i)sample', r'(?i)copy', r'(?i)not for distribution'
]

def _is_watermark(text: str) -> bool:
    """Check if the text matches common watermark patterns."""
    if not text: return False
    clean = text.strip()
    if len(clean) < 3 or len(clean) > 30: return False
    for p in _WATERMARK_PATTERNS:
        if re.search(p, clean):
            return True
    return False

def convert_pdf_to_images_safe(path, dpi=300, max_pages=None):
    from pdf2image import convert_from_path
    poppler = os.environ.get('POPPLER_PATH')
    if not poppler:
         for p in [r"C:\poppler\Library\bin", r"C:\poppler\bin"]:
             if os.path.exists(p):
                 poppler = p
                 break
    
    # pdf2image uses first_page and last_page (1-indexed)
    params = {'dpi': dpi, 'poppler_path': poppler}
    if max_pages:
        params['last_page'] = max_pages

    try:
        return convert_from_path(path, **params)
    except Exception:
        if 'poppler_path' in params: del params['poppler_path']
        return convert_from_path(path, **params)

def remove_watermarks_and_enhance(image_cv):
    """
    Remove light-colored background watermarks and enhance contrast for better OCR.
    Uses 'bleaching' technique for gray/light-colored text.
    """
    if image_cv is None: return None
    
    # 1. Convert to grayscale
    gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
    
    # 2. Bleaching: Watermarks are often intermediate gray.
    # We use a high threshold to push everything light to white.
    # Typical watermark gray is around 180-230.
    _, bleached = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
    
    # 3. Use the bleached mask to clean the original image (make background pure white)
    # This keeps dark text but removes light watermarks.
    enhanced = cv2.cvtColor(bleached, cv2.COLOR_GRAY2BGR)
    
    # 4. Sharpen for OCR
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    enhanced = cv2.filter2D(enhanced, -1, kernel)
    
    return enhanced

def split_columns_simple(image_path, filename_base, output_dir):
    """
    Detect and crop columns in a document page using whitespace analysis.
    
    Returns: list of image paths (1 per column). If single-column → [original_path]
    """
    img = cv2.imread(image_path)
    if img is None:
        return [image_path]
        
    h, w = img.shape[:2]
    
    # Minimum width for multi-column detection (small documents are usually 1 column)
    if w < 800:
        return [image_path]
    
    # Convert to grayscale and binarize
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    
    # Vertical projection: calculate white pixel ratio per column-x
    # Ignore top 8% and bottom 8% (header/footer are usually full-width)
    margin_y = int(h * 0.08)
    roi = binary[margin_y:h - margin_y, :]
    
    # Calculate % white pixels per x-column
    white_ratio = np.mean(roi == 255, axis=0)  # array shape (w,)
    
    # Robust smoothing — proportional to image width
    # Use 1% of width for strong noise reduction (e.g. 35px for 3508px wide A4 @ 300dpi)
    k_size = max(7, int(w * 0.01))
    kernel = np.ones(k_size) / k_size
    white_smooth = np.convolve(white_ratio, kernel, mode='same')
    
    # Skip column splitting for the first page (Cover Page) if it looks like a cover
    # Only match actual page-0 naming patterns from OCR pipeline (page_xxx_0.png)
    # NOT DOCX preview files (DOCX_FULL_xxx_0.jpg, DOCX_xxx_0.jpg)
    basename = os.path.basename(image_path).lower()
    is_docx_preview = basename.startswith("docx_")
    is_cover = (not is_docx_preview) and (
        "_0.png" in basename or 
        basename.endswith("_0.jpg") or 
        "cover" in basename
    )
    if is_cover:
        # For cover pages, use an even stricter gap requirement (5%)
        min_gap_width_current = int(w * 0.05) 
        gap_threshold_current = 0.98  # Very white
        is_gap_current = white_smooth > gap_threshold_current
        
        # Find contiguous gap segments (cover page only)
        gaps = []
        in_gap = False
        gap_start = 0
        for x in range(w):
            if is_gap_current[x] and not in_gap:
                gap_start = x
                in_gap = True
            elif not is_gap_current[x] and in_gap:
                gap_width = x - gap_start
                if gap_width >= min_gap_width_current:
                    gap_center = gap_start + gap_width // 2
                    if gap_center > w * 0.05 and gap_center < w * 0.95:
                        gaps.append(gap_center)
                in_gap = False
    else:
        # ── Multi-pass gap detection: strict → lenient ──
        # Real column gutters are consistently white (>95%) through the full page height.
        # False positives from margins, indented text, etc only appear at lower thresholds.
        # Start strict and work down — first valid result wins.
        gaps = []
        pass_configs = [
            # (threshold, min_gap_width_pct, description)
            (0.95, 0.02, "strict"),    # Real column gutters: >95% white, >2% page width
            (0.90, 0.015, "medium"),   # Slightly less strict
            (0.85, 0.012, "lenient"),  # More tolerant
        ]
        
        for pass_thresh, pass_min_pct, pass_desc in pass_configs:
            is_gap_pass = white_smooth > pass_thresh
            min_gap_w = max(10, int(w * pass_min_pct))
            
            pass_gaps = []
            in_gap = False
            gap_start = 0
            for x in range(w):
                if is_gap_pass[x] and not in_gap:
                    gap_start = x
                    in_gap = True
                elif not is_gap_pass[x] and in_gap:
                    gap_width = x - gap_start
                    if gap_width >= min_gap_w:
                        gap_center = gap_start + gap_width // 2
                        if gap_center > w * 0.05 and gap_center < w * 0.95:
                            pass_gaps.append(gap_center)
                    in_gap = False
            
            if pass_gaps:
                # Filter close gaps
                pass_gaps.sort()
                filtered = [pass_gaps[0]]
                for g in pass_gaps[1:]:
                    if g - filtered[-1] > w * 0.15:
                        filtered.append(g)
                
                num_found = len(filtered) + 1
                if 2 <= num_found <= 4:
                    gaps = filtered
                    logger.info(f"   Column detection pass '{pass_desc}' (thresh={pass_thresh}, minW={min_gap_w}px): found {num_found} cols, gaps at {gaps}")
                    break  # Use first valid result
    
    if not gaps:
        return [image_path]
    
    # Filter gaps that are too close to each other (less than 15% of width)
    # Each column should be at least 15% of the page width
    filtered_gaps = []
    if gaps:
        gaps.sort()
        filtered_gaps.append(gaps[0])
        for g in gaps[1:]:
            if g - filtered_gaps[-1] > w * 0.15:
                filtered_gaps.append(g)
    
    gaps = filtered_gaps
    
    # Build column boundaries
    col_boundaries = [0] + sorted(gaps) + [w]
    num_cols = len(col_boundaries) - 1
    
    # Skip splitting if columns are too unbalanced or narrow
    if num_cols > 1:
        col_widths = []
        valid_cols = []
        for i in range(num_cols):
            cw = col_boundaries[i+1] - col_boundaries[i]
            col_widths.append(cw)
            if cw > w * 0.10:  # Column must be at least 10% of page
                valid_cols.append(i)
        
        if len(valid_cols) < 2:
            logger.info("Column split: candidates found but too narrow/unbalanced, defaulting to single column")
            return [image_path]
        
        # Balance check: widest valid column shouldn't be >3x the narrowest valid
        valid_widths = [col_widths[i] for i in valid_cols]
        if max(valid_widths) > 3 * min(valid_widths):
            logger.info(f"Column split: unbalanced widths {[int(cw) for cw in col_widths]}, defaulting to single column")
            return [image_path]
 
    # Sanity: max 4 columns (manual books can have 4 columns)
    if num_cols > 4:
        logger.warning(f"Too many columns detected ({num_cols}), capping at 4")
        gaps = gaps[:3]
        col_boundaries = [0] + sorted(gaps) + [w]
        num_cols = len(col_boundaries) - 1
    
    logger.info(f"Column split: detected {num_cols} columns (w={w}, h={h}, gaps={gaps})")
    
    # Crop each column and save as high-quality PNG for OCR
    column_paths = []
    for col_idx in range(num_cols):
        col_x1 = int(col_boundaries[col_idx])
        col_x2 = int(col_boundaries[col_idx + 1])
        
        # Small padding
        pad = max(5, int(w * 0.005))
        col_x1 = max(0, col_x1 - pad)
        col_x2 = min(w, col_x2 + pad)
        
        col_img = img[0:h, col_x1:col_x2]
        col_fname = f"COL_{filename_base}_c{col_idx + 1}.png"
        col_path = os.path.join(output_dir, col_fname)
        cv2.imwrite(col_path, col_img)
        column_paths.append(col_path)
    
    if len(column_paths) <= 1:
        return [image_path]
    
    return column_paths
