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
        Teknik Image Processing untuk membersihkan noise/watermark.
        Menggunakan Adaptive Thresholding.
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Adaptive Thresholding: Bagus untuk memisahkan teks hitam dari background keruh/watermark
        # Block Size 11, C=2
        clean_img = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                          cv2.THRESH_BINARY, 11, 2)
        
        # Note: Untuk OCR, binary image ini bagus. 
        # Tapi untuk 'Cropping' gambar (Figures), kita mungkin ingin gambar asli berwarna.
        # Jadi fungsi ini me-return gambar bersih untuk keperluan OCR.
        return clean_img

    def scan_document(self, image_path, filename_base):
        """
        Layout Analysis: Identifikasi elemen (Teks, Tabel, Gambar).
        """
        original_img = cv2.imread(image_path)
        
        # 1. Pre-process for better OCR (The Eye cleans the image)
        clean_for_ocr = self.remove_watermark(original_img)
        
        # 2. Run AI Layout Analysis
        # Note: We pass original_img to PPStructure as it handles its own pre-processing internally usually,
        # but conceptually "The Eye" manages this.
        result = self.engine(original_img)
        
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
                # Safety clip
                x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
                
                crop_img = original_img[y1:y2, x1:x2]
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
                'defibrillator', 'sphygmomanometer', 'electrocardiogram', 'ecg', 'ekg',
                'oximeter', 'nebulizer', 'ventilator', 'stethoscope', 'thermometer',
                'syringe', 'catheter', 'cannula', 'tourniquet', 'autoclave',
                'sterilization', 'disinfection', 'biomedical', 'biosafety'
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
    Fixed-Layout Export dengan LOCKED settings.
    """
    def __init__(self):
        pass
    
    def _set_fixed_margins(self, doc):
        """Lock document margins and page size"""
        sections = doc.sections
        for section in sections:
            # Page Size (Letter) - LOCKED
            section.page_height = Inches(11)
            section.page_width = Inches(8.5)
            
            # Margins (FIXED) - LOCKED
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1.25)
            section.right_margin = Inches(1.25)
            
            # Header/Footer spacing
            section.header_distance = Inches(0.5)
            section.footer_distance = Inches(0.5)
    
    def _set_fixed_styles(self, doc):
        """Lock font and paragraph styles"""
        
        # Normal Style - LOCKED
        normal_style = doc.styles['Normal']
        normal_font = normal_style.font
        normal_font.name = 'Arial'
        normal_font.size = Pt(11)
        normal_font.color.rgb = RGBColor(0, 0, 0)
        
        normal_para = normal_style.paragraph_format
        normal_para.line_spacing = 1.15
        normal_para.space_after = Pt(6)
        
        # Heading 1 (Chapter Titles) - LOCKED
        h1_style = doc.styles['Heading 1']
        h1_font = h1_style.font
        h1_font.name = 'Arial'
        h1_font.size = Pt(16)
        h1_font.bold = True
        h1_font.color.rgb = RGBColor(0, 0, 0)
        
        h1_para = h1_style.paragraph_format
        h1_para.space_before = Pt(12)
        h1_para.space_after = Pt(6)
        h1_para.keep_with_next = True
        
        # Heading 2 (Subtitles) - LOCKED
        h2_style = doc.styles['Heading 2']
        h2_font = h2_style.font
        h2_font.name = 'Arial'
        h2_font.size = Pt(14)
        h2_font.bold = True
        h2_font.color.rgb = RGBColor(31, 56, 100)  # Dark blue
        
        h2_para = h2_style.paragraph_format
        h2_para.space_before = Pt(10)
        h2_para.space_after = Pt(4)

    def build_report(self, classified_data, original_filename):
        from datetime import datetime
        
        doc = Document()
        
        # ===== APPLY FIXED LAYOUT SETTINGS =====
        self._set_fixed_margins(doc)
        self._set_fixed_styles(doc)
        
        # Document Title Page
        title = doc.add_heading('BioManual Standardization Report', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        doc.add_paragraph(f"Source Document: {original_filename}")
        doc.add_paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        doc.add_paragraph("Powered by BioManual Auto-Standardizer AI").italic = True
        
        doc.add_page_break()
        
        # Grouping Data by Chapter
        grouped = {k: [] for k in BioBrain().taxonomy.keys()}
        for item in classified_data:
            key = item['chapter_id']
            if key in grouped:
                grouped[key].append(item)
            else:
                grouped["BAB 1"].append(item) # Fallback

        # Construction Loop
        for bab_id, items in grouped.items():
            bab_title = BioBrain().taxonomy[bab_id]["title"]
            
            # Chapter Header
            h = doc.add_heading(f"{bab_id}: {bab_title}", level=1)
            h.alignment = WD_ALIGN_PARAGRAPH.LEFT
            
            if not items:
                p = doc.add_paragraph("[Tidak ada konten terdeteksi]")
                p.italic = True
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                doc.add_page_break()
                continue
                
            for item in items:
                content_type = item['type']
                text = item['normalized']
                
                # Handling Elements
                if content_type == 'title':
                    doc.add_heading(text, level=2)
                
                elif content_type in ['figure', 'table']:
                    # Visual Evidence
                    if item['crop_local'] and os.path.exists(item['crop_local']):
                        # Label
                        label = doc.add_paragraph()
                        label_run = label.add_run(f"[{content_type.upper()}]")
                        label_run.bold = True
                        label_run.font.color.rgb = RGBColor(31, 56, 100)
                        
                        # Image with FIXED width
                        try:
                            doc.add_picture(item['crop_local'], width=Inches(5))
                            
                            # Center align
                            last_paragraph = doc.paragraphs[-1]
                            last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            
                        except Exception as e:
                            logger.error(f"Error adding picture: {e}")
                            doc.add_paragraph(f"[Image error: {e}]")
                        
                        # Caption
                        if text and text != "[TABLE DATA DETECTED]":
                            caption = doc.add_paragraph(text)
                            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            caption.runs[0].italic = True
                            caption.runs[0].font.size = Pt(9)
                    else:
                        doc.add_paragraph(f"[{content_type} detected but image missing]")
                        
                else:  # Body Text
                    p = doc.add_paragraph(text)
                    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                    
                    # Highlight if has typo
                    if item.get('has_typo'):
                        # Add warning note
                        warning = doc.add_paragraph()
                        warning_run = warning.add_run("⚠ Possible typos detected in this section")
                        warning_run.font.size = Pt(9)
                        warning_run.font.color.rgb = RGBColor(255, 165, 0)  # Orange
            
            # Page break after each chapter
            doc.add_page_break()

        # Save Word File
        word_filename = f"Standardized_{Path(original_filename).stem}.docx"
        word_path = os.path.join(BASE_PATH, word_filename)
        doc.save(word_path)
        logger.info(f"✓ Word file saved: {word_filename}")
        
        # ===== EXPORT TO PDF =====
        pdf_filename = f"Standardized_{Path(original_filename).stem}.pdf"
        pdf_path = os.path.join(BASE_PATH, pdf_filename)
        
        try:
            from docx2pdf import convert
            convert(word_path, pdf_path)
            logger.info(f"✓ PDF exported: {pdf_filename}")
        except Exception as e:
            logger.warning(f"PDF export failed (docx2pdf not available): {e}")
            logger.info("Tip: Install Microsoft Word or use alternative PDF converter")
            pdf_filename = None
        
        return {
            "word_file": word_filename,
            "pdf_file": pdf_filename
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
            images = convert_pdf_to_images_safe(temp_path)
        else:
            images = [temp_path]
        
        # Initialize list to store cleaned page URLs for frontend preview
        clean_pages_urls = []
        
        total_pages = len(images)
        progress_tracker[session_id]["total_pages"] = total_pages
        progress_tracker[session_id]["message"] = f"Processing {total_pages} page(s)..."

        # STEP 2: LOOP THROUGH PAGES
        for i, img_src in enumerate(images):
            current_page = i + 1
            
            # Update progress
            progress_tracker[session_id].update({
                "status": "processing",
                "current_page": current_page,
                "percentage": int((current_page / total_pages) * 100),
                "message": f"Processing page {current_page} of {total_pages}..."
            })
            
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

        # STEP 3: THE ARCHITECT (Build)
        progress_tracker[session_id].update({
            "status": "building",
            "percentage": 95,
            "message": "Generating Word/PDF reports..."
        })
        
        result = architect_module.build_report(structured_data, file.filename)
        
        word_url = f"http://127.0.0.1:8000/files/{result['word_file']}"
        pdf_url = f"http://127.0.0.1:8000/files/{result['pdf_file']}" if result['pdf_file'] else None
        
        # Mark as complete
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
            "clean_pages": clean_pages_urls # NEW: List of cleaned page URLs
        }

    except Exception as e:
        logger.error(f"Workflow Failed: {e}")
        import traceback
        traceback.print_exc()
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