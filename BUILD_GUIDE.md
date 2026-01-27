# 🏗️ BUILD GUIDE - Windows App

## 📋 Prerequisites

### Required Software:
- ✅ Flutter SDK (already installed)
- ✅ Python 3.8+ (already installed)
- ✅ Visual Studio Build Tools (for Flutter Windows)

### Check Installation:
```bash
flutter doctor
python --version
```

---

## 🚀 BUILD PROCESS

### Option 1: Automated Build (RECOMMENDED)

**Simply run:**
```bash
build-windows-app.bat
```

This will:
1. Build Flutter Windows app
2. Build Backend executable
3. Package everything together
4. Create distributable folder

**Output:** `dist\Manbook-v4\` (ready to distribute!)

---

### Option 2: Manual Build

#### Step 1: Build Flutter App
```bash
cd frontend
flutter build windows --release
```

**Output:** `frontend\build\windows\x64\runner\Release\`

#### Step 2: Build Backend Executable
```bash
cd backend
pip install pyinstaller
pyinstaller --onefile --name manbook-backend main.py
```

**Output:** `backend\dist\manbook-backend.exe`

#### Step 3: Package Together

Create folder structure:
```
Manbook-v4/
├── app/
│   ├── frontend.exe          (from Flutter build)
│   ├── flutter_windows.dll
│   ├── data/
│   │   └── bin/
│   │       ├── backend.exe   (from PyInstaller)
│   │       └── reference.csv
│   └── ... (other Flutter files)
└── README.txt
```

---

## 📦 DISTRIBUTION

### Create Installer (Optional)

**Using Inno Setup:**

1. Download Inno Setup: https://jrsoftware.org/isdl.php
2. Create `installer.iss`:

```iss
[Setup]
AppName=Manbook-v4
AppVersion=4.0
DefaultDirName={pf}\Manbook-v4
DefaultGroupName=Manbook-v4
OutputDir=installer
OutputBaseFilename=Manbook-v4-Setup

[Files]
Source: "dist\Manbook-v4\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\Manbook-v4"; Filename: "{app}\app\frontend.exe"
Name: "{commondesktop}\Manbook-v4"; Filename: "{app}\app\frontend.exe"
```

3. Compile with Inno Setup
4. Get installer: `installer\Manbook-v4-Setup.exe`

---

### Simple ZIP Distribution

```bash
# Compress the folder
cd dist
tar -a -c -f Manbook-v4.zip Manbook-v4
```

**Send to users:**
- `Manbook-v4.zip` (all-in-one package)
- Users extract and run `app\frontend.exe`

---

## 🧪 TESTING

### Before Distribution:

1. **Test on clean machine** (without Python/Flutter)
2. **Check all features:**
   - [ ] Upload PDF
   - [ ] Upload Image
   - [ ] Watermark removal works
   - [ ] Crop gambar/tabel works
   - [ ] OCR reads text correctly
   - [ ] Typo detection works
   - [ ] 7 BAB classification correct
   - [ ] Word export works
   - [ ] PDF export works
   - [ ] Layout is locked (margins, fonts)

3. **Performance test:**
   - [ ] Small PDF (1-5 pages)
   - [ ] Medium PDF (10-20 pages)
   - [ ] Large PDF (50+ pages)

---

## 🐛 TROUBLESHOOTING

### Issue: "VCRUNTIME140.dll not found"
**Solution:** Include Visual C++ Redistributable
```bash
# Download and include in installer:
https://aka.ms/vs/17/release/vc_redist.x64.exe
```

### Issue: Backend fails to start
**Solution:** Check backend.log
```bash
# Add logging to backend
python main.py > backend.log 2>&1
```

### Issue: PDF export fails
**Solution:** docx2pdf requires Microsoft Word
```bash
# Alternative: Use reportlab for PDF generation
# Or include PDF converter in package
```

### Issue: App too large
**Solution:** Optimize build
```bash
# Flutter: Remove debug symbols
flutter build windows --release --split-debug-info=debug-info

# Backend: Use PyInstaller options
pyinstaller --onefile --strip main.py
```

---

## 📊 BUILD SIZE ESTIMATE

**Expected Sizes:**
- Flutter App: ~50-80 MB
- Backend Executable: ~100-150 MB
- Total Package: ~150-230 MB

**Optimization:**
- Compress with UPX: -30%
- Remove debug symbols: -20%
- Final size: ~100-160 MB

---

## 🎯 DEPLOYMENT CHECKLIST

### Before Release:

- [ ] All features tested
- [ ] No errors in logs
- [ ] Performance acceptable
- [ ] README included
- [ ] Version number updated
- [ ] License file included
- [ ] User guide created

### Release Package Should Include:

```
Manbook-v4/
├── app/
│   └── (application files)
├── README.txt
├── LICENSE.txt
├── USER_GUIDE.pdf
└── CHANGELOG.txt
```

---

## 📝 VERSION MANAGEMENT

**Update version in:**
1. `frontend/pubspec.yaml` - version: 4.0.0
2. `backend/main.py` - __version__ = "4.0.0"
3. Installer script - AppVersion=4.0
4. README.txt - Version 4.0

---

## 🚀 NEXT STEPS

After successful build:

1. **Test thoroughly**
2. **Create user documentation**
3. **Prepare deployment**
4. **Train users**
5. **Monitor feedback**

---

## 💡 TIPS

### For Internal Use:
- Simple ZIP distribution is enough
- No need for installer
- Just extract and run

### For External Distribution:
- Create professional installer
- Include auto-update feature
- Add digital signature
- Create landing page

---

## 📞 SUPPORT

If build fails:
1. Check `flutter doctor`
2. Check Python version
3. Check build logs
4. Verify all dependencies installed

Need help? Check:
- TROUBLESHOOTING.md
- Build logs in `build/`
- Backend logs in `backend.log`
