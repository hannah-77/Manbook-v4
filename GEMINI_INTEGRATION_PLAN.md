# 🚀 Gemini Integration Plan - Kirei UI Improvements

## Masalah yang Ditemukan

### 1. **Tidak Ada PDF Preview**
- ❌ Setelah upload, tidak ada preview PDF di side-by-side view
- ❌ User tidak bisa melihat dokumen yang sedang diproses

### 2. **Hasil AI Tidak Akurat**
- ❌ Menggunakan PaddleOCR (OCR tradisional)
- ❌ Tidak semua text terbaca dengan baik
- ❌ Gambar dan tabel tidak akurat

### 3. **Belum Menggunakan Gemini API**
- ❌ Backend belum terintegrasi dengan Gemini
- ❌ Tidak memanfaatkan AI multimodal untuk analisis dokumen

---

## Solusi yang Akan Diimplementasikan

### **Phase 1: PDF Preview (Frontend)** ✅
**File:** `frontend/lib/main.dart`

**Perubahan:**
1. Tambahkan package `syncfusion_flutter_pdfviewer` atau `pdf_render`
2. Ubah layout side-by-side:
   - **Panel Kiri:** PDF Preview + Upload Button
   - **Panel Kanan:** AI Results
3. Simpan file path untuk ditampilkan di viewer

**Implementasi:**
```dart
// Tambah di pubspec.yaml
dependencies:
  syncfusion_flutter_pdfviewer: ^latest

// Tambah widget PDF Viewer
Widget _buildPdfPreview() {
  if (_selectedFilePath == null) return _buildUploadZone();
  
  return Column(
    children: [
      Expanded(
        child: SfPdfViewer.file(File(_selectedFilePath!)),
      ),
      ElevatedButton(
        onPressed: _pickAndUpload,
        child: Text('Upload Another'),
      ),
    ],
  );
}
```

---

### **Phase 2: Gemini API Integration (Backend)** 🔥
**File:** `backend/main.py`

**Perubahan:**
1. Install Google Generative AI SDK
2. Ganti `BioVision` class untuk menggunakan Gemini Vision
3. Kirim gambar halaman ke Gemini untuk analisis
4. Gunakan prompt engineering untuk ekstraksi terstruktur

**Implementasi:**

#### A. Install Dependencies
```bash
pip install google-generativeai pillow
```

#### B. Setup API Key
```python
import google.generativeai as genai
import os

# Di awal file
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'YOUR_API_KEY_HERE')
genai.configure(api_key=GEMINI_API_KEY)
```

#### C. Buat Gemini Vision Module
```python
class BioVisionGemini:
    """
    Menggunakan Gemini Vision API untuk analisis dokumen yang lebih akurat
    """
    def __init__(self):
        self.model = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("✓ Gemini Vision Engine Ready")
    
    def analyze_page(self, image_path):
        """
        Analisis halaman menggunakan Gemini Vision
        Returns: Structured data dengan text, tables, figures
        """
        from PIL import Image
        
        img = Image.open(image_path)
        
        prompt = """
        Analyze this biomedical manual page and extract:
        
        1. **Text Content**: All readable text in order
        2. **Tables**: Identify any tables with their data
        3. **Figures**: Identify any diagrams, images, or illustrations
        4. **Layout**: Bounding boxes for each element (approximate)
        
        Return in JSON format:
        {
          "elements": [
            {
              "type": "text|title|table|figure",
              "content": "extracted text or description",
              "bbox": [x1, y1, x2, y2],
              "confidence": 0.0-1.0
            }
          ]
        }
        
        Be thorough and accurate. Extract ALL text, even in tables and figures.
        """
        
        response = self.model.generate_content([prompt, img])
        
        # Parse JSON response
        import json
        try:
            # Extract JSON from markdown code blocks if present
            text = response.text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            data = json.loads(text.strip())
            return data.get('elements', [])
        except:
            logger.warning("Failed to parse Gemini response as JSON")
            # Fallback: treat as plain text
            return [{
                "type": "text",
                "content": response.text,
                "bbox": [0, 0, 100, 100],
                "confidence": 0.8
            }]
```

#### D. Update Process Workflow
```python
# Ganti vision_module
vision_module = BioVisionGemini()  # Instead of BioVision()

# Di endpoint /process
for i, img_src in enumerate(images):
    page_path = img_src
    if not isinstance(img_src, str):
        page_path = os.path.join(BASE_PATH, f"page_{i}.png")
        img_src.save(page_path, "PNG")
    
    # A. THE EYE (Gemini Vision)
    layout_elements = vision_module.analyze_page(page_path)
    
    # B. THE BRAIN (Classify)
    for element in layout_elements:
        # ... rest of the code
```

---

### **Phase 3: Hybrid Approach (Best of Both)** 🎯

