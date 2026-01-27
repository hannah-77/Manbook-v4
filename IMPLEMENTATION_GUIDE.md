# 🔧 Implementation Guide - Missing Features

## 📋 Overview

Dokumen ini berisi **code examples** untuk mengimplementasikan 2 fitur yang masih kurang:
1. **Typo Detection & Highlight**
2. **Fixed Layout Lock**

---

## 1️⃣ TYPO DETECTION & HIGHLIGHT

### Option A: Spell Checker Library (Recommended untuk Start)

#### Step 1: Install Dependencies
```bash
cd backend
pip install pyspellchecker
pip install language-tool-python  # Optional: Grammar check
```

#### Step 2: Update `main.py` - BioBrain Class

**Replace line 162-168:**

```python
class BioBrain:
    def __init__(self):
        # ... existing code ...
        
        # Add spell checker
        from spellchecker import SpellChecker
        self.spell = SpellChecker()
        
        # Optional: Add medical terms dictionary
        self.spell.word_frequency.load_words(['defibrillator', 'sphygmomanometer', 'electrocardiogram'])
    
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
        
        words = text.split()
        typo_words = self.spell.unknown(words)
        
        corrected_words = []
        typo_positions = []
        
        for i, word in enumerate(words):
            if word.lower() in typo_words:
                correction = self.spell.correction(word)
                if correction:
                    corrected_words.append(correction)
                    typo_positions.append({
                        "position": i,
                        "original": word,
                        "suggestion": correction
                    })
                else:
                    corrected_words.append(word)
            else:
                corrected_words.append(word)
        
        corrected_text = " ".join(corrected_words)
        
        return {
            "original": text,
            "corrected": corrected_text,
            "typos": typo_positions,
            "has_typo": len(typo_positions) > 0,
            "confidence": 1.0 - (len(typo_positions) / len(words)) if words else 1.0
        }
```

#### Step 3: Update Processing Workflow

**Update line 336-338:**

```python
# B. THE BRAIN (Classify)
for element in layout_elements:
    # Normalization (NOW RETURNS DICT)
    normalized_result = brain_module.normalize_text(element['text'])
    
    # Update element with normalized data
    element['text'] = normalized_result['corrected']
    element['original_text'] = normalized_result['original']
    element['typos'] = normalized_result['typos']
    element['has_typo'] = normalized_result['has_typo']
    element['text_confidence'] = normalized_result['confidence']
    
    # Semantic Mapping (use corrected text)
    bab_id, bab_title = brain_module.semantic_mapping(element)
    
    # Add Metadata
    structured_data.append({
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
```

---

### Option B: AI-Powered (OpenAI/Gemini)

#### Step 1: Install Dependencies
```bash
pip install openai
# or
pip install google-generativeai
```

#### Step 2: Setup API Key

**Create `.env` file in backend:**
```env
OPENAI_API_KEY=your_api_key_here
# or
GEMINI_API_KEY=your_api_key_here
```

#### Step 3: Update BioBrain Class

```python
import os
from dotenv import load_dotenv
import openai

class BioBrain:
    def __init__(self):
        # ... existing code ...
        
        # Load API key
        load_dotenv()
        openai.api_key = os.getenv('OPENAI_API_KEY')
    
    def normalize_text_with_ai(self, text):
        """
        AI-powered typo correction using GPT-4
        """
        if not text or len(text.strip()) == 0:
            return {
                "original": text,
                "corrected": text,
                "typos": [],
                "has_typo": False,
                "confidence": 1.0
            }
        
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a medical text correction assistant. 
                        Fix typos and OCR errors in medical manual text.
                        Return JSON with: original, corrected, typos (array of {position, original, suggestion})
                        Preserve medical terminology and technical terms."""
                    },
                    {
                        "role": "user",
                        "content": f"Fix typos in this text: {text}"
                    }
                ],
                temperature=0.3
            )
            
            result = json.loads(response.choices[0].message.content)
            result['has_typo'] = len(result.get('typos', [])) > 0
            result['confidence'] = 0.95  # AI confidence
            
            return result
            
        except Exception as e:
            logger.error(f"AI normalization failed: {e}")
            # Fallback to original
            return {
                "original": text,
                "corrected": text,
                "typos": [],
                "has_typo": False,
                "confidence": 1.0
            }
```

