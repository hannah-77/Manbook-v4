# Panduan Install Visual Studio Build Tools untuk Flutter

## Langkah-langkah Manual (PENTING!)

### 1. Download Installer
Link download sudah dibuka di browser Anda:
https://aka.ms/vs/17/release/vs_BuildTools.exe

Atau download manual dari:
https://visualstudio.microsoft.com/downloads/
(Scroll ke bawah, cari "Build Tools for Visual Studio 2022")

### 2. Jalankan Installer
1. Buka file `vs_BuildTools.exe` yang sudah didownload
2. Tunggu Visual Studio Installer terbuka

### 3. Pilih Workload yang Diperlukan
Di Visual Studio Installer, centang:

✅ **Desktop development with C++**

Lalu di panel kanan (Optional), pastikan tercentang:
- ✅ MSVC v143 - VS 2022 C++ x64/x86 build tools
- ✅ Windows 11 SDK (10.0.22000.0 atau lebih baru)
- ✅ C++ CMake tools for Windows

### 4. Install
1. Klik tombol "Install" di kanan bawah
2. Tunggu proses download dan instalasi (sekitar 5-15 menit)
3. **RESTART KOMPUTER** setelah selesai

### 5. Verifikasi Instalasi
Buka PowerShell BARU dan jalankan:
```powershell
flutter doctor -v
```

Harusnya muncul:
```
[✓] Visual Studio - develop Windows apps (Visual Studio Build Tools 2022)
```

### 6. Build Aplikasi Flutter
```powershell
cd c:\Users\Hanna\Manbook-v4\frontend
flutter clean
flutter pub get
flutter run -d windows
```

---

## Troubleshooting

**Jika masih error setelah install:**
1. Pastikan sudah RESTART komputer
2. Buka PowerShell BARU (jangan yang lama)
3. Cek `flutter doctor -v` lagi

**Jika flutter doctor masih mengeluh:**
```powershell
flutter config --enable-windows-desktop
```

---

## Alternatif: Gunakan Chocolatey (Lebih Mudah)

Jika punya Chocolatey, bisa install dengan:
```powershell
choco install visualstudio2022buildtools --package-parameters "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

---

**Setelah selesai install dan restart, aplikasi Flutter Anda akan bisa di-build!**