**Strategi:**
1. **Gemini Vision** untuk text extraction (lebih akurat)
2. **PaddleOCR** untuk bounding box detection (lebih presisi)
3. **Combine** keduanya untuk hasil optimal

```python
class BioVisionHybrid:
    def __init__(self):
        # Gemini for content
        self.gemini = genai.GenerativeModel('gemini-1.5-flash')
        
        # PaddleOCR for layout
        self.paddle = PPStructure(show_log=False, lang='en')
        
        logger.info("✓ Hybrid Vision Engine Ready (Gemini + Paddle)")
    
    def scan_document(self, image_path, filename_base):
        """
        Hybrid approach:
        1. PaddleOCR detects layout (bbox)
        2. Gemini extracts accurate content
        """
        from PIL import Image
        import cv2
        
        original_img = cv2.imread(image_path)
        pil_img = Image.open(image_path)
        
        # Step 1: Get layout from PaddleOCR
        paddle_result = self.paddle(original_img)
        paddle_result.sort(key=lambda x: x['bbox'][1])
        
        # Step 2: For each region, use Gemini to extract content
        extracted_elements = []
        
        for idx, region in enumerate(paddle_result):
            box = region['bbox']
            region_type = region['type']
            
            # Crop region
            x1, y1, x2, y2 = box
            h, w, _ = original_img.shape
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            
            crop_img_cv = original_img[y1:y2, x1:x2]
            
            # Convert to PIL for Gemini
            crop_pil = Image.fromarray(cv2.cvtColor(crop_img_cv, cv2.COLOR_BGR2RGB))
            
            # Use Gemini to extract text from this region
            if region_type in ['text', 'title']:
                prompt = "Extract all text from this image region. Return only the text, no formatting."
                response = self.gemini.generate_content([prompt, crop_pil])
                text_content = response.text.strip()
            elif region_type == 'table':
                prompt = "This is a table. Extract all data in structured format. Preserve rows and columns."
                response = self.gemini.generate_content([prompt, crop_pil])
                text_content = response.text.strip()
            elif region_type == 'figure':
                prompt = "Describe this figure/diagram in detail. What does it show?"
                response = self.gemini.generate_content([prompt, crop_pil])
                text_content = f"[FIGURE: {response.text.strip()}]"
            else:
                text_content = ""
            
            # Save crop
            crop_url = None
            crop_local = None
            if region_type in ['figure', 'table']:
                crop_fname = f"{filename_base}_{region_type}_{idx}.jpg"
                crop_local = os.path.join(OUTPUT_DIR, crop_fname)
                cv2.imwrite(crop_local, crop_img_cv)
                crop_url = f"http://127.0.0.1:8000/output/{crop_fname}"
            
            extracted_elements.append({
                "type": region_type,
                "bbox": box,
                "text": text_content,
                "confidence": 0.95,  # Gemini is highly accurate
                "crop_url": crop_url,
                "crop_local": crop_local
            })
        
        return extracted_elements
```

---

## Langkah Implementasi

### **Step 1: Setup Gemini API Key**
```bash
# Windows
setx GEMINI_API_KEY "your-api-key-here"

# Atau tambahkan di .env file
echo GEMINI_API_KEY=your-api-key-here > .env
```

### **Step 2: Install Dependencies**
```bash
cd backend
pip install google-generativeai python-dotenv
```

### **Step 3: Update Backend Code**
- Modifikasi `main.py` dengan Hybrid Vision
- Test dengan sample PDF

### **Step 4: Update Frontend**
- Tambah PDF viewer di `main.dart`
- Update layout side-by-side

### **Step 5: Testing**
- Upload sample biomedical manual
- Verify PDF preview muncul
- Verify AI results lebih akurat

---

## Expected Results

### Before (Current)
- ❌ No PDF preview
- ❌ PaddleOCR misses text in tables/images
- ❌ Low accuracy on complex layouts

### After (With Gemini)
- ✅ PDF preview in left panel
- ✅ Gemini reads ALL text accurately
- ✅ Tables and figures properly extracted
- ✅ Better chapter classification

---

## API Key Information

**Get Gemini API Key:**
1. Go to: https://aistudio.google.com/app/apikey
2. Create new API key
3. Copy and set as environment variable

**Free Tier Limits:**
- 15 requests per minute
- 1,500 requests per day
- Good enough for testing and moderate use

---

## Next Steps

1. **Dapatkan Gemini API Key** dari Google AI Studio
2. **Pilih approach:** Full Gemini atau Hybrid (recommended)
3. **Implement** perubahan di backend
4. **Add PDF viewer** di frontend
5. **Test** dengan dokumen real

Apakah Anda sudah punya Gemini API key? Atau perlu bantuan untuk mendapatkannya?
