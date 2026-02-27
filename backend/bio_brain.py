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
            "BAB 1": {"title": "Tujuan Penggunaan & Keamanan", "keywords": ["tujuan", "intended", "safety", "warning", "caution", "bahaya", "introduction", "overview"]},
            "BAB 2": {"title": "Instalasi", "keywords": ["install", "setup", "pasang", "mounting", "connect", "power", "unboxing"]},
            "BAB 3": {"title": "Panduan Operasional & Pemantauan Klinis", "keywords": ["operation", "operasional", "monitor", "display", "screen", "tombol", "measure", "klinis"]},
            "BAB 4": {"title": "Perawatan, Pemeliharaan & Pembersihan", "keywords": ["maintenance", "clean", "bersih", "replace", "ganti", "battery", "care"]},
            "BAB 5": {"title": "Pemecahan Masalah", "keywords": ["trouble", "masalah", "error", "fail", "rusak", "solution", "solusi"]},
            "BAB 6": {"title": "Spesifikasi Teknis & Kepatuhan Standar", "keywords": ["spec", "tech", "data", "dimension", "weight", "standar", "iso", "iec"]},
            "BAB 7": {"title": "Garansi & Layanan", "keywords": ["warrant", "garansi", "service", "layanan", "contact", "support"]},
            
            # English Variants
            "Chapter 1": {"title": "Intended Use & Safety", "keywords": ["purpose", "safety", "intended", "warning", "caution", "danger", "introduction", "overview"]},
            "Chapter 2": {"title": "Installation", "keywords": ["install", "setup", "mounting", "connect", "power", "unboxing"]},
            "Chapter 3": {"title": "Operation & Clinical Monitoring", "keywords": ["operation", "monitor", "display", "screen", "buttons", "measure", "clinical"]},
            "Chapter 4": {"title": "Maintenance, Care & Cleaning", "keywords": ["maintenance", "cleaning", "care", "replace", "battery", "sterilize"]},
            "Chapter 5": {"title": "Troubleshooting", "keywords": ["trouble", "error", "fail", "problem", "solution", "faq"]},
            "Chapter 6": {"title": "Technical Specifications & Standards", "keywords": ["spec", "technical", "data", "dimension", "weight", "standards", "iso", "iec"]},
            "Chapter 7": {"title": "Warranty & Service", "keywords": ["warranty", "guarantee", "service", "contact", "support"]}
        }
        self.current_context = "BAB 1"
        
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
        # 7. Check for critical keywords with slight typos
        
        # We only auto-correct if it's very close (cutoff=0.85) to avoid false positives
        # And only for words in our specific dictionary (not general English)
        words_list = cleaned.split()
        final_words = []
        
        # Build whitelist set for speed
        try:
            spell_words = list(self.spell.word_frequency.words())
        except Exception:
            spell_words = []
        vocab_set = set(spell_words + list(self.taxonomy.keys()))


        for w in words_list:
            # If word is already correct, keep it
            if w.lower() in vocab_set or (self.spell and w.lower() in self.spell):
                final_words.append(w)
                continue
            
            # If not, try to find a close match in our specific medical/manual terms
            # We DONT use general dictionary for auto-correct to be safe
            matches = get_close_matches(w.lower(), list(vocab_set), n=1, cutoff=0.85)
            
            if matches:
                # Preserve original casing if possible (simple heuristic)
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
                if hits >= 3:  # Butuh setidaknya 3 keywords untuk pindah bab di tengah teks
                     self.current_context = code

        # Return Decision
        return self.current_context, self.taxonomy[self.current_context]["title"]
