"""
MODULE 2: THE BRAIN 🧠 (Logic & Classification)
================================================
Bertugas membaca teks, normalisasi, dan klasifikasi ke 7 BAB Standar.
Menggunakan Semantic Mapping.

Updated: February 2026
"""

import re
import logging
from difflib import get_close_matches

logger = logging.getLogger("BioManual")


class BioBrain:
    """
    Bertugas membaca teks, normalisasi, dan klasifikasi ke 7 BAB Standar.
    Menggunakan Semantic Mapping.
    """
    def __init__(self):
        # The 7 Standard Chapters (Fixed Schema)
        self.taxonomy = {
            "BAB 1": {"title": "Tujuan Penggunaan & Keamanan", "keywords": ["tujuan", "intended", "safety", "warning", "caution", "bahaya", "peringatan", "keamanan", "introduction", "overview"]},
            "BAB 2": {"title": "Instalasi", "keywords": ["install", "setup", "pasang", "mounting", "connect", "power", "unboxing", "rakit", "assembly"]},
            "BAB 3": {"title": "Panduan Operasional & Pemantauan Klinis", "keywords": ["operation", "operasional", "monitor", "display", "screen", "tombol", "measure", "klinis", "prosedur", "langkah", "cara kerja", "penggunaan"]},
            "BAB 4": {"title": "Perawatan, Pemeliharaan & Pembersihan", "keywords": ["maintenance", "clean", "bersih", "replace", "ganti", "battery", "care", "steril", "disinfeksi"]},
            "BAB 5": {"title": "Pemecahan Masalah", "keywords": ["trouble", "masalah", "error", "fail", "rusak", "solution", "solusi", "alarm", "kode"]},
            "BAB 6": {"title": "Spesifikasi Teknis & Kepatuhan Standar", "keywords": ["spec", "tech", "data", "dimension", "weight", "standar", "iso", "iec", "klasifikasi", "suhu"]},
            "BAB 7": {"title": "Garansi & Layanan", "keywords": ["warrant", "garansi", "service", "layanan", "kontak", "distributor", "contact", "support", "permai", "osowilangun", "purna jual"]},
            
            # English Variants
            "Chapter 1": {"title": "Intended Use & Safety", "keywords": ["purpose", "safety", "intended", "warning", "caution", "danger", "introduction", "overview"]},
            "Chapter 2": {"title": "Installation", "keywords": ["install", "installation", "setup", "mounting", "connect", "power", "unboxing", "assembly"]},
            "Chapter 3": {"title": "Operation & Clinical Monitoring", "keywords": ["operation", "monitor", "display", "screen", "buttons", "measure", "clinical", "procedure", "usage", "how to use"]},
            "Chapter 4": {"title": "Maintenance, Care & Cleaning", "keywords": ["maintenance", "cleaning", "care", "replace", "battery", "sterilize", "disinfect"]},
            "Chapter 5": {"title": "Troubleshooting", "keywords": ["trouble", "error", "fail", "problem", "solution", "faq", "alarm codes"]},
            "Chapter 6": {"title": "Technical Specifications & Standards", "keywords": ["spec", "technical", "data", "dimension", "weight", "standards", "iso", "iec", "environmental"]},
            "Chapter 7": {
                "title": "Warranty & Service",
                "keywords": ['warranty', 'service', 'support', 'contact', 'distributor', 'repair', 'after sales', 'guarantees', 'guarantee', 'osowilangun', 'permai']
            }
        }
        self.current_context = "BAB 1"
        self.spell = None
        # Note: spell checker is fully initialized in reset_context()

        
    def reset_context(self):
        """Reset classification state for a new document."""
        self.current_context = "BAB 1"
        logger.info("🔄 Brain context reset to BAB 1")
        
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

    def normalize_text(self, text, lang='id'):
        """
        Koreksi Typo & Normalisasi
        - Regex cleanup (OCR artifacts): ALWAYS runs (language-agnostic)
        - Spell checking: ONLY for English. Indonesian text is left as-is
          because the English spell checker actively corrupts Indonesian words.
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
        # NOTE: Fuzzy matching HANYA untuk bahasa Inggris.
        # Untuk Indonesia, text_corrector.py menangani koreksi OCR secara lebih presisi.
        # BioBrain fuzzy matching DINONAKTIFKAN untuk 'id' karena kamus spell checker
        # (bahasa Inggris) salah mencocokkan kata Indonesia ke kata asing.
        if lang != 'id':
            words_list = cleaned.split()
            final_words = []
            # Only fuzzy match against taxonomy keys to prevent infinite loops.
            # Actual spell checking occurs later via self.spell.correction()
            vocab_set = set(self.taxonomy.keys())

            for w in words_list:
                if w.lower() in vocab_set or (self.spell and w.lower() in self.spell):
                    final_words.append(w)
                    continue
                matches = get_close_matches(w.lower(), list(vocab_set), n=1, cutoff=0.85)
                if matches:
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
        
        # For Indonesian: SKIP spell checker entirely!
        # The English spell checker would "correct" valid Indonesian words
        # like 'penggunaan' → some random English word. This is HARMFUL.
        if lang == 'id' or not self.spell:
            return {
                "original": text.strip(),
                "corrected": text.strip(),
                "typos": [],
                "has_typo": False,
                "confidence": 1.0
            }
        
        # For English: spell checker runs normally
        
        # Split into words (preserve punctuation context)
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
        Ultimate Semantic Mapping using Regex + Hard-Switch logic.
        """
        import re
        text = (item.get('text') or "").lower()
        rtype = item.get('type', 'text')
        
        # 1. Explicit Headers (Absolute Priority) - e.g., "BAB 2", "Chapter 2", "8AB 2"
        for i in range(1, 8):
            # Catch common OCR misreads like '8AB', 'B4B', 'Chapt', 'Ch.'
            if re.search(rf'\b(bab|chapter|bagian|section|8ab|b4b|chapt|ch\.)\s*{i}\b', text):
                # Use BAB X as internal standard
                key = f"BAB {i}" 
                if (f"Chapter {i}" in self.taxonomy) and (re.search(r'chapter|chapt|ch\.', text)):
                    key = f"Chapter {i}"
                
                logger.info(f"📍 Context Switch: Found Explicit Header '{text.upper()}' -> {key}")
                self.current_context = key
                return key, self.taxonomy.get(key, {}).get("title", "Unknown")

        # 2. Hard-Switch Keywords (Priority 2)
        # If these appear in a title/heading, we MUST switch immediately.
        hard_switches = {
            "BAB 1": [r'\bintended', r'\btujuan', r'\bsafety', r'\bkeamanan', r'\bwarning', r'\bperingatan', r'\bintro'],
            "BAB 2": [r'\binstall', r'\bpasang', r'\bsetup', r'\bassembly', r'\bmerakit'],
            "BAB 3": [r'\boperation', r'\boperasional', r'\bmonitor', r'\buse', r'\bpenggunaan', r'\binstruksi', r'\bmanual'],
            "BAB 4": [r'\bmaintenance', r'\bperawatan', r'\bpemeliharaan', r'\bclean', r'\bbersih', r'\bsteril'],
            "BAB 5": [r'\btrouble', r'\bmasalah', r'\berror', r'\bsolusi', r'\bkerusakan'],
            "BAB 6": [r'\bspecification', r'\bspesifikasi', r'\bteknis', r'\btechnical', r'\bdata sheet'],
            "BAB 7": [r'\bwarranty', r'\bgaransi', r'\bservice', r'\blayanan', r'\bkontak', r'\bcontact', r'\bsupport']
        }
        
        if rtype in ('title', 'heading'):
            for code, patterns in hard_switches.items():
                for p in patterns:
                    if re.search(p, text):
                        # Map internal BAB code to taxonomy keys
                        target_key = code
                        # Handle Chapter mapping if the doc seems to use English chapters
                        if self.current_context.startswith("Chapter") and f"Chapter {code[-1]}" in self.taxonomy:
                            target_key = f"Chapter {code[-1]}"
                        
                        logger.info(f"📍 Context Switch: Hard-Switch Keyword '{p}' found in heading -> {target_key}")
                        self.current_context = target_key
                        return self.current_context, self.taxonomy[target_key]["title"]

        # 3. Dynamic Keyword Scoring (Priority 3)
        best_match = None
        max_score = 0
        
        for code, meta in self.taxonomy.items():
            score = 0
            for k in meta['keywords']:
                if re.search(rf'\b{re.escape(k)}', text):
                    score += 1
            
            if score > max_score:
                max_score = score
                best_match = code
        
        # Thresholds for change
        if rtype in ('title', 'heading') and max_score >= 1:
            self.current_context = best_match
        elif max_score >= 2:
            self.current_context = best_match
            
        return self.current_context, self.taxonomy.get(self.current_context, {}).get("title", "Unknown")

    def classify_chapter_ai(self, text, current_chapter, lang="id"):
        """
        Use Gemini AI to classify which chapter the text belongs to.
        Returns code (e.g. 'BAB 2') or None.
        """
        try:
            from openrouter_client import get_openrouter_client
            client = get_openrouter_client()
            if not client: return None
            
            chapters_summary = "\n".join([f"{k}: {v['title']}" for k, v in self.taxonomy.items() if "BAB" in k])
            
            prompt = f"""Identify which chapter this text belongs to in a technical manual.
Chapters:
{chapters_summary}

Text: "{text}"

Current Context: {current_chapter}

Guidelines:
- If the text is a new heading, assign the most relevant BAB.
- If it's ambiguous, return the current context.
- Return ONLY the chapter code (e.g. 'BAB 4').

Result:"""
            result = client.call(prompt, timeout=10).strip()
            # Extract pattern like BAB 1 or Chapter 1
            match = re.search(r'(BAB|Chapter)\s*(\d)', result, re.IGNORECASE)
            if match:
                code = f"BAB {match.group(2)}"
                return code
        except Exception as e:
            logger.warning(f"AI classification failed: {e}")
        return None
