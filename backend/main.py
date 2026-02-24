import os
import sys
import cv2
import numpy as np
import shutil
import logging
import uvicorn
from pathlib import Path
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from paddleocr import PPStructure
from rapidfuzz import process, fuzz
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import Gemini Vision (optional - falls back to PaddleOCR if not available)
try:
    from gemini_vision import create_vision_engine
    GEMINI_AVAILABLE = True
except Exception as e:
    GEMINI_AVAILABLE = False
    logging.warning(f"Gemini Vision not available: {e}")

# ==========================================
# CONFIGURATION
# ==========================================
def get_base_path():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_PATH = get_base_path()
OUTPUT_DIR = os.path.join(BASE_PATH, "output_results")
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [BioManual] - %(message)s')
logger = logging.getLogger("BioManual")

# Configuration: Choose vision engine mode
# Options: 'paddle' (PaddleOCR only), 'gemini' (Gemini only), 'hybrid' (Gemini + PaddleOCR)
VISION_MODE = os.getenv('VISION_MODE', 'hybrid')  # Default to hybrid for best results

app = FastAPI(title="BioManual Auto-Standardizer")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# ==========================================
# MODULE 1: THE EYE 👁️ (Vision & Pre-processing)
# ==========================================
class BioVision:
    """
    Bertugas melakukan scanning, penghapusan watermark, dan pemotongan gambar/tabel.
    """
    def __init__(self):
        logger.info("Initializing BioVision (PaddleOCR)...")
        try:
            # Using PaddleOCR for Layout Analysis (Text/Table/Figure detection)
            self.engine = PPStructure(show_log=False, lang='en', enable_mkldnn=False)
            logger.info("✓ Vision Engine Ready")
        except Exception as e:
            logger.error(f"Vision Init Failed: {e}")
            sys.exit(1)

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
            
            # Range 2: 170-180 (Red/Pink/Purple)
            # WIDENED start to 160 to catch Purple/Pink
            lower_red2 = np.array([160, 30, 30])
            upper_red2 = np.array([180, 255, 255])
            
            # Ranges for Orange (often confused with red in low quality scans)
            lower_orange = np.array([10, 50, 50])
            upper_orange = np.array([25, 255, 255])
            
            # 3. Create Masks
            mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
            mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
            mask_orange = cv2.inRange(hsv, lower_orange, upper_orange)
            
            watermark_mask = mask1 + mask2 + mask_orange
            
            # 4. Dilate mask to cover anti-aliased edges (The "Black Line" killer)
            # Increase iterations for stronger cleaning
            kernel = np.ones((3,3), np.uint8)
            dilated_mask = cv2.dilate(watermark_mask, kernel, iterations=2)
            
            # 5. Inpaint / Turn White
            clean_color = image.copy()
            clean_color[dilated_mask > 0] = (255, 255, 255)
            
            # 6. Convert to Grayscale & Threshold (for OCR)
            gray = cv2.cvtColor(clean_color, cv2.COLOR_BGR2GRAY)
            
            # Gentle Threshold
            clean_binary = cv2.adaptiveThreshold(
                gray, 
                255, 
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY, 
                15, 
                10
            )
            
            return clean_binary
        except Exception as e:
            logger.warning(f"Preprocessing failed: {e}")
            return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def smart_crop(self, image):
        """
        Refines a crop by finding the actual content boundaries.
        1. Cleans the image (remove watermark/noise).
        2. Finds the largest contour (the actual object).
        3. Returns a tight crop around that object.
        """
        try:
            if image is None or image.size == 0: return image
            
            # 1. Get Clean Binary Mask (White content on Black background)
            # Use remove_watermark to get clean binary, then invert for contours
            clean = self.remove_watermark(image)
            # Threshold to ensure binary (Content=Black, Background=White from adaptive)
            # We want Content=White for findContours
            _, thresh = cv2.threshold(clean, 240, 255, cv2.THRESH_BINARY_INV)
            
            # 2. Find Contours
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                return image
            
            # 3. Find Largest Contour (The main object)
            c = max(contours, key=cv2.contourArea)
            current_area = cv2.contourArea(c)
            total_area = image.shape[0] * image.shape[1]
            
            # Safety: If refined area is too small (<5%), keep original
            if current_area < (total_area * 0.05):
                return image
                
            x, y, w, h = cv2.boundingRect(c)
            
            # 4. Crop
            # Add small padding to tight crop (5px)
            pad = 5
            h_img, w_img, _ = image.shape
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(w_img, x + w + pad)
            y2 = min(h_img, y + h + pad)
            
            return image[y1:y2, x1:x2]
            
        except Exception as e:
            logger.warning(f"Smart crop failed: {e}")
            return image

    def scan_document(self, image_path, filename_base):
        """
        Layout Analysis: Identifikasi elemen (Teks, Tabel, Gambar).
        """
        original_img = cv2.imread(image_path)
        
        # 1. Pre-process for better OCR (The Eye cleans the image)
        clean_for_ocr = self.remove_watermark(original_img)
        
        # 2. Run AI Layout Analysis
        # CRITICAL: Use CLEAN image for OCR to avoid watermark artifacts
        # Convert back to BGR for Paddle compatibility
        clean_bgr = cv2.cvtColor(clean_for_ocr, cv2.COLOR_GRAY2BGR)
        result = self.engine(clean_bgr)
        
        if not result:
            return []

        # Sort top-to-bottom (Reading Order)
        result.sort(key=lambda x: x['bbox'][1])
        
        extracted_elements = []
        h, w, _ = original_img.shape

        for line in result:
            line.pop('img', None)
            box = line['bbox']
            region_type = line['type'] # 'text', 'title', 'figure', 'table'
            res = line['res']
            
            # Extract content
            text_content = ""
            confidence = 0.0
            
            if region_type == 'table':
                text_content = "[TABLE DATA DETECTED]"
            else:
                texts = [x['text'] for x in res]
                text_content = " ".join(texts)
                confs = [x['confidence'] for x in res]
                confidence = np.mean(confs) if confs else 0

            # 3. Component Extraction (Cropping)
            crop_url = None
            crop_local = None
            
            # Crop Figures & Tables (Visual Evidence)
            if region_type in ['figure', 'table']:
                x1, y1, x2, y2 = box
                
                # Add SAFETY PADDING (20px)
                pad = 20
                px1 = max(0, x1 - pad)
                py1 = max(0, y1 - pad)
                px2 = min(w, x2 + pad)
                py2 = min(h, y2 + pad)
                
                # Use ORIGINAL COLOR IMAGE
                # Initial "Loose" Crop (with padding)
                loose_crop = original_img[py1:py2, px1:px2]
                
                # Apply SMART CROP (Auto-Trim to content)
                crop_img = self.smart_crop(loose_crop)
                
                if crop_img.size > 0:
                    crop_fname = f"{filename_base}_{region_type}_{x1}_{y1}.jpg"
                    crop_local = os.path.join(OUTPUT_DIR, crop_fname)
                    cv2.imwrite(crop_local, crop_img)
                    crop_url = f"http://127.0.0.1:8000/output/{crop_fname}".replace("\\", "/")

            extracted_elements.append({
                "type": region_type,
                "bbox": box,
                "text": text_content,
                "confidence": confidence,
                "crop_url": crop_url,
                "crop_local": crop_local
            })
            
        return extracted_elements

