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

from fastapi import FastAPI, UploadFile, File, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import cv2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ──────────────────────────────────────────────
# Import Modules
# ──────────────────────────────────────────────
from bio_brain import BioBrain
from bio_architect import BioArchitect
from language_filter import enforce_language, enforce_language_on_items, get_language_instruction, clean_text

try:
    from vision_engine import create_vision_engine
    VISION_ENGINE_AVAILABLE = True
except Exception as e:
    VISION_ENGINE_AVAILABLE = False
    logging.warning(f"Vision Engine not available: {e}")

try:
    from direct_reader import is_text_pdf, extract_docx_direct, extract_pdf_direct
    DIRECT_READER_AVAILABLE = True
    logging.info("✓ DirectReader loaded (DOCX + PDF text extraction)")
except Exception as e:
    DIRECT_READER_AVAILABLE = False
    logging.warning(f"DirectReader not available: {e}")

try:
    from text_corrector import (
        correct_ocr_text as _ocr_correct,
        correct_ocr_text_with_highlights as _ocr_correct_hl,
    )
    TEXT_CORRECTOR_AVAILABLE = True
    logging.info("✓ TextCorrector loaded (with highlights support)")
except Exception as e:
    TEXT_CORRECTOR_AVAILABLE = False
    logging.warning(f"TextCorrector not available: {e}")

def apply_text_correction(text: str, lang: str = 'id') -> str:
    """Terapkan koreksi OCR jika text_corrector tersedia (tanpa highlights)."""
    if TEXT_CORRECTOR_AVAILABLE and text and text.strip():
        return _ocr_correct(text, lang=lang)
    return text

