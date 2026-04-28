# Laporan Kegiatan Pengembangan Proyek Manbook-v4
**Periode: Januari - April 2026**

## Pendahuluan
Laporan ini merangkum seluruh kegiatan pengembangan yang telah dilakukan pada proyek **Manbook-v4 (BioManual Document Pipeline)**. Fokus utama proyek ini adalah membangun sistem ekstraksi dokumen teknis (manual book) medis yang cerdas, akurat, dan siap produksi.

---

## 📊 Tabel Jadwal Kegiatan Pengembangan

Berikut adalah tabel jadwal kegiatan yang disesuaikan dengan progress pengerjaan proyek dari Januari hingga April 2026:

| No | Kegiatan | Januari | Februari | Maret | April |
|:---|:---|:---:|:---:|:---:|:---:|
| | | **M1 M2 M3 M4** | **M1 M2 M3 M4** | **M1 M2 M3 M4** | **M1 M2 M3 M4** |
| **1** | **Penyesuaian Awal** | | | | |
| 1.1 | Briefing tujuan normalisasi 308 dokumen | X X | | | |
| 1.2 | Analisis variasi struktur PDF Manual Book | X X X X | | | |
| 1.3 | Studi pustaka framework OCR dan arsitektur LLM | | X X | | |
| **2** | **Pengembangan Pipeline OCR & AI** | | | | |
| 2.1 | Implementasi PaddleOCR, Tesseract, dan Surya OCR | | X X X X | X X | X X |
| 2.2 | Integrasi LLM via OpenRouter untuk normalisasi | | | X X X | |
| 2.3 | Eksperimen Prompt Engineering teknis alkes | | | X X X | |
| **3** | **Pembuatan Software - Backend** | | | | |
| 3.1 | Perancangan arsitektur API menggunakan FastAPI | | X X | | |
| 3.2 | Pembuatan kode program manajemen data & logika | | X X X X | X X | |
| **4** | **Pembuatan Software - Frontend (Flutter)** | | | | |
| 4.1 | Implementasi struktur dasar antarmuka pada Flutter | | | X X | |
| 4.2 | Styling antarmuka responsif dengan Material Design | | | X X X X | |
| 4.3 | Integrasi komponen UI dengan API Backend | | | X X X X | |
| **5** | **Uji Fungsi dan Validasi** | | | | |
| 5.1 | Pengujian fungsionalitas sistem secara menyeluruh | | | | X X |
| 5.2 | Validasi akurasi hasil oleh tim QC dan R&D | | | | X X |
| **6** | **Laporan dan Dokumentasi** | | | | |
| 6.1 | Penyusunan Laporan Akhir Magang | | X X | X X | X X X |
| 6.2 | Presentasi Akhir dan serah terima sistem | | | | X X |

---

## 🛠️ Ringkasan Pencapaian Teknis
1.  **Akurasi OCR:** >95% dengan dukungan typo correction otomatis menggunakan PaddleOCR & Tesseract.
2.  **Klasifikasi:** Pemetaan otomatis ke 7 bab standar medis menggunakan integrasi LLM (Gemini/OpenRouter).
3.  **Ekspor:** Format Word (.docx) dengan layout tetap (fixed font, margin, dan paging).
4.  **Performa:** Akselerasi GPU (Surya OCR) pada RTX 4050 mempercepat pemrosesan hingga 60%.
5.  **Robustness:** Menangani dokumen multi-kolom dan berbagai format (PDF/DOCX/Images).

---
*Laporan ini dibuat secara otomatis berdasarkan history pengembangan pada repository Manbook-v4.*
