"""
MANBOOK-V4 — BioManual Auto-Standardizer
=========================================
FastAPI Server & System Orchestrator

Modules:
  - bio_brain.py       → BioBrain (text normalization & chapter classification)
  - bio_architect.py   → BioArchitect (DOCX report builder)
  - vision_engine.py   → BioVisionHybrid (OCR + layout detection + AI classification)
  - orchestrator.py    → SystemOrchestrator (Main logic handler)
  - image_processing.py → Image utilities

Updated: April 2026
"""

import os
import sys
import time
import uuid
import json
import re
import shutil
import logging
import traceback
import uvicorn
import torch
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("Device:", device)
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
from image_processing import convert_pdf_to_images_safe, split_columns_simple
from orchestrator import SystemOrchestrator
import pdfplumber
import PyPDF2
import docx
from docx import Document
import urllib.parse
from urllib.parse import quote
import langdetect
from langdetect import detect, DetectorFactory
import base64

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
        correct_ocr_text_with_highlights as _ocr_correct_hl,
    )
    TEXT_CORRECTOR_AVAILABLE = True
    logging.info("✓ TextCorrector loaded (with highlights support)")
except Exception as e:
    TEXT_CORRECTOR_AVAILABLE = False
    logging.warning(f"TextCorrector not available: {e}")

def apply_text_correction_with_highlights(text: str, lang: str = 'id') -> dict:
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

VISION_MODE = os.getenv('VISION_MODE', 'hybrid')

app = FastAPI(title="BioManual Auto-Standardizer")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")

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
# SYSTEM INITIALIZATION
# ==========================================
def initialize_vision_module():
    if VISION_MODE in ['gemini', 'hybrid'] and VISION_ENGINE_AVAILABLE:
        try:
            logger.info(f"Initializing {VISION_MODE.upper()} vision mode...")
            return create_vision_engine(mode=VISION_MODE)
        except Exception as e:
            logger.error(f"Failed to initialize Vision Engine: {e}")
            return None
    return None

vision_module = initialize_vision_module()
architect_module = BioArchitect()
progress_tracker = {}
active_sessions = {}

# ==========================================
# MODELS
# ==========================================

class GenerateChapterRequest(BaseModel):
    chapter_id: str
    product_name: str
    product_desc: str
    lang: str = "id"

class CheckCompletenessRequest(BaseModel):
    chapter_id: str
    items: list[dict]
    lang: str = "id"

class GenerateReportRequest(BaseModel):
    items: list[dict]
    filename: str
    lang: str = "id"
    custom_product_name: str | None = None
    custom_product_desc: str | None = None

class RecropRequest(BaseModel):
    source_image_local: str
    bbox: list[int]
    element_type: str

# Instantiate Orchestrator
orchestrator = SystemOrchestrator(
    vision_module=vision_module,
    brain_module=BioBrain(),
    architect_module=architect_module,
    progress_tracker=progress_tracker
)

# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/health")
def health():
    return {"status": "BioManual System Online"}

@app.get("/ping")
def ping():
    return {"status": "pong"}

@app.post("/start")
async def start_session():
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
    if session_id in progress_tracker:
        return progress_tracker[session_id]
    return {"error": "Session not found"}