def apply_text_correction_with_highlights(text: str, lang: str = 'id') -> dict:
    """
    Terapkan koreksi OCR dan kembalikan juga highlights kata meragukan.
    Returns: { 'text': str, 'highlights': list }
    """
    if TEXT_CORRECTOR_AVAILABLE and text and text.strip():
        return _ocr_correct_hl(text, lang=lang)
    return {'text': text, 'highlights': []}

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
file_handler = logging.FileHandler('backend.log', encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - [BioManual] - %(message)s'))
logger.addHandler(file_handler)

# Configuration: Choose vision engine mode
VISION_MODE = os.getenv('VISION_MODE', 'hybrid')

app = FastAPI(title="BioManual Auto-Standardizer")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

# Serve static files from backend directory (e.g., letterhead.png)
@app.api_route("/files/{filename}", methods=["GET", "HEAD"])
async def serve_backend_file(filename: str):
    file_path = os.path.join(BASE_PATH, filename)
    if os.path.exists(file_path):
        from fastapi.responses import FileResponse
        content_type = "application/pdf" if filename.lower().endswith('.pdf') else None
        return FileResponse(file_path, media_type=content_type)
    from fastapi import Response
    return Response(content="File not found", status_code=404)

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


def _split_columns_simple(image_path, filename_base):
    """
    Deteksi dan crop kolom pada halaman dokumen menggunakan whitespace analysis.
    
    Cara kerja (simple & reliable):
      1. Convert ke grayscale → threshold → biner
      2. Hitung vertical projection (jumlah pixel gelap per kolom-x)
      3. Cari celah lebar (banyak pixel putih berturut-turut) → column gap
      4. Crop setiap kolom → simpan sebagai file terpisah
    
    Returns: list of image paths (1 per column). Jika single-column → [original_path]
    """
    import cv2
    import numpy as np
    
    img = cv2.imread(image_path)
    if img is None:
        return [image_path]
    
    h, w = img.shape[:2]
    
    # Minimum width untuk multi-column detection (dokumen kecil biasa 1 kolom)
    if w < 800:
        return [image_path]
    
    # Convert ke grayscale dan binarize
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    
    # Vertical projection: hitung persentase pixel putih per kolom-x
    # Ignore top 5% dan bottom 5% (header/footer biasanya full-width)
    margin_y = int(h * 0.05)
    roi = binary[margin_y:h - margin_y, :]
    
    # Untuk setiap kolom x, hitung berapa % pixel yang putih
    white_ratio = np.mean(roi == 255, axis=0)  # array shape (w,)
    
    # Smooth dengan moving average untuk menghilangkan noise
    kernel_size = max(5, w // 100)
    kernel = np.ones(kernel_size) / kernel_size
    white_smooth = np.convolve(white_ratio, kernel, mode='same')
    
    # Cari region yang "hampir semua putih" (> 95% putih) → column gap
    # 95% lebih akurat dari 90% — menghindari false gap dari noise
    gap_threshold = 0.95
    is_gap = white_smooth > gap_threshold
    
    # Cari gap yang cukup lebar (minimal 1.5% dari lebar halaman)
    min_gap_width = max(15, int(w * 0.015))
    
    # Find contiguous gap segments
    gaps = []
    in_gap = False
    gap_start = 0
    for x in range(w):
        if is_gap[x] and not in_gap:
            gap_start = x
            in_gap = True
        elif not is_gap[x] and in_gap:
            gap_width = x - gap_start
            if gap_width >= min_gap_width:
                gap_center = gap_start + gap_width // 2
                # Ignore gaps too close to edges (within 5% of page width)
                if gap_center > w * 0.08 and gap_center < w * 0.92:
                    gaps.append(gap_center)
            in_gap = False
    
    if not gaps:
        logger.info(f"📊 Column split: no column gaps found — single column")
        return [image_path]
    
    # Build column boundaries
    col_boundaries = [0] + sorted(gaps) + [w]
    num_cols = len(col_boundaries) - 1
    
    # Sanity: max 6 columns (lebih dari itu kemungkinan noise)
    if num_cols > 6:
        logger.warning(f"📊 Too many columns detected ({num_cols}) — likely noise, skipping split")
        return [image_path]
    
    logger.info(f"📊 Column split: detected {num_cols} columns (gaps at x={[int(g) for g in gaps]})")
    
    # Crop each column
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(backend_dir, "output_results")
    os.makedirs(output_dir, exist_ok=True)
    
    column_paths = []
    for col_idx in range(num_cols):
        col_x1 = int(col_boundaries[col_idx])
        col_x2 = int(col_boundaries[col_idx + 1])
        
        # Small padding
        pad = max(3, int(w * 0.003))
        col_x1 = max(0, col_x1 - pad)
        col_x2 = min(w, col_x2 + pad)
        
        # Skip very narrow columns (< 10% of page width — likely noise)
        if (col_x2 - col_x1) < w * 0.10:
            continue
        
        col_img = img[0:h, col_x1:col_x2]
        
        col_fname = f"COL_{filename_base}_c{col_idx + 1}.png"
        col_path = os.path.join(output_dir, col_fname)
        cv2.imwrite(col_path, col_img)
        column_paths.append(col_path)
        
        logger.info(f"   Column {col_idx + 1}: x={col_x1}-{col_x2} ({col_x2-col_x1}px wide)")
    
    if len(column_paths) <= 1:
        # Hanya 1 kolom valid → kembalikan original
        return [image_path]
    
    return column_paths

# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/health")
def health():
    return {"status": "BioManual System Online"}

class GenerateChapterRequest(BaseModel):
    chapter_id: str
    product_name: str
    product_desc: str
    lang: str = "id"

@app.post("/generate_chapter")
async def generate_chapter(req: GenerateChapterRequest):
    try:
        from openrouter_client import get_openrouter_client
        from bio_brain import BioBrain
        import json, re
        
        client = get_openrouter_client()
        if not client:
            return {"success": False, "error": "AI client not configured."}
            
        lang_str = "Bahasa Indonesia" if req.lang == "id" else "English"
        
        # Get actual chapter title from taxonomy
        brain = BioBrain()
        chapter_title = ""
        if req.chapter_id in brain.taxonomy:
            chapter_title = brain.taxonomy[req.chapter_id]["title"]
            
        # Bilingual Support
        if req.lang == "en":
            table_instruction = "Use clear explanatory paragraphs."
            if req.chapter_id in ('BAB 5', 'Chapter 5'):
                table_instruction = """BECAUSE THIS IS TROUBLESHOOTING, YOUR ANSWER MUST BE FORMATTED AS A MARKDOWN TABLE.
Example format inside the paragraph content:
| Problem | Possible Cause | Action/Solution |
|---|---|---|
| Screen is black | Power cable disconnected | Check and connect cable |"""

            prompt = f"""You are an expert technical writer for medical equipment. Format your response EXACTLY as a JSON array.

Your task is to draft content for this manual book chapter:
CHAPTER: {req.chapter_id}
TITLE: {chapter_title}

Medical Device Information:
- Product Name: {req.product_name}
- Description: {req.product_desc}

CRITICAL RULES:
1. You MUST ONLY write about topics related to "{chapter_title}".
2. DO NOT include "Technical Specifications" unless this is the Specification chapter.
3. DO NOT invent unnecessary components. Focus on standard operational procedures for this medical device.
4. {table_instruction}
5. No Markdown headers outside the JSON array. Strictly return ONLY the JSON array.

{get_language_instruction('en')}

The return format MUST BE a pure JSON array (NOT standard markdown), where each element has a "type" and "normalized". Example:
[
  {{"type": "heading", "normalized": "Routine Cleaning"}},
  {{"type": "paragraph", "normalized": "Turn off the device before starting the cleaning process..."}}
]
Output JSON ONLY. Do not write any introduction or conclusion sentences.
"""
        else:
            table_instruction = "Gunakan paragraf teks penjelasan yang jelas."
            if req.chapter_id in ('BAB 5', 'Chapter 5'):
                 table_instruction = """KARENA INI ADALAH PEMECAHAN MASALAH, FORMAT JAWABAN ANDA HARUS BERUPA TABEL MARKDOWN.
Contoh penulisan di dalam isi paragraph:
| Permasalahan | Kemungkinan Penyebab | Tindakan/Solusi |
|---|---|---|
| Layar mati | Kabel power lepas | Periksa dan pasang kabel |"""

            prompt = f"""You are an expert technical writer for medical equipment. Format your response EXACTLY as a JSON array.

Tugas Anda adalah menulis konten draf untuk manual book bagian:
BAB: {req.chapter_id}
JUDUL BAB: {chapter_title}

Informasi Alat Kesehatan:
- Nama Produk: {req.product_name}
- Deskripsi: {req.product_desc}

ATURAN SANGAT PENTING:
1. Anda HANYA boleh menulis topik seputar "{chapter_title}".
2. JANGAN memasukkan "Spesifikasi Teknis" jika ini bukan bab Spesifikasi.
3. JANGAN mengarang komponen yang tidak perlu. Fokus pada prosedur umum standar alat tersebut.
4. {table_instruction}
5. No Markdown headers outside the JSON array. Strictly return ONLY the JSON array.

{get_language_instruction('id')}

Format kembalian BUKAN markdown biasa, melainkan murni JSON array, tiap elemen memiliki "type" dan "normalized". Contoh:
[
  {{"type": "heading", "normalized": "Pembersihan Rutin"}},
  {{"type": "paragraph", "normalized": "Matikan daya alat sebelum memulai pembersihan..."}}
]
Keluarkan output JSON saja. Jangan tulis kalimat pengantar/penutup apapun.
"""
        response_text = client.call(prompt)
        
        # Enforce target language: strip ALL non-Latin characters
        response_text = enforce_language(response_text, lang=req.lang)

        cleaned_json = re.sub(r'```json\s*|\s*```', '', response_text).strip()
        # Find first [ and last ]
        start_idx = cleaned_json.find('[')
        end_idx = cleaned_json.rfind(']')
        if start_idx != -1 and end_idx != -1:
            cleaned_json = cleaned_json[start_idx:end_idx+1]
            
        items = json.loads(cleaned_json)
        
        # Ensure format and assign chapter
        for item in items:
            item["chapter_id"] = req.chapter_id
            
        return {"success": True, "items": items}
    except Exception as e:
        import traceback
        logging.error(f"Error generating chapter: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}

class CheckCompletenessRequest(BaseModel):
    chapter_id: str
    items: list[dict]
    lang: str = "id"

@app.post("/check_chapter_completeness")
async def check_chapter_completeness(req: CheckCompletenessRequest):
    try:
        from openrouter_client import get_openrouter_client
        import base64
        import re
        
        # 1. Collect unique source images for this chapter
        source_images = set()
        extracted_texts = []
        for item in req.items:
            img_path = item.get("source_image_local")
            if img_path and os.path.exists(img_path):
                source_images.add(img_path)
            
            # Build extracted text dump
            if item.get("type") in ["paragraph", "title", "heading", "list"]:
                extracted_texts.append(f"[{item.get('type')}] {item.get('normalized', '')}")
            elif item.get("type") in ["figure", "table"]:
                extracted_texts.append(f"[{item.get('type')}] (Gambar/Tabel yang diekstrak)")

        if not source_images:
            return {"success": False, "error": "Tidak ada gambar dokumen asli yang terkait dengan bab ini (Mungkin perlu re-scan/upload ulang dokumen)."}

        # 2. Build prompt
        lang_instruction = "Gunakan bahasa Indonesia." if req.lang == 'id' else "Use English language."
        prompt = f"""You are a QA Auditor for document extraction.
Tugas Anda: Bandingkan Teks Ekstraksi di bawah ini dengan ISI di GAMBAR ASLI yang dilampirkan.
Apakah ada informasi penting di gambar (paragraf, poin penting, judul, atau peringatan) yang HILANG / TIDAK TEREKSTRAK ke dalam teks?

Teks Hasil Ekstraksi Bab '{req.chapter_id}':
-----------------
{chr(10).join(extracted_texts)}
-----------------

Evaluasi secara menyeluruh. {lang_instruction}
Kembalikan HANYA format JSON valid berikut (tanpa markdown box):
{{
  "score": <0-100 angka seberapa lengkap teks mewakili keseluruhan gambar>,
  "analysis": "<String analisis singkat mengenai apa yang kurang atau informasi bahwa semuanya sudah masuk>"
}}"""

        # 3. Read images
        images_base64 = []
        for img_path in sorted(list(source_images)):
            img_cv = cv2.imread(img_path)
            if img_cv is not None:
                h, w = img_cv.shape[:2]
                if w > 1200:
                    scale = 1200 / w
                    img_cv = cv2.resize(img_cv, (int(w*scale), int(h*scale)))
                _, buffer = cv2.imencode('.jpg', img_cv, [cv2.IMWRITE_JPEG_QUALITY, 80])
                img_b64 = base64.b64encode(buffer).decode('utf-8')
                images_base64.append(img_b64)

        # 4. Call AI
        client = get_openrouter_client()
        content = [{"type": "text", "text": prompt}]
        for img_b64 in images_base64[:4]: # Limit max 4 images to save tokens/avoid 413
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}",
                    "detail": "low"
                }
            })

        logger.info(f"🔍 AI Completeness Check untuk {req.chapter_id} dengan {len(images_base64)} gambar...")
        os.environ["AI_VISION_MODEL"] = "google/gemini-2.5-flash"  # Ensure using flash for speed
        response_text = client.call(content)
        
        # Parse JSON
        cleaned_json = re.sub(r'```json\s*|\s*```', '', response_text).strip()
        start_idx = cleaned_json.find('{')
        end_idx = cleaned_json.rfind('}')
        if start_idx != -1 and end_idx != -1:
            cleaned_json = cleaned_json[start_idx:end_idx+1]
            
        result = json.loads(cleaned_json)
        return {"success": True, "score": result.get("score", 0), "analysis": result.get("analysis", "")}

    except Exception as e:
        import traceback
        logging.error(f"Completeness Check Error: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}

class GenerateReportRequest(BaseModel):
    items: list[dict]
    filename: str
    lang: str = "id"
    custom_product_name: str | None = None
    custom_product_desc: str | None = None

@app.post("/generate_custom_report")
async def generate_custom_report(req: GenerateReportRequest):
    try:
        # ── Debug: trace crop_local values ──
        fig_count = 0
        crop_found = 0
        crop_missing = 0
        for item in req.items:
            if item.get('type') in ('figure', 'table'):
                fig_count += 1
                cl = item.get('crop_local')
                cu = item.get('crop_url')
                if cl and os.path.exists(cl):
                    crop_found += 1
                    logger.info(f"✅ crop_local EXISTS: {cl}")
                else:
                    crop_missing += 1
                    logger.warning(
                        f"❌ crop_local MISSING: {cl!r} "
                        f"(exists={os.path.exists(cl) if cl else 'N/A'}, "
                        f"crop_url={cu!r}, "
                        f"keys={list(item.keys())})"
                    )
        logger.info(f"📊 Export: {fig_count} figures/tables, {crop_found} crops found, {crop_missing} crops missing")

        # Panggil BioArchitect dengan data "items" baru yang sudah di-edit pengguna
        result = architect_module.build_report(
            req.items, req.filename, lang=req.lang,
            custom_product_name=req.custom_product_name,
            custom_product_desc=req.custom_product_desc
        )
        word_filename = result.get('word_file')
        pdf_filename = result.get('pdf_file')
        
        if word_filename:
            from urllib.parse import quote
            word_url = f"http://127.0.0.1:8000/files/{quote(word_filename)}"
            pdf_url = f"http://127.0.0.1:8000/files/{quote(pdf_filename)}" if pdf_filename else None
            docx_path = os.path.join(architect_module.base_path, word_filename)
            return {
                "success": True,
                "word_url": word_url,
                "pdf_url": pdf_url,
                "local_path": docx_path,
            }
        else:
            return {"success": False, "error": "Report build failed or file not found"}
    except Exception as e:
        import traceback
        logging.error(f"Error in /generate_custom_report: {e}\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}

class RecropRequest(BaseModel):
    source_image_local: str
    bbox: list[int]
    element_type: str

@app.post("/recrop")
async def recrop_image(req: RecropRequest):
    try:
        if not os.path.exists(req.source_image_local):
            return {"success": False, "error": "Source image not found on server"}
            
        img = cv2.imread(req.source_image_local)
        if img is None:
            return {"success": False, "error": "Failed to load source image"}
            
        x1, y1, x2, y2 = req.bbox
        h, w = img.shape[:2]
        
        # Validasi batas gambar
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(w, int(x2)), min(h, int(y2))
        
        if x2 <= x1 or y2 <= y1:
            return {"success": False, "error": "Invalid bbox dimensions"}
            
        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return {"success": False, "error": "Empty crop area"}
            
        crop_fname = f"recrop_{req.element_type}_{uuid.uuid4().hex[:6]}.png"
        crop_path = os.path.join(OUTPUT_DIR, crop_fname)
        cv2.imwrite(crop_path, crop)
        
        from urllib.parse import quote
        crop_url = f"http://127.0.0.1:8000/output/{quote(crop_fname)}"
        
        logger.info(f"✂️ Re-cropped {req.element_type} to: {req.bbox}")
        
        return {
            "success": True,
            "crop_url": crop_url,
            "crop_local": crop_path
        }
    except Exception as e:
        logger.error(f"Recrop error: {e}")
        return {"success": False, "error": str(e)}

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
            
            # If still not enough text, check tables (manuals often use tables for layout)
            if sum(len(p) for p in paragraphs) < 100:
                for table in doc.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            if cell.text.strip():
                                paragraphs.append(cell.text.strip())
                            if sum(len(p) for p in paragraphs) > 800:
                                break
                        if sum(len(p) for p in paragraphs) > 800:
                            break
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


def _detect_lang_with_ai(file_path: str, fname_lower: str) -> dict:
    """
    AI Vision fallback: send the first page of the document as an image
    to the AI model and ask it to detect the language.
    Used when text extraction yields too little text for statistical detection.
    """
    import base64

    try:
        from openrouter_client import get_openrouter_client
        client = get_openrouter_client()
        if not client.is_available:
            logger.warning("AI lang-detect fallback: OpenRouter not available")
            return None

        # ── Convert first page to image ──
        image_path = None
        temp_images = []

        if fname_lower.endswith('.pdf'):
            # PDF → convert first page to image
            try:
                images = convert_pdf_to_images_safe(file_path)
                if images:
                    img_path = os.path.join(BASE_PATH, f"_langdetect_ai_page.png")
                    images[0].save(img_path, "PNG")
                    image_path = img_path
                    temp_images.append(img_path)
            except Exception as e:
                logger.warning(f"AI lang-detect: PDF conversion failed: {e}")

        elif fname_lower.endswith(('.docx', '.doc')):
            # DOCX → convert to PDF first, then to image
            try:
                from docx2pdf import convert
                import pythoncom
                pythoncom.CoInitialize()
                pdf_path = file_path + "._langdetect.pdf"
                convert(file_path, pdf_path)
                temp_images.append(pdf_path)
                images = convert_pdf_to_images_safe(pdf_path)
                if images:
                    img_path = os.path.join(BASE_PATH, f"_langdetect_ai_page.png")
                    images[0].save(img_path, "PNG")
                    image_path = img_path
                    temp_images.append(img_path)
            except Exception as e:
                logger.warning(f"AI lang-detect: DOCX→PDF conversion failed: {e}")
                # Fallback: extract first image directly from docx ZIP
                try:
                    import zipfile
                    with zipfile.ZipFile(file_path, 'r') as z:
                        media_files = [f for f in z.namelist() if f.startswith('word/media/')]
                        for media_path in sorted(media_files):
                            ext = os.path.splitext(media_path)[1].lower()
                            if ext in ('.png', '.jpg', '.jpeg'):
                                img_data = z.read(media_path)
                                img_path = os.path.join(BASE_PATH, f"_langdetect_ai_page{ext}")
                                with open(img_path, 'wb') as f:
                                    f.write(img_data)
                                image_path = img_path
                                temp_images.append(img_path)
                                break
                except Exception as e2:
                    logger.warning(f"AI lang-detect: Direct DOCX image extraction failed: {e2}")

        elif fname_lower.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.tiff')):
            image_path = file_path

        if not image_path or not os.path.exists(image_path):
            logger.warning("AI lang-detect: no image available")
            # Clean up temp files
            for t in temp_images:
                if os.path.exists(t):
                    try: os.remove(t)
                    except: pass
            return None

        # ── Encode image to base64 ──
        # Resize to save tokens (max 800px wide)
        img_cv = cv2.imread(image_path)
        if img_cv is None:
            for t in temp_images:
                if os.path.exists(t):
                    try: os.remove(t)
                    except: pass
            return None

        h, w = img_cv.shape[:2]
        if w > 800:
            scale = 800 / w
            img_cv = cv2.resize(img_cv, (800, int(h * scale)))

        _, buffer = cv2.imencode('.jpg', img_cv, [cv2.IMWRITE_JPEG_QUALITY, 75])
        img_b64 = base64.b64encode(buffer).decode('utf-8')

        # ── Ask AI to detect language ──
        vision_model = os.getenv("AI_VISION_MODEL", "google/gemini-2.0-flash-001")
        old_model = client.model
        client.model = vision_model

        try:
            prompt = """Look at this document page. What language is the main text written in?
Respond with ONLY a JSON object, nothing else:
{"lang": "id" or "en", "confidence": 0.0-1.0, "reason": "brief reason"}

Use "id" for Bahasa Indonesia / Malay.
Use "en" for English.
If you see both languages, pick the DOMINANT one."""

            response = client.call(prompt, image_base64=img_b64, timeout=20)

            if not response:
                return None

            # Parse AI response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                logger.warning(f"AI lang-detect: no JSON in response: {response[:100]}")
                return None

            ai_result = json.loads(json_match.group())
            detected = ai_result.get('lang', '').lower()

            if detected not in ('id', 'en'):
                logger.warning(f"AI lang-detect: unexpected lang '{detected}'")
                return None

            ai_conf = float(ai_result.get('confidence', 0.8))
            reason = ai_result.get('reason', '')

            if detected == 'id':
                label = "Bahasa Indonesia"
                flag = "🇮🇩"
                message = f"{flag} Dokumen terdeteksi sebagai Bahasa Indonesia oleh AI Vision."
            else:
                label = "English"
                flag = "🇬🇧"
                message = f"{flag} Document detected as English by AI Vision."

            logger.info(f"🧠 AI lang-detect: {detected} (conf={ai_conf}, reason={reason})")

            return {
                "detected": detected,
                "confidence": round(ai_conf, 2),
                "confidence_label": "AI Vision",
                "label": label,
                "message": message,
                "ai_detected": True,
                "ai_reason": reason,
            }

        finally:
            client.model = old_model
            # Clean up temp files
            for t in temp_images:
                if os.path.exists(t):
                    try: os.remove(t)
                    except: pass

    except Exception as e:
        logger.error(f"AI lang-detect fallback error: {e}")
        return None


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

        # Detect language (text-based)
        result = _detect_lang_from_text(sample_text)

        # ── AI Vision Fallback: jika teks terlalu sedikit ──
        if result.get("detected") is None:
            logger.info("🧠 Text too short — trying AI Vision fallback...")
            ai_result = _detect_lang_with_ai(temp_path, fname_lower)
            if ai_result and ai_result.get("detected"):
                ai_result["filename"] = file.filename
                ai_result["sample_length"] = len(sample_text)
                return ai_result
            else:
                logger.info("⚠️ AI Vision fallback juga gagal")

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
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as e:
            logger.warning(f"Could not remove lang-detect temp file: {e}")


@app.post("/process")
async def process_workflow(request: Request, file: UploadFile = File(...)):
    # Gunakan session_id dan language dari header
    session_id = request.headers.get("X-Session-Id") or str(uuid.uuid4())
    doc_language = request.headers.get("X-Language", "id")  # 'id' or 'en'
    direct_translate = request.headers.get("X-Direct-Translate", "false") == "true"

    # Initialize Brain per request (fresh context)
    brain_module = BioBrain()
    # Set initial context based on language
    brain_module.current_context = "Chapter 1" if doc_language == 'en' else "BAB 1"
    logger.info(f"Starting BioManual Workflow for: {file.filename} (Session: {session_id}, Direct Translate: {direct_translate})")

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

        # Chapter titles lookup (both Indonesian and English) — used by all paths
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

        # ─── BRANCH: DOCX / DOC (DIRECT READ — No OCR!) ─────────────────
        use_direct_docx = False
        use_direct_pdf = False
        images = []

        if fname_lower.endswith('.docx') and DIRECT_READER_AVAILABLE:
            print(f"\n{'='*60}")
            print(f"  📝 File   : {file.filename}")
            print(f"  ⚡ Mode   : DIRECT READ (No OCR — 100% accurate)")
            print(f"{'='*60}")

            progress_tracker[session_id].update({
                "status": "processing",
                "message": "Reading Word document directly (no OCR needed)...",
                "percentage": 10,
            })

            try:
                direct_elements = extract_docx_direct(temp_path, lang=doc_language)
                if direct_elements:
                    use_direct_docx = True
                    logger.info(f"✅ DOCX Direct Read: {len(direct_elements)} elements extracted")
                else:
                    logger.warning("⚠️ DOCX Direct Read returned empty — falling back to OCR")
            except Exception as e:
                logger.warning(f"⚠️ DOCX Direct Read failed: {e} — falling back to OCR")

        if fname_lower.endswith('.doc') and not use_direct_docx:
            # .doc format needs conversion to PDF first (python-docx only supports .docx)
            print(f"\n{'='*60}")
            print(f"  📝 File   : {file.filename}")
            print(f"  🔄 Step 1 : Converting .doc to PDF for scanning...")
            print(f"{'='*60}")
            progress_tracker[session_id].update({
                "status": "processing",
                "message": "Converting .doc to PDF...",
                "percentage": 10,
            })
            from docx2pdf import convert
            pdf_path = temp_path + ".pdf"
            try:
                import pythoncom
                pythoncom.CoInitialize()
                convert(temp_path, pdf_path)
                temp_path = pdf_path
                fname_lower = fname_lower + ".pdf"
            except Exception as e:
                logger.error(f"Cannot convert .doc to PDF: {e}")
                return {"success": False, "error": f"Gagal mengonversi .doc: {e}"}

        if not use_direct_docx and fname_lower.endswith('.docx'):
            # DOCX direct read failed — convert to PDF and try OCR
            print(f"  🔄 Fallback: Converting DOCX to PDF for OCR...")
            progress_tracker[session_id].update({
                "status": "processing",
                "message": "Converting Word to PDF for OCR fallback...",
                "percentage": 10,
            })
            from docx2pdf import convert
            pdf_path = temp_path + ".pdf"
            try:
                import pythoncom
                pythoncom.CoInitialize()
                convert(temp_path, pdf_path)
                temp_path = pdf_path
                fname_lower = fname_lower + ".pdf"
            except Exception as e:
                logger.error(f"Cannot convert Word to PDF: {e}")
                return {"success": False, "error": f"Gagal mengonversi Word ke format visual: {e}"}

        # ─── BRANCH: PDF — auto-detect text vs scanned ────────────────────
        if not use_direct_docx and fname_lower.endswith('.pdf'):
            # Check if PDF is text-based
            if DIRECT_READER_AVAILABLE:
                pdf_info = is_text_pdf(temp_path)
                if pdf_info['is_text_based']:
                    print(f"\n{'='*60}")
                    print(f"  📄 File   : {file.filename}")
                    print(f"  ⚡ Mode   : PDF DIRECT READ (text-based, no OCR needed)")
                    print(f"  📊 Info   : {pdf_info['avg_chars_per_page']} chars/page, {pdf_info['total_pages']} pages")
                    print(f"{'='*60}")

                    progress_tracker[session_id].update({
                        "status": "processing",
                        "message": "Reading PDF text directly (no OCR needed)...",
                        "percentage": 15,
                    })

                    try:
                        pdf_result = extract_pdf_direct(temp_path, lang=doc_language)
                        if pdf_result and pdf_result.get('pages'):
                            use_direct_pdf = True
                            logger.info(f"✅ PDF Direct Read: {len(pdf_result['pages'])} pages")
                    except Exception as e:
                        logger.warning(f"⚠️ PDF Direct Read failed: {e} — falling back to OCR")

            # Fallback: scanned PDF → convert to images for OCR
            if not use_direct_pdf:
                progress_tracker[session_id]["message"] = "Converting PDF to images for OCR..."
                print(f"\n{'='*60}")
                print(f"  📄 File   : {file.filename}")
                print(f"  🔍 Mode   : OCR (scanned/image-based PDF)")
                print(f"  🔄 Step 1 : Converting PDF to images...")
                print(f"{'='*60}")
                images = convert_pdf_to_images_safe(temp_path)
        elif not use_direct_docx:
            images = [temp_path]

        # ═══════════════════════════════════════════════════════════════
        # DIRECT READ PATH — DOCX or text-based PDF (no OCR)
        # ═══════════════════════════════════════════════════════════════
        if use_direct_docx:
            # ── Process DOCX elements directly ──
            total_pages = 1  # DOCX treated as single "page"
            progress_tracker[session_id].update({
                "total_pages": total_pages,
                "status": "processing",
                "message": f"Processing {len(direct_elements)} extracted elements...",
                "percentage": 40,
            })

            print(f"\n  📑 Elements: {len(direct_elements)}")
            print(f"  🔄 Step 2 : Classifying & normalizing...")

            for element in direct_elements:
                if direct_translate:
                    corrected = element['text']
                    highlights = []
                    normalized_result = {
                        'original': corrected,
                        'corrected': corrected,
                        'typos': 0,
                        'has_typo': False
                    }
                    bab_id = "Chapter 1" if doc_language == 'en' else "BAB 1"
                    bab_title = "Translated Content" if doc_language == 'en' else "Konten Terjemahan"
                    elem_lang = doc_language
                else:
                    normalized_result = brain_module.normalize_text(element['text'], lang=doc_language)
                    # No OCR correction needed — text is already 100% accurate
                    corrected = normalized_result['corrected']
                    highlights = []

                    elem_lang = element.get('lang', '')
                    if not elem_lang:
                        txt_lower = element['text'].lower()
                        en_keywords = ['the', 'and', 'for', 'user', 'manual', 'this', 'with', 'installation',
                                       'operation', 'maintenance', 'warning', 'caution', 'chapter',
                                       'table', 'figure', 'if', 'is', 'are', 'can', 'not', 'may']
                        en_hits = sum(1 for kw in en_keywords if f' {kw} ' in f' {txt_lower} ')
                        elem_lang = 'en' if en_hits >= 2 else 'id'

                    bab_id = element.get('chapter', '')
                    if bab_id and bab_id in chapter_titles:
                        bab_title = chapter_titles[bab_id]
                    else:
                        bab_id, bab_title = brain_module.semantic_mapping(element)

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

                _clean_original = enforce_language(normalized_result['original'], lang=doc_language)
                _clean_normalized = enforce_language(normalized_result['corrected'], lang=doc_language)

                structured_data.append({
                    "chapter_id"    : bab_id,
                    "chapter_title" : bab_title,
                    "type"          : element['type'],
                    "original"      : _clean_original,
                    "normalized"    : _clean_normalized,
                    "typos"         : normalized_result.get('typos', 0),
                    "has_typo"      : normalized_result.get('has_typo', False),
                    "text_confidence": element.get('confidence', 1.0),
                    "match_score"   : 100,
                    "lang"          : elem_lang,
                    "crop_url"      : element.get('crop_url'),
                    "crop_local"    : element.get('crop_local'),
                    "source_image_local": None,
                    "bbox"          : element.get('bbox'),
                    "highlights"    : highlights,
                    "_direct_read"  : True,
                })

            progress_tracker[session_id]["percentage"] = 80
            print(f"  ✅ Direct read complete: {len(structured_data)} elements")

        elif use_direct_pdf:
            # ── Process PDF pages via direct text extraction ──
            pdf_pages = pdf_result['pages']
            total_pages = len(pdf_pages)
            progress_tracker[session_id].update({
                "total_pages": total_pages,
                "status": "processing",
                "message": f"Processing {total_pages} page(s) (direct read)...",
                "percentage": 20,
            })

            print(f"\n  📑 Total  : {total_pages} halaman (direct read)")
            print(f"  🔄 Step 2 : Classifying & normalizing...")

            # Also convert PDF to images for preview & figure crop
            try:
                preview_images = convert_pdf_to_images_safe(temp_path)
            except Exception:
                preview_images = []

            for page_data in pdf_pages:
                page_num = page_data['page_num']
                page_elements = page_data.get('elements', [])

                if not page_elements:
                    continue

                pct = int(((page_num + 1) / total_pages) * 80) + 20
                progress_tracker[session_id].update({
                    "current_page": page_num + 1,
                    "percentage": min(pct, 90),
                    "message": f"Processing page {page_num + 1} of {total_pages} (direct read)...",
                })
                _print_progress(page_num + 1, total_pages, f"Hal. {page_num+1}/{total_pages}")

                # Save preview image for this page
                preview_path = None
                if page_num < len(preview_images):
                    pimg = preview_images[page_num]
                    preview_fname = f"PREVIEW_{file.filename}_{page_num}.jpg"
                    preview_path = os.path.join(OUTPUT_DIR, preview_fname)
                    if not isinstance(pimg, str):
                        pimg.save(preview_path, "JPEG", quality=90)
                    else:
                        import shutil as sh
                        sh.copy2(pimg, preview_path)
                    from urllib.parse import quote
                    clean_pages_urls.append(f"http://127.0.0.1:8000/output/{quote(preview_fname)}")

                # Crop figures/tables from preview image
                original_img = None
                if preview_path and os.path.exists(preview_path):
                    original_img = cv2.imread(preview_path)

                for elem_idx, element in enumerate(page_elements):
                    # Crop visual elements (table/figure) from preview image
                    if element['type'] in ('table', 'figure') and original_img is not None:
                        h_img, w_img = original_img.shape[:2]
                        # Scale pdfplumber coords (72 DPI) to image coords (300 DPI)
                        # pdfplumber uses PDF points; preview images are at 300 DPI
                        scale = w_img / 612  # Approx — standard US Letter width = 612pt
                        bx1 = max(0, int(element['bbox'][0] * scale) - 10)
                        by1 = max(0, int(element['bbox'][1] * scale) - 10)
                        bx2 = min(w_img, int(element['bbox'][2] * scale) + 10)
                        by2 = min(h_img, int(element['bbox'][3] * scale) + 10)

                        if bx2 > bx1 and by2 > by1:
                            crop_visual = original_img[by1:by2, bx1:bx2]
                            if crop_visual.size > 0:
                                crop_fname = f"{file.filename}_{page_num}_crop_{element['type']}_{elem_idx}.png"
                                crop_path = os.path.join(OUTPUT_DIR, crop_fname)
                                cv2.imwrite(crop_path, crop_visual)
                                from urllib.parse import quote
                                element['crop_url'] = f"http://127.0.0.1:8000/output/{quote(crop_fname)}"
                                element['crop_local'] = crop_path

                    if direct_translate:
                        corrected = element['text']
                        highlights = []
                        normalized_result = {
                            'original': corrected,
                            'corrected': corrected,
                            'typos': 0,
                            'has_typo': False
                        }
                        bab_id = "Chapter 1" if doc_language == 'en' else "BAB 1"
                        bab_title = "Translated Content" if doc_language == 'en' else "Konten Terjemahan"
                        elem_lang = doc_language
                    else:
                        normalized_result = brain_module.normalize_text(element['text'], lang=doc_language)
                        corrected = normalized_result['corrected']
                        highlights = []

                        elem_lang = element.get('lang', '')
                        if not elem_lang:
                            txt_lower = element['text'].lower()
                            en_keywords = ['the', 'and', 'for', 'user', 'manual', 'this', 'with', 'installation',
                                           'operation', 'maintenance', 'warning', 'caution', 'chapter',
                                           'table', 'figure', 'if', 'is', 'are', 'can', 'not', 'may']
                            en_hits = sum(1 for kw in en_keywords if f' {kw} ' in f' {txt_lower} ')
                            elem_lang = 'en' if en_hits >= 2 else 'id'

                        bab_id = element.get('chapter', '')
                        if bab_id and bab_id in chapter_titles:
                            bab_title = chapter_titles[bab_id]
                        else:
                            bab_id, bab_title = brain_module.semantic_mapping(element)

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

                    _clean_original = enforce_language(normalized_result['original'], lang=doc_language)
                    _clean_normalized = enforce_language(normalized_result['corrected'], lang=doc_language)

                    structured_data.append({
                        "chapter_id"    : bab_id,
                        "chapter_title" : bab_title,
                        "type"          : element['type'],
                        "original"      : _clean_original,
                        "normalized"    : _clean_normalized,
                        "typos"         : normalized_result.get('typos', 0),
                        "has_typo"      : normalized_result.get('has_typo', False),
                        "text_confidence": element.get('confidence', 1.0),
                        "match_score"   : 100,
                        "lang"          : elem_lang,
                        "crop_url"      : element.get('crop_url'),
                        "crop_local"    : element.get('crop_local'),
                        "source_image_local": preview_path,
                        "bbox"          : element.get('bbox'),
                        "highlights"    : highlights,
                        "_direct_read"  : True,
                    })

            print(f"  ✅ PDF direct read complete: {len(structured_data)} elements")

        else:
            # ═══════════════════════════════════════════════════════════════
            # OCR PATH — original pipeline for scanned documents
            # ═══════════════════════════════════════════════════════════════
            total_pages = len(images)
            progress_tracker[session_id]["total_pages"] = total_pages
            progress_tracker[session_id]["message"] = f"Processing {total_pages} page(s)..."
            progress_tracker[session_id]["status"] = "processing"

            print(f"\n  📑 Total  : {total_pages} halaman")
            print(f"  🔄 Step 2 : Scanning setiap halaman (OCR)...")

            # ───── MAIN OCR PROCESSING LOOP ─────────────────────────────────
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

                # ── Column detection: split multi-column pages ──
                try:
                    col_paths = _split_columns_simple(page_path, f"{file.filename}_{i}")
                except Exception as e:
                    logger.warning(f"Column split failed (non-fatal): {e}")
                    col_paths = [page_path]

                if len(col_paths) > 1:
                    logger.info(f"📊 Page {current_page}: split into {len(col_paths)} columns")

                # ── Process each column (or full page if single column) ──
                for col_idx, col_path in enumerate(col_paths):
                    col_suffix = f"_col{col_idx}" if len(col_paths) > 1 else ""

                    # A. THE EYE (Scan) — pass language for OCR engine selection
                    scan_result = vision_module.scan_document(
                        col_path, f"{file.filename}_{i}{col_suffix}", lang=doc_language, direct_translate=direct_translate
                    )

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
                            col_label = f"page {current_page} col {col_idx+1}" if len(col_paths) > 1 else f"page {current_page}"
                            logger.info(f"📷 Preview {col_label}: {clean_img_url}")
                        else:
                            clean_img_url = None

                    # B. THE BRAIN (Classify + Normalize) — per column
                    for element in layout_elements:
                        if direct_translate:
                            corrected = element['text']
                            highlights = []
                            normalized_result = {
                                'original': corrected,
                                'corrected': corrected,
                                'typos': 0,
                                'has_typo': False
                            }
                            # Bypass standardization, put all inside initial chapter
                            bab_id = "Chapter 1" if doc_language == 'en' else "BAB 1"
                            bab_title = "Translated Content" if doc_language == 'en' else "Konten Terjemahan"
                            elem_lang = doc_language
                            element['text'] = corrected
                        else:
                            normalized_result = brain_module.normalize_text(element['text'], lang=doc_language)
                            # Terapkan text_corrector SETELAH BioBrain — gunakan versi highlights
                            correction_result = apply_text_correction_with_highlights(
                                normalized_result['corrected'], lang=doc_language
                            )
                            corrected  = correction_result['text']
                            highlights = correction_result['highlights']
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

                        # ── Enforce target language on ALL text fields ──
                        _clean_original = enforce_language(normalized_result['original'], lang=doc_language)
                        _clean_normalized = enforce_language(normalized_result['corrected'], lang=doc_language)

                        structured_data.append({
                            "chapter_id"    : bab_id,
                            "chapter_title" : bab_title,
                            "type"          : element['type'],
                            "original"      : _clean_original,
                            "normalized"    : _clean_normalized,
                            "typos"         : normalized_result['typos'],
                            "has_typo"      : normalized_result['has_typo'],
                            "text_confidence": element.get('confidence', 1.0),
                            "match_score"   : 100,
                            "lang"          : elem_lang,
                            "crop_url"      : element.get('crop_url'),
                            "crop_local"    : element.get('crop_local'),
                            "source_image_local": element.get('source_image_local'),
                            "bbox"          : element.get('bbox'),
                            "highlights"    : highlights,
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
        # ── STEP 2.6: AI Cover Page Extraction ─────────────────────────
        # Extract product name & description strictly from the first page (cover) using AI
        first_page_image_path = None
        for img in clean_pages_urls:
            filename = img.split('/')[-1]
            local_path = os.path.join(OUTPUT_DIR, filename)
            if ("_0.jpg" in filename or "_0_col0.jpg" in filename or "_0.png" in filename) and os.path.exists(local_path):
                first_page_image_path = local_path
                break
        
        if not first_page_image_path and images and isinstance(images[0], str):
            first_page_image_path = images[0]
            
        cover_ai_result = None
        if first_page_image_path:
            logger.info(f"🤖 Calling AI to analyze Cover Page from: {first_page_image_path}")
            try:
                from openrouter_client import get_openrouter_client
                import base64
                
                client = get_openrouter_client()
                if client and client.is_available:
                    # Convert to base64
                    img_cv = cv2.imread(first_page_image_path)
                    if img_cv is not None:
                        h, w = img_cv.shape[:2]
                        if w > 1000:
                            scale = 1000 / w
                            img_cv = cv2.resize(img_cv, (1000, int(h * scale)))
                        _, buffer = cv2.imencode('.jpg', img_cv, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        img_b64 = base64.b64encode(buffer).decode('utf-8')
                        
                        vision_model = os.getenv("AI_VISION_MODEL", "google/gemini-2.0-flash-001")
                        old_model = client.model
                        client.model = vision_model
                        
                        prompt = """Analyze this document cover page. I need exactly 2 strings:
1. The Product Name (usually the biggest, boldest text, often a short code like "SP10W" or "Spirometer").
2. The Company Name or short description (e.g. "Contec Medical Systems Co., Ltd.").

Respond ONLY with a valid pure JSON object in this exact format, with NO markdown formatting:
{"product_name": "...", "description": "..."}"""

                        response = client.call(prompt, image_base64=img_b64, timeout=20)
                        client.model = old_model
                        
                        if response:
                            import re
                            json_match = re.search(r'\{.*\}', response, re.DOTALL)
                            if json_match:
                                cover_ai_result = json.loads(json_match.group())
                                logger.info(f"✅ AI Cover Result: {cover_ai_result}")
            except Exception as e:
                logger.error(f"AI Cover Extraction failed: {e}")

        # Remove previous heuristic cover marking. If AI succeeded, inject it explicitly.
        first_chapter = "Chapter 1" if doc_language == 'en' else "BAB 1"
        first_chapter_title = chapter_titles.get(first_chapter, "")
        
        if cover_ai_result and cover_ai_result.get("product_name"):
            # Inject at the very beginning
            structured_data.insert(0, {
                "chapter_id": first_chapter,
                "chapter_title": first_chapter_title,
                "type": "heading",
                "original": cover_ai_result["product_name"],
                "normalized": cover_ai_result["product_name"],
                "is_cover": True,
                "has_typo": False,
                "text_confidence": 1.0,
                "match_score": 100
            })
            if cover_ai_result.get("description"):
                structured_data.insert(1, {
                    "chapter_id": first_chapter,
                    "chapter_title": first_chapter_title,
                    "type": "paragraph",
                    "original": cover_ai_result["description"],
                    "normalized": cover_ai_result["description"],
                    "is_cover": True,
                    "has_typo": False,
                    "text_confidence": 1.0,
                    "match_score": 100
                })
        else:
            # Fallback to extremely strict heuristic just in case AI fails
            cover_count = 0
            for item in structured_data:
                if item.get('chapter_id') != first_chapter:
                    continue
                if cover_count >= 2:
                    break
                if item.get('type') in ('title', 'heading'):
                    text = (item.get('normalized', '') or '').strip()
                    source_image = item.get('source_image_local') or ''
                    is_first_page = f"{file.filename}_0" in source_image
                    if is_first_page and len(text) < 40 and not any(kw in text.lower() for kw in ('manual', 'table of contents')):
                        item['is_cover'] = True
                        cover_count += 1

        # 2.7 CHECK MISSING CHAPTERS (Report only — no auto-generation)
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
        
        from urllib.parse import quote
        word_url = f"http://127.0.0.1:8000/files/{quote(result['word_file'])}"
        pdf_url = f"http://127.0.0.1:8000/files/{quote(result['pdf_file'])}" if result['pdf_file'] else None
        
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
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as e:
            logger.warning(f"Could not remove temp file {temp_path}: {e}")

        # Store session data for potential supplementary uploads
        if structured_data and session_id:
             active_sessions[session_id] = {
                 "original_filename": file.filename,
                 "structured_data": structured_data,
                 "images_count": len(images) if 'images' in locals() else 0
             }


# ==========================================
# TRANSLATE ENDPOINT
# ==========================================
@app.post("/translate/{session_id}")
async def translate_session(session_id: str):
    """
    Translate semua teks dalam session dari English → Bahasa Indonesia.
    Menggunakan OpenRouter AI untuk terjemahan yang akurat.
    Setelah translate, regenerate Word/PDF dengan teks terjemahan.
    """
    if session_id not in active_sessions:
        return {"success": False, "error": "Session not found"}
    
    session = active_sessions[session_id]
    structured_data = session.get("structured_data", [])
    
    if not structured_data:
        return {"success": False, "error": "No data to translate"}
    
    try:
        from openrouter_client import get_openrouter_client
        client = get_openrouter_client()
        
        if not client.is_available:
            return {"success": False, "error": "AI not available — check OPENROUTER_API_KEY in .env"}
        
        logger.info(f"🌐 Translation started for session {session_id}: {len(structured_data)} items")
        
        # Kumpulkan teks yang perlu ditranslate (hanya heading & paragraph, bukan table/figure)
        texts_to_translate = []
        for idx, item in enumerate(structured_data):
            if item.get('type') in ('heading', 'paragraph') and item.get('normalized'):
                texts_to_translate.append((idx, item['normalized']))
        
        if not texts_to_translate:
            return {"success": False, "error": "No text elements to translate"}
        
        logger.info(f"🌐 Translating {len(texts_to_translate)} text elements...")
        
        # Batch translate: kirim maks 10 teks per API call untuk efisiensi
        BATCH_SIZE = 10
        translated_count = 0
        
        for batch_start in range(0, len(texts_to_translate), BATCH_SIZE):
            batch = texts_to_translate[batch_start:batch_start + BATCH_SIZE]
            
            # Siapkan teks untuk batch
            numbered_texts = []
            for i, (idx, text) in enumerate(batch):
                numbered_texts.append(f"[{i+1}] {text}")
            
            batch_text = "\n\n".join(numbered_texts)
            
            prompt = f"""Translate the following English texts to Bahasa Indonesia.
Each text is numbered [1], [2], etc. Return translations with the same numbering.

RULES:
- Translate naturally and accurately to Bahasa Indonesia
- Keep technical terms that are commonly used in English (e.g., "display", "sensor", "battery")
- Keep product names, model numbers, and brand names as-is
- Keep measurement units as-is (e.g., "mL", "mmHg", "°C")
- Maintain the same formatting (headings stay as headings)
- Return ONLY the translations with numbering, nothing else

{get_language_instruction('id')}

Texts to translate:
{batch_text}"""
            
            response = client.call(prompt, timeout=60)
            
            if response:
                # Parse response — match [1], [2], etc.
                lines = response.strip().split('\n')
                current_num = None
                current_text = []
                translations = {}
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Check if line starts with [N]
                    import re
                    match = re.match(r'^\[(\d+)\]\s*(.*)', line)
                    if match:
                        # Save previous
                        if current_num is not None and current_text:
                            translations[current_num] = ' '.join(current_text)
                        current_num = int(match.group(1))
                        current_text = [match.group(2)] if match.group(2) else []
                    elif current_num is not None:
                        current_text.append(line)
                
                # Save last one
                if current_num is not None and current_text:
                    translations[current_num] = ' '.join(current_text)
                
                # Apply translations back to structured_data
                for i, (idx, original_text) in enumerate(batch):
                    batch_num = i + 1
                    if batch_num in translations:
                        # Enforce target language on translated text
                        translated = enforce_language(translations[batch_num], lang='id')
                        if translated:
                            structured_data[idx]['original_en'] = structured_data[idx].get('normalized', '')
                            structured_data[idx]['normalized'] = translated
                            structured_data[idx]['lang'] = 'id'
                            structured_data[idx]['translated'] = True
                            translated_count += 1
                
                logger.info(f"🌐 Batch {batch_start//BATCH_SIZE + 1}: "
                           f"translated {len(translations)}/{len(batch)} items")
            else:
                logger.warning(f"🌐 Batch {batch_start//BATCH_SIZE + 1}: AI returned empty response")
        
        logger.info(f"✅ Translation complete: {translated_count}/{len(texts_to_translate)} items translated")
        
        # ── Remap chapter IDs & titles to Indonesian ──
        chapter_en_to_id = {
            "Chapter 1": ("BAB 1", "Tujuan Penggunaan & Keamanan"),
            "Chapter 2": ("BAB 2", "Instalasi"),
            "Chapter 3": ("BAB 3", "Panduan Operasional & Pemantauan Klinis"),
            "Chapter 4": ("BAB 4", "Perawatan, Pemeliharaan & Pembersihan"),
            "Chapter 5": ("BAB 5", "Pemecahan Masalah"),
            "Chapter 6": ("BAB 6", "Spesifikasi Teknis & Kepatuhan Standar"),
            "Chapter 7": ("BAB 7", "Garansi & Layanan"),
        }
        for item in structured_data:
            ch_id = item.get('chapter_id', '')
            if ch_id in chapter_en_to_id:
                new_id, new_title = chapter_en_to_id[ch_id]
                item['chapter_id'] = new_id
                item['chapter_title'] = new_title
        
        logger.info("🌐 Chapter IDs remapped: Chapter → BAB")
        
        # Update session
        session["structured_data"] = structured_data
        
        # Regenerate Word/PDF with translated text
        result = architect_module.build_report(structured_data, session["original_filename"], lang='id')
        from urllib.parse import quote
        word_url = f"http://127.0.0.1:8000/files/{quote(result['word_file'])}"
        pdf_url = f"http://127.0.0.1:8000/files/{quote(result['pdf_file'])}" if result.get('pdf_file') else None
        
        return {
            "success": True,
            "translated_count": translated_count,
            "total_items": len(texts_to_translate),
            "results": structured_data,
            "word_url": word_url,
            "pdf_url": pdf_url,
        }
    
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.post("/supplement/{session_id}")
async def supplement_workflow(
    session_id: str, 
    files: list[UploadFile] = File(...),
    target_chapter: str = Form(None)
):
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
    logger.info(f"Supplementing Session {session_id} with files: {file_names}, target_chapter: {target_chapter}")
    
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
                    # Terapkan text_corrector SETELAH BioBrain — gunakan versi highlights
                    correction_result = apply_text_correction_with_highlights(
                        normalized_result['corrected'], lang=supp_lang
                    )
                    corrected  = correction_result['text']
                    highlights = correction_result['highlights']
                    element['text'] = corrected
                    normalized_result['corrected'] = corrected
                    
                    if target_chapter:
                        bab_id = target_chapter
                        bab_title = brain_module.taxonomy.get(bab_id, {}).get("title", "")
                    else:
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
                        "chapter_id"    : bab_id,
                        "chapter_title" : bab_title,
                        "type"          : element['type'],
                        "original"      : enforce_language(normalized_result['original'], lang=supp_lang),
                        "normalized"    : enforce_language(normalized_result['corrected'], lang=supp_lang),
                        "typos"         : normalized_result['typos'],
                        "has_typo"      : normalized_result['has_typo'],
                        "text_confidence": element.get('confidence', 1.0),
                        "match_score"   : 100,
                        "crop_url"      : element.get('crop_url'),
                        "crop_local"    : element.get('crop_local'),
                        "source_image_local": element.get('source_image_local'),
                        "bbox"          : element.get('bbox'),
                        "highlights"    : highlights,
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
        
        from urllib.parse import quote
        word_url = f"http://127.0.0.1:8000/files/{quote(result['word_file'])}"
        pdf_url = f"http://127.0.0.1:8000/files/{quote(result['pdf_file'])}" if result['pdf_file'] else None
        
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