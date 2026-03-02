"""
MANBOOK-V4 — BioManual Auto-Standardizer
=========================================
FastAPI Server & System Orchestrator

Modules:
  - bio_brain.py       → BioBrain (text normalization & chapter classification)
  - bio_architect.py   → BioArchitect (DOCX report builder)
  - vision_engine.py   → BioVisionHybrid (OCR + layout detection + AI classification)
  - openrouter_client.py → OpenRouter API client

Updated: February 2026
"""

import os
import sys
import time
import uuid
import json
import shutil
import logging
import traceback
import uvicorn
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ──────────────────────────────────────────────
# Import Modules
# ──────────────────────────────────────────────
from bio_brain import BioBrain
from bio_architect import BioArchitect

try:
    from vision_engine import create_vision_engine
    VISION_ENGINE_AVAILABLE = True
except Exception as e:
    VISION_ENGINE_AVAILABLE = False
    logging.warning(f"Vision Engine not available: {e}")

try:
    from text_corrector import correct_ocr_text as _ocr_correct
    TEXT_CORRECTOR_AVAILABLE = True
    logging.info("✓ TextCorrector loaded")
except Exception as e:
    TEXT_CORRECTOR_AVAILABLE = False
    logging.warning(f"TextCorrector not available: {e}")

def apply_text_correction(text: str, lang: str = 'id') -> str:
    """Terapkan koreksi OCR jika text_corrector tersedia."""
    if TEXT_CORRECTOR_AVAILABLE and text and text.strip():
        return _ocr_correct(text, lang=lang)
    return text

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
VISION_MODE = os.getenv('VISION_MODE', 'hybrid')

app = FastAPI(title="BioManual Auto-Standardizer")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Serve static files from backend directory (e.g., letterhead.png)
@app.get("/files/{filename}")
async def serve_backend_file(filename: str):
    file_path = os.path.join(BASE_PATH, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "File not found"}

# ==========================================
# SYSTEM ORCHESTRATOR (Integration)
# ==========================================

def initialize_vision_module():
    """Initialize vision module based on VISION_MODE setting"""
    if VISION_MODE in ['gemini', 'hybrid'] and VISION_ENGINE_AVAILABLE:
        try:
            logger.info(f"Initializing {VISION_MODE.upper()} vision mode...")
            return create_vision_engine(mode=VISION_MODE)
        except Exception as e:
            logger.error(f"Failed to initialize Vision Engine: {e}")
            logger.info("Falling back to basic mode...")
            return None
    return None

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
    print(f"\r  \033[92m[{bar}]\033[0m \033[96m{pct:3d}%\033[0m  {label}   ", end='', flush=True)
    if current >= total:
        print()  # newline when done

# ==========================================
# Helper Functions
# ==========================================
def convert_pdf_to_images_safe(path):
    from pdf2image import convert_from_path
    poppler = os.environ.get('POPPLER_PATH')
    if not poppler:
         for p in [r"C:\poppler\Library\bin", r"C:\poppler\bin"]:
             if os.path.exists(p):
                 poppler = p
                 break
    dpi = int(os.getenv('PDF_DPI', '300'))
    try:
        return convert_from_path(path, dpi=dpi, poppler_path=poppler)
    except Exception:
        return convert_from_path(path, dpi=dpi)

# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/health")
def health():
    return {"status": "BioManual System Online"}

@app.post("/start")
async def start_session():
    """Pre-register a session so frontend can poll /progress before processing starts."""
    session_id = str(uuid.uuid4())
    progress_tracker[session_id] = {
        "status": "waiting",
        "current_page": 0,
        "total_pages": 0,
        "percentage": 0,
        "message": "Mengunggah file..."
    }
    return {"session_id": session_id}

@app.get("/progress/{session_id}")
async def get_progress(session_id: str):
    """Get processing progress for a session"""
    if session_id in progress_tracker:
        return progress_tracker[session_id]
    return {"error": "Session not found"}

# NOTE: /files/{filename} endpoint already defined at top of file

