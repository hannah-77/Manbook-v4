# 🔍 AUDIT REPORT — Manbook-v4 Project
**Date:** 2026-02-26  
**Audited by:** Antigravity AI  
**Scope:** Backend, Frontend, AI Pipeline, Security, Structure, Performance

---

## 📊 OVERALL SCORE: ~78/100

| Area | Score | Notes |
|------|-------|-------|
| Backend Architecture | 7/10 | Functional but monolithic |
| Frontend UI/UX | 7/10 | Clean layout, needs state management |
| AI Pipeline Performance | 8/10 | Smart single-call design |
| Code Quality | 6/10 | Duplicates, dead code, mixed languages |
| Security | 4/10 | API key exposed, no auth |
| Project Cleanliness | 5/10 | Too many stale docs, temp files |
| Error Handling | 6/10 | Inconsistent, some bare excepts |
| Performance | 7/10 | Good for single user, won't scale |

---

## 🔴 PRIORITY 1 — CRITICAL (Fix Immediately)

### 1.1 ⚠️ API Key Exposed in `.env` (Committed to Git)
**File:** `backend/.env` line 8  
**Risk:** Your `OPENROUTER_API_KEY` is visible in the file. While `.env` IS in `.gitignore`, the `.env example` file also exists and could leak the pattern.  
**Fix:**
- Verify `.env` is NOT in git history (`git log --all -- backend/.env`)
- Use `.env.example` (without real key) as template
- Rotate your API key if it was ever committed

### 1.2 ⚠️ Duplicate `/files/{filename}` Endpoint
**File:** `backend/main.py` lines 54-59 AND lines 1289-1294  
**Impact:** Two identical routes — FastAPI will use the FIRST one, but the second is dead code that confuses maintenance.  
**Fix:** Remove the duplicate at lines 1289-1294.

### 1.3 ⚠️ `letterhead.png` in `.gitignore` but Required
**File:** `.gitignore` line 53: `backend/*.png`  
**Impact:** This ignores ALL .png files in backend, including `letterhead.png` which is REQUIRED for the app. New clones will break.  
**Fix:** Add `!backend/letterhead.png` exception to `.gitignore`.

### 1.4 ⚠️ `main.py` is 1732 Lines — Too Large
**Impact:** All logic (Vision, Brain, Architect, API endpoints) in ONE file makes it hard to maintain, test, and debug.  
**Fix:** Split into modules:
```
backend/
├── main.py              (API routes only, ~200 lines)
├── vision_engine.py     (already exists ✓)
├── brain.py             (BioBrain class)
├── architect.py         (BioArchitect class)
├── openrouter_client.py (already exists ✓)
└── config.py            (BASE_PATH, OUTPUT_DIR, etc.)
```

---

## 🟠 PRIORITY 2 — IMPORTANT (Fix This Week)

### 2.1 No CORS Configuration
**File:** `backend/main.py`  
**Impact:** Currently works because Flutter desktop calls localhost, but if you ever deploy or use web frontend, requests will be blocked.  
**Fix:** Add `CORSMiddleware`:
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

### 2.2 `import` Statements Inside Functions
**Files:** `main.py` lines 349, 379, 432, 570, 770, 897, 1200, 1271, 1345, 1348  
**Impact:** `import re`, `import uuid`, `from difflib import ...` are called INSIDE functions on every request. This is slower and makes dependencies unclear.  
**Fix:** Move all imports to the top of the file.

### 2.3 Bare `except:` Without Error Handling
**File:** `main.py` line 1728: `except:` (no exception type)  
**File:** `main.py` line 1715: `pass` after return (unreachable code)  
**Impact:** Silently swallows ALL errors including KeyboardInterrupt and SystemExit.  
**Fix:** Use `except Exception as e:` and log the error.

### 2.4 `BioBrain` Instantiated Multiple Times
**File:** `main.py` line 953: `BioBrain()` inside `_build_toc_page` and line 1304  
**Impact:** Creates new SpellChecker + loads medical dictionary on EVERY request. Memory/CPU waste.  
**Fix:** Use a singleton or pass the existing BioBrain instance.

