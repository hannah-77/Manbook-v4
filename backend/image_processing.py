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
    """
    Convert PDF to a list of PIL Images using PyMuPDF (fitz).
    This is much more reliable than pdf2image (poppler) and handles DRM
    and complex vectors better without generating blank pages.
    """
    import fitz
    from PIL import Image as PILImage
    import gc
    
    # Calculate scale factor for requested DPI (72 dpi is the default)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    
    all_images = []
    
    try:
        doc = fitz.open(path)
        total_pages = len(doc)
        
        if max_pages and total_pages > max_pages:
            total_pages = max_pages
            
        logger.info(f"📄 PDF→Images: processing {total_pages} pages at {dpi} DPI using PyMuPDF")
        
        for i in range(total_pages):
            page = doc[i]
            # Render page to a pixmap
            pix = page.get_pixmap(matrix=mat, alpha=False)
            
            # Convert fitz pixmap to PIL Image
            if pix.colorspace and pix.colorspace.n == 4:
                # CMYK to RGB
                mode = "CMYK"
            elif pix.alpha:
                mode = "RGBA"
            else:
                mode = "RGB"
                
            img = PILImage.frombytes(mode, [pix.width, pix.height], pix.samples)
            
            # Ensure it's always RGB for OCR/OpenCV
            if img.mode != "RGB":
                img = img.convert("RGB")
                
            all_images.append(img)
            
            # Free memory periodically
            if i % 10 == 0:
                gc.collect()
                
        doc.close()
        return all_images
        
    except Exception as e:
        logger.error(f"❌ Failed to convert PDF to images via PyMuPDF: {e}")
        # Return empty list or raise
        return []

def remove_watermarks_and_enhance(image_cv):
    """
    Remove colored watermarks (red/pink/light text overlays) WITHOUT destroying
    the actual document content.
    
    Strategy:
      - Use HSV color masking to isolate only colored watermark pixels
        (red, pink, orange, light-colored diagonal text)
      - Replace those pixels with white
      - If no watermark pixels found, return None (skip enhancement)
      
    IMPORTANT: This function must NEVER bleach the entire page.
    The old threshold(220) approach was catastrophic — it turned every page blank.
    """
    if image_cv is None: return None
    
    try:
        h, w = image_cv.shape[:2]
        total_pixels = h * w
        
        # Convert to HSV for color-based watermark detection
        hsv = cv2.cvtColor(image_cv, cv2.COLOR_BGR2HSV)
        
        # Target: Red/Pink watermarks (common in medical device manuals)
        mask_red1 = cv2.inRange(hsv, np.array([0,   40, 150]), np.array([10,  255, 255]))
        mask_red2 = cv2.inRange(hsv, np.array([160, 40, 150]), np.array([180, 255, 255]))
        # Target: Orange/Yellow watermarks
        mask_orange = cv2.inRange(hsv, np.array([10,  50, 150]), np.array([25,  255, 255]))
        # Target: Light gray watermarks (very light, NOT normal text)
        # Normal text is dark (value < 150), watermarks are light (value > 200)
        gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
        # Light gray pixels that are NOT white background (180-220 range = typical watermark gray)
        mask_light_gray = cv2.inRange(gray, 180, 225)
        
        # Combine color masks (not gray — gray mask is too risky)
        watermark_mask = mask_red1 | mask_red2 | mask_orange
        
        # Dilate slightly to cover watermark edges
        kernel = np.ones((3, 3), np.uint8)
        watermark_mask = cv2.dilate(watermark_mask, kernel, iterations=1)
        
        # Safety: Only apply if watermark covers < 15% of page
        # (real watermarks are sparse; if it's more, we're probably catching content)
        watermark_ratio = cv2.countNonZero(watermark_mask) / total_pixels
        
        if watermark_ratio < 0.001:
            # No significant watermark detected — skip enhancement entirely
            return None
        
        if watermark_ratio > 0.15:
            # Too much detected — probably catching actual content, abort
            logger.info(f"Watermark removal: {watermark_ratio:.1%} of pixels matched — too much, skipping")
            return None
        
        logger.info(f"Watermark removal: cleaning {watermark_ratio:.1%} of pixels (colored watermark)")
        
        # Replace watermark pixels with white
        enhanced = image_cv.copy()
        enhanced[watermark_mask > 0] = (255, 255, 255)
        
        return enhanced
        
    except Exception as e:
        logger.warning(f"Watermark removal failed: {e}")
        return None

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
    # Ignore top 12% and bottom 12% (header/footer and spanning titles usually live here)
    margin_y = int(h * 0.12)
    roi = binary[margin_y:h - margin_y, :]
    
    # Calculate % white pixels per x-column in the ROI
    white_ratio = np.mean(roi == 255, axis=0)  # array shape (w,)
    
    # Robust smoothing — use 1% of width for strong noise reduction
    k_size = max(7, int(w * 0.01))
    kernel = np.ones(k_size) / k_size
    white_smooth = np.convolve(white_ratio, kernel, mode='same')
    
    basename = os.path.basename(image_path).lower()
    is_docx_preview = basename.startswith("docx_")
    is_cover = (not is_docx_preview) and (
        "_0.png" in basename or 
        basename.endswith("_0.jpg") or 
        "cover" in basename
    )
    
    if is_cover:
        # Cover pages: stricter gap requirement
        min_gap_width = int(w * 0.05) 
        gap_threshold = 0.98
    else:
        # Standard pages: 90% white threshold, 2.0% minimum gap width
        min_gap_width = max(15, int(w * 0.02))
        gap_threshold = 0.90
        
    is_gap = white_smooth > gap_threshold
    
    gaps = []
    in_gap = False
    gap_start = 0
    # Max gap width: real column gutters are narrow (30-200px). Margins/tables are much wider.
    max_gap_w = max(200, int(w * 0.12))
    
    for x in range(w):
        if is_gap[x] and not in_gap:
            gap_start = x
            in_gap = True
        elif not is_gap[x] and in_gap:
            gap_width = x - gap_start
            if gap_width >= min_gap_width and gap_width <= max_gap_w:
                gap_center = gap_start + gap_width // 2
                # Ignore gaps too close to edges (must be in central 80%)
                if gap_center > w * 0.10 and gap_center < w * 0.90:
                    gaps.append((gap_center, gap_width))
            in_gap = False
            
    if not gaps:
        return [image_path]
        
    # Filter gaps that are too close to each other
    # Each column should be at least 15% of the page width
    gaps.sort(key=lambda g: g[0])
    filtered_gaps = [gaps[0][0]]
    for g_center, g_width in gaps[1:]:
        if g_center - filtered_gaps[-1] > w * 0.15:
            filtered_gaps.append(g_center)
            
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
            if cw > w * 0.12:  # Column must be at least 12% of page
                valid_cols.append(i)
        
        if len(valid_cols) < 2:
            logger.info("Column split: candidates found but too narrow, defaulting to single column")
            return [image_path]
        
        # Balance check: widest valid column shouldn't be >3x the narrowest valid
        valid_widths = [col_widths[i] for i in valid_cols]
        if max(valid_widths) > 3.0 * min(valid_widths):
            logger.info(f"Column split: unbalanced widths {[int(cw) for cw in col_widths]}, defaulting to single column")
            return [image_path]
 
    # Sanity: max 4 columns
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
        
        # Small padding to avoid cutting text at edges
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