@app.post("/process")
async def process_workflow(request: Request, file: UploadFile = File(...)):
    session_id = request.headers.get("X-Session-Id") or str(uuid.uuid4())
    doc_language = request.headers.get("X-Language", "id")
    direct_translate = request.headers.get("X-Direct-Translate", "false") == "true"

    logger.info(f"🚀 Processing: {file.filename} (Lang: {doc_language})")
    
    file_uuid = uuid.uuid4().hex[:8]
    temp_path = os.path.join(BASE_PATH, f"temp_{session_id}_{file_uuid}_{file.filename}")
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    if session_id not in progress_tracker:
        progress_tracker[session_id] = {"status": "starting", "percentage": 0}

    try:
        fname_lower = file.filename.lower()
        structured_data = []
        clean_pages_urls = []
        
        # ─── PATH 1: DOCX Direct ─────────────────
        if fname_lower.endswith('.docx') and DIRECT_READER_AVAILABLE:
            try:
                elements = extract_docx_direct(temp_path, lang=doc_language)
                if elements:
                    logger.info("⚡ Using DOCX Direct Extraction + AI Normalization")
                    
                    # AI-Corrected Normalization for Word Docs
                    from text_corrector import correct_text_ai
                    
                    for elem in elements:
                        # Use Gemini for Word docs normalization instead of simple OCR rules
                        item = orchestrator._normalize_element(elem, doc_language, direct_translate, correct_text_ai)
                        structured_data.append(item)
                    
                    # ── Layout Preview for DOCX (Convert to Images) ──
                    try:
                        from docx2pdf import convert
                        import pythoncom
                        import win32com.client
                        
                        pythoncom.CoInitialize()
                        
                        # Use absolute paths for COM-based conversion
                        abs_temp_path = os.path.abspath(temp_path)
                        abs_pdf_preview = os.path.abspath(temp_path.replace(".docx", "_preview.pdf").replace(".doc", "_preview.pdf"))
                        
                        logger.info(f"🔄 Converting DOCX to PDF for preview: {abs_temp_path}")
                        
                        # Use docx2pdf with explicit paths
                        convert(abs_temp_path, abs_pdf_preview)
                        
                        if os.path.exists(abs_pdf_preview):
                            preview_imgs = convert_pdf_to_images_safe(abs_pdf_preview)
                            for idx, img in enumerate(preview_imgs):
                                # Save full page at HIGH quality — critical for column gap detection
                                full_img_fname = f"DOCX_FULL_{session_id}_{idx}.jpg"
                                full_img_path = os.path.join(OUTPUT_DIR, full_img_fname)
                                img.save(full_img_path, "JPEG", quality=95)
                                
                                # Split into columns
                                try:
                                    col_paths = split_columns_simple(full_img_path, f"DOCX_{session_id}_{idx}", OUTPUT_DIR)
                                    logger.info(f"📐 DOCX Preview Page {idx}: split_columns returned {len(col_paths)} paths")
                                    if len(col_paths) > 1:
                                        for col_path in col_paths:
                                            col_basename = os.path.basename(col_path)
                                            clean_pages_urls.append(f"http://127.0.0.1:8000/output/{quote(col_basename)}")
                                    else:
                                        clean_pages_urls.append(f"http://127.0.0.1:8000/output/{quote(full_img_fname)}")
                                except Exception as e_col:
                                    logger.warning(f"DOCX Column split failed: {e_col}")
                                    clean_pages_urls.append(f"http://127.0.0.1:8000/output/{quote(full_img_fname)}")
                                
                            try: os.remove(abs_pdf_preview)
                            except: pass
                            logger.info(f"🖼️ Generated {len(clean_pages_urls)} preview items for DOCX")
                        else:
                            logger.error(f"DOCX Preview: PDF file was not created at {abs_pdf_preview}")
                            
                    except Exception as e_preview:
                        logger.error(f"Failed to generate DOCX preview images: {str(e_preview)}")
                        
                        # FALLBACK: Use images extracted directly from DOCX as "preview"
                        if not clean_pages_urls:
                            logger.info("Using extracted figures as fallback preview for DOCX")
                            for elem in elements:
                                if elem.get('type') == 'figure' and elem.get('crop_url'):
                                    clean_pages_urls.append(elem['crop_url'])
                        
                    progress_tracker[session_id].update({"status": "processing", "percentage": 80})
            except Exception as e:
                logger.warning(f"DOCX Direct Read failed, falling back: {e}")

        # ─── PATH 2: PDF Hybrid Direct (Text-based + Surya Layout) ──
        if not structured_data and fname_lower.endswith('.pdf') and DIRECT_READER_AVAILABLE:
            pdf_info = is_text_pdf(temp_path)
            if pdf_info['is_text_based'] and VISION_ENGINE_AVAILABLE:
                try:
                    logger.info("⚡ Using Hybrid Direct Pipeline (Surya Layout + PDF Text)")
                    structured_data, clean_pages_urls = await orchestrator.run_hybrid_direct_pipeline(
                        temp_path, file.filename, session_id, doc_language, direct_translate, 
                        _ocr_correct_hl if TEXT_CORRECTOR_AVAILABLE else None
                    )
                except Exception as e:
                    logger.warning(f"Hybrid Direct Pipeline failed, falling back: {e}")

        # ─── PATH 3: OCR Pipeline (Scanned) ───────
        if not structured_data:
            logger.info("🔍 Using OCR Pipeline")
            images = []
            if fname_lower.endswith('.pdf'):
                images = convert_pdf_to_images_safe(temp_path)
            else:
                images = [temp_path]
            
            structured_data, clean_pages_urls = await orchestrator.run_ocr_pipeline(
                images, file.filename, session_id, doc_language, direct_translate, 
                _ocr_correct_hl if TEXT_CORRECTOR_AVAILABLE else None
            )

        # ─── Cover Analysis ────────────────────────
        ai_prod_name, ai_prod_desc = orchestrator.extract_cover_info(clean_pages_urls, doc_language)
        
        # ─── Build Report ──────────────────────────
        progress_tracker[session_id].update({"status": "building", "percentage": 90, "message": "Building DOCX..."})
        result = architect_module.build_report(
            structured_data, file.filename, lang=doc_language,
            custom_product_name=ai_prod_name,
            custom_product_desc=ai_prod_desc
        )

        word_url = f"http://127.0.0.1:8000/files/{quote(result['word_file'])}"
        pdf_url = f"http://127.0.0.1:8000/files/{quote(result['pdf_file'])}" if result.get('pdf_file') else None

        progress_tracker[session_id].update({"status": "complete", "percentage": 100, "message": "Done!"})
        
        print(f"\n  📁  Word Report: {result['word_file']}")
        print(f"  📁  PDF Report : {result.get('pdf_file', 'N/A')}")
        print(f"{'='*60}\n")
        
        # Store for session persistence
        active_sessions[session_id] = {
            "original_filename": file.filename,
            "structured_data": structured_data,
            "doc_language": doc_language
        }

        return {
            "success": True,
            "session_id": session_id,
            "results": structured_data,
            "word_url": word_url,
            "pdf_url": pdf_url,
            "clean_pages": clean_pages_urls,
            "ai_product_name": ai_prod_name or "",
            "ai_product_desc": ai_prod_desc or ""
        }

    except Exception as e:
        logger.error(f"Workflow Error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass

# ... (middle of file)

@app.post("/generate_chapter")
async def generate_chapter(req: GenerateChapterRequest):
    try:
        client = get_openrouter_client()
        if not client:
            return {"success": False, "error": "AI client not configured."}
            
        # Get actual chapter title from taxonomy
        brain = BioBrain()
        chapter_title = ""
        if req.chapter_id in brain.taxonomy:
            chapter_title = brain.taxonomy[req.chapter_id]["title"]
            
        prompt = f"""You are an expert technical writer for medical equipment.
Draft content for: {req.chapter_id} - {chapter_title}
Product: {req.product_name}
Description: {req.product_desc}

Return ONLY a JSON array of elements:
[{"type": "heading", "normalized": "..."}, {"type": "paragraph", "normalized": "..."}]"""

        response_text = client.call(prompt)
        response_text = enforce_language(response_text, lang=req.lang)
        
        cleaned_json = re.sub(r'```json\s*|\s*```', '', response_text).strip()
        match = re.search(r'\[.*\]', cleaned_json, re.DOTALL)
        if match:
            items = json.loads(match.group())
            for item in items:
                item["chapter_id"] = req.chapter_id
            return {"success": True, "items": items}
        return {"success": False, "error": "Could not parse AI response."}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/check_chapter_completeness")
async def check_chapter_completeness(req: CheckCompletenessRequest):
    """
    AI Vision Auditor: Melakukan audit otomatis untuk memastikan hasil ekstraksi
    lengkap dibandingkan dengan gambar asli dokumen.
    """
    try:
        # 1. Kumpulkan gambar sumber unik untuk bab ini
        source_images = set()
        extracted_texts = []
        for item in req.items:
            img_path = item.get("source_image_local")
            if img_path and os.path.exists(img_path):
                source_images.add(img_path)
            
            # Bangun dump teks ekstraksi untuk AI
            if item.get("type") in ["paragraph", "title", "heading", "list"]:
                extracted_texts.append(f"[{item.get('type')}] {item.get('normalized', '')}")
            elif item.get("type") in ["figure", "table"]:
                extracted_texts.append(f"[{item.get('type')}] (Visual Element)")

        if not source_images:
            return {"success": False, "error": "Tidak ada gambar dokumen asli yang terhubung dengan bab ini."}

        # 2. Siapkan prompt audit
        lang_instruction = "Gunakan bahasa Indonesia." if req.lang == 'id' else "Use English language."
        prompt = f"""You are a Document QA Auditor.
Compare the following EXTRACTED TEXT with the attached ORIGINAL DOCUMENT IMAGES.
Determine if any critical info (paragraphs, warnings, tables, symbols) is MISSING.

EXTRACTED TEXT for Chapter '{req.chapter_id}':
-----------------
{chr(10).join(extracted_texts)}
-----------------

Evaluate thoroughly. {lang_instruction}
Return ONLY JSON:
{{
  "score": <0-100 score of completeness>,
  "analysis": "<short analysis of what is missing or confirmation of completeness>"
}}"""

        # 3. Baca gambar dan konversi ke Base64 (maks 4 gambar pertama)
        images_base64 = []
        for img_path in sorted(list(source_images))[:4]:
            img_cv = cv2.imread(img_path)
            if img_cv is not None:
                h, w = img_cv.shape[:2]
                # Resize agar tidak terlalu besar dalam payload API
                if w > 1200:
                    scale = 1200 / w
                    img_cv = cv2.resize(img_cv, (int(w*scale), int(h*scale)))
                _, buffer = cv2.imencode('.jpg', img_cv, [cv2.IMWRITE_JPEG_QUALITY, 75])
                images_base64.append(base64.b64encode(buffer).decode('utf-8'))

        # 4. Panggil AI Vision (Gemini Flash)
        client = get_openrouter_client()
        vision_model = os.getenv("AI_VISION_MODEL", "google/gemini-2.0-flash-001")
        old_model = client.model
        client.model = vision_model
        
        try:
            # Build multimodal content payload
            content = [{"type": "text", "text": prompt}]
            for img_b64 in images_base64:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_b64}", "detail": "low"}
                })

            logger.info(f"🔍 AI Completeness Check: Audit bab {req.chapter_id}...")
            response_text = client.call(content)
            
            # Parse JSON hasil
            cleaned_json = re.sub(r'```json\s*|\s*```', '', response_text).strip()
            match = re.search(r'\{.*\}', cleaned_json, re.DOTALL)
            if match:
                result = json.loads(match.group())
                
                # Print result to terminal
                print(f"\n  🔍  Audit Result for {req.chapter_id}:")
                print(f"      - Score: {result.get('score')}/100")
                print(f"      - Analysis: {result.get('analysis')}\n")
                
                return {
                    "success": True, 
                    "score": result.get("score", 0), 
                    "analysis": result.get("analysis", "")
                }
            return {"success": False, "error": "AI response was not in valid JSON format."}
        finally:
            client.model = old_model

    except Exception as e:
        logger.error(f"Completeness Check Error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/generate_custom_report")
