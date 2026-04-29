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
omset operasi orde panduan panjang paragraf pemasangan pemeliharaan pemakaian
pembuatan penarikan penggunaan pengerjaan perangkat perawatan peringatan perlu
pertama petunjuk pilih posisi produk program prosedur rangkaian rasio rata
rekomendasi rusak saat sama sarana sebab sebelum seharusnya selesai serta
siap sistem sisi standar status suhu sumber tabel tahap tekanan teknis terdiri
terkait tidak tindakan tinggi tipe uji unit untuk urutan pada
voltase warna yang yaitu berikan biasa boleh butuh cegah dampak daya
deskripsi deteksi digital dimensi hitung instruksi
kategori keamanan kebijakan kecil keluar kemudian
nyata pahami penting
risiko setting sinyal spesifikasi timer tombol
troubleshoot ukuran versi waktu warning
label garansi berlaku sedang gratis material penghapusan penggantian expedisi
ketika menjamin cacat kecelakaan perbaikan siapapun diizinkan
alarm diperbaiki kebijakannya menyediakan pengganti dipastikan
pastikan lakukan jalankan hubungkan sambungkan lepaskan tekan putar geser tarik
dorong bersihkan keringkan simpan tutup pasang copot cabut nyalakan hidupkan
matikan padamkan periksa cermati amati perhatikan catat tulis bacakan jelaskan
sampaikan kirim terima ambil letakkan tempatkan arahkan sesuaikan kendalikan
operasikan aktifkan nonaktifkan reset mulai hentikan lanjutkan ulangi
selesaikan lengkapi verifikasi validasi konfirmasi tandai hapus ubah salin
pindahkan angkat turunkan naikkan kurangi tambahkan masukkan keluarkan
badan benda body frame rangka casing housing penutup tutup pelindung
konektor terminal pin soket colokan adaptor charger pengisi daya baterai
sensor probe detektor indikator lampu display layar panel saklar switch
relay fuse sekering trafo transformator motor pompa fan kipas valve katup
pipa selang filter saringan gasket seal bearing bantalan gear roda gigi
poros shaft belt sabuk rantai chain spring pegas baut mur ring washer
sekrup obeng kunci tang palu sikat lap kain sarung tangan masker kacamata
pelumas oli grease minyak cairan fluida coolant pendingin refrigerant
tegangan arus daya watt ampere volt ohm frekuensi hertz resistansi impedansi
kapasitas volume tekanan suhu temperatur kelembaban kecepatan putaran torsi
getaran vibration noise kebisingan emisi radiasi kebocoran korosi karat aus
keausan retak patah pecah bengkok melengkung deformasi
kalibrasi pengujian inspeksi audit pemeriksaan evaluasi penilaian pengukuran
penggantian penyesuaian perbaikan overhaul rekondisi modifikasi upgrade
jadwal interval periodik rutin harian mingguan bulanan tahunan berkala
garansi warranty jaminan klaim retur pengembalian
bahaya berbahaya beracun korosif mudah terbakar meledak
wajib dilarang jangan hindari perhatian awas hati peringatan
dengan tanpa menggunakan melalui setelah sebelum selama saat ketika apabila
bila karena sebab akibat agar supaya sehingga meskipun walaupun namun tetapi
akan sedang telah sudah belum pernah selalu sering jarang kadang
semua setiap masing tiap beberapa salah satu lain lainnya tersebut
sangat cukup agak kurang lebih paling terlalu sesuai tepat benar salah
baru lama besar kecil panjang pendek lebar sempit tebal tipis
tinggi rendah berat ringan keras lunak kasar halus basah kering
panas dingin hangat sejuk
atas bawah kiri kanan depan belakang samping tengah dalam luar
pertama kedua ketiga keempat kelima keenam ketujuh kedelapan kesembilan kesepuluh
satu dua tiga empat lima enam tujuh delapan sembilan sepuluh
seratus ribu juta miliar persen derajat meter sentimeter milimeter
kilogram gram liter mililiter detik menit jam hari minggu bulan tahun
secara melalui terhadap antara seperti berikut sebagai mengenai menurut
dibersihkan dibuka ditutup dipasang dilepas dimatikan dihidupkan
diperiksa diperbaiki diganti digunakan diisi dikosongkan diputar
ditekan ditarik didorong diangkat diturunkan diatur disesuaikan
membersihkan membuka menutup memasang melepas mematikan menghidupkan
memeriksa memperbaiki mengganti mengisi mengosongkan memutar
menekan menarik mendorong mengangkat menurunkan mengatur menyesuaikan
terhubung terputus terpasang terlepas terisi terkunci terbuka tertutup
terdeteksi terbaca tercetak terjadi terdapat tersedia tersambung
pemasangan pelepasan pembersihan pengisian pengosongan pemutaran
penekanan penarikan pendorongan pengangkatan penurunan pengaturan
penyesuaian pengecekan penggantian penggunaan perbaikan pemeriksaan
merupakan memiliki memberikan melakukan menunjukkan menjelaskan
memastikan menyebabkan membutuhkan menghasilkan memungkinkan
dilakukan dilengkapi direkomendasikan diperlukan dibutuhkan diharapkan
terdiri terbuat terletak termasuk terkena terkait tergantung
pembacaan pencatatan penyimpanan pengiriman penerimaan pemuatan
kerusakan kebocoran keretakan keausan keamanan keselamatan kegagalan
berbagai bersama berdasarkan bertujuan berlangsung beroperasi bergerak
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
    # ── "bahan" vs "badan" — OCR sering salah baca 'd' → 'h' ──────
    # Konteks ORGANISASI/LEMBAGA → "bahan" yang benar adalah "badan"
    {
        "target": "bahan",
        "correct": "badan",
        "triggers": ["usaha", "hukum", "pengurus", "penanggung", "jawab",
                     "pengelola", "produsen", "manajemen", "organisasi",
                     "lembaga", "instansi", "pemerintah", "resmi", "bayi"],
        "lang": "id",
    },
    # Konteks BAHAN KIMIA/MATERIAL → "badan" yang salah baca harusnya tetap "bahan"
    {
        "target": "badan",
        "correct": "bahan",
        "triggers": ["kimia", "berbahaya", "bakar", "baku", "campuran",
                     "cairan", "padat", "cair", "reaktif", "toksik",
                     "material", "kandungan", "komposisi"],
        "lang": "id",
    },
    # English
    {
        "target": "installation",
        "correct": "installation",
        "triggers": [],  # placeholder — no change needed, just an example template
        "lang": "en",
    },
    # ── Merek dan Nama Produk ──────────────────────
    {
        "target": "ptb",
        "correct": "PTB",
        "triggers": ["model", "seri", "produk", "type", "nomor", "alat", "device", "2in", "in", "1"],
        "lang": "id",
    },
    {
        "target": "ptb",
        "correct": "PTB",
        "triggers": ["model", "series", "product", "type", "number", "device", "2in", "in", "1"],
        "lang": "en",
    },
    {
        "target": "elitech",
        "correct": "Elitech",
        "triggers": ["pt", "perusahaan", "produk", "company", "manufacturer", "buatan", "oleh", "by"],
        "lang": "id",
    },
    {
        "target": "elitech",
        "correct": "Elitech",
        "triggers": ["pt", "perusahaan", "produk", "company", "manufacturer", "buatan", "oleh", "by"],
        "lang": "en",
    },
    {
        "target": "sink",
        "correct": "SINKO",
        "triggers": ["pt", "prime", "prima", "alloy", "copyright"],
        "lang": "id",
    },
    {
        "target": "sink",
        "correct": "SINKO",
        "triggers": ["pt", "prime", "prima", "alloy", "copyright"],
        "lang": "en",
    },
    {
        "target": "prime",
        "correct": "PRIMA",
        "triggers": ["pt", "sink", "sinko", "alloy"],
        "lang": "id",
    },
    {
        "target": "prime",
        "correct": "PRIMA",
        "triggers": ["pt", "sink", "sinko", "alloy"],
        "lang": "en",
    },
]


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Menghitung jarak numerik (Edit Distance) murni tanpa library eksternal."""
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for index2, char2 in enumerate(s2):
        new_distances = [index2 + 1]
        for index1, char1 in enumerate(s1):
            if char1 == char2:
                new_distances.append(distances[index1])
            else:
                new_distances.append(1 + min((distances[index1], distances[index1 + 1], new_distances[-1])))
        distances = new_distances
    return distances[-1]

def _stage_b_context(text: str, lang: str = "id", window_size: int = 5) -> str:
    """Koreksi kata berdasarkan konteks kata-kata di sekitarnya. Mendukung Typo / Fuzzy Matching (Levenshtein)."""
    tokens = text.split()
    new_tokens = tokens.copy()

    active_rules = [r for r in _CONTEXT_RULES if r.get("lang", "id") == lang and r["triggers"]]

    for i, word in enumerate(tokens):
        clean_word = re.sub(r"[^\w]", "", word.lower())
        if not clean_word:
            continue

        for rule in active_rules:
            target = rule["target"]
            is_match = False
            # 1. Exact Match
            if clean_word == target:
                is_match = True
            # 2. Fuzzy Match (Jika memungkinkan, toleransi proporsional)
            else:
                max_dist = 1 if len(target) <= 4 else 2
                if abs(len(clean_word) - len(target)) <= max_dist:
                    dist = _levenshtein_distance(clean_word, target)
                    if dist <= max_dist:
                        is_match = True
                    
            if is_match:
                start = max(0, i - window_size)
                end   = min(len(tokens), i + window_size + 1)
                context_window = [re.sub(r"[^\w]", "", t.lower()) for t in tokens[start:end]]

                if any(trigger in context_window for trigger in rule["triggers"]):
                    # Ganti kata aslinya dengan kata yang benar menurut rule
                    # Pertahankan huruf kapital awal
                    correct_word = rule["correct"]
                    if word.isupper():
                        correct_word = correct_word.upper()
                    elif word[0].isupper():
                        correct_word = correct_word.capitalize()
                        
                    # Gabungkan kembali tanda baca (prefix/suffix)
                    prefix = re.match(r"^([^\w]*)", word).group(1)
                    suffix = re.search(r"([^\w]*)$", word).group(1)
                    
                    new_tokens[i] = prefix + correct_word + suffix
                    logger.debug(
                        f"[ContextRule] Fuzzy Match: '{word}' (mirip '{target}') → '{correct_word}' "
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
    "sinko"       : "SINKO",
    "PRIMAL"      : "PRIMA",
    "TECHNOVISON" : "TECHNOVISION",
    "Elteeh"      : "Elitech",      
    "ELTEEH"      : "ELITECH",
    "Eltechf"     : "Elitech",  
    "Elitecho"    : "Elitech",
    "PUB"         : "PTB",
    "pub"         : "PTB",
    "Pub"         : "PTB",
    "PTB"         : "PTB",
    "ptb"         : "PTB",
    "Ptb"         : "PTB",

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
    # ⚠️ JANGAN tambahkan kata-kata valid bahasa Indonesia di sini!
    # Entity map hanya untuk kata yang PASTI merupakan OCR error (tidak pernah valid)
    # Contoh SALAH: "bahan"→"badan" (bahan = kata valid), "gunakan"→"digunakan" (gramatikal valid)
    "angepakan"  : "pengepakan",
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
    # ── Brand & nama perusahaan ──────────────────────────────────
    "STINKO"      : "SINKO",
    "SINK"        : "SINKO",
    "PRIMAL"      : "PRIMA",
    "PRIME"       : "PRIMA",
    "TECHNOVISON" : "TECHNOVISION",
    "GERMAN"      : "PERMAI",   # Fix AI hallucination
    "OSOWILANGUN" : "OSOWILANGUN", # Protect
    "PERMAI"      : "PERMAI",      # Protect
    "SINKO"       : "SINKO",       # Protect
    "PRIMA"       : "PRIMA",       # Protect
    
    # Existing...
    "Elteeh"      : "Elitech",      
    "ELTEEH"      : "ELITECH",
    "Eltechf"     : "Elitech",
    "Elitecho"    : "Elitech",
    "Elitech"     : "Elitech",
    "PUB"         : "PTB",
    
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
# STAGE A variant: SymSpell with highlight tracking
# ─────────────────────────────────────────────────────────────────

def _stage_a_symspell_with_tracking(text: str, lang: str = "id") -> tuple:
    """
    Sama seperti _stage_a_symspell, tapi JUGA menghasilkan daftar kata yang:
      - Tidak ditemukan di kamus (tidak bisa dikoreksi otomatis), ATAU
      - Ditemukan tapi edit distance-nya tinggi (>= 2, artinya kurang yakin)
    
    Returns:
        (corrected_text: str, highlights: list[dict])
        
        Setiap highlight: {
            "word"       : kata asli (sebelum koreksi),
            "corrected"  : kata hasil koreksi otomatis (bisa sama),
            "start"      : posisi karakter mulai di corrected_text,
            "end"        : posisi karakter selesai di corrected_text,
            "suggestions": [...] daftar saran alternatif (maks 5),
            "edit_distance": int,
            "confidence" : float (0.0–1.0, makin rendah makin tidak yakin)
        }
    """
    try:
        from symspellpy import Verbosity
    except ImportError:
        return text, []

    ss = _get_symspell(lang)
    if ss is None:
        return text, []

    words    = text.split()
    corrected_tokens = []
    highlights = []
    char_offset = 0

    for word in words:
        # Pisahkan punctuation
        prefix = re.match(r"^([^\w]*)", word).group(1)
        suffix = re.search(r"([^\w]*)$", word).group(1)
        core   = word[len(prefix):len(word) - len(suffix)] if suffix else word[len(prefix):]

        if not core or not core.isalpha() or len(core) < 3:
            corrected_tokens.append(word)
            char_offset += len(word) + 1  # +1 for space
            continue

        # Lookup with ALL suggestions (up to 5) so we can offer alternatives
        suggestions = ss.lookup(core.lower(), Verbosity.ALL, max_edit_distance=2)

        if suggestions:
            best      = suggestions[0]
            best_term = best.term
            best_dist = best.distance

            # Pertahankan kapitalisasi asli
            if core.isupper():
                best_term = best_term.upper()
            elif core[0].isupper():
                best_term = best_term.capitalize()

            token_out = prefix + best_term + suffix
            corrected_tokens.append(token_out)

            # Tandai sebagai "tidak yakin" jika edit-distance tinggi (>= 2)
            if best_dist >= 2:
                word_start = char_offset + len(prefix)
                word_end   = word_start + len(best_term)
                sugg_list  = [
                    s.term for s in suggestions[:5]
                    if s.term != best_term.lower()
                ]
                # confidence makin rendah jika edit-distance makin tinggi
                conf = max(0.1, 1.0 - (best_dist * 0.4))
                highlights.append({
                    "word"         : core,
                    "corrected"    : best_term,
                    "start"        : word_start,
                    "end"          : word_end,
                    "suggestions"  : sugg_list[:4],  # max 4 alternatif
                    "edit_distance": best_dist,
                    "confidence"   : round(conf, 2),
                })
        else:
            # Kata tidak ada di kamus sama sekali — paling tidak yakin
            corrected_tokens.append(word)
            word_start = char_offset + len(prefix)
            word_end   = word_start + len(core)
            highlights.append({
                "word"         : core,
                "corrected"    : core,   # tidak diubah
                "start"        : word_start,
                "end"          : word_end,
                "suggestions"  : [],
                "edit_distance": 99,
                "confidence"   : 0.0,
            })

        char_offset += len(token_out if suggestions else word) + 1

    corrected_text = " ".join(corrected_tokens)
    return corrected_text, highlights


# ─────────────────────────────────────────────────────────────────
# MAIN PUBLIC FUNCTION
# ─────────────────────────────────────────────────────────────────

def correct_ocr_text(text: str, lang: str = "id") -> str:
    """
    Koreksi teks pasca-OCR.
    Hanya menjalankan Stage B (context) dan Stage C (entity/brand).
    Stage A (Symspell Typo correction per-huruf) dimatikan.
    """
    text = _stage_b_context(text, lang=lang)
    text = _stage_c_entities(text, lang=lang)
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


def correct_ocr_text_with_highlights(text: str, lang: str = "id") -> dict:
    """
    Applies Stage B (Context) and Stage C (Entity Map) corrections.
    Stage A (Symspell auto-correction with highlights) is DISABLED.
    Returns: {"text": corrected_text, "highlights": []}
    """
    corrected = correct_ocr_text(text, lang=lang)
    return {"text": corrected, "highlights": []}

def correct_text_ai(text: str, lang: str = "id") -> dict:
    """
    Uses Gemini AI (via OpenRouter) to normalize and fix text.
    STRICT MODE: Only fixes typos and OCR errors. Does NOT add, remove, or rephrase content.
    """
    if not text or len(text.strip()) < 5:
        return {"text": text, "highlights": []}
        
    try:
        from openrouter_client import get_openrouter_client
        client = get_openrouter_client()
        if not client: return {"text": text, "highlights": []}
        
        lang_label = "Indonesian" if lang == "id" else "English"
        prompt = f"""Fix ONLY spelling errors and OCR artifacts in this {lang_label} technical manual text.

STRICT RULES:
- Do NOT add any new words, sentences, or explanations
- Do NOT remove any existing content
- Do NOT rephrase or restructure sentences
- Do NOT add formatting like bullet points or numbering that wasn't there
- ONLY fix obvious typos and broken characters
- The output must have approximately the SAME length as the input
- Return ONLY the corrected text, nothing else

TEXT:
{text}"""

        corrected = client.call(prompt, timeout=15)
        if corrected and len(corrected) > 5:
            corrected = corrected.strip()
            
            # LENGTH GUARD: Reject AI output that is significantly longer than input
            # This prevents the AI from adding content that wasn't in the original
            input_len = len(text.strip())
            output_len = len(corrected)
            if output_len > input_len * 1.3:  # More than 30% longer = AI added content
                logger.warning(
                    f"AI correction rejected: output ({output_len} chars) is >30% longer "
                    f"than input ({input_len} chars). Using original text."
                )
                return {"text": text, "highlights": []}
            
            return {"text": corrected, "highlights": []}
    except Exception as e:
        logger.warning(f"AI correction failed: {e}")
        
    return {"text": text, "highlights": []}