---

### Frontend: Typo Highlighting (Flutter)

#### Update `main.dart` - Add Highlight Widget

**Add after line 340:**

```dart
// Build highlighted text with typos
Widget _buildHighlightedText(dynamic item) {
  String original = item['original'] ?? "";
  List typos = item['typos'] ?? [];
  
  if (typos.isEmpty) {
    return Text(original, style: const TextStyle(fontSize: 12));
  }
  
  List<String> words = original.split(' ');
  List<TextSpan> spans = [];
  
  for (int i = 0; i < words.length; i++) {
    bool isTypo = typos.any((t) => t['position'] == i);
    
    spans.add(TextSpan(
      text: words[i] + ' ',
      style: TextStyle(
        fontSize: 12,
        backgroundColor: isTypo ? Colors.yellow.shade200 : null,
        decoration: isTypo ? TextDecoration.underline : null,
        decorationColor: Colors.red,
        decorationStyle: TextDecorationStyle.wavy,
      ),
    ));
  }
  
  return RichText(
    text: TextSpan(
      style: const TextStyle(color: Colors.black),
      children: spans,
    ),
  );
}
```

**Replace line 340-344:**

```dart
// Text Content with Typo Highlighting
if (type != 'figure')
  Padding(
    padding: const EdgeInsets.all(8.0),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Show typo warning
        if (item['has_typo'] == true)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            margin: const EdgeInsets.only(bottom: 8),
            decoration: BoxDecoration(
              color: Colors.orange.shade100,
              borderRadius: BorderRadius.circular(4),
            ),
            child: Row(
              children: [
                const Icon(Icons.warning_amber, size: 16, color: Colors.orange),
                const SizedBox(width: 4),
                Text(
                  '${(item['typos'] as List).length} possible typo(s)',
                  style: const TextStyle(fontSize: 10, color: Colors.orange),
                ),
              ],
            ),
          ),
        
        // Highlighted text
        _buildHighlightedText(item),
        
        // Show corrected version if different
        if (item['original'] != item['normalized'])
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: Colors.green.shade50,
                border: Border.all(color: Colors.green.shade200),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Suggested Correction:',
                    style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    item['normalized'],
                    style: const TextStyle(fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
      ],
    ),
  )
```

---

## 2️⃣ FIXED LAYOUT LOCK

### Step 1: Install PDF Export Library

```bash
cd backend
pip install docx2pdf
# or for cross-platform
pip install python-docx-template
pip install reportlab  # Alternative: Generate PDF directly
```

### Step 2: Update `BioArchitect` Class

**Replace line 224-283 with enhanced version:**