# ==========================================
# MODULE 2: THE BRAIN 🧠 (Logic & Classification)
# ==========================================
class BioBrain:
    """
    Bertugas membaca teks, normalisasi, dan klasifikasi ke 7 BAB Standar.
    Menggunakan Semantic Mapping.
    """
    def __init__(self):
        # The 7 Standard Chapters (Fixed Schema)
        self.taxonomy = {
            "BAB 1": {"title": "Tujuan Penggunaan & Keamanan", "keywords": ["tujuan", "intended", "safety", "warning", "caution", "bahaya", "introduction"]},
            "BAB 2": {"title": "Instalasi", "keywords": ["install", "setup", "pasang", "mounting", "connect", "power", "unboxing"]},
            "BAB 3": {"title": "Panduan Operasional & Pemantauan Klinis", "keywords": ["operation", "operasional", "monitor", "display", "screen", "tombol", "measure", "klinis"]},
            "BAB 4": {"title": "Perawatan, Pemeliharaan & Pembersihan", "keywords": ["maintenance", "clean", "bersih", "replace", "ganti", "battery", "care"]},
            "BAB 5": {"title": "Pemecahan Masalah", "keywords": ["trouble", "masalah", "error", "fail", "rusak", "solution", "solusi"]},
            "BAB 6": {"title": "Spesifikasi Teknis & Kepatuhan Standar", "keywords": ["spec", "tech", "data", "dimension", "weight", "standar", "iso", "iec"]},
            "BAB 7": {"title": "Garansi & Layanan", "keywords": ["warrant", "garansi", "service", "layanan", "contact", "support"]}
        }
        self.current_context = "BAB 1"
        
        # Initialize Spell Checker
        try:
            from spellchecker import SpellChecker
            self.spell = SpellChecker()
            
            # Add medical/technical terms to dictionary (won't be flagged as typos)
            medical_terms = [
                # Devices
                'defibrillator', 'sphygmomanometer', 'electrocardiogram', 'ecg', 'ekg',
                'oximeter', 'nebulizer', 'ventilator', 'stethoscope', 'thermometer',
                'syringe', 'catheter', 'cannula', 'tourniquet', 'autoclave',
                'sterilization', 'disinfection', 'biomedical', 'biosafety',
                'ultrasound', 'monitor', 'sensor', 'electrode', 'transducer',
                
                # Manual Keywords (Indonesian & English)
                'instalasi', 'pemasangan', 'penggunaan', 'pemeliharaan', 'perawatan',
                'masalah', 'solusi', 'spesifikasi', 'teknis', 'garansi', 'layanan',
                'installation', 'maintenance', 'troubleshooting', 'specification',
                'warranty', 'service', 'operation', 'cleaning', 'calibration',
                'warning', 'caution', 'danger', 'note', 'perhatian', 'bahaya',
                'catatan', 'tindakan', 'pencegahan', 'sebelum', 'sesudah',
                
                # Units & Tech
                'voltage', 'watt', 'hertz', 'ampere', 'volt', 'ac', 'dc',
                'kg', 'cm', 'mm', 'hz', 'vac', 'vdc', 'mah', 'battery',
                'lithium', 'ion', 'led', 'lcd', 'interface', 'usb', 'rs232',
                
                # Common OCR misreads whitelisted
                'bab', 'chapter', 'fig', 'table', 'gambar', 'tabel',
                'no', 'nomor', 'halaman', 'page', 'telp', 'fax', 'email'
            ]
            self.spell.word_frequency.load_words(medical_terms)
            logger.info("✓ Spell checker initialized with medical dictionary")
        except Exception as e:
            logger.warning(f"Spell checker init failed: {e}. Typo detection disabled.")
            self.spell = None

    def normalize_text(self, text):
        """
        Koreksi Typo & Normalisasi dengan Spell Checker
        """
        if not text or len(text.strip()) == 0:
            return {
                "original": text,
                "corrected": text,
                "typos": [],
                "has_typo": False,
                "confidence": 1.0
            }

        # --- SMART REGEX CLEANER (Paddle Optimization) ---
        import re
        
        # 1. Fix broken newlines (hyphenated words at end of line)
        # e.g. "communi-\ncation" -> "communication"
        cleaned = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
        
        # 2. Fix common OCR number confusions (Context aware)
        # "l" or "I" inside numbers -> "1" (e.g. "20I5" -> "2015")
        cleaned = re.sub(r'(\d)[lI](?=\d)', r'\g<1>1', cleaned)
        cleaned = re.sub(r'(\d)[O](?=\d)', r'\g<1>0', cleaned)  # "O" to "0" inside numbers
        
        # 3. Remove "scanned noise" (random isolated symbols)
        # e.g. " . " or " * " on its own line
        cleaned = re.sub(r'^\s*[^a-zA-Z0-9\(\)]\s*$', '', cleaned, flags=re.MULTILINE)
        
        # 4. Fix spaced out words (common in justified text)
        # e.g. "T a b l e" -> "Table"
        def fix_spaced_chars(match):
            return match.group(0).replace(" ", "")
        cleaned = re.sub(r'\b(?:[A-Z]\s){2,}[A-Z]\b', fix_spaced_chars, cleaned)
        
        # 5. Collapse multiple spaces
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        
        # 6. Fix "1l" -> "ll" in words (e.g. "wi11" -> "will")
        # Ganti: huruf 1 di antara huruf kecil -> l
        cleaned = re.sub(r'([a-z])1([a-z])', r'\1l\2', cleaned)
        
        # --- CONTEXT AWARE CORRECTION (Fuzzy Matching) ---
        # 7. Check for critical keywords with slight typos
        from difflib import get_close_matches
        
        # We only auto-correct if it's very close (cutoff=0.85) to avoid false positives
        # And only for words in our specific dictionary (not general English)
        words_list = cleaned.split()
        final_words = []
        
        # Build whitelist set for speed
        try:
            spell_words = list(self.spell.word_frequency.words())
        except Exception:
            spell_words = []
        vocab_set = set(spell_words + list(self.taxonomy.keys()))


        for w in words_list:
            # If word is already correct, keep it
            if w.lower() in vocab_set or (self.spell and w.lower() in self.spell):
                final_words.append(w)
                continue
            
            # If not, try to find a close match in our specific medical/manual terms
            # We DONT use general dictionary for auto-correct to be safe
            matches = get_close_matches(w.lower(), list(vocab_set), n=1, cutoff=0.85)
            
            if matches:
                # Preserve original casing if possible (simple heuristic)
                best = matches[0]
                if w.istitle(): best = best.capitalize()
                elif w.isupper(): best = best.upper()
                final_words.append(best)
            else:
                final_words.append(w)
                
        cleaned = " ".join(final_words)
        # --- END CONTEXT AWARE CORRECTION ---
        
        # Preserve cleaned text for next steps
        text = cleaned.strip()
        
        # --- END SMART REGEX CLEANER ---
        
        # If spell checker not available, return as-is
        if not self.spell:
            return {
                "original": text,
                "corrected": text.strip(),
                "typos": [],
                "has_typo": False,
                "confidence": 1.0
            }
        
        # Split into words (preserve punctuation context)
        import re
        words = re.findall(r'\b\w+\b', text)
        
        if not words:
            return {
                "original": text,
                "corrected": text.strip(),
                "typos": [],
                "has_typo": False,
                "confidence": 1.0
            }
        
        # Find typos
        typo_words = self.spell.unknown(words)
        
        corrected_text = text
        typo_positions = []
        
        for word in typo_words:
            # Skip very short words (likely abbreviations)
            if len(word) <= 2:
                continue
            
            # Skip numbers
            if word.isdigit():
                continue
            
            # Get correction suggestion
            correction = self.spell.correction(word)
            
            if correction and correction != word:
                # Replace in text (case-insensitive)
                corrected_text = re.sub(
                    r'\b' + re.escape(word) + r'\b',
                    correction,
                    corrected_text,
                    flags=re.IGNORECASE
                )
                
                typo_positions.append({
                    "original": word,
                    "suggestion": correction,
                    "position": text.lower().find(word.lower())
                })
        
        # Calculate confidence (1.0 = perfect, lower = more typos)
        confidence = 1.0 - (len(typo_positions) / len(words)) if words else 1.0
        
        return {
            "original": text.strip(),
            "corrected": corrected_text.strip(),
            "typos": typo_positions,
            "has_typo": len(typo_positions) > 0,
            "confidence": round(confidence, 2)
        }

    def semantic_mapping(self, item):
        """
        Memetakan konten ke dalam 7 BAB.
        Logika:
        1. Cek Header Eksplisit ("BAB 2", "Chapter 5").
        2. Cek Kesamaan Judul (Title Matching).
        3. Cek Kata Kunci Konten (Content Keywords).
        4. Context Persistence (Jika ragu, ikut bab sebelumnya).
        """
        text = item['text'].lower()
        rtype = item['type']
        
        # 1. Explicit Headers (Absolute Priority)
        for i in range(1, 8):
            key = f"BAB {i}"
            if key.lower() in text or f"chapter {i}" in text:
                self.current_context = key
                return key, self.taxonomy[key]["title"]

        # 2. Title Analysis
        if rtype == 'title':
            best_match = None
            max_score = 0
            for code, meta in self.taxonomy.items():
                # Count keyword hits
                hits = sum(1 for k in meta['keywords'] if k in text)
                if hits > max_score:
                    max_score = hits
                    best_match = code
            
            if best_match and max_score >= 1:
                self.current_context = best_match
        
        # 3. Content Analysis (Switch context only on strong signal)
        elif rtype == 'text':
             for code, meta in self.taxonomy.items():
                hits = sum(1 for k in meta['keywords'] if k in text)
                if hits >= 3: # Butuh setidaknya 3 keywords untuk pindah bab di tengah teks
                     self.current_context = code

        # Return Decision
        return self.current_context, self.taxonomy[self.current_context]["title"]

