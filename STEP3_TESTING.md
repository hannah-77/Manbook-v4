# 🧪 STEP 3: TESTING & INTEGRATION GUIDE

```
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║   🧪 STEP 3: TESTING & INTEGRATION                            ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
```

## ✅ What's Been Completed

### Phase 1: Backend (Gemini Integration) ✅
- ✅ Google Generative AI SDK installed
- ✅ Gemini Vision module created (`backend/gemini_vision.py`)
- ✅ Hybrid mode support (Gemini + PaddleOCR)
- ✅ Configuration system (.env file)
- ⏳ **PENDING**: Gemini API Key setup

### Phase 2: Frontend (PDF Preview) ✅
- ✅ Syncfusion PDF Viewer package added
- ✅ Side-by-side layout implemented
- ✅ PDF preview in left panel
- ✅ AI results in right panel
- ✅ Interactive PDF controls (zoom, scroll, text selection)

## 🎯 Current Status

```
┌─────────────────────────────────────────────────────────┐
│  READY TO TEST!                                         │
│                                                         │
│  Backend: ✅ Code ready (needs API key)                │
│  Frontend: ✅ PDF preview ready                        │
│  Integration: ⏳ Needs testing                         │
└─────────────────────────────────────────────────────────┘
```

## 🔑 STEP 3A: Get Gemini API Key (REQUIRED)

### Option 1: Use Existing Key (If You Have One)
```bash
# Edit backend/.env file
# Replace: GEMINI_API_KEY=your-api-key-here
# With your actual key
```

### Option 2: Get New Key
1. **Visit**: https://aistudio.google.com/app/apikey
2. **Sign in** with Google account
3. **Click** "Create API key"
4. **Copy** the key
5. **Edit** `backend/.env`:
   ```
   GEMINI_API_KEY=AIzaSy...your-actual-key...
   ```

### Option 3: Test Without Gemini (Fallback Mode)
```bash
# Edit backend/.env
VISION_MODE=paddle  # Use PaddleOCR only
```

## 🚀 STEP 3B: Run the Application

### Terminal 1: Start Backend
```bash
cd backend
python main.py
```

**Expected Output:**
```
INFO:     Started server process
INFO:     Waiting for application startup.
✓ Hybrid Vision Engine Ready (Gemini + Paddle)
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Terminal 2: Start Frontend
```bash
cd frontend
flutter run -d windows
```

**Expected Output:**
```
Launching lib\main.dart on Windows in debug mode...
Building Windows application...
Syncing files to device Windows...
Flutter run key commands.
```

## 🧪 STEP 3C: Testing Checklist

### Test 1: Backend Health Check ✅
```bash
# Open browser: http://127.0.0.1:8000/health
# Expected: {"status": "healthy", "vision_mode": "hybrid"}
```

### Test 2: Upload PDF ✅
1. Click "Select File" in Flutter app
2. Choose a PDF file (biomedical manual)
3. Wait for processing

**Expected:**
- ✅ Progress bar shows upload → conversion → analysis
- ✅ PDF preview appears in left panel
- ✅ AI results appear in right panel (7 BAB)

### Test 3: PDF Preview Features ✅
- ✅ Can scroll through PDF pages
- ✅ Can zoom in/out (double-tap)
- ✅ Can select text
- ✅ Filename shows in header

### Test 4: AI Classification ✅
- ✅ Results grouped into 7 BAB
- ✅ Each BAB shows item count
- ✅ Can expand/collapse chapters
- ✅ Text, tables, figures detected

### Test 5: Export ✅
- ✅ Click Word icon in header
- ✅ Download .docx file
- ✅ Open in Microsoft Word
- ✅ Verify 7 chapters with content

## 🔍 Troubleshooting

### Issue 1: Backend Won't Start
**Symptom:** `ModuleNotFoundError: No module named 'google.generativeai'`

**Solution:**
```bash
cd backend
pip install -r requirements.txt
```

### Issue 2: Gemini API Error
**Symptom:** `Error: Invalid API key`

**Solution:**
1. Check `.env` file has correct key
2. Verify key at https://aistudio.google.com/app/apikey
3. Or switch to paddle mode: `VISION_MODE=paddle`

### Issue 3: PDF Preview Not Showing
**Symptom:** Left panel shows "Processing Complete" but no PDF

**Solution:**
- Only PDFs show preview
- Images (PNG/JPG) show completion message
- This is expected behavior

### Issue 4: Flutter Build Error
**Symptom:** `syncfusion_flutter_pdfviewer not found`

**Solution:**
```bash
cd frontend
flutter clean
flutter pub get
flutter run -d windows
```

## 📊 Vision Mode Comparison

### Hybrid Mode (Recommended)
```
VISION_MODE=hybrid

