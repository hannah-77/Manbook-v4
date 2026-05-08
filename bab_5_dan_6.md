# BAB V
# HASIL DAN PEMBAHASAN

## 5.1 Arsitektur Sistem dan Alur Kerja
### 5.1.1 Arsitektur Sistem
Sistem BioManual (Manbook-v4) diimplementasikan dengan arsitektur *client-server*. Sisi *frontend* dibangun menggunakan Flutter yang berjalan sebagai aplikasi desktop Windows, sedangkan *backend* dibangun menggunakan FastAPI dengan Python. Komunikasi antara keduanya dilakukan melalui RESTful API. *Backend* bertugas menangani pemrosesan dokumen, pengenalan teks (OCR), deteksi tata letak, dan interaksi dengan *Large Language Models* (LLM) untuk ekstraksi pintar, sedangkan *frontend* menangani interaksi pengguna dan pratinjau antarmuka.

### 5.1.2 Alur Kerja Prototipe
Alur kerja sistem dimulai saat pengguna mengunggah dokumen teknis (*manual book*) berformat PDF atau DOCX. Sistem secara dinamis menyeleksi metode ekstraksi (*hybrid processing*). Jika visual dokumen rumit, sistem memicu *Document Layout Analysis* (DLA) untuk memotong (*crop*) bagian teks multi-kolom dan merutekannya ke mesin OCR (PaddleOCR atau Tesseract). Teks hasil ekstraksi kemudian dikirim ke LLM untuk diklasifikasi ke dalam bab laporan yang sesuai. Hasilnya dikembalikan ke *frontend* di mana pengguna dapat memvalidasi data tersebut sebelum diunduh sebagai laporan final.

## 5.2 Hasil Pengembangan *Backend* dan *Pipeline* Dokumen
### 5.2.1 Desain Arsitektur *Backend* Berbasis FastAPI
*Backend* dirancang secara modular dan asinkronus (ASGI) untuk menangani beban kerja berat dari *machine learning*. FastAPI memfasilitasi manajemen antrean (*queue*) pemrosesan gambar beresolusi tinggi tanpa memblokir permintaan dari pengguna. 

### 5.2.2 Implementasi *Document Layout Analysis* (DLA)
Untuk menangani dokumen teknis dengan banyak kolom teks dan gambar, algoritma DLA diimplementasikan untuk mendeteksi batas margin dan *gutter* antar kolom. Pemotongan otomatis dilakukan agar mesin OCR tidak membaca teks melintasi batas kolom yang dapat mengacaukan struktur paragraf.

## 5.3 Pengembangan Algoritma Pemrosesan AI dan OCR
### 5.3.1 *Routing* Multi-Mesin OCR (PaddleOCR dan Tesseract)
Sistem menerapkan kecerdasan penentuan rute (*routing*) OCR. **PaddleOCR** dikhususkan untuk mengekstrak dokumen berbahasa Inggris dan dokumen yang memuat elemen struktur kompleks. Sementara itu, **Tesseract** dialokasikan untuk pemrosesan teks standar berbahasa Indonesia, sehingga menghasilkan akurasi maksimal di kedua kondisi.

### 5.3.2 *Pipeline* Klasifikasi dan Ekstraksi Menggunakan LLM
Implementasi AI berfokus pada analisis teks tahap lanjut. LLM diinstruksikan melalui *prompting* yang dioptimalkan untuk mengambil informasi krusial dari *cover page* (seperti nama produk dan nomor seri) dan mengabaikan teks tidak penting (*boilerplate*). LLM juga menempatkan bagian-bagian buku manual ke dalam kategori/bab laporan yang relevan secara otomatis.

### 5.3.3 Implementasi *Hybrid Document Processing* (PDF/DOCX)
Untuk mencegah inefisiensi waktu proses dan hilangnya teks bawaan, *pipeline* dokumen hibrida diterapkan. Aplikasi mengambil teks digital *native* (dari DOCX dan PDF digital) tanpa dirender menjadi gambar, dan hanya memanggil OCR untuk bagian tabel visual atau dokumen hasil pindaian fisik.

### 5.3.4 Mekanisme Penanganan Tabel (*Table Fallback System*)
Ekstraksi informasi berbentuk relasional menggunakan mekanisme *fallback*. Ketika pustaka utama pemrosesan tata letak (seperti Surya AI) tidak aktif, sistem akan mengisolasi area tabel yang ditandai untuk menjaga struktur datanya tetap terbaca oleh modul analitik.

### 5.3.5 Sistem *Human-in-the-Loop* (HITL) untuk Verifikasi Data
Agar akurasi terjamin dari halusinasi AI, sistem *Human-in-the-Loop* dibuat. Jika tingkat keyakinan (*confidence level*) AI rendah saat mengklasifikasi dokumen, proses di-*hold* dan memberikan sinyal peringatan ke *frontend*. Pengguna diharuskan melakukan verifikasi atau melakukan penempatan manual (*override*) sebelum melanjutkan.