# ==========================================
# MODULE 3: THE ARCHITECT 🏗️ (Builder)
# ==========================================
class BioArchitect:
    """
    Bertugas menyusun kembali data ke Template Standar (.docx).
    Template profesional Manual Book standar industri.
    """

    # Warna tema buku manual (biru tua Biosys)
    COLOR_PRIMARY   = RGBColor(0x1E, 0x3A, 0x8A)   # Biru tua #1E3A8A
    COLOR_SECONDARY = RGBColor(0x3B, 0x82, 0xF6)   # Biru muda #3B82F6
    COLOR_WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
    COLOR_GRAY      = RGBColor(0x6B, 0x72, 0x80)
    COLOR_BLACK     = RGBColor(0x00, 0x00, 0x00)

    def __init__(self):
        self.letterhead_path = self._resolve_letterhead()

    def _resolve_letterhead(self):
        """Cari file letterhead relatif terhadap folder backend."""
        raw = os.getenv("LETTERHEAD_PATH", "").strip()
        if not raw:
            return None
        # Coba absolut dulu, lalu relatif ke BASE_PATH
        if os.path.isabs(raw) and os.path.exists(raw):
            return raw
        candidate = os.path.join(BASE_PATH, raw)
        if os.path.exists(candidate):
            return candidate
        logger.warning(f"Letterhead tidak ditemukan: {raw}")
        return None

    # ─────────────────────────────────────────────
    # Layout & Style
    # ─────────────────────────────────────────────
    def _set_fixed_margins(self, doc):
        """Ukuran A4, margin standar manual book Indonesia."""
        for section in doc.sections:
            from docx.shared import Cm
            section.page_height  = Cm(29.7)
            section.page_width   = Cm(21.0)
            section.top_margin   = Cm(2.5)
            section.bottom_margin= Cm(2.5)
            section.left_margin  = Cm(3.0)   # lebih lebar untuk binding
            section.right_margin = Cm(2.0)
            section.header_distance = Cm(1.25)
            section.footer_distance = Cm(1.25)

    def _set_fixed_styles(self, doc):
        """Font, spacing, dan heading styles."""
        # ── Normal (Body Text) ──────────────────────────────
        s = doc.styles['Normal']
        s.font.name = 'Arial'
        s.font.size = Pt(11)
        s.font.color.rgb = self.COLOR_BLACK
        s.paragraph_format.line_spacing     = Pt(16.5)   # ≈ 1.5 × 11pt
        s.paragraph_format.space_before     = Pt(0)
        s.paragraph_format.space_after      = Pt(8)
        s.paragraph_format.first_line_indent= Inches(0.35)

        # ── Heading 1 (Judul BAB) ───────────────────────────
        h1 = doc.styles['Heading 1']
        h1.font.name = 'Arial'
        h1.font.size = Pt(14)
        h1.font.bold = True
        h1.font.color.rgb = self.COLOR_WHITE
        h1.paragraph_format.space_before    = Pt(0)
        h1.paragraph_format.space_after     = Pt(12)
        h1.paragraph_format.keep_with_next  = True
        h1.paragraph_format.first_line_indent = Pt(0)

        # ── Heading 2 (Sub-judul) ───────────────────────────
        h2 = doc.styles['Heading 2']
        h2.font.name = 'Arial'
        h2.font.size = Pt(12)
        h2.font.bold = True
        h2.font.color.rgb = self.COLOR_PRIMARY
        h2.paragraph_format.space_before    = Pt(10)
        h2.paragraph_format.space_after     = Pt(4)
        h2.paragraph_format.first_line_indent = Pt(0)

    # ─────────────────────────────────────────────
    # Header & Footer
    # ─────────────────────────────────────────────
    def _add_header_footer(self, doc, bab_label=""):
        """
        Header: nama dokumen (kiri) | label BAB (kanan)
        Footer: logo strip perusahaan (kiri) + nomor halaman (kanan)
        """
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        section = doc.sections[0]

        # ── HEADER ──────────────────────────────────────────
        section.different_first_page_header_footer = True
        header = section.header
        header.is_linked_to_previous = False

        if not header.paragraphs:
            header.add_paragraph()
        hp = header.paragraphs[0]
        hp.clear()
        hp.paragraph_format.space_before = Pt(0)
        hp.paragraph_format.space_after  = Pt(4)

        # Kiri: nama aplikasi
        run_left = hp.add_run("BioManual Auto-Standardizer")
        run_left.font.name  = 'Arial'
        run_left.font.size  = Pt(9)
        run_left.font.color.rgb = self.COLOR_GRAY
        run_left.font.italic = True

        # Tab ke kanan
        tab = OxmlElement('w:tab')
        run_left._r.append(tab)

        # Set tab stop kanan
        pPr = hp._p.get_or_add_pPr()
        tabs = OxmlElement('w:tabs')
        tab_el = OxmlElement('w:tab')
        tab_el.set(qn('w:val'), 'right')
        tab_el.set(qn('w:pos'), '9360')   # 6.5" dalam twips (1"=1440)
        tabs.append(tab_el)
        pPr.append(tabs)

        # Kanan: label BAB
        run_right = hp.add_run(bab_label)
        run_right.font.name  = 'Arial'
        run_right.font.size  = Pt(9)
        run_right.font.bold  = True
        run_right.font.color.rgb = self.COLOR_PRIMARY

        # Garis bawah header via border XML
        pBdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'),  'single')
        bottom.set(qn('w:sz'),   '6')
        bottom.set(qn('w:space'),'1')
        bottom.set(qn('w:color'), '1E3A8A')
        pBdr.append(bottom)
        pPr.append(pBdr)

        # ── FOOTER ──────────────────────────────────────────
        footer = section.footer
        footer.is_linked_to_previous = False

        if not footer.paragraphs:
            footer.add_paragraph()
        fp = footer.paragraphs[0]
        fp.clear()

        # Garis atas footer
        fpPr = fp._p.get_or_add_pPr()
        fBdr = OxmlElement('w:pBdr')
        top  = OxmlElement('w:top')
        top.set(qn('w:val'),  'single')
        top.set(qn('w:sz'),   '4')
        top.set(qn('w:space'),'1')
        top.set(qn('w:color'), '1E3A8A')
        fBdr.append(top)
        fpPr.append(fBdr)

        # Logo strip perusahaan (kiri)
        if self.letterhead_path:
            try:
                run_logo = fp.add_run()
                run_logo.add_picture(self.letterhead_path, height=Pt(28))
            except Exception as e:
                logger.warning(f"Gagal load letterhead: {e}")
                fp.add_run("© BioManual").font.size = Pt(8)
        else:
            run_co = fp.add_run("© BioManual Auto-Standardizer")
            run_co.font.name  = 'Arial'
            run_co.font.size  = Pt(8)
            run_co.font.color.rgb = self.COLOR_GRAY

        # Tab ke kanan
        run_tab = fp.add_run()
        tab2 = OxmlElement('w:tab')
        run_tab._r.append(tab2)

        set_tabs2 = OxmlElement('w:tabs')
        tab_el2   = OxmlElement('w:tab')
        tab_el2.set(qn('w:val'), 'right')
        tab_el2.set(qn('w:pos'), '9360')
        set_tabs2.append(tab_el2)
        fpPr.append(set_tabs2)

        # Nomor halaman (kanan)
        run_pg = fp.add_run()
        run_pg.font.name  = 'Arial'
        run_pg.font.size  = Pt(9)
        run_pg.font.color.rgb = self.COLOR_PRIMARY
        run_pg.font.bold  = True

        fldChar1 = OxmlElement('w:fldChar')
        fldChar1.set(qn('w:fldCharType'), 'begin')
        instrText = OxmlElement('w:instrText')
        instrText.text = ' PAGE '
        fldChar2 = OxmlElement('w:fldChar')
        fldChar2.set(qn('w:fldCharType'), 'end')
        run_pg._r.extend([fldChar1, instrText, fldChar2])

    # ─────────────────────────────────────────────
    # Cover Page
    # ─────────────────────────────────────────────
    def _build_cover_page(self, doc, original_filename, product_name="", product_code=""):
        """
        Cover page layout (sesuai referensi):
          - Kiri atas  : Nama produk bold + kode model
          - Tengah     : "BUKU MANUAL" bold besar
          - Bawah      : Letterhead full-width (wave + logo)
        """
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
        from docx.shared import Cm

        # ── Kiri atas: Nama Produk ───────────────────────────
        p_name = doc.add_paragraph()
        p_name.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p_name.paragraph_format.space_before = Pt(40)
        p_name.paragraph_format.space_after  = Pt(0)
        p_name.paragraph_format.first_line_indent = Pt(0)
        rn = p_name.add_run(product_name or Path(original_filename).stem.upper())
        rn.font.name  = 'Arial'
        rn.font.size  = Pt(18)
        rn.font.bold  = True
        rn.font.color.rgb = self.COLOR_BLACK

        # Kode model (misal: EEG-32)
        if product_code:
            p_code = doc.add_paragraph()
            p_code.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p_code.paragraph_format.space_before = Pt(8)
            p_code.paragraph_format.space_after  = Pt(0)
            p_code.paragraph_format.first_line_indent = Pt(0)
            rc = p_code.add_run(product_code)
            rc.font.name  = 'Arial'
            rc.font.size  = Pt(16)
            rc.font.bold  = True
            rc.font.color.rgb = self.COLOR_BLACK

        # ── Spasi besar di tengah ────────────────────────────
        for _ in range(10):
            sp = doc.add_paragraph()
            sp.paragraph_format.first_line_indent = Pt(0)
            sp.paragraph_format.space_before = Pt(0)
            sp.paragraph_format.space_after  = Pt(0)

        # ── Tengah: BUKU MANUAL ──────────────────────────────
        p_bm = doc.add_paragraph()
        p_bm.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_bm.paragraph_format.space_before = Pt(0)
        p_bm.paragraph_format.space_after  = Pt(0)
        p_bm.paragraph_format.first_line_indent = Pt(0)
        rbm = p_bm.add_run("BUKU MANUAL")
        rbm.font.name  = 'Arial'
        rbm.font.size  = Pt(28)
        rbm.font.bold  = True
        rbm.font.color.rgb = self.COLOR_BLACK

        # ── Spasi menuju bawah ──────────────────────────────
        for _ in range(10):
            sp = doc.add_paragraph()
            sp.paragraph_format.first_line_indent = Pt(0)
            sp.paragraph_format.space_before = Pt(0)
            sp.paragraph_format.space_after  = Pt(0)

        # ── Bawah: Letterhead full-width ─────────────────────
        if self.letterhead_path:
            try:
                # Lebar konten A4: 21cm - 3cm (kiri) - 2cm (kanan) = 16cm
                p_logo = doc.add_paragraph()
                p_logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p_logo.paragraph_format.space_before = Pt(0)
                p_logo.paragraph_format.space_after  = Pt(0)
                p_logo.paragraph_format.first_line_indent = Pt(0)

                # Negatif marjin kiri/kanan agar full-width
                p_logo.paragraph_format.left_indent  = Cm(-3.0)
                p_logo.paragraph_format.right_indent = Cm(-2.0)

                p_logo.add_run().add_picture(
                    self.letterhead_path,
                    width=Cm(21)   # lebar penuh A4
                )
            except Exception as e:
                logger.warning(f"Cover letterhead error: {e}")
                p_fb = doc.add_paragraph("[ Letterhead gagal dimuat ]")
                p_fb.paragraph_format.first_line_indent = Pt(0)

        doc.add_page_break()

    # ─────────────────────────────────────────────
    # Chapter Header (kotak biru)
    # ─────────────────────────────────────────────
    def _add_chapter_header(self, doc, bab_id, bab_title):
        """Judul BAB dengan kotak biru tua + teks putih."""
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        h = doc.add_heading(f"  {bab_id}: {bab_title}", level=1)
        h.alignment = WD_ALIGN_PARAGRAPH.LEFT
        h.paragraph_format.first_line_indent = Pt(0)

        # Shading biru pada paragraf heading
        pPr = h._p.get_or_add_pPr()
        shd = OxmlElement('w:shd')
        shd.set(qn('w:val'),   'clear')
        shd.set(qn('w:color'), 'auto')
        shd.set(qn('w:fill'),  '1E3A8A')   # biru tua
        pPr.append(shd)

        # Padding atas-bawah via spacing
        h.paragraph_format.space_before = Pt(14)
        h.paragraph_format.space_after  = Pt(14)

    # ─────────────────────────────────────────────
    # Daftar Isi (Table of Contents)
    # ─────────────────────────────────────────────
    def _build_toc_page(self, doc, grouped):
        """
        Halaman Daftar Isi.
        - Insert field TOC standar Word (auto-update saat buka file)
        - Fallback: daftar statis BAB 1-7 dengan nomor halaman estimasi
        """
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        # ── Judul "DAFTAR ISI" ─────────────────────────────
        p_title = doc.add_paragraph()
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_title.paragraph_format.space_before = Pt(0)
        p_title.paragraph_format.space_after  = Pt(20)
        p_title.paragraph_format.first_line_indent = Pt(0)
        rt = p_title.add_run("DAFTAR ISI")
        rt.font.name  = 'Arial'
        rt.font.size  = Pt(16)
        rt.font.bold  = True
        rt.font.color.rgb = self.COLOR_PRIMARY

        # Garis bawah biru
        pPr = p_title._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        bot  = OxmlElement('w:bottom')
        bot.set(qn('w:val'),  'single')
        bot.set(qn('w:sz'),   '8')
        bot.set(qn('w:space'),'2')
        bot.set(qn('w:color'), '1E3A8A')
        pBdr.append(bot)
        pPr.append(pBdr)

        doc.add_paragraph().paragraph_format.first_line_indent = Pt(0)

        # ── Insert TOC field (Word akan render otomatis) ────────
        # Field: { TOC \o "1-2" \h \z \u }
        # \o 1-2  = include Heading 1 & 2
        # \h      = hyperlink
        # \z      = hide tab leader in web view
        # \u      = use applied paragraph outline level
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.first_line_indent = Pt(0)
        run = paragraph.add_run()

        fldChar_begin = OxmlElement('w:fldChar')
        fldChar_begin.set(qn('w:fldCharType'), 'begin')

        instrText = OxmlElement('w:instrText')
        instrText.set(qn('xml:space'), 'preserve')
        instrText.text = ' TOC \\o "1-2" \\h \\z \\u '

        fldChar_sep = OxmlElement('w:fldChar')
        fldChar_sep.set(qn('w:fldCharType'), 'separate')

        # Placeholder text (sebelum Word update)
        fldChar_end = OxmlElement('w:fldChar')
        fldChar_end.set(qn('w:fldCharType'), 'end')

        run._r.extend([fldChar_begin, instrText, fldChar_sep, fldChar_end])

        # ── Fallback statis: daftar BAB yang ada ──────────────
        # Ini muncul sebagai preview sebelum Word update field
        bab_meta = BioBrain().taxonomy
        page_est  = 3   # estimasi mulai halaman 3 (setelah cover + toc)

        for bab_id, items in grouped.items():
            bab_title = bab_meta[bab_id]['title']
            has_content = len(items) > 0

            p_entry = doc.add_paragraph()
            p_entry.paragraph_format.first_line_indent = Pt(0)
            p_entry.paragraph_format.space_before = Pt(4)
            p_entry.paragraph_format.space_after  = Pt(4)

            # Tab stop kanan untuk nomor halaman
            pPr2 = p_entry._p.get_or_add_pPr()
            tabs2 = OxmlElement('w:tabs')
            t1 = OxmlElement('w:tab')
            t1.set(qn('w:val'), 'right')
            t1.set(qn('w:pos'), '9360')
            t1.set(qn('w:leader'), 'dot')   # ............. leader
            tabs2.append(t1)
            pPr2.append(tabs2)

            # Teks BAB
            r_bab = p_entry.add_run(f"{bab_id}   {bab_title}")
            r_bab.font.name  = 'Arial'
            r_bab.font.size  = Pt(11)
            r_bab.font.bold  = has_content
            r_bab.font.color.rgb = self.COLOR_BLACK if has_content else self.COLOR_GRAY

            # Tab + nomor halaman
            r_tab = p_entry.add_run("\t")
            r_pg  = p_entry.add_run(str(page_est))
            r_pg.font.name  = 'Arial'
            r_pg.font.size  = Pt(11)
            r_pg.font.bold  = has_content
            r_pg.font.color.rgb = self.COLOR_PRIMARY

            # Estimasi kasar: tiap BAB ~2 halaman jika ada konten
            page_est += (2 if has_content else 1)

        doc.add_page_break()

    # ─────────────────────────────────────────────
    # Main Builder
    # ─────────────────────────────────────────────
    def build_report(self, classified_data, original_filename):
        doc = Document()

        self._set_fixed_margins(doc)
        self._set_fixed_styles(doc)
        self._add_header_footer(doc)

        # Ekstrak nama produk & kode model dari classified_data (BAB 1, tipe title)
        product_name = ""
        product_code = ""
        for item in classified_data:
            if item.get('type') in ('title', 'heading') and item.get('chapter_id') == 'BAB 1':
                text = item.get('normalized', '').strip()
                if text and len(text) > 3:
                    if not product_name:
                        product_name = text
                    elif not product_code:
                        product_code = text
                        break

        self._build_cover_page(doc, original_filename, product_name, product_code)

        # Kelompokkan per BAB (dilakukan lebih awal agar bisa dipakai TOC & konten)
        taxonomy_keys = list(BioBrain().taxonomy.keys())
        grouped = {k: [] for k in taxonomy_keys}
        for item in classified_data:
            key = item['chapter_id']
            if key in grouped:
                grouped[key].append(item)
            else:
                grouped["BAB 1"].append(item)

        # Halaman Daftar Isi
        self._build_toc_page(doc, grouped)

        # Bangun konten per BAB
        for bab_id, items in grouped.items():
            bab_title = BioBrain().taxonomy[bab_id]["title"]

            self._add_chapter_header(doc, bab_id, bab_title)

            if not items:
                p = doc.add_paragraph("[ Tidak ada konten terdeteksi pada bab ini ]")
                p.italic = True
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.first_line_indent = Pt(0)
                p.runs[0].font.color.rgb = self.COLOR_GRAY
                doc.add_page_break()
                continue

            for item in items:
                content_type = item['type']
                text         = item['normalized']

                if content_type in ('title', 'heading'):
                    h2 = doc.add_heading(text, level=2)
                    h2.paragraph_format.first_line_indent = Pt(0)

                elif content_type in ('figure', 'table'):
                    if item.get('crop_local') and os.path.exists(item['crop_local']):
                        # Label
                        lbl = doc.add_paragraph()
                        lbl.paragraph_format.first_line_indent = Pt(0)
                        lr  = lbl.add_run(f"[ {content_type.upper()} ]")
                        lr.bold = True
                        lr.font.color.rgb = self.COLOR_PRIMARY
                        lr.font.size = Pt(10)

                        # Gambar dengan border tipis via tabel 1-cell
                        try:
                            tbl = doc.add_table(rows=1, cols=1)
                            tbl.style = 'Table Grid'
                            cell = tbl.cell(0, 0)
                            cell_para = cell.paragraphs[0]
                            cell_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            cell_para.paragraph_format.first_line_indent = Pt(0)
                            run_img = cell_para.add_run()
                            run_img.add_picture(item['crop_local'], width=Inches(4.5))
                        except Exception as e:
                            logger.error(f"Error adding picture: {e}")
                            doc.add_paragraph(f"[ Gagal load gambar: {e} ]")

                        # Caption
                        if text and text not in ("[TABLE DATA DETECTED]", "[FIGURE]", "[TABLE]"):
                            cap = doc.add_paragraph(text)
                            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            cap.paragraph_format.space_before = Pt(4)
                            cap.paragraph_format.first_line_indent = Pt(0)
                            cap.runs[0].italic = True
                            cap.runs[0].font.size = Pt(9)
                            cap.runs[0].font.color.rgb = self.COLOR_GRAY

                        doc.add_paragraph()   # spasi setelah gambar

                    else:
                        p = doc.add_paragraph(f"[ {content_type} — gambar tidak tersedia ]")
                        p.paragraph_format.first_line_indent = Pt(0)
                        p.runs[0].font.color.rgb = self.COLOR_GRAY

                else:  # Body text
                    p = doc.add_paragraph(text)
                    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

                    if item.get('has_typo'):
                        warn = doc.add_paragraph()
                        warn.paragraph_format.first_line_indent = Pt(0)
                        wr = warn.add_run("⚠ Possible OCR typos detected")
                        wr.font.size = Pt(8)
                        wr.font.color.rgb = RGBColor(0xFF, 0xA5, 0x00)  # Orange

            doc.add_page_break()

        # Simpan
        word_filename = f"Standardized_{Path(original_filename).stem}.docx"
        word_path     = os.path.join(BASE_PATH, word_filename)
        doc.save(word_path)
        logger.info(f"✓ Word file saved: {word_filename}")

        return {
            "word_file": word_filename,
            "pdf_file":  None
        }

