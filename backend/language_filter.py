"""
LANGUAGE FILTER — Enforce Target Language on All Text Output
============================================================

Ensures ALL text output strictly follows the selected document language:
  - 'id' → Bahasa Indonesia only (Latin script)
  - 'en' → English only (Latin script)

Any non-Latin scripts (CJK/Mandarin, Cyrillic, Arabic, Thai, Korean, etc.)
are automatically stripped. This prevents PaddleOCR (Baidu) from injecting
Chinese characters and AI models from mixing in unwanted languages.

Usage:
    from language_filter import enforce_language, clean_text

    text = enforce_language("Hello 你好 World", lang='en')
    # Result: "Hello  World"

Updated: March 2026
"""

import re
import logging

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# CHARACTER RANGES TO REMOVE (non-Latin scripts)
# ══════════════════════════════════════════════════════════════════

# CJK Unified Ideographs (Chinese/Japanese Kanji)
_CJK_MAIN      = r'\u4e00-\u9fff'
_CJK_EXT_A     = r'\u3400-\u4dbf'
_CJK_EXT_B     = r'\U00020000-\U0002a6df'
_CJK_COMPAT    = r'\u3300-\u33ff\ufe30-\ufe4f\uf900-\ufaff'

# CJK Symbols, Punctuation & Fullwidth Forms
_CJK_SYMBOLS   = r'\u3000-\u303f'
_FULLWIDTH      = r'\uff00-\uffef'

# Japanese Hiragana & Katakana
_HIRAGANA       = r'\u3040-\u309f'
_KATAKANA       = r'\u30a0-\u30ff'

# Korean Hangul
_HANGUL         = r'\uac00-\ud7af\u1100-\u11ff\u3130-\u318f'

# Cyrillic (Russian, etc.)
_CYRILLIC       = r'\u0400-\u04ff\u0500-\u052f'

# Arabic
_ARABIC         = r'\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff'

# Thai
_THAI           = r'\u0e00-\u0e7f'

# Devanagari (Hindi, etc.)
_DEVANAGARI     = r'\u0900-\u097f'

# Combined pattern: ALL non-Latin scripts
_NON_LATIN_PATTERN = re.compile(
    r'['
    + _CJK_MAIN + _CJK_EXT_A + _CJK_COMPAT
    + _CJK_SYMBOLS + _FULLWIDTH
    + _HIRAGANA + _KATAKANA
    + _HANGUL
    + _CYRILLIC
    + _ARABIC
    + _THAI
    + _DEVANAGARI
    + r']+'
)

# ══════════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def clean_text(text: str) -> str:
    """
    Remove ALL non-Latin script characters from text.
    Keeps: Latin letters (a-z, A-Z), accented chars (é, ñ, ü, etc.),
           digits, punctuation, whitespace.
    Removes: CJK, Cyrillic, Arabic, Thai, Korean, Devanagari, etc.
    """
    if not text:
        return text

    cleaned = _NON_LATIN_PATTERN.sub('', text)

    # Clean up: collapse multiple spaces left by removed characters
    cleaned = re.sub(r'  +', ' ', cleaned)

    # Remove orphaned punctuation left by removed characters
    # e.g., "Hello（）World" → "Hello World"
    cleaned = re.sub(r'\(\s*\)', '', cleaned)
    cleaned = re.sub(r'\[\s*\]', '', cleaned)
    cleaned = re.sub(r'「\s*」', '', cleaned)
    cleaned = re.sub(r'『\s*』', '', cleaned)

    return cleaned.strip()


def enforce_language(text: str, lang: str = 'id') -> str:
    """
    Enforce that text follows the target language.

    1. Removes ALL non-Latin script characters (CJK, Cyrillic, etc.)
    2. Logs a warning if significant content was removed

    Args:
        text: Input text (may contain mixed scripts)
        lang: Target language ('id' for Indonesian, 'en' for English)

    Returns:
        Cleaned text containing only Latin-script characters
    """
    if not text:
        return text

    original_len = len(text)
    cleaned = clean_text(text)
    cleaned_len = len(cleaned)

    # Log if we removed a significant amount of foreign characters
    removed_chars = original_len - cleaned_len
    if removed_chars > 0:
        removed_pct = (removed_chars / original_len) * 100
        if removed_pct > 5:  # More than 5% was non-Latin → worth logging
            lang_name = "Indonesian" if lang == 'id' else "English"
            logger.warning(
                f"🔤 Language filter ({lang_name}): removed {removed_chars} "
                f"non-Latin chars ({removed_pct:.0f}%) from text "
                f"({original_len} → {cleaned_len} chars)"
            )

    return cleaned


def enforce_language_on_items(items: list, lang: str = 'id') -> list:
    """
    Apply language enforcement to a list of structured data items.
    Cleans 'original', 'normalized', and 'text' fields.

    Args:
        items: List of dicts with text fields
        lang:  Target language ('id' or 'en')

    Returns:
        Same list with cleaned text fields (in-place modification)
    """
    text_fields = ['original', 'normalized', 'text', 'corrected']
    cleaned_count = 0

    for item in items:
        for field in text_fields:
            if field in item and isinstance(item[field], str):
                original = item[field]
                cleaned = enforce_language(original, lang=lang)
                if cleaned != original:
                    item[field] = cleaned
                    cleaned_count += 1

    if cleaned_count > 0:
        lang_name = "Indonesian" if lang == 'id' else "English"
        logger.info(
            f"🔤 Language filter: cleaned {cleaned_count} text fields "
            f"to enforce {lang_name}"
        )

    return items


def get_language_instruction(lang: str = 'id') -> str:
    """
    Get a standardized AI prompt instruction that enforces output language.
    Include this in ALL AI prompts to prevent mixed-language output.

    Args:
        lang: Target language ('id' or 'en')

    Returns:
        Prompt instruction string
    """
    if lang == 'id':
        return (
            "ATURAN BAHASA WAJIB:\n"
            "- Tulis SELURUH jawaban dalam Bahasa Indonesia.\n"
            "- DILARANG KERAS menggunakan aksara non-Latin "
            "(Mandarin/Chinese, Jepang, Korea, Arab, Cyrillic, Thai, dll).\n"
            "- Hanya gunakan huruf Latin (a-z, A-Z), angka, dan tanda baca standar.\n"
            "- Istilah teknis yang umum dipakai dalam bahasa Inggris "
            "(display, sensor, battery, dll) boleh tetap dalam bahasa Inggris.\n"
            "- Satuan ukuran tetap dalam format internasional (mL, mmHg, °C, dll).\n"
        )
    else:
        return (
            "LANGUAGE RULES (MANDATORY):\n"
            "- Write the ENTIRE response in English ONLY.\n"
            "- ABSOLUTELY NO non-Latin scripts allowed "
            "(Chinese/Mandarin, Japanese, Korean, Arabic, Cyrillic, Thai, etc.).\n"
            "- Use ONLY Latin characters (a-z, A-Z), numbers, and standard punctuation.\n"
            "- Keep product names, model numbers, and brand names as-is.\n"
            "- Keep measurement units in international format (mL, mmHg, °C, etc.).\n"
        )