```python
from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

class BioArchitect:
    """
    Bertugas menyusun kembali data ke Template Standar (.docx).
    Fixed-Layout Export dengan LOCKED settings.
    """
    def __init__(self):
        pass
    
    def _set_fixed_margins(self, doc):
        """Lock document margins"""
        sections = doc.sections
        for section in sections:
            # Page Size (Letter)
            section.page_height = Inches(11)
            section.page_width = Inches(8.5)
            
            # Margins (FIXED)
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1.25)
            section.right_margin = Inches(1.25)
            
            # Header/Footer
            section.header_distance = Inches(0.5)
            section.footer_distance = Inches(0.5)
    
    def _set_fixed_styles(self, doc):
        """Lock font and paragraph styles"""
        
        # Normal Style
        normal_style = doc.styles['Normal']
        normal_font = normal_style.font
        normal_font.name = 'Arial'
        normal_font.size = Pt(11)
        normal_font.color.rgb = RGBColor(0, 0, 0)
        
        normal_para = normal_style.paragraph_format
        normal_para.line_spacing = 1.15
        normal_para.space_after = Pt(6)
        
        # Heading 1 (Chapter Titles)
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
        
        # Heading 2 (Subtitles)
        h2_style = doc.styles['Heading 2']
        h2_font = h2_style.font
        h2_font.name = 'Arial'
        h2_font.size = Pt(14)
        h2_font.bold = True
        h2_font.color.rgb = RGBColor(31, 56, 100)  # Dark blue
        
        h2_para = h2_style.paragraph_format
        h2_para.space_before = Pt(10)
        h2_para.space_after = Pt(4)
    
    def _add_header_footer(self, doc, filename):
        """Add header and footer"""
        section = doc.sections[0]
        
        # Header
        header = section.header
        header_para = header.paragraphs[0]
        header_para.text = "BioManual Standardization Report"
        header_para.style = doc.styles['Header']
        header_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Footer with page number
        footer = section.footer
        footer_para = footer.paragraphs[0]
        footer_para.text = f"Source: {filename} | Page "
        footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # Add page number field
        run = footer_para.add_run()
        fldChar1 = OxmlElement('w:fldChar')
        fldChar1.set(qn('w:fldCharType'), 'begin')
        
        instrText = OxmlElement('w:instrText')
        instrText.set(qn('xml:space'), 'preserve')
        instrText.text = "PAGE"
        
        fldChar2 = OxmlElement('w:fldChar')
        fldChar2.set(qn('w:fldCharType'), 'end')
        
        run._r.append(fldChar1)
        run._r.append(instrText)
        run._r.append(fldChar2)

    def build_report(self, classified_data, original_filename):
        doc = Document()
        
        # ===== APPLY FIXED LAYOUT SETTINGS =====
        self._set_fixed_margins(doc)
        self._set_fixed_styles(doc)
        self._add_header_footer(doc, original_filename)
        
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
                grouped["BAB 1"].append(item)

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
                            pic = doc.add_picture(item['crop_local'], width=Inches(5))
                            
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
        
        # ===== EXPORT TO PDF =====
        pdf_filename = f"Standardized_{Path(original_filename).stem}.pdf"
        pdf_path = os.path.join(BASE_PATH, pdf_filename)
        
        try:
            from docx2pdf import convert
            convert(word_path, pdf_path)
            logger.info(f"✓ PDF exported: {pdf_filename}")
        except Exception as e:
            logger.warning(f"PDF export failed: {e}")
            pdf_filename = None
        
        return {
            "word_file": word_filename,
            "pdf_file": pdf_filename
        }
```

### Step 3: Update API Response

**Update line 359-365:**

```python
# STEP 3: THE ARCHITECT (Build)
result = architect_module.build_report(structured_data, file.filename)

word_url = f"http://127.0.0.1:8000/files/{result['word_file']}"
pdf_url = f"http://127.0.0.1:8000/files/{result['pdf_file']}" if result['pdf_file'] else None

return {
    "success": True,
    "results": structured_data,
    "word_url": word_url,
    "pdf_url": pdf_url
}
```

---

## 3️⃣ TESTING

### Test Typo Detection

```python
# Add to backend/test_typo.py
from main import BioBrain

brain = BioBrain()

test_texts = [
    "The defibrillator is usde for cardiac arrest",  # typo: usde -> used
    "Instalation procedur is simple",  # typos: instalation, procedur
    "Maintenence should be done monthly"  # typo: maintenence
]

for text in test_texts:
    result = brain.normalize_text(text)
    print(f"Original: {result['original']}")
    print(f"Corrected: {result['corrected']}")
    print(f"Typos: {result['typos']}")
    print(f"Has Typo: {result['has_typo']}")
    print("---")
```

### Test Fixed Layout