# ==========================================
# SYSTEM ORCHESTRATOR (Integration)
# ==========================================

# Initialize Vision Module based on configuration
def initialize_vision_module():
    """Initialize vision module based on VISION_MODE setting"""
    if VISION_MODE in ['gemini', 'hybrid'] and GEMINI_AVAILABLE:
        try:
            logger.info(f"Initializing {VISION_MODE.upper()} vision mode...")
            return create_vision_engine(mode=VISION_MODE)
        except Exception as e:
            logger.error(f"Failed to initialize Gemini: {e}")
            logger.info("Falling back to PaddleOCR...")
            return BioVision()
    else:
        logger.info("Using PaddleOCR vision mode...")
        return BioVision()

vision_module = initialize_vision_module()
architect_module = BioArchitect()

# Progress tracking
progress_tracker = {}
# Session Data Storage (for Supplementary Uploads)
active_sessions = {}

def _print_progress(current: int, total: int, label: str = "", width: int = 40):
    """Print a colored ASCII progress bar to the terminal."""
    pct = int((current / total) * 100) if total > 0 else 0
    filled = int(width * current / total) if total > 0 else 0
    bar = '█' * filled + '░' * (width - filled)
    # ANSI: green bar, cyan percentage
    print(f"\r  \033[92m[{bar}]\033[0m \033[96m{pct:3d}%\033[0m  {label}   ", end='', flush=True)
    if current >= total:
        print()  # newline when done