### 2.5 PDF DPI = 200 — Consider 300
**File:** `main.py` line 1727: `dpi=200`  
**Impact:** 200 DPI is OK but 300 DPI significantly improves OCR accuracy for small text.  
**Trade-off:** 300 DPI = ~2x memory, ~1.5x time. Worth it for accuracy.  
**Fix:** Make DPI configurable via `.env`.

### 2.6 Frontend: No State Management
**File:** `frontend/lib/main.dart` — 1542 lines in one StatefulWidget  
**Impact:** All state in one widget = hard to test, hard to add features, frequent full-rebuilds.  
**Fix:** Consider:
- **Provider** or **Riverpod** for state management
- Split into separate files: `upload_page.dart`, `preview_page.dart`, `results_panel.dart`

### 2.7 Backend Base URL Hardcoded in Frontend
**Files:** `main.dart` lines 198, 217, etc.: `http://127.0.0.1:8000`  
**Impact:** If backend port changes or app is deployed, every URL breaks.  
**Fix:** Use a central `const String backendUrl` or environment config.

---

## 🟡 PRIORITY 3 — IMPROVEMENTS (Fix This Month)

### 3.1 No Input Validation on File Upload
**File:** `main.py` `/process` endpoint  
**Impact:** No check on file size, file type validation (beyond extension), or malicious filenames.  
**Fix:**
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.docx', '.doc'}
```

### 3.2 Process Runs Synchronously — Blocks Server
**File:** `main.py` `/process` endpoint  
**Impact:** Processing a 20-page PDF takes 60+ seconds. During this time, the server can't handle other requests.  
**Fix:** Use FastAPI `BackgroundTasks` or `asyncio.to_thread()`.

### 3.3 No Cleanup of Temporary Files
**File:** temp files like `temp_*.docx`, `page_*.png`, output crops  
**Impact:** Temp files accumulate over time, consuming disk space.  
**Fix:** Add a cleanup task that runs after processing completes, or use Python's `tempfile` module.

### 3.4 `_serverProcess` Never Used (Dead Code)
**File:** `main.dart` line 28: `Process? _serverProcess;`  
**Impact:** Declared but never assigned. Dead code.

### 3.5 SpellChecker Corrects Indonesian + English Mixed
**File:** `main.py` BioBrain.normalize_text  
**Impact:** English spell checker may "correct" valid Indonesian words. For a bilingual app, this creates false corrections.  
**Fix:** Use language-specific spell checking based on detected `lang` field.

### 3.6 `semantic_mapping()` Always Returns BAB Format
**File:** `main.py` line 504: `self.current_context = key` always sets BAB format  
**Impact:** Even when English chapters are needed, the semantic mapper defaults to BAB format. The backend remap (BAB→Chapter) fixes this post-hoc, but it's better to handle it natively.  
**Fix:** Pass language context to `semantic_mapping()`.

### 3.7 `vision_engine.py` — Fallback Has Indentation Bug
**File:** `vision_engine.py` `_fallback_paddle_scan` method  
**Impact:** The `return` and `except` block appear to be inside the `for` loop, meaning only the FIRST region is processed before returning.  
**Fix:** Fix indentation so return is after the loop completes.

### 3.8 Frontend — No Loading Skeleton / Shimmer
**Impact:** When processing, user sees a basic spinner. Adding skeleton loading or progress animation would make UX feel much more premium.

### 3.9 No Retry Logic for DOCX Conversion
**File:** `main.py` line 1350: `docx2pdf.convert()`  
**Impact:** If Word/LibreOffice is busy, conversion fails with no retry.  
**Fix:** Add retry with exponential backoff.

---

## 🟢 PRIORITY 4 — POLISH (When Time Allows)

### 4.1 Project Root Has 20+ Stale Documentation Files
**Files:** `CHECKLIST.md`, `GEMINI_*.md`, `PHASE1_COMPLETE.md`, `STEP1_COMPLETE.md`, etc.  
**Impact:** These are leftover from development iterations. They confuse new developers.  
**Fix:** Archive to a `docs/archive/` folder or delete. Keep only `README.md`.

### 4.2 Test Documents in Backend Folder
**Files:** `backend/45. rev04 - MBENG_Fox Baby.docx`, `backend/User Manual.docx`, etc.  
**Impact:** 12+ test documents (~25MB) polluting the backend folder.  
**Fix:** Move to `tests/samples/` or add to `.gitignore`.

### 4.3 Debug Files Left in Backend
**Files:** `debug_structured_data.json`, `dump.txt`, `dump_input.txt`, `dump_output.txt`, `res_dump.txt`, `error.log`, `backend.log`  
**Fix:** Add `*.json`, `dump*.txt`, `res_dump.txt` to `.gitignore`.

### 4.4 requirements.txt Has Unused Dependencies
**File:** `backend/requirements.txt`  
- `pandas` — never imported in main.py/vision_engine.py
- `reportlab` — never imported
- `openai` — using openrouter_client.py with `requests`, not OpenAI SDK
- `pyspellchecker` — imported as `spellchecker`, make sure package name matches  
**Fix:** Run `pip freeze` and compare with actual imports.

### 4.5 Multiple Startup Scripts
**Files:** `start.bat`, `start-all.bat`, `start-backend.bat`, `start-flutter.bat`, `build-windows-app.bat`  
**Impact:** Confusing which one to use.  
**Fix:** Keep ONE `start.bat`, remove or consolidate others.

### 4.6 Frontend: `print()` Debug Statements
**File:** `main.dart` line 713: `print("🖼️ Clean Pages (${_cleanPages.length}): ${_cleanPages.take(2)}")`  
**Impact:** Debug output in production.  
**Fix:** Remove or use `debugPrint()` which is stripped in release builds.

### 4.7 `_showCleanView` Variable Never Used
**File:** `main.dart` line 40  
**Impact:** Dead state variable.

---

## 🚀 AI PIPELINE PERFORMANCE RECOMMENDATIONS

### Current Architecture (Good ✅)
```
Page Image → Single AI Call → JSON (text + layout + chapter) → Structured Data → DOCX
                                      ↓ (if AI fails)
                              PPStructure + PaddleOCR fallback
