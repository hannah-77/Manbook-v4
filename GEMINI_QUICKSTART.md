# 🚀 Gemini Integration - Quick Start Guide

## ✅ Step 1: Get Gemini API Key

1. Open your browser and go to: **https://aistudio.google.com/app/apikey**
2. Sign in with your Google account
3. Click **"Create API key in new project"** (or select existing project)
4. Copy the API key that appears

## ✅ Step 2: Configure API Key

1. Open the file: `backend\.env`
2. Find the line: `GEMINI_API_KEY=your-api-key-here`
3. Replace `your-api-key-here` with your actual API key
4. Save the file

Example:
```
GEMINI_API_KEY=AIzaSyABC123XYZ789...
```

## ✅ Step 3: Install Dependencies

Open terminal in the `backend` folder and run:

```bash
cd backend
pip install -r requirements.txt
```

Or simply run the setup script:
```bash
setup-gemini.bat
```

## ✅ Step 4: Start Backend

```bash
python main.py
```

Or use:
```bash
start-backend.bat
```

## 🎯 Vision Mode Options

The backend supports 3 vision modes (configured in `.env`):

### 1. **Hybrid Mode** (Recommended) ⭐
```
VISION_MODE=hybrid
```
- Uses PaddleOCR for precise layout detection
- Uses Gemini for accurate text extraction
- **Best accuracy and reliability**

### 2. **Gemini Only Mode**
```
VISION_MODE=gemini
```
- Uses only Gemini Vision API
- Good for simple documents
- Faster but less precise layout detection

### 3. **PaddleOCR Only Mode** (Fallback)
```
VISION_MODE=paddle
```
- Uses only PaddleOCR (traditional OCR)
- No API key needed
- Lower accuracy for complex layouts

## 🧪 Testing

After starting the backend, test with:

1. Open browser: `http://127.0.0.1:8000/health`
2. Should see: `{"status": "BioManual System Online"}`

## 📊 Expected Improvements

### Before (PaddleOCR only):
- ❌ Misses text in tables/images
- ❌ Low accuracy on complex layouts
- ❌ Poor handling of biomedical terminology

### After (Gemini Hybrid):
- ✅ Reads ALL text accurately
- ✅ Tables and figures properly extracted
- ✅ Better understanding of medical terms
- ✅ Improved chapter classification

## 🔧 Troubleshooting

### Error: "GEMINI_API_KEY not set"
- Make sure you edited `.env` file
- Check that API key doesn't have quotes
- Restart the backend after editing

### Error: "Failed to initialize Gemini"
- Check your internet connection
- Verify API key is valid
- Check API quota limits (15 requests/min for free tier)

### Gemini not working
- Backend will automatically fallback to PaddleOCR
- Check logs for error messages

## 📝 API Rate Limits (Free Tier)

- **15 requests per minute**
- **1,500 requests per day**
- Good enough for testing and moderate use

For production, consider upgrading to paid tier.

## 🎉 Next Steps

Once Gemini is working:
1. Test with a sample biomedical manual PDF
2. Compare results with old PaddleOCR-only version
3. Adjust `VISION_MODE` if needed
4. Consider adding PDF preview to frontend (Phase 2)

---

**Need help?** Check the main `GEMINI_INTEGRATION_PLAN.md` for detailed implementation guide.