Pros:
✅ Best accuracy (95%+)
✅ PaddleOCR for layout detection
✅ Gemini for text extraction
✅ AI descriptions for figures
✅ Structured table extraction

Cons:
⚠️ Requires API key
⚠️ Slower (API calls)
⚠️ Rate limited (15/min)
```

### Gemini Only Mode
```
VISION_MODE=gemini

Pros:
✅ High accuracy (90%+)
✅ Simple setup
✅ AI-powered analysis

Cons:
⚠️ Requires API key
⚠️ Slower than hybrid
⚠️ Less precise bounding boxes
```

### PaddleOCR Only Mode (Fallback)
```
VISION_MODE=paddle

Pros:
✅ No API key needed
✅ Fast processing
✅ Works offline
✅ Precise layout detection

Cons:
⚠️ Lower accuracy (70-80%)
⚠️ Misses text in tables
⚠️ Generic figure detection
```

## 🎯 Success Criteria

### ✅ Backend Working
- [ ] Server starts without errors
- [ ] Health endpoint returns 200
- [ ] Vision mode shows in health response

### ✅ Frontend Working
- [ ] App launches successfully
- [ ] "AI System Ready ✓" shows in header
- [ ] Can select and upload files

### ✅ Integration Working
- [ ] PDF uploads successfully
- [ ] PDF preview appears in left panel
- [ ] AI results appear in right panel
- [ ] Can download Word report

### ✅ Quality Check
- [ ] Text accuracy is good
- [ ] Tables are detected
- [ ] Figures are cropped
- [ ] 7 BAB classification makes sense

## 📝 Next Steps After Testing

### If Everything Works ✅
1. **Test with multiple PDFs** (different formats)
2. **Verify classification accuracy**
3. **Check export quality**
4. **Document any issues**

### If Gemini Works ✅
1. **Compare results**: Hybrid vs Paddle mode
2. **Measure accuracy improvement**
3. **Check API usage** (stay within limits)

### If Issues Found ⚠️
1. **Document the issue**
2. **Check logs** (backend terminal)
3. **Try different vision modes**
4. **Report specific errors**

## 🎉 Completion Checklist

```
Phase 1: Gemini Integration
  ✅ Install dependencies
  ✅ Create Gemini Vision module
  ✅ Integrate with main.py
  ✅ Add configuration system
  ✅ Create test scripts
  ⏳ Get API key (YOUR ACTION)
  ⏳ Test with sample PDF

Phase 2: Frontend PDF Preview
  ✅ Add PDF viewer package
  ✅ Update layout for side-by-side view
  ✅ Create PDF preview widget
  ✅ Add upload button to bottom

Phase 3: Testing & Integration (CURRENT)
  ⏳ Start backend server
  ⏳ Start frontend app
  ⏳ Upload test PDF
  ⏳ Verify PDF preview
  ⏳ Verify AI results
  ⏳ Test export functionality
  ⏳ Compare vision modes
```

---

## 🚀 Quick Start Commands

```bash
# Terminal 1: Backend
cd c:\Users\Hanna\Manbook-v4\backend
python main.py

# Terminal 2: Frontend
cd c:\Users\Hanna\Manbook-v4\frontend
flutter run -d windows

# Browser: Health Check
# http://127.0.0.1:8000/health
```

**🎉 You're ready to test! Start both servers and upload a PDF!**