async def generate_custom_report(req: GenerateReportRequest):
    try:
        result = architect_module.build_report(
            req.items, req.filename, lang=req.lang,
            custom_product_name=req.custom_product_name,
            custom_product_desc=req.custom_product_desc
        )
        word_url = f"http://127.0.0.1:8000/files/{quote(result['word_file'])}"
        pdf_url = f"http://127.0.0.1:8000/files/{quote(result['pdf_file'])}" if result.get('pdf_file') else None
        return {"success": True, "word_url": word_url, "pdf_url": pdf_url}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/recrop")
async def recrop_image(req: RecropRequest):
    try:
        img = cv2.imread(req.source_image_local)
        x1, y1, x2, y2 = req.bbox
        crop = img[int(y1):int(y2), int(x1):int(x2)]
        crop_fname = f"recrop_{uuid.uuid4().hex[:6]}.png"
        crop_path = os.path.join(OUTPUT_DIR, crop_fname)
        cv2.imwrite(crop_path, crop)
        return {"success": True, "crop_url": f"http://127.0.0.1:8000/output/{quote(crop_fname)}", "crop_local": crop_path}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Language detection settings
DetectorFactory.seed = 0

def _detect_lang_from_text(text: str, filename: str = "") -> dict:
    """
    Robust language detection using weighted scoring:
    1. Filename hints (eng, idn, etc.)
    2. Manual-specific keywords (bab, chapter, etc.)
    3. Common stop-words (yang, adalah vs the, with)
    4. langdetect as tie-breaker
    """
    if not text: text = ""
    text_lower = (text + " " + filename.replace("_", " ").replace("-", " ")).lower()
    
    en_score = 0
    id_score = 0
    
    # ── 1. Filename / String Hints (Strongest) ──
    # Note: 'id' and 'ind' are too common in technical text (ID number, Index)
    # We look for specific language tag patterns
    if re.search(r'[-_. ](eng|en|english|uk|us)[-_. ]', "." + text_lower + "."): en_score += 15
    if re.search(r'[-_. ](idn|indo|indonesia|bahasa)[-_. ]', "." + text_lower + "."): id_score += 15
    
    # ── 2. Technical Manual Keywords ──
    en_tech = ['specification', 'warning', 'safety', 'installation', 'operating', 'troubleshooting', 'warranty', 'chapter', 'contents']
    id_tech = ['spesifikasi', 'peringatan', 'keamanan', 'instalasi', 'operasional', 'pemecahan masalah', 'garansi', 'bab', 'daftar isi']
    
    en_score += sum(4 for k in en_tech if k in text_lower)
    id_score += sum(4 for k in id_tech if k in text_lower)
    
    # ── 3. Common Stop-words (Statistical) ──
    # Using multiple occurrences for stronger signal
    en_stop = [' the ', ' with ', ' for ', ' from ', ' and ', ' this ']
    id_stop = [' yang ', ' dengan ', ' untuk ', ' adalah ', ' dari ', ' ini ']
    
    for word in en_stop:
        en_score += text_lower.count(word) * 2
    for word in id_stop:
        id_score += text_lower.count(word) * 2
    
    logger.info(f"📊 Lang Scoring: ID={id_score}, EN={en_score}")
    
    if en_score > id_score + 3: return {"lang": "en", "conf": 0.95}
    if id_score > en_score + 3: return {"lang": "id", "conf": 0.95}
    
    # ── 4. AI Tie-breaker ──
    try:
        lang = detect(text)
        conf = 0.85
        if lang == 'id': return {"lang": "id", "conf": conf}
        if lang == 'en': return {"lang": "en", "conf": conf}
    except:
        pass
        
    # Default fallback
    return {"lang": "id" if id_score >= en_score else "en", "conf": 0.5}