# ── Language detection helper ─────────────────────────────────────
def _quick_extract_text(file_path: str, fname_lower: str) -> str:
    """
    Extract a sample of text from a file (not full OCR — just enough
    for langdetect to work, typically 300-500 characters).
    """
    text = ""

    try:
        # DOCX — fastest: python-docx reads embedded text directly
        if fname_lower.endswith(('.docx', '.doc')):
            from docx import Document
            doc = Document(file_path)
            paragraphs = []
            for para in doc.paragraphs:
                if para.text.strip():
                    paragraphs.append(para.text.strip())
                if sum(len(p) for p in paragraphs) > 800:
                    break
            text = ' '.join(paragraphs)

        # PDF — extract embedded text with PyPDF2 (no OCR needed for text PDFs)
        elif fname_lower.endswith('.pdf'):
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    pages_text = []
                    for page in reader.pages[:3]:  # First 3 pages only
                        pages_text.append(page.extract_text() or "")
                        if sum(len(p) for p in pages_text) > 800:
                            break
                    text = ' '.join(pages_text)
            except Exception:
                pass  # Will fall back to OCR below

        # IMAGE — quick OCR on thumbnail (resized for speed)
        if not text.strip() and fname_lower.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff')):
            import cv2
            img = cv2.imread(file_path)
            if img is not None:
                h, w = img.shape[:2]
                scale = min(800 / w, 600 / h, 1.0)
                if scale < 1.0:
                    img = cv2.resize(img, (int(w * scale), int(h * scale)))
                from paddleocr import PaddleOCR
                ocr = PaddleOCR(use_angle_cls=False, lang='en', show_log=False)
                result = ocr.ocr(img, cls=False)
                if result and result[0]:
                    text = ' '.join(line[1][0] for line in result[0] if line[1][1] > 0.4)

    except Exception as e:
        logger.warning(f"quick_extract_text error: {e}")

    return text.strip()


def _detect_lang_from_text(text: str) -> dict:
    """
    Detect language using langdetect with Indonesian/English keyword heuristic
    as a secondary validator.
    Returns: {detected, confidence, label, message}
    """
    if not text or len(text) < 30:
        return {
            "detected": None,
            "confidence": 0.0,
            "label": "Tidak Diketahui",
            "message": "Teks terlalu sedikit untuk mendeteksi bahasa."
        }

    # ── Keyword heuristic (fast, reliable for ID vs EN) ──────────
    text_lower = text.lower()
    id_keywords = ['dan', 'yang', 'dengan', 'atau', 'untuk', 'pada', 'adalah',
                   'ini', 'itu', 'dari', 'tidak', 'bab', 'halaman', 'serta',
                   'dalam', 'akan', 'dapat', 'telah', 'juga', 'oleh']
    en_keywords = ['the', 'and', 'for', 'with', 'this', 'that', 'from', 'not',
                   'chapter', 'page', 'use', 'user', 'manual', 'installation',
                   'operation', 'maintenance', 'warning', 'caution', 'table']

    id_hits = sum(1 for kw in id_keywords if f' {kw} ' in f' {text_lower} ')
    en_hits = sum(1 for kw in en_keywords if f' {kw} ' in f' {text_lower} ')
    total   = id_hits + en_hits or 1

    kw_lang       = 'id' if id_hits >= en_hits else 'en'
    kw_confidence = max(id_hits, en_hits) / total

    # ── langdetect (statistical model) ───────────────────────────
    ld_lang = None
    ld_confidence = 0.0
    try:
        from langdetect import detect_langs
        results = detect_langs(text)
        # Filter to id/en only (langdetect returns ISO codes)
        for r in results:
            if r.lang in ('id', 'en'):
                ld_lang = r.lang
                ld_confidence = round(r.prob, 2)
                break
    except Exception as e:
        logger.warning(f"langdetect error: {e}")

    # ── Combine: keyword heuristic wins if langdetect unclear ────
    if ld_lang and ld_confidence >= 0.70:
        final_lang = ld_lang
        final_conf = ld_confidence
    else:
        final_lang = kw_lang
        final_conf = round(kw_confidence, 2)

    # ── Human-readable response ───────────────────────────────────
    if final_lang == 'id':
        label   = "Bahasa Indonesia"
        flag    = "🇮🇩"
        message = f"{flag} Dokumen terdeteksi sebagai Bahasa Indonesia. Tesseract OCR akan digunakan."
    else:
        label   = "English"
        flag    = "🇬🇧"
        message = f"{flag} Document detected as English. PaddleOCR will be used."

    # Confidence tier
    if final_conf >= 0.85:
        confidence_label = "Sangat Yakin" if final_lang == 'id' else "High Confidence"
    elif final_conf >= 0.60:
        confidence_label = "Cukup Yakin" if final_lang == 'id' else "Medium Confidence"
    else:
        confidence_label = "Kurang Yakin" if final_lang == 'id' else "Low Confidence"

    return {
        "detected"          : final_lang,
        "confidence"        : final_conf,
        "confidence_label"  : confidence_label,
        "label"             : label,
        "message"           : message,
        "id_keyword_hits"   : id_hits,
        "en_keyword_hits"   : en_hits,
    }