```python
# Add to backend/test_layout.py
from main import BioArchitect

architect = BioArchitect()

test_data = [
    {
        "chapter_id": "BAB 1",
        "chapter_title": "Tujuan Penggunaan & Keamanan",
        "type": "text",
        "original": "This is a test",
        "normalized": "This is a test",
        "typos": [],
        "has_typo": False,
        "crop_url": None,
        "crop_local": None
    }
]

result = architect.build_report(test_data, "test.pdf")
print(f"Word file: {result['word_file']}")
print(f"PDF file: {result['pdf_file']}")
```

---

## 4️⃣ DEPLOYMENT CHECKLIST

### Before Deployment

- [ ] Install all dependencies
  ```bash
  pip install pyspellchecker
  pip install docx2pdf
  pip install python-dotenv  # if using AI
  ```

- [ ] Update `requirements.txt`
  ```bash
  pip freeze > requirements.txt
  ```

- [ ] Test typo detection
  ```bash
  python test_typo.py
  ```

- [ ] Test layout export
  ```bash
  python test_layout.py
  ```

- [ ] Test full workflow
  ```bash
  python main.py
  # Upload a test PDF via web interface
  ```

### After Deployment

- [ ] Verify Word export has locked margins
- [ ] Verify PDF export works
- [ ] Verify typo highlighting in Flutter
- [ ] Check performance with large PDFs
- [ ] Test with various manual book formats

---

## 5️⃣ TROUBLESHOOTING

### Issue: docx2pdf not working on Windows

**Solution:**
```bash
# Install Microsoft Word or use alternative
pip uninstall docx2pdf
pip install python-docx-template
pip install reportlab

# Use reportlab for PDF generation instead
```

### Issue: Spell checker too aggressive

**Solution:**
```python
# Add custom dictionary
self.spell.word_frequency.load_words([
    'defibrillator', 'sphygmomanometer', 'electrocardiogram',
    'oximeter', 'nebulizer', 'ventilator'
    # Add more medical terms
])

# Or load from file
with open('medical_terms.txt') as f:
    terms = f.read().splitlines()
    self.spell.word_frequency.load_words(terms)
```

### Issue: AI API rate limit

**Solution:**
```python
# Add retry logic
import time
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def normalize_text_with_ai(self, text):
    # ... existing code ...
```

---

## 📊 EXPECTED RESULTS

After implementing these changes:

### Typo Detection
- ✅ Typos highlighted in yellow
- ✅ Suggestions shown in green box
- ✅ Confidence score displayed
- ✅ User can see original vs corrected

### Fixed Layout
- ✅ Margins: 1" top/bottom, 1.25" left/right
- ✅ Font: Arial 11pt for body, 16pt for H1
- ✅ Page size: Letter (8.5" x 11")
- ✅ Export to both Word and PDF
- ✅ Header/footer with page numbers

### Overall Score
**82% → 100%** ✅

---

## 🎯 NEXT STEPS

1. **Implement Typo Detection** (2-3 days)
   - Choose Option A (spell checker) or Option B (AI)
   - Update backend code
   - Update Flutter UI
   - Test with sample documents

2. **Implement Fixed Layout** (1 day)
   - Update BioArchitect class
   - Test Word export
   - Test PDF export
   - Verify layout consistency

3. **Integration Testing** (1 day)
   - Test full workflow
   - Test with various document formats
   - Performance testing
   - Bug fixes

**Total Estimated Time: 4-5 days**

---

## 💡 TIPS

1. **Start with Option A (Spell Checker)** for typo detection
   - Easier to implement
   - No API costs
   - Good for most cases

2. **Upgrade to Option B (AI)** later if needed
   - Better accuracy
   - Context-aware corrections
   - Can handle medical terminology better

3. **Test incrementally**
   - Test typo detection first
   - Then add layout fixes
   - Don't change everything at once

4. **Keep backups**
   - Git commit before major changes
   - Test on sample data first
   - Have rollback plan

---

## 📞 SUPPORT

Jika ada pertanyaan atau butuh bantuan implementasi, silakan tanya! 😊

Saya bisa bantu:
- Debug code
- Optimize performance
- Add more features
- Testing strategy