```

### Recommendations:

1. **Model Selection:** Your current model `qwen/qwen3-vl-235b-a22b-instruct` is VERY large (235B params). Consider:
   - `google/gemini-2.0-flash-001` — faster, multimodal, good accuracy
   - `anthropic/claude-sonnet-4` — excellent for structured output
   - Add a `AI_VISION_MODEL_FAST` for simple pages, `AI_VISION_MODEL_ACCURATE` for complex ones

2. **Batch Processing:** Process pages in parallel (2-3 concurrent API calls) instead of sequentially.

3. **Caching:** Cache AI results by file hash to avoid re-processing the same document.

4. **Token Optimization:** The AI prompt is ~500 tokens. For simple pages (few elements), this overhead is significant. Consider a shorter prompt for simple pages.

5. **Image Compression:** Currently JPEG quality 85. For OCR, quality 70-75 is sufficient and reduces API latency by 20-30%.

---

## 📋 QUICK WINS (Implementable in < 1 hour each)

| # | Item | Impact | Effort |
|---|------|--------|--------|
| 1 | Remove duplicate `/files/` endpoint | Fix potential bugs | 2 min |
| 2 | Move imports to top of file | Clean code, faster | 10 min |
| 3 | Delete stale .md files from root | Clean project | 5 min |
| 4 | Add `!backend/letterhead.png` to .gitignore | Fix deployment | 1 min |
| 5 | Centralize backend URL in frontend | Maintainability | 15 min |
| 6 | Remove debug print statements | Production-ready | 5 min |
| 7 | Add CORS middleware | Future-proofing | 3 min |
| 8 | Remove unused requirements | Smaller install | 5 min |
| 9 | Fix bare except clauses | Better error handling | 10 min |
| 10 | Remove dead code variables | Clean code | 5 min |