@app.post("/detect-language")
async def detect_language(file: UploadFile = File(...)):
    """
    Quickly detect the language of an uploaded document without full OCR.
    Used by the frontend immediately after file selection to suggest a language.

    Returns:
      - detected: 'id' | 'en' | null
      - confidence: 0.0 - 1.0
      - label: human-readable language name
      - message: UI notification text
    """
    fname_lower = file.filename.lower()
    temp_path   = os.path.join(BASE_PATH, f"_langdetect_temp_{file.filename}")

    try:
        # Save uploaded file temporarily
        with open(temp_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)

        # Extract sample text
        sample_text = _quick_extract_text(temp_path, fname_lower)
        logger.info(f"📝 LangDetect: extracted {len(sample_text)} chars from {file.filename}")

        # Detect language
        result = _detect_lang_from_text(sample_text)
        result["filename"] = file.filename
        result["sample_length"] = len(sample_text)

        return result

    except Exception as e:
        logger.error(f"detect-language error: {e}")
        return {
            "detected"   : None,
            "confidence" : 0.0,
            "label"      : "Error",
            "message"    : f"Tidak dapat mendeteksi bahasa: {str(e)}"
        }
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/process")
async def process_workflow(request: Request, file: UploadFile = File(...)):
    # Gunakan session_id dan language dari header
    session_id = request.headers.get("X-Session-Id") or str(uuid.uuid4())
    doc_language = request.headers.get("X-Language", "id")  # 'id' or 'en'

    # Initialize Brain per request (fresh context)
    brain_module = BioBrain()
    # Set initial context based on language
    brain_module.current_context = "Chapter 1" if doc_language == 'en' else "BAB 1"
    logger.info(f"Starting BioManual Workflow for: {file.filename} (Session: {session_id})")

    temp_path = os.path.join(BASE_PATH, f"temp_{file.filename}")
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    structured_data = []

    # Initialize / reset progress (session bisa sudah ada dari /start)
    progress_tracker[session_id] = {
        "status": "starting",
        "current_page": 0,
        "total_pages": 0,
        "percentage": 0,
        "message": "Initializing..."
    }

    try:
        # Variabel default (dipakai oleh image/pdf branch; DOCX tidak perlu)
        images = []
        clean_pages_urls = []
        total_pages = 0

        # Normalize filename extension
        fname_lower = file.filename.lower()

        # ─── BRANCH: DOCX / DOC ─────────────────────────────────────────
        if fname_lower.endswith('.docx') or fname_lower.endswith('.doc'):
            print(f"\n{'='*60}")
            print(f"  📝 File   : {file.filename}")
            print(f"  🔄 Step 1 : Converting Word document to PDF for Visual Scanning...")
            print(f"{'='*60}")

            progress_tracker[session_id].update({
                "status": "processing",
                "message": "Converting Word to PDF to preserve visual tables...",
                "percentage": 10,
            })

            from docx2pdf import convert
            pdf_path = temp_path + ".pdf"
            try:
                import pythoncom
                pythoncom.CoInitialize()  # Required for COM in threads (Windows)
                convert(temp_path, pdf_path)
                temp_path = pdf_path       # Point to PDF for subsequent processing
                fname_lower = fname_lower + ".pdf"  # So it enters PDF branch below
            except Exception as e:
                logger.error(f"Cannot convert Word to PDF: {e}")
                return {"success": False, "error": f"Gagal mengonversi Word ke format visual: {e}"}

        # ─── BRANCH: PDF / IMAGE ─────────────────────────────────────────
        if fname_lower.endswith('.pdf'):
            progress_tracker[session_id]["message"] = "Converting PDF to images..."
            print(f"\n{'='*60}")
            print(f"  📄 File   : {file.filename}")
            print(f"  🔄 Step 1 : Converting PDF to images...")
            print(f"{'='*60}")
            images = convert_pdf_to_images_safe(temp_path)
        else:
            images = [temp_path]

        total_pages = len(images)
        progress_tracker[session_id]["total_pages"] = total_pages
        progress_tracker[session_id]["message"] = f"Processing {total_pages} page(s)..."
        progress_tracker[session_id]["status"] = "processing"

        print(f"\n  📑 Total  : {total_pages} halaman")
        print(f"  🔄 Step 2 : Scanning setiap halaman...")

        # Chapter titles lookup (both Indonesian and English)
        chapter_titles = {
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

        # ───── MAIN PROCESSING LOOP ─────────────────────────────────
        for i, img_src in enumerate(images):
            current_page = i + 1
            pct = int((current_page / total_pages) * 100)

            progress_tracker[session_id].update({
                "status": "processing",
                "current_page": current_page,
                "percentage": pct,
                "message": f"Processing page {current_page} of {total_pages}..."
            })
            _print_progress(current_page, total_pages, f"Hal. {current_page}/{total_pages}  ({pct}%)")
            logger.info(f"Processing page {current_page}/{total_pages}")

            # Resolve image path
            page_path = img_src
            if not isinstance(img_src, str):
                page_path = os.path.join(BASE_PATH, f"page_{i}.png")
                img_src.save(page_path, "PNG")

            # A. THE EYE (Scan) — pass language for OCR engine selection
            scan_result = vision_module.scan_document(page_path, f"{file.filename}_{i}", lang=doc_language)

            # Handle return format
            if isinstance(scan_result, list):
                layout_elements = scan_result
                clean_img_url = None
            else:
                layout_elements = scan_result.get('elements', [])
                clean_path = scan_result.get('clean_image_path')
                if clean_path and os.path.exists(clean_path):
                    from urllib.parse import quote
                    fname_base = os.path.basename(clean_path)
                    clean_img_url = f"http://127.0.0.1:8000/output/{quote(fname_base)}"
                    clean_pages_urls.append(clean_img_url)
                    logger.info(f"📷 Preview page {current_page}: {clean_img_url}")
                else:
                    clean_img_url = None

            # B. THE BRAIN (Classify + Normalize)
            for element in layout_elements:
                normalized_result = brain_module.normalize_text(element['text'], lang=doc_language)
                # Terapkan text_corrector SETELAH BioBrain (koreksi OCR lebih presisi)
                corrected = apply_text_correction(normalized_result['corrected'], lang=doc_language)
                element['text'] = corrected
                normalized_result['corrected'] = corrected

                # Detect element language (from AI or auto-detect from text)
                elem_lang = element.get('lang', '')
                if not elem_lang:
                    txt_lower = element['text'].lower()
                    en_keywords = ['the', 'and', 'for', 'user', 'manual', 'this', 'with', 'installation',
                                   'operation', 'maintenance', 'warning', 'caution', 'chapter',
                                   'table', 'figure', 'if', 'is', 'are', 'can', 'not', 'may']
                    en_hits = sum(1 for kw in en_keywords if f' {kw} ' in f' {txt_lower} ')
                    elem_lang = 'en' if en_hits >= 2 else 'id'

                # Use AI-provided chapter if available, else fallback to BioBrain
                bab_id = element.get('chapter', '')
                if bab_id and bab_id in chapter_titles:
                    bab_title = chapter_titles[bab_id]
                else:
                    bab_id, bab_title = brain_module.semantic_mapping(element)

                # Remap BAB→Chapter or Chapter→BAB based on selected language
                if doc_language == 'en' and bab_id.startswith('BAB '):
                    bab_num = bab_id.replace('BAB ', '')
                    new_key = f"Chapter {bab_num}"
                    if new_key in chapter_titles:
                        bab_id = new_key
                        bab_title = chapter_titles[new_key]
                elif doc_language == 'id' and bab_id.startswith('Chapter '):
                    bab_num = bab_id.replace('Chapter ', '')
                    new_key = f"BAB {bab_num}"
                    if new_key in chapter_titles:
                        bab_id = new_key
                        bab_title = chapter_titles[new_key]

                structured_data.append({
                    "chapter_id": bab_id,
                    "chapter_title": bab_title,
                    "type": element['type'],
                    "original": normalized_result['original'],
                    "normalized": normalized_result['corrected'],
                    "typos": normalized_result['typos'],
                    "has_typo": normalized_result['has_typo'],
                    "text_confidence": element.get('confidence', 1.0),
                    "match_score": 100,
                    "lang": elem_lang,
                    "crop_url": element.get('crop_url'),
                    "crop_local": element.get('crop_local')
                })

            # Cleanup temp page image
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

        # 2.5 CHECK MISSING CHAPTERS (Report only — no auto-generation)
        existing_chapters = set(item['chapter_id'] for item in structured_data)
        all_chapters = [f"Chapter {i}" for i in range(1, 8)] if doc_language == 'en' else [f"BAB {i}" for i in range(1, 8)]
        
        missing = set(all_chapters) - existing_chapters
        if missing:
            logger.info(f"⚠️ Missing chapters: {sorted(missing)}")

        # STEP 3: THE ARCHITECT (Build)
        progress_tracker[session_id].update({
            "status": "building",
            "percentage": 95,
            "message": "Generating Word/PDF reports..."
        })
        print(f"\n  🏗️  Step 3 : Menyusun laporan Word ({len(structured_data)} elemen)...")
        
        result = architect_module.build_report(structured_data, file.filename, lang=doc_language)
        
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
            "clean_pages": clean_pages_urls,
            "missing_chapters": list(set(all_chapters) - existing_chapters)
        }

    except Exception as e:
        logger.error(f"Workflow Failed: {e}")
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
async def supplement_workflow(session_id: str, files: list[UploadFile] = File(...)):
    """
    Endpoint untuk mengupload file tambahan ke sesi yang sudah ada.
    Menggabungkan hasil ekstraksi baru dengan yang lama.
    Mendukung multiple files upload sekaligus.
    """
    if session_id not in active_sessions:
        return {"success": False, "error": "Session ID not found or expired"}
    
    existing_session = active_sessions[session_id]
    original_data = existing_session["structured_data"]
    base_filename = existing_session["original_filename"]
    
    file_names = [f.filename for f in files]
    logger.info(f"Supplementing Session {session_id} with files: {file_names}")
    
    progress_tracker[session_id].update({
        "status": "processing_supplement",
        "message": f"Processing {len(files)} supplementary file(s)..."
    })

    supplementary_data = []
    total_new_pages = 0

    try:
        brain_module = BioBrain() 
        current_page_offset = existing_session.get("images_count", 0)

        for file_index, file in enumerate(files):
            temp_path = os.path.join(BASE_PATH, f"temp_supp_{session_id}_{file.filename}")
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
                
            # STEP 1: IMAGE CONVERSION (Reuse logic)
            images = []
            if file.filename.lower().endswith('.pdf'):
                images = convert_pdf_to_images_safe(temp_path)
            else:
                images = [temp_path]
                
            total_pages = len(images)
            total_new_pages += total_pages
            
            # Detect language from existing data
            existing_chapter_ids = set(item.get('chapter_id') for item in original_data + supplementary_data if item.get('chapter_id'))
            supp_lang = 'en' if any(ch.startswith('Chapter') for ch in existing_chapter_ids) else 'id'
            
            # STEP 2: LOOP & PROCESS
            for i, img_src in enumerate(images):
                # Resolve image path
                page_path = img_src
                if not isinstance(img_src, str):
                    page_path = os.path.join(BASE_PATH, f"supp_{session_id}_{file_index}_{i}.png")
                    img_src.save(page_path, "PNG")

                # A. THE EYE (Scan)
                if vision_module:
                    scan_result = vision_module.scan_document(page_path, f"supp_{file.filename}_{i}", lang=supp_lang)
                else:
                    scan_result = []
                
                if isinstance(scan_result, list):
                    layout_elements = scan_result
                else:
                    layout_elements = scan_result.get('elements', [])
                
                # B. THE BRAIN (Classify)
                all_ch = [f"Chapter {i}" for i in range(1, 8)] if supp_lang == 'en' else [f"BAB {i}" for i in range(1, 8)]
                
                for element in layout_elements:
                    normalized_result = brain_module.normalize_text(element['text'], lang=supp_lang)
                    # Terapkan text_corrector SETELAH BioBrain
                    corrected = apply_text_correction(normalized_result['corrected'], lang=supp_lang)
                    element['text'] = corrected
                    normalized_result['corrected'] = corrected
                    
                    # Cek missing chapter assignment
                    bab_id, bab_title = "", ""
                    missing_chapters = [c for c in all_ch if c not in existing_chapter_ids]

                    if missing_chapters and len(element['text'].strip()) > 10:
                        bab_id, bab_title = brain_module.semantic_mapping(element)
                        
                        # Jika Fallback ke BAB 1/Chapter 1 padahal sudah ada
                        first_ch = all_ch[0]
                        if bab_id == first_ch and first_ch not in missing_chapters:
                            bab_id = missing_chapters[0]
                            bab_title = brain_module.taxonomy[bab_id]["title"]
                            brain_module.current_context = bab_id
                    else:
                        bab_id, bab_title = brain_module.semantic_mapping(element)
                    
                    supplementary_data.append({
                        "chapter_id": bab_id,
                        "chapter_title": bab_title,
                        "type": element['type'],
                        "original": normalized_result['original'],
                        "normalized": normalized_result['corrected'],
                        "typos": normalized_result['typos'],
                        "has_typo": normalized_result['has_typo'],
                        "text_confidence": element.get('confidence', 1.0),
                        "match_score": 100,
                        "crop_url": element.get('crop_url'),
                        "crop_local": element.get('crop_local')
                    })
                
                # Cleanup
                if not isinstance(img_src, str):
                     try:
                         if os.path.exists(page_path):
                             os.remove(page_path)
                     except Exception:
                         pass
            
            # Cleanup temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # STEP 3: MERGE & RE-BUILD
        combined_data = original_data + supplementary_data
        
        # Update session data
        active_sessions[session_id]["structured_data"] = combined_data
        active_sessions[session_id]["images_count"] += total_new_pages
        
        # Re-run Architect
        progress_tracker[session_id]["message"] = "Regenerating reports with merged data..."
        result = architect_module.build_report(combined_data, base_filename)
        
        word_url = f"http://127.0.0.1:8000/files/{result['word_file']}"
        pdf_url = f"http://127.0.0.1:8000/files/{result['pdf_file']}" if result['pdf_file'] else None
        
        progress_tracker[session_id].update({
            "status": "complete",
            "message": "Supplementary merge complete!"
        })
        
        # Detect language for missing chapters
        all_ch_final = [f"Chapter {i}" for i in range(1, 8)] if supp_lang == 'en' else [f"BAB {i}" for i in range(1, 8)]
        
        return {
            "success": True,
            "session_id": session_id,
            "results": combined_data,
            "word_url": word_url,
            "pdf_url": pdf_url,
            "total_pages": active_sessions[session_id]["images_count"],
            "missing_chapters": list(set(all_ch_final) - set(item['chapter_id'] for item in combined_data))
        }

    except Exception as e:
        logger.error(f"Supplement Workflow Failed: {e}")
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)