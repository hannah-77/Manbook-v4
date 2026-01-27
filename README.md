# 📱 Manbook-v4 - Manual Alat Medis OCR

Aplikasi untuk mendeteksi dan menormalisasi nama alat medis menggunakan OCR (Optical Character Recognition).

## 🚀 Cara Menjalankan Aplikasi

### Opsi 1: Menggunakan Script (RECOMMENDED)

#### A. Jalankan Semuanya Sekaligus
```bash
# Double-click file ini atau jalankan:
start-all.bat
```
Script ini akan membuka backend dan Flutter dalam window terpisah.

#### B. Jalankan Backend Saja
```bash
start-backend.bat
```

#### C. Jalankan Flutter Saja
```bash
start-flutter.bat
```

### Opsi 2: Membuat Desktop Shortcuts

Jalankan PowerShell script untuk membuat shortcut di desktop:
```powershell
powershell -ExecutionPolicy Bypass -File create-shortcuts.ps1
```

Setelah itu, Anda akan memiliki 3 shortcut di desktop:
- 🔧 **Manbook Backend** - Start backend server
- 📱 **Manbook Flutter** - Start Flutter app
- 🚀 **Manbook (Full)** - Start keduanya sekaligus

### Opsi 3: Manual

#### Backend
```bash
cd backend
python main.py
```

#### Flutter
```bash
cd frontend
flutter run
```

## 📦 Instalasi Dependencies

### Backend (Python)
```bash
cd backend
pip install -r requirements.txt
```

### Frontend (Flutter)
```bash
cd frontend
flutter pub get
```

## ⚙️ Troubleshooting

### Error: "ConvertPtrAttribute2RuntimeAttribute not support"

Ini adalah error PaddleOCR yang sudah diperbaiki di versi terbaru. Jika masih muncul:

**Solusi 1: Reinstall PaddlePaddle dan PaddleOCR**
```bash
pip uninstall paddlepaddle paddleocr -y
pip install paddlepaddle==2.6.0
pip install paddleocr==2.7.0.3
```

**Solusi 2: Downgrade ke versi stable**
```bash
pip uninstall paddlepaddle paddleocr -y
pip install paddlepaddle==2.5.1
pip install paddleocr==2.6.1.3
```

**Solusi 3: Gunakan versi CPU only**
```bash
pip uninstall paddlepaddle -y
pip install paddlepaddle -i https://mirror.baidu.com/pypi/simple
```

### Error: Poppler not found (untuk PDF)

Download Poppler untuk Windows:
1. Download dari: https://github.com/oschwartz10612/poppler-windows/releases/
2. Extract ke `C:\poppler`
3. Atau set environment variable: `POPPLER_PATH=C:\path\to\poppler\bin`

### Error: Flutter command not found

Install Flutter:
1. Download dari: https://flutter.dev/docs/get-started/install
2. Extract dan tambahkan ke PATH
3. Jalankan `flutter doctor` untuk cek instalasi

## 🔌 API Endpoints

### Health Check
```
GET http://127.0.0.1:8000/health
```

### Process Image/PDF
```
POST http://127.0.0.1:8000/process
Content-Type: multipart/form-data
Body: file (image or PDF)
```

## 📁 Struktur Project

```
Manbook-v4/
├── backend/
│   ├── main.py              # FastAPI server
│   ├── reference.csv        # Database referensi alat medis
│   └── requirements.txt     # Python dependencies
├── frontend/
│   ├── lib/                 # Flutter source code
│   └── pubspec.yaml         # Flutter dependencies
├── start-backend.bat        # Script untuk start backend
├── start-flutter.bat        # Script untuk start Flutter
├── start-all.bat            # Script untuk start semuanya
└── create-shortcuts.ps1     # Script untuk create desktop shortcuts
```

## 💡 Tips

1. **Selalu jalankan backend dulu** sebelum Flutter app
2. Backend berjalan di: `http://127.0.0.1:8000`
3. Cek log di file `backend.log` jika ada error
4. Gunakan script `start-all.bat` untuk kemudahan

## 📝 Notes

- Backend menggunakan PaddleOCR untuk deteksi text
- Fuzzy matching menggunakan RapidFuzz
- Support gambar (JPG, PNG) dan PDF
- Normalisasi otomatis menggunakan database referensi

## 🛠️ Versi yang Direkomendasikan

- Python: 3.8 - 3.11
- PaddlePaddle: 2.5.1 atau 2.6.0
- PaddleOCR: 2.6.1.3 atau 2.7.0.3
- Flutter: Latest stable version
