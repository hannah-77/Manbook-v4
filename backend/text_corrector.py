"""
TEXT CORRECTOR — BioManual OCR Post-Processor
=============================================

3-stage pipeline untuk membersihkan hasil OCR:

  Stage A: SymSpell     → koreksi typo per-kata (edit distance)
  Stage B: Context Rule → koreksi berdasarkan kata-kata di sekitarnya
  Stage C: Entity Map   → standarisasi brand & entitas spesifik

Dipanggil oleh vision_engine.py tepat setelah teks OCR diekstrak,
sebelum masuk chapter classification (Stage 3).

Designed to work for BOTH bahasa Indonesia ('id') and English ('en').
"""

import os
import re
import logging
import urllib.request

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# SymSpell Setup (lazy-loaded, singleton per language)
# ─────────────────────────────────────────────────────────────────

_sym_spell_id = None   # Indonesian corrector
_sym_spell_en = None   # English corrector

_DICT_DIR = os.path.dirname(os.path.abspath(__file__))
_DICT_ID_PATH = os.path.join(_DICT_DIR, "kamus_dasar_id.txt")
_DICT_EN_PATH = os.path.join(_DICT_DIR, "kamus_dasar_en.txt")

# URL kamus bahasa Inggris (bawaan SymSpell di PyPI — fallback online)
_URL_EN = (
    "https://raw.githubusercontent.com/mammothb/symspellpy/master/symspellpy/frequency_dictionary_en_82_765.txt"
)

# Kata dasar Indonesia yang paling umum (bundled — tidak perlu internet)
# Mencakup kata kerja, kata benda, kata sifat, dan preposisi umum
_KATA_DASAR_ID = """
ada adalah agar air akan akar akhir aksi alam alat alur ambil aman amat
amil anak angka angin anjur antara apa apabila apakah arah asal asli atas
atau atur awas ayah bab bagi bagian bahan baik bak baku balik banyak barat
baru batas bawa bayar beli benar benda bentuk berat bersih bila biaya bisa
buat buka bukan bunyi cara cek cepat cipta cocok contoh cukup dagang dalam
dan dapat dari dasar data depan desain diri dua dual dukung elemen faktor
fungsi ganti garis gerak gunakan halaman harga hari hasil harus hidup hubungan
ikan ikut imbas industri informasi instalasi izin jaga jaminan jenis jika
juga jual jumlah kabel kadar kaki kalau kami kamu kapan karena kata kedua
keempat ketiga ketujuh keenam kelima keselamatan kesesuaian kerusakan keterangan
ketujuh ke komponen kondisi koneksi konfigurasi kontrol kualitas kurang lain
langkah lanjut lebih letal level listrik lokasi maka makin manual masa masalah
mata memasang memasukan memastikan memerlukan memperbaiki menggunakan merawat
metode minta mode model mudah mulai nama nasional nilai nomor normal oleh
omset operasi orde panduan panjang paragaraf pemasangan pemeliharaan pemakaian
pembuatan penarikan penggunaan pengerjaan perangkat perawatan peringatan perlu
pertama petunjuk pilih posisi produk program prosedur rangkaian rasio rata
rekomendasi rusak saat sama sarana sebab sebelum seharusnya selesai serta
siap sistem sisi standar status suhu sumber tabel tahap tekanan teknis terdiri
terkait tidak tindakan tinggi tipe tidak uji unit untuk urutan pada penggunaan
voltase warna yang yaitu berikan biasa boleh butuh cara cegah dampak daya
depan deskripsi deteksi digital dimensi fungsi hitung informasi instruksi
kategori keamanan kebijakan kecil keluar kemudian komponen koneksi langkah
mata matikan mesin nilai normal nyata pahami penting pilih prosedur rangkaian
risiko setting sinyal sistem spesifikasi suhu tekanan teknis timer tombol
troubleshoot ukuran versi waktu warning
label garansi berlaku sedang gratis material penghapusan penggantian expedisi
ketika menjamin batas cacat kecelakaan perbaikan siapapun diizinkan
alarm diperbaiki kebijakannya terdiri menyediakan pengganti dipastikan
"""


def _build_id_dictionary(ss) -> bool:
    """
    Load bundled kata dasar Indonesia ke SymSpell.
    Selalu berhasil (tidak butuh internet).
    """
    words = _KATA_DASAR_ID.split()
    for word in words:
        word = word.strip().lower()
        if word and word.isalpha():
            ss.create_dictionary_entry(word, 1)

    # Coba juga load dari file jika sudah diunduh/dibuat sebelumnya
    if os.path.exists(_DICT_ID_PATH):
        try:
            with open(_DICT_ID_PATH, "r", encoding="utf-8", errors="ignore") as fh:
                extra = 0
                for line in fh:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    word = parts[0].lower()
                    freq = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 1
                    if word.isalpha():
                        ss.create_dictionary_entry(word, freq)
                        extra += 1
            logger.info(f"   └─ Tambahan dari file: {extra} kata")
        except Exception as e:
            logger.debug(f"Opsional file kamus gagal dibaca: {e}")

    logger.info(f"✅ Kamus Indonesia siap ({len(words)} kata dasar bundled).")
    return True