@app.get("/health")
def health():
    return {"status": "BioManual System Online"}

@app.get("/progress/{session_id}")
async def get_progress(session_id: str):
    """Get processing progress for a session"""
    if session_id in progress_tracker:
        return progress_tracker[session_id]
    return {"error": "Session not found"}

@app.get("/files/{filename}")
async def serve_file(filename: str):
    path = os.path.join(BASE_PATH, filename)
    if os.path.exists(path):
        return FileResponse(path)
    return {"error": "File not found"}

@app.post("/process")
async def process_workflow(file: UploadFile = File(...)):
    import uuid
    
    # Generate session ID for progress tracking
    session_id = str(uuid.uuid4())
    
    # Initialize Brain per request (fresh context)
    brain_module = BioBrain()
    
    logger.info(f"Starting BioManual Workflow for: {file.filename} (Session: {session_id})")
    
    temp_path = os.path.join(BASE_PATH, f"temp_{file.filename}")
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    structured_data = []
    
    # Initialize progress
    progress_tracker[session_id] = {
        "status": "starting",
        "current_page": 0,
        "total_pages": 0,
        "percentage": 0,
        "message": "Initializing..."
    }

    try:
        # STEP 1: IMAGE CONVERSION
        images = []
        if file.filename.lower().endswith('.pdf'):
            progress_tracker[session_id]["message"] = "Converting PDF to images..."
            print(f"\n{'='*60}")
            print(f"  📄 File   : {file.filename}")
            print(f"  🔄 Step 1 : Converting PDF to images...")
            print(f"{'='*60}")
            images = convert_pdf_to_images_safe(temp_path)
        else:
            images = [temp_path]
        
        # Initialize list to store cleaned page URLs for frontend preview
        clean_pages_urls = []
        
        total_pages = len(images)
        progress_tracker[session_id]["total_pages"] = total_pages
        progress_tracker[session_id]["message"] = f"Processing {total_pages} page(s)..."
        print(f"\n  📑 Total  : {total_pages} halaman")
        print(f"  🔄 Step 2 : Scanning setiap halaman...")

        # STEP 2: LOOP THROUGH PAGES
        for i, img_src in enumerate(images):
            current_page = i + 1
            pct = int((current_page / total_pages) * 100)
            
            # Update progress
            progress_tracker[session_id].update({
                "status": "processing",
                "current_page": current_page,
                "percentage": pct,
                "message": f"Processing page {current_page} of {total_pages}..."
            })
            
            # ── Terminal Progress Bar ──
            _print_progress(current_page, total_pages,
                            f"Hal. {current_page}/{total_pages}  ({pct}%)")
            
            logger.info(f"Processing page {current_page}/{total_pages}")
            
            # Resolve image path
            page_path = img_src
            if not isinstance(img_src, str):
                page_path = os.path.join(BASE_PATH, f"page_{i}.png")
                img_src.save(page_path, "PNG")

            # A. THE EYE (Scan)
            # Returns dict: {'elements': [], 'clean_image_path': 'path/to/img.jpg'}
            scan_result = vision_module.scan_document(page_path, f"{file.filename}_{i}")
            
            # Handle return format (Backward compatibility check)
            if isinstance(scan_result, list):
                layout_elements = scan_result
                clean_img_url = None
            else:
                layout_elements = scan_result.get('elements', [])
                clean_path = scan_result.get('clean_image_path')
                
                # Convert path to URL
                if clean_path and os.path.exists(clean_path):
                     fname = os.path.basename(clean_path)
                     clean_img_url = f"http://127.0.0.1:8000/output/{fname}"
                     clean_pages_urls.append(clean_img_url)
                else:
                     clean_img_url = None
            
            # B. THE BRAIN (Classify)
            for element in layout_elements:
                # Normalization with Typo Detection
                normalized_result = brain_module.normalize_text(element['text'])
                
                # Update element with corrected text for classification
                element['text'] = normalized_result['corrected']
                
                # Semantic Mapping (use corrected text)
                bab_id, bab_title = brain_module.semantic_mapping(element)
                
                # Add Metadata with Typo Information
                structured_data.append({
                    "chapter_id": bab_id,
                    "chapter_title": bab_title,
                    "type": element['type'],
                    "original": normalized_result['original'],
                    "normalized": normalized_result['corrected'],
                    "typos": normalized_result['typos'],
                    "has_typo": normalized_result['has_typo'],
                    "text_confidence": normalized_result['confidence'],
                    "match_score": 100, # Mock score
                    "crop_url": element['crop_url'],
                    "crop_local": element['crop_local']
                })

            # Cleanup
            # Cleanup with retry
            import time
            if not isinstance(img_src, str):
                for attempt in range(3):
                    try:
                        if os.path.exists(page_path):
                            os.remove(page_path)
                        break
                    except PermissionError:
                         time.sleep(0.5)
                    except Exception:
                         pass


        # 2.5 CHECK MISSING CHAPTERS (Auto-Fill)
        existing_chapters = set(item['chapter_id'] for item in structured_data)
        
        # Check for missing Maintenance Chapter (BAB 4)
        if "BAB 4" not in existing_chapters and hasattr(vision_module, 'generate_chapter_content'):
            logger.info("⚠️ BAB 4 (Maintenance) is missing. Attempting AI generation...")
            
            progress_tracker[session_id].update({
                "message": "Generating missing Maintenance Chapter (AI)..."
            })
            
            # Context Extraction (Product Knowledge)
            # Aggregate text from BAB 1 (Info) and BAB 2 (Installation)
            context_text = []
            for item in structured_data:
                if item['chapter_id'] in ["BAB 1", "BAB 2"]:
                    context_text.append(item['normalized'])
            
            product_context = "\n".join(context_text[:50]) # Limit context to first 50 paragraphs to avoid token limits
            
            # Generate Logic
            generated_content = vision_module.generate_chapter_content(
                topic="BAB 4: Perawatan, Pemeliharaan & Pembersihan",
                context=product_context
            )
            
            if generated_content and not generated_content.startswith("["):
                 # Parse paragraphs
                 lines = generated_content.split('\n')
                 for line in lines:
                     if not line.strip(): continue
                     
                     is_heading = line.strip().isupper() or line.startswith('#') or line.startswith('**')
                     
                     structured_data.append({
                        "chapter_id": "BAB 4",
                        "chapter_title": BioBrain().taxonomy["BAB 4"]["title"],
                        "type": "title" if is_heading else "text",
                        "original": line,
                        "normalized": line.replace('**','').replace('#','').strip(),
                        "typos": [],
                        "has_typo": False,
                        "text_confidence": 0.9,
                        "match_score": 100,
                        "crop_url": None,
                        "crop_local": None
                    })
                 logger.info("✓ BAB 4 generated successfully.")

        # STEP 3: THE ARCHITECT (Build)
        progress_tracker[session_id].update({
            "status": "building",
            "percentage": 95,
            "message": "Generating Word/PDF reports..."
        })
        print(f"\n  🏗️  Step 3 : Menyusun laporan Word ({len(structured_data)} elemen)...")
        
        result = architect_module.build_report(structured_data, file.filename)
        
        word_url = f"http://127.0.0.1:8000/files/{result['word_file']}"
        pdf_url = f"http://127.0.0.1:8000/files/{result['pdf_file']}" if result['pdf_file'] else None
        
        # Mark as complete
        _print_progress(total_pages, total_pages, "✅ SELESAI!")
        print(f"  📁 Output : {result.get('word_file', '-')}")
        print(f"{'='*60}\n")
        progress_tracker[session_id].update({
            "status": "complete",
            "percentage": 100,
            "message": "Processing complete!"
        })
        
        return {
            "success": True,
            "session_id": session_id,
            "results": structured_data,
            "word_url": word_url,
            "pdf_url": pdf_url,
            "total_pages": progress_tracker[session_id]["total_pages"],
            "clean_pages": clean_pages_urls, # NEW: List of cleaned page URLs
            "missing_chapters": list(set(["BAB 1", "BAB 2", "BAB 3", "BAB 4", "BAB 5", "BAB 6", "BAB 7"]) - existing_chapters)
        }

    except Exception as e:
        logger.error(f"Workflow Failed: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

        # Store session data for potential supplementary uploads
        if structured_data and session_id:
             active_sessions[session_id] = {
                 "original_filename": file.filename,
                 "structured_data": structured_data,
                 "images_count": len(images) if 'images' in locals() else 0
             }

@app.post("/supplement/{session_id}")
async def supplement_workflow(session_id: str, file: UploadFile = File(...)):
    """
    Endpoint untuk mengupload file tambahan ke sesi yang sudah ada.
    Menggabungkan hasil ekstraksi baru dengan yang lama.
    """
    if session_id not in active_sessions:
        return {"success": False, "error": "Session ID not found or expired"}
    
    existing_session = active_sessions[session_id]
    original_data = existing_session["structured_data"]
    base_filename = existing_session["original_filename"]
    
    logger.info(f"Supplementing Session {session_id} with file: {file.filename}")
    
    temp_path = os.path.join(BASE_PATH, f"temp_supp_{file.filename}")
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    supplementary_data = []
    
    # Initialize separate progress for supplement (or update existing?)
    # For now, let's update the existing session's progress to show activity
    progress_tracker[session_id].update({
        "status": "processing_supplement",
        "message": f"Processing supplementary file: {file.filename}..."
    })

    try:
        # STEP 1: IMAGE CONVERSION (Reuse logic)
        images = []
        if file.filename.lower().endswith('.pdf'):
            images = convert_pdf_to_images_safe(temp_path)
        else:
            images = [temp_path]
            
        total_pages = len(images)
        current_page_offset = existing_session.get("images_count", 0) + 1
        
        # STEP 2: LOOP & PROCESS
        for i, img_src in enumerate(images):
            # Resolve image path
            page_path = img_src
            if not isinstance(img_src, str):
                page_path = os.path.join(BASE_PATH, f"supp_{session_id}_{i}.png")
                img_src.save(page_path, "PNG")

            # A. THE EYE (Scan)
            scan_result = vision_module.scan_document(page_path, f"supp_{file.filename}_{i}")
            
            if isinstance(scan_result, list):
                layout_elements = scan_result
            else:
                layout_elements = scan_result.get('elements', [])
            
            # B. THE BRAIN (Classify)
            # Re-initialize Brain module for fresh context?? 
            # Actually, we might want to pass previous context if we were smart, 
            # but for now let's just treat it as new chunks that will be appended.
            brain_module = BioBrain() 
            
            for element in layout_elements:
                normalized_result = brain_module.normalize_text(element['text'])
                element['text'] = normalized_result['corrected']
                bab_id, bab_title = brain_module.semantic_mapping(element)
                
                supplementary_data.append({
                    "chapter_id": bab_id,
                    "chapter_title": bab_title,
                    "type": element['type'],
                    "original": normalized_result['original'],
                    "normalized": normalized_result['corrected'],
                    "typos": normalized_result['typos'],
                    "has_typo": normalized_result['has_typo'],
                    "text_confidence": normalized_result['confidence'],
                    "match_score": 100,
                    "crop_url": element['crop_url'],
                    "crop_local": element['crop_local']
                })
            
            # Cleanup
            import time
            if not isinstance(img_src, str):
                 try:
                     if os.path.exists(page_path):
                         os.remove(page_path)
                 except: pass

        # STEP 3: MERGE & RE-BUILD
        combined_data = original_data + supplementary_data
        
        # Sort headers? No, append is safer for now unless we have page numbers. 
        # Ideally user uploads Part 1 then Part 2.
        
        # Update session data
        active_sessions[session_id]["structured_data"] = combined_data
        active_sessions[session_id]["images_count"] += total_pages
        
        # Re-run Architect
        progress_tracker[session_id]["message"] = "Regenerating reports with merged data..."
        result = architect_module.build_report(combined_data, base_filename) # Keep original filename as base
        
        word_url = f"http://127.0.0.1:8000/files/{result['word_file']}"
        pdf_url = f"http://127.0.0.1:8000/files/{result['pdf_file']}" if result['pdf_file'] else None
        
        progress_tracker[session_id].update({
            "status": "complete",
            "message": "Supplementary merge complete!"
        })
        
        return {
            "success": True,
            "session_id": session_id,
            "results": combined_data,
            "word_url": word_url,
            "pdf_url": pdf_url,
            "total_pages": active_sessions[session_id]["images_count"],
            "missing_chapters": list(set(["BAB 1", "BAB 2", "BAB 3", "BAB 4", "BAB 5", "BAB 6", "BAB 7"]) - set(item['chapter_id'] for item in combined_data))
        }

    except Exception as e:
        logger.error(f"Supplement Workflow Failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

# Helper
def convert_pdf_to_images_safe(path):
    from pdf2image import convert_from_path
    poppler = os.environ.get('POPPLER_PATH')
    if not poppler:
         for p in [r"C:\poppler\Library\bin", r"C:\poppler\bin"]:
             if os.path.exists(p):
                 poppler = p
                 break
    try:
        return convert_from_path(path, dpi=200, poppler_path=poppler)
    except:
        return convert_from_path(path, dpi=200)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)