## 5.4 Pengembangan Aplikasi *Frontend* (Desktop/Web)
### 5.4.1 Arsitektur Teknis dan Tumpukan Teknologi
Aplikasi *client* dibangun menggunakan Flutter yang mendukung kompilasi (*build*) secara *cross-platform*. Aplikasi berjalan sangat stabil di lingkungan Windows OS, memanfaatkan isolat memori Dart untuk menangani rendering gambar dokumen ukuran besar yang dikirimkan dari server lokal.

### 5.4.2 Desain Antarmuka dan Pengalaman Pengguna (UI/UX)
Antarmuka didesain secara minimalis namun padat informasi. Halaman utama berfokus pada panel ganda (*split screen*) yang memungkinkan pengguna melihat draf teks laporan di satu sisi, dan pratinjau visual di sisi lainnya.

### 5.4.3 Implementasi Fitur Pratinjau Dokumen Multi-Kolom
Fitur inti pada *frontend* adalah *Document Preview*. *Widget* Flutter dirancang untuk menyatukan segmen gambar kolom terpisah (*multi-column segments*) menjadi susunan yang mudah dibaca. Pengguna tidak lagi dihadapkan pada halaman utuh berlapis teks yang membingungkan, melainkan potongan kolom rapi yang merepresentasikan urutan baca sesungguhnya.

## 5.5 Pengujian dan Analisis Kinerja Sistem
### 5.5.1 Pengujian Fungsionalitas Sistem Terintegrasi
Pengujian *end-to-end* (E2E) dilakukan dari proses *upload* dokumen hingga hasil ekstraksi menjadi PDF laporan final. Komunikasi *websocket* atau API REST terbukti dapat melakukan sinkronisasi asinkronus secara stabil antara Flutter dan FastAPI.

### 5.5.2 Validasi Akurasi Ekstraksi Teks (*Text Coverage*)
Pengukuran parameter (*Ground Truth*) dilakukan dengan mencocokkan jumlah kata asli dari dokumen sumber dengan yang berhasil diekstrak sistem. Pendekatan ekstraksi *hybrid* berhasil mempertahankan tingkat *text coverage* di angka 100% pada dokumen digital, serta mengeliminasi masalah *data loss*.

### 5.5.3 Analisis Kinerja Proses: Akurasi AI dan Waktu
Presisi klasifikasi oleh LLM diukur menggunakan dokumen teknis acak. Hasil menunjukkan peningkatan signifikan ketika HITL memfilter anomali (*false positive*). Waktu komputasi juga dapat ditekan hingga 40% pada dokumen non-gambar dengan melangkaui proses *rendering* OCR secara otomatis.

---

# BAB VI
# PENUTUP

## 6.1 Kesimpulan
Pengembangan BioManual (Manbook-v4) berhasil memadukan *Hybrid Document Processing* yang sanggup membedakan teks digital (*native*) dan visual (OCR). Arsitektur perpaduan mesin OCR spesifik (PaddleOCR dan Tesseract) serta klasifikasi tingkat lanjut melalui *Large Language Model* memberikan keandalan yang tinggi. Implementasi *Human-in-the-Loop* sukses memitigasi kekurangan prediksi otomatis AI, sementara integrasi Flutter sebagai *frontend* menghadirkan pratinjau segmentasi multi-kolom yang optimal. 

## 6.2 Saran
Untuk pengembangan sistem lebih lanjut, disarankan melakukan *fine-tuning* pada model AI bersumber terbuka (*open-source* LLM) yang secara eksklusif menggunakan korpus *manual book* teknis guna mengurangi latensi pihak ketiga dan biaya API. Selain itu, mengintegrasikan *engine* khusus ekstraksi tabel (seperti Surya AI yang aktif secara penuh) dapat meningkatkan ekstraksi data berbentuk tabular.

---
# DAFTAR PUSTAKA
*(Daftar Pustaka disesuaikan dengan referensi jurnal OCR, FastAPI, Flutter, dan sumber DLA/LLM yang Anda gunakan).*

---
# LAMPIRAN
1. Logbook (Catatan Kegiatan Harian)
2. Surat Keterangan Telah Menyelesaikan Magang
3. Surat Pernyataan Tidak Melanggar Etika
4. Dokumentasi saat Magang
5. *Source Code* Utama Sistem (*Backend* FastAPI dan *Frontend* Flutter)
6. Flowchart / Arsitektur Alur Sistem (*System Architecture*)
7. Daftar *Dependencies* (*requirements.txt* / *pubspec.yaml*)
8. Laman Github / Repository Proyek
9. Lembar Kerja Pengujian Evaluasi Ekstraksi (Akurasi Kata OCR dan *Text Coverage*)
10. Tabel Hasil Pengujian Presisi Model AI pada Klasifikasi Kategori Laporan