def _download_file(url: str, dest: str) -> bool:
    """Download a file from url to dest. Returns True on success."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        return True
    except Exception as e:
        logger.warning(f"⚠️ Gagal unduh kamus dari {url}: {e}")
        return False


def _get_symspell(lang: str = "id"):
    """
    Return a (lazily initialised) SymSpell instance for the given language.
    Returns None if symspellpy is not installed.
    """
    global _sym_spell_id, _sym_spell_en

    try:
        from symspellpy import SymSpell, Verbosity  # noqa: F401  (just to test import)
    except ImportError:
        logger.warning("⚠️ symspellpy tidak terpasang — jalankan: pip install symspellpy")
        return None

    from symspellpy import SymSpell

    if lang == "id":
        if _sym_spell_id is not None:
            return _sym_spell_id

        ss = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)

        # Gunakan bundled kata dasar (tidak perlu internet)
        logger.info("📖 Memuat kamus dasar Indonesia (bundled)...")
        _build_id_dictionary(ss)

        _sym_spell_id = ss
        return _sym_spell_id

    else:  # 'en'
        if _sym_spell_en is not None:
            return _sym_spell_en

        ss = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)

        if not os.path.exists(_DICT_EN_PATH):
            logger.info("📥 Mengunduh kamus dasar Inggris...")
            ok = _download_file(_URL_EN, _DICT_EN_PATH)
            if not ok:
                logger.warning("⚠️ Kamus Inggris tidak tersedia, melewati SymSpell.")
                return None

        # English dictionary: "word frequency" format (space-separated)
        try:
            loaded = ss.load_dictionary(_DICT_EN_PATH, term_index=0, count_index=1)
            if loaded:
                logger.info("✅ Kamus Inggris berhasil dimuat ke SymSpell.")
            else:
                logger.warning("⚠️ Kamus Inggris gagal dimuat (format tidak dikenali).")
                return None
        except Exception as e:
            logger.warning(f"⚠️ Gagal memuat kamus Inggris: {e}")
            return None

        _sym_spell_en = ss
        return _sym_spell_en


# ─────────────────────────────────────────────────────────────────
# Public API: teach the engine domain-specific vocabulary
# ─────────────────────────────────────────────────────────────────

def learn_vocabulary(text: str, lang: str = "id", weight: int = 1000) -> int:
    """
    Ajarkan kata-kata dari teks referensi ke SymSpell agar tidak dikoreksi.
    Dipanggil saat user meng-upload Manual Book acuan.

    Args:
        text   : Full teks dari dokumen referensi.
        lang   : 'id' atau 'en'.
        weight : Frekuensi yang diberikan (tinggi = lebih diutamakan).

    Returns:
        Jumlah kata yang dipelajari.
    """
    ss = _get_symspell(lang)
    if ss is None:
        return 0

    words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
    count = 0
    for word in words:
        ss.create_dictionary_entry(word.lower(), weight)
        count += 1

    logger.info(f"✨ SymSpell mempelajari {count} kata dari dokumen referensi ({lang})")
    return count


# ─────────────────────────────────────────────────────────────────
# STAGE A: SymSpell — koreksi typo per kata
# ─────────────────────────────────────────────────────────────────

def _stage_a_symspell(text: str, lang: str = "id") -> str:
    """Koreksi setiap kata menggunakan SymSpell lookup."""
    from symspellpy import Verbosity

    ss = _get_symspell(lang)
    if ss is None:
        return text  # pass-through jika tidak tersedia

    words = text.split()
    corrected = []

    for word in words:
        # Pisahkan punctuation dari kata
        prefix = re.match(r"^([^\w]*)", word).group(1)
        suffix = re.search(r"([^\w]*)$", word).group(1)
        core   = word[len(prefix):len(word) - len(suffix)] if suffix else word[len(prefix):]

        if not core or not core.isalpha() or len(core) < 3:
            corrected.append(word)
            continue

        suggestions = ss.lookup(core.lower(), Verbosity.CLOSEST, max_edit_distance=2)
        if suggestions:
            best = suggestions[0].term
            # Pertahankan kapitalisasi asli
            if core.isupper():
                best = best.upper()
            elif core[0].isupper():
                best = best.capitalize()
            corrected.append(prefix + best + suffix)
        else:
            corrected.append(word)

    return " ".join(corrected)


# ─────────────────────────────────────────────────────────────────
# STAGE B: Context-aware correction
# ─────────────────────────────────────────────────────────────────

# Aturan koreksi berbasis konteks.
# Format:
#   target   : kata yang sering salah dideteksi OCR
#   correct  : kata yang seharusnya
#   triggers : kata-kata di sekitarnya yang mengindikasikan konteks ini
#
# Tambahkan aturan baru di sini sesuai kebutuhan produk.

_CONTEXT_RULES = [
    # Bahasa Indonesia
    {
        "target": "baterai",
        "correct": "material",
        "triggers": ["bahan", "komponen", "cacat", "pengerjaan", "fisik"],
        "lang": "id",
    },
    {
        "target": "atlas",
        "correct": "atas",
        "triggers": ["kebijakan", "nama", "dasar", "permintaan", "sendiri"],
        "lang": "id",
    },
    {
        "target": "untuck",
        "correct": "untuk",
        "triggers": ["digunakan", "memastikan", "menjaga", "mencegah"],
        "lang": "id",
    },
    {
        "target": "rusk",
        "correct": "rusak",
        "triggers": ["komponen", "perbaikan", "ganti", "cacat", "perangkat"],
        "lang": "id",
    },
    # ── Baru: konteks dari sampel teks nyata ──────────────────────
    {
        "target": "cara",
        "correct": "cacat",
        "triggers": ["material", "bahan", "pengerjaan", "komponen", "batas"],
        "lang": "id",
    },
    {
        "target": "materai",
        "correct": "material",
        "triggers": ["bahan", "komponen", "cacat", "pengerjaan", "batas", "dari"],
        "lang": "id",
    },
    {
        "target": "cegah",
        "correct": "tidak",
        "triggers": ["memenuhi", "spesifikasi", "jika", "produk", "sesuai"],
        "lang": "id",
    },
    {
        "target": "garis",
        "correct": "gratis",
        "triggers": ["memperbaiki", "mengganti", "bagian", "cara", "perbaikan"],
        "lang": "id",
    },
    # English
    {
        "target": "installation",
        "correct": "installation",
        "triggers": [],  # placeholder — no change needed, just an example template
        "lang": "en",
    },
]


def _stage_b_context(text: str, lang: str = "id", window_size: int = 5) -> str:
    """Koreksi kata berdasarkan konteks kata-kata di sekitarnya."""
    tokens = text.split()
    new_tokens = tokens.copy()

    active_rules = [r for r in _CONTEXT_RULES if r.get("lang", "id") == lang and r["triggers"]]

    for i, word in enumerate(tokens):
        clean_word = re.sub(r"[^\w]", "", word.lower())

        for rule in active_rules:
            if clean_word == rule["target"]:
                start = max(0, i - window_size)
                end   = min(len(tokens), i + window_size + 1)
                context_window = [re.sub(r"[^\w]", "", t.lower()) for t in tokens[start:end]]

                if any(trigger in context_window for trigger in rule["triggers"]):
                    new_tokens[i] = word.lower().replace(rule["target"], rule["correct"])
                    logger.debug(
                        f"[ContextRule] '{rule['target']}' → '{rule['correct']}' "
                        f"(trigger found in window)"
                    )
                    break  # Only apply the first matching rule

    return " ".join(new_tokens)


# ─────────────────────────────────────────────────────────────────
# STAGE C: Entity / brand standardization
# ─────────────────────────────────────────────────────────────────

# Kata-kata atau brand yang sering salah dibaca OCR.
# Format: { "salah_baca": "yang_benar" }
# Case-insensitive matching, word-boundary aware.

_ENTITY_MAP_ID = {
    # ── Brand & nama perusahaan ──────────────────────────────────
    "STINKO"      : "SINKO",
    "PRIMAL"      : "PRIMA",
    "TECHNOVISON" : "TECHNOVISION",
    "Elteeh"      : "Elitech",      # 'Elteeh' → 'Elitech'
    "ELTEEH"      : "ELITECH",      # uppercase variant

    # ── Kata OCR yang SELALU salah (tidak ambigu) ─────────────────
    # Koreksi kata-kata ini aman dilakukan tanpa melihat konteks
    "pengerjaar" : "pengerjaan",
    "sheri"      : "seri",
    "dario"      : "dari",
    "omasa"      : "masa",
    "benjamin"   : "menjamin",
    "rusk"       : "rusak",
    "untuck"     : "untuk",
    "yank"       : "yang",
    "digunaan"   : "digunakan",
    "kerusaan"   : "kerusakan",
    "pemasan"    : "pemasangan",
    # ── Baru: temuan dari sampel teks nyata ───────────────────────
    "tau"        : "atau",      # sangat umum: 'tau' → 'atau'
    "karen"      : "karena",    # 'karen' → 'karena'
    "bats"       : "batas",     # 'bats' → 'batas'
    "abel"       : "label",     # 'abel' → 'label'
    "sedan"      : "sedang",    # 'sedan' → 'sedang'
    "but"        : "berlaku",   # 'alarm garansi but' → 'berlaku'
    "garis"      : "gratis",    # 'cara garis' → 'cara gratis'
}

_ENTITY_MAP_EN = {
    # Common OCR errors in English manuals
    "installtion": "installation",
    "maintenence": "maintenance",
    "troubleshoting": "troubleshooting",
    "specfication": "specification",
    "warrnty": "warranty",
}


def _stage_c_entities(text: str, lang: str = "id") -> str:
    """Standarisasi brand & entitas khusus menggunakan regex word boundary."""
    entity_map = _ENTITY_MAP_ID if lang == "id" else _ENTITY_MAP_EN

    # Pass 1: Koreksi frasa multi-kata (sebelum word-boundary loop)
    # Tangani kasus SymSpell ubah 'abel' → 'kabel' sebelum entity map jalan
    if lang == "id":
        text = re.sub(r'\bkabel(\s+)(nomor|versi|pembuatan|seri)\b',
                      r'label\1\2', text, flags=re.IGNORECASE)

    # Pass 2: Word-boundary koreksi satu-per-satu
    for wrong, right in entity_map.items():
        if wrong.lower() == right.lower():
            continue  # skip no-op entries
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)

    return text


# ─────────────────────────────────────────────────────────────────
# MAIN PUBLIC FUNCTION
# ─────────────────────────────────────────────────────────────────

def correct_ocr_text(text: str, lang: str = "id") -> str:
    """
    Jalankan pipeline koreksi 3-stage pada teks hasil OCR.

    Pipeline:
      A → SymSpell typo correction (per kata)
      B → Context-based correction (window 5)
      C → Entity / brand standardisation

    Args:
        text : Teks mentah hasil OCR.
        lang : 'id' (Indonesia) atau 'en' (English).

    Returns:
        Teks yang sudah dikoreksi.
    """
    if not text or not text.strip():
        return text

    original = text

    # Pipeline urutan PENTING:
    # C dulu (entity map paling presisi, regex exact-match)
    # A kemudian (SymSpell — ubah sisa typo yang tidak ada di entity map)
    # B terakhir (context rules — butuh teks yang sudah lebih bersih)

    try:
        # Stage C: Entity map — PERTAMA (sebelum SymSpell mengubah kata)
        text = _stage_c_entities(text, lang=lang)
    except Exception as e:
        logger.warning(f"[TextCorrector] Stage C (Entity) failed: {e}")

    try:
        # Stage A: SymSpell
        text = _stage_a_symspell(text, lang=lang)
    except Exception as e:
        logger.warning(f"[TextCorrector] Stage A (SymSpell) failed: {e}")

    try:
        # Stage B: Context rules
        text = _stage_b_context(text, lang=lang)
    except Exception as e:
        logger.warning(f"[TextCorrector] Stage B (Context) failed: {e}")

    if text != original:
        logger.debug(f"[TextCorrector] Corrected: '{original[:60]}' → '{text[:60]}'")

    return text


def add_context_rule(target: str, correct: str, triggers: list, lang: str = "id"):
    """
    Tambahkan aturan context-based correction baru secara runtime.
    Berguna jika ada istilah khusus yang perlu dikoreksi berdasarkan konteks.

    Args:
        target   : Kata yang salah dideteksi OCR.
        correct  : Kata yang seharusnya.
        triggers : Daftar kata pemicu di sekitarnya.
        lang     : 'id' atau 'en'.
    """
    _CONTEXT_RULES.append({
        "target"  : target.lower(),
        "correct" : correct.lower(),
        "triggers": [t.lower() for t in triggers],
        "lang"    : lang,
    })
    logger.info(f"[TextCorrector] Aturan baru ditambahkan: '{target}' → '{correct}' (triggers: {triggers})")


def add_entity_mapping(wrong: str, right: str, lang: str = "id"):
    """
    Tambahkan pasangan entitas baru ke entity map secara runtime.

    Args:
        wrong : Kata yang salah (OCR error atau brand salah eja).
        right : Kata yang benar.
        lang  : 'id' atau 'en'.
    """
    entity_map = _ENTITY_MAP_ID if lang == "id" else _ENTITY_MAP_EN
    entity_map[wrong] = right
    logger.info(f"[TextCorrector] Entity mapping baru: '{wrong}' → '{right}' ({lang})")
