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

def convert_pdf_to_images_safe(path, dpi=300):
    from pdf2image import convert_from_path
    poppler = os.environ.get('POPPLER_PATH')
    if not poppler:
         for p in [r"C:\poppler\Library\bin", r"C:\poppler\bin"]:
             if os.path.exists(p):
                 poppler = p
                 break
    try:
        return convert_from_path(path, dpi=dpi, poppler_path=poppler)
    except Exception:
        return convert_from_path(path, dpi=dpi)

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
        
    # --- OPTIONAL: Enhance before column splitting ---
    # img = remove_watermarks_and_enhance(img)
    
    h, w = img.shape[:2]
    
    # Minimum width for multi-column detection (small documents are usually 1 column)
    if w < 800:
        return [image_path]
    
    # Convert to grayscale and binarize
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    
    # Vertical projection: calculate white pixel ratio per column-x
    # Ignore top 10% and bottom 10% (header/footer are usually full-width)
    margin_y = int(h * 0.10)
    roi = binary[margin_y:h - margin_y, :]
    
    # Calculate % white pixels per x-column
    white_ratio = np.mean(roi == 255, axis=0)  # array shape (w,)
    
    # Smooth with moving average to remove noise
    kernel_size = max(10, w // 80)
    kernel = np.ones(kernel_size) / kernel_size
    white_smooth = np.convolve(white_ratio, kernel, mode='same')
    
    # Region that is "almost all white" (> 90%) → column gap
    gap_threshold = 0.90
    is_gap = white_smooth > gap_threshold
    
    # Minimum gap width (set to a more conservative 3.5% of page width)
    # Real column gutters in manuals are usually quite wide.
    min_gap_width = max(40, int(w * 0.035))
    
    # Skip column splitting for the first page (Cover Page) if it looks like a cover
    is_cover = "_0.png" in image_path.lower() or image_path.endswith("_0.jpg")
    if is_cover:
        # For cover pages, use an even stricter gap requirement (5%)
        min_gap_width_current = int(w * 0.05) 
        gap_threshold_current = 0.98  # Very white
        is_gap_current = white_smooth > gap_threshold_current
    else:
        is_gap_current = is_gap
        min_gap_width_current = min_gap_width
 
    # Find contiguous gap segments
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
                # Ignore gaps too close to edges (within 15% of page width)
                if gap_center > w * 0.15 and gap_center < w * 0.85:
                    gaps.append(gap_center)
            in_gap = False
    
    if not gaps:
        return [image_path]
    
    # Filter gaps that are too close to each other (less than 20% of width)
    # Each column should be at least 20% of the page width
    filtered_gaps = []
    if gaps:
        gaps.sort()
        filtered_gaps.append(gaps[0])
        for g in gaps[1:]:
            if g - filtered_gaps[-1] > w * 0.20:
                filtered_gaps.append(g)
    
    gaps = filtered_gaps
    
    # Build column boundaries
    col_boundaries = [0] + sorted(gaps) + [w]
    num_cols = len(col_boundaries) - 1
    
    # Skip splitting if columns are too unbalanced or narrow
    if num_cols > 1:
        valid_cols = []
        for i in range(num_cols):
            cw = col_boundaries[i+1] - col_boundaries[i]
            if cw > w * 0.20: # Column must be at least 20% of page
                valid_cols.append(i)
        
        if len(valid_cols) < 2:
            logger.info("📊 Column split: candidates found but too narrow/unbalanced, defaulting to single column")
            return [image_path]
 
    # Sanity: max 3 columns (manual books rarely have 4 real text columns)
    if num_cols > 3:
        logger.warning(f"Too many columns detected ({num_cols}) — likely noise, capping at 3")
        gaps = gaps[:2]
        col_boundaries = [0] + sorted(gaps) + [w]
        num_cols = len(col_boundaries) - 1
    
    logger.info(f"📊 Column split: detected {num_cols} columns")
    
    # Crop each column
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