@app.post("/detect-language")
async def detect_language(file: UploadFile = File(...)):
    """
    Detect document language (Indonesian vs English).
    Uses weighted scoring of content and metadata.
    """
    file_uuid = uuid.uuid4().hex[:8]
    temp_path = os.path.join(BASE_PATH, f"_lang_det_{file_uuid}_{file.filename}")
    
    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        
        sample_text = ""
        ext = file.filename.lower()
        
        # Quick text extraction for sampling
        if ext.endswith('.pdf'):
            try:
                with open(temp_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    for i in range(min(3, len(reader.pages))):
                        sample_text += (reader.pages[i].extract_text() or "") + " "
            except: pass
        elif ext.endswith('.docx'):
            try:
                doc = Document(temp_path)
                for p in doc.paragraphs[:15]:
                    sample_text += p.text + " "
            except: pass
            
        result = _detect_lang_from_text(sample_text, filename=file.filename)
        detected = result["lang"]
        label = "Bahasa Indonesia" if detected == 'id' else "English"
        
        logger.info(f"🌐 Language Detection: {file.filename} -> {detected} ({label}, conf={result['conf']})")
        return {"detected": detected, "label": label, "confidence": result["conf"]}
        
    except Exception as e:
        logger.error(f"Language detection failed: {e}")
        return {"detected": "id", "label": "Bahasa Indonesia", "confidence": 0.5}
    finally:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass

@app.post("/translate/{session_id}")
async def translate_session(session_id: str):
    # This would call orchestrator.translate_session (logic moved there)
    return {"success": True, "message": "Fitur translasi sedang disinkronkan."}

@app.post("/supplement/{session_id}")
async def supplement_workflow(session_id: str, files: list[UploadFile] = File(...)):
    # This would call orchestrator.supplement_workflow
    return {"success": True, "message": "Fitur suplemen sedang disinkronkan."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)