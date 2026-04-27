import 'dart:io';
import 'dart:convert';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:file_picker/file_picker.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:syncfusion_flutter_pdfviewer/pdfviewer.dart';
import 'report_editor_page.dart';

void main() {
  runApp(const MaterialApp(
    title: 'Manual Book Data Normalization',
    debugShowCheckedModeBanner: false,
    home: ManbookHome(),
  ));
}

class ManbookHome extends StatefulWidget {
  const ManbookHome({super.key});

  @override
  State<ManbookHome> createState() => _ManbookHomeState();
}

class _ManbookHomeState extends State<ManbookHome> {
  // Server State
  Process? _serverProcess;
  bool _isEngineReady = false;
  String _engineStatus = "Checking AI Engine...";

  // App State
  bool _isProcessing = false;
  String? _selectedFilePath;
  String? _selectedFileName;
  List<dynamic> _results = [];
  String? _wordReportUrl;
  String? _pdfReportUrl;
  List<String> _cleanPages = [];
  bool _showCleanView = false;
  List<String> _missingChapters = []; // Track missing chapters
  String _selectedLanguage = 'id'; // 'id' = Indonesia, 'en' = English
  bool _isTranslating = false;
  bool _isTranslated = false;
  bool _directTranslate = false; // Bypass OCR & BioBrain option
  
  // AI Cover Info (from backend)
  String _aiProductName = '';
  String _aiProductDesc = '';
  
  // Progress tracking
  String? _sessionId;
  int _currentPage = 0;
  int _totalPages = 0;
  double _progress = 0.0;
  String _progressMessage = "";
  
  // Zoom controls
  double _zoomLevel = 1.0;
  final double _minZoom = 0.5;
  final double _maxZoom = 4.0;
  // TransformationController agar InteractiveViewer bisa dikontrol dari tombol
  final TransformationController _previewZoomCtrl = TransformationController();

  // Page navigation
  PageController? _pageController;
  int _currentPreviewPage = 0;

  // ── Language: uses explicit user selection ──
  String get _docLang => _selectedLanguage;

  Map<String, String> get _localizedChapters {
    if (_docLang == 'en') {
      return {
        "Chapter 1": "Intended Use & Safety",
        "Chapter 2": "Installation",
        "Chapter 3": "Operation & Clinical Monitoring",
        "Chapter 4": "Maintenance, Care & Cleaning",
        "Chapter 5": "Troubleshooting",
        "Chapter 6": "Technical Specifications & Standards",
        "Chapter 7": "Warranty & Service",
      };
    }
    return {
      "BAB 1": "Tujuan Penggunaan & Keamanan",
      "BAB 2": "Instalasi",
      "BAB 3": "Panduan Operasional & Pemantauan Klinis",
      "BAB 4": "Perawatan, Pemeliharaan & Pembersihan",
      "BAB 5": "Pemecahan Masalah",
      "BAB 6": "Spesifikasi Teknis & Kepatuhan Standar",
      "BAB 7": "Garansi & Layanan",
    };
  }

  @override
  void initState() {
    super.initState();
    _checkBackend();
  }

  @override
  void dispose() {
    _serverProcess?.kill();
    _pageController?.dispose();
    _previewZoomCtrl.dispose();
    super.dispose();
  }

  Future<void> _checkBackend() async {
    // Poll for Health
    for (int i = 0; i < 10; i++) {
      try {
        debugPrint('Checking backend health...');
        final res = await http.get(Uri.parse('http://127.0.0.1:8000/health'));
        debugPrint('Backend health status: ${res.statusCode}');
        if (res.statusCode == 200) {
          setState(() {
            _isEngineReady = true;
            _engineStatus = "AI System Ready ✓";
          });
          return;
        }
      } catch (_) {}
      await Future.delayed(const Duration(seconds: 1));
    }
    
    setState(() => _engineStatus = "Engine Offline - Please start backend");
  }

  /// Poll backend /progress/{session_id} setiap 1.5 detik sampai selesai.
  Future<void> _pollProgress(String sessionId) async {
    while (_isProcessing) {
      await Future.delayed(const Duration(milliseconds: 1500));
      if (!_isProcessing) break;
      try {
        debugPrint('Polling progress for session: $sessionId');
        final res = await http.get(
          Uri.parse('http://127.0.0.1:8000/progress/$sessionId'),
        ).timeout(const Duration(seconds: 3));
        if (res.statusCode == 200) {
          debugPrint('Progress response: ${res.body}');
          final data = json.decode(res.body);
          final pct = (data['percentage'] ?? 0) as int;
          final msg = (data['message'] ?? '') as String;
          final cur = (data['current_page'] ?? 0) as int;
          final tot = (data['total_pages'] ?? 0) as int;
          if (mounted) {
            setState(() {
              _progress = pct / 100.0;
              _progressMessage = msg;
              _currentPage = cur;
              if (tot > 0) _totalPages = tot;
            });
          }
        }
      } catch (_) {
        // jika polling gagal, diam saja dan coba lagi
      }
    }
  }

  Future<void> _pickFile() async {
    try {
      FilePickerResult? result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['pdf', 'png', 'jpg', 'jpeg', 'docx', 'doc'],
      );

      if (result != null && result.files.single.path != null) {
        final filePath = result.files.single.path!;
        final fileName = result.files.single.name;

        setState(() {
          _selectedFilePath = filePath;
          _selectedFileName = fileName;
          _results = [];
          _cleanPages = [];
          _showCleanView = false;
          _wordReportUrl = null;
          _pdfReportUrl = null;
          _progress = 0.0;
          _currentPage = 0;
          _totalPages = 0;
          _sessionId = null;
        });

        // Auto-detect language in background
        _detectFileLanguage(filePath, fileName);
      }
    } catch (e) {
      _showError(e.toString());
    }
  }

  /// Auto-detect language silently after file pick.
  /// Always sets a language — no manual selection prompts, no failure warnings.
  /// Fallback chain: text-based → AI Vision → default 'id' (all handled by backend).
  Future<void> _detectFileLanguage(String filePath, String fileName) async {
    debugPrint('Step 1: Starting Auto-Detect lifecycle for ($fileName)');
    
    _showDetectingFeedback();

    try {
      final List<String> hosts = ['127.0.0.1', 'localhost'];
      String? matchedHost;

      // PRE-CHECK: Try pinging the server first (Fast & Lightweight)
      debugPrint('Step 2: Pinging backend health status...');
      for (var host in hosts) {
        try {
          final pingUrl = Uri.parse('http://$host:8000/ping');
          final pingRes = await http.get(pingUrl).timeout(const Duration(seconds: 3));
          if (pingRes.statusCode == 200) {
            matchedHost = host;
            debugPrint('Step 2a: Successfully reached backend on $host');
            break;
          }
        } catch (_) {}
      }

      if (matchedHost == null) {
        debugPrint('Step 2b: UNABLE TO REACH BACKEND ON ANY LOCAL HOST');
        _dismissDetectingFeedback();
        _showError('Server deteksi tidak ditemukan (Offline). Gunakan menu manual jika perlu.');
        return;
      }

      final baseUrl = 'http://$matchedHost:8000';
      debugPrint('Step 3: Preparing Multipart Request to $baseUrl/detect-language');
      
      var request = http.MultipartRequest(
        'POST',
        Uri.parse('$baseUrl/detect-language'),
      );
      
      debugPrint('Step 4: Reading file from path: $filePath');
      request.files.add(await http.MultipartFile.fromPath('file', filePath));

      debugPrint('Step 5: Sending request (120s timeout)...');
      final streamedRes = await request.send().timeout(const Duration(seconds: 120));
      debugPrint('Step 6: Stream reached, reading response body...');
      final res        = await http.Response.fromStream(streamedRes);

      _dismissDetectingFeedback();

      if (res.statusCode != 200) {
        debugPrint('Step 7a: Detection server error: ${res.statusCode}');
        _showError('Gagal deteksi bahasa (Server Error ${res.statusCode}). Default: Indonesia.');
        return;
      }

      debugPrint('Step 7b: Success! Decoding body: ${res.body.substring(0, (res.body.length < 50 ? res.body.length : 50))}...');
      final data       = json.decode(res.body);
      final detected   = (data['detected'] as String?) ?? 'id';
      final label      = data['label'] ?? (detected == 'id' ? 'Bahasa Indonesia' : 'English');
      final confLabel  = data['confidence_label'] ?? '';
      final confidence = ((data['confidence'] ?? 0.0) * 100).round();
      final bool aiDetected = data['ai_detected'] == true;

      if (!mounted) return;
      setState(() => _selectedLanguage = detected);

      debugPrint('Step 8: Finalizing UI with detected language: $detected');
      _showDetectedBanner(detected, label, confLabel, confidence, aiDetected);

    } catch (e) {
      _dismissDetectingFeedback();
      debugPrint('Step ❌: Language detection CRITICAL FAIL: $e');
      _showError('Terjadi kegagalan koneksi: $e. Klik lencana untuk ganti bahasa manual.');
    }
  }

  void _showDetectingFeedback() {
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Row(
            children: [
               SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)),
               SizedBox(width: 12),
               Text('🔍 Sedang mendeteksi bahasa... (Mungkin butuh <1 menit)'),
            ],
          ),
          backgroundColor: Colors.blueGrey,
          duration: Duration(seconds: 120),
        ),
    );
  }

  void _dismissDetectingFeedback() {
    if (!mounted) return;
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
  }

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.redAccent),
    );
  }

  void _showDetectedBanner(String detected, String label, String confLabel, int confidence, bool aiDetected) {
      final Color bannerColor = aiDetected 
          ? const Color(0xFF6D28D9) 
          : (detected == 'id' ? const Color(0xFF1565C0) : const Color(0xFF1B5E20));

      final String flagEmoji = detected == 'id' ? '🇮🇩' : '🇬🇧';
      final String subtitle = aiDetected
          ? '🧠 AI Vision — bahasa dideteksi oleh AI'
          : '$confLabel ($confidence%) — bahasa disesuaikan otomatis';
          
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          margin: const EdgeInsets.all(16),
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          backgroundColor: bannerColor,
          duration: const Duration(seconds: 5),
          content: Row(
            children: [
               Text(flagEmoji, style: const TextStyle(fontSize: 26)),
               const SizedBox(width: 12),
               Expanded(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Bahasa Terdeteksi: $label',
                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14),
                    ),
                    const SizedBox(height: 2),
                    Text(subtitle, style: TextStyle(color: Colors.white.withAlpha(210), fontSize: 12)),
                  ],
                ),
               ),
            ],
          ),
        ),
      );
  }
  
  // ── TRANSLATE EN → ID ──
  Future<void> _translateToIndonesian() async {
    if (_sessionId == null) {
      _showError("No active session. Please analyze a file first.");
      return;
    }
    if (_isTranslating) return;

    setState(() {
      _isTranslating = true;
    });

    // Show progress snackbar
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Row(
          children: const [
            SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)),
            SizedBox(width: 12),
            Text('🌐 Translating to Bahasa Indonesia...'),
          ],
        ),
        backgroundColor: const Color(0xFF7C3AED),
        duration: const Duration(seconds: 120),
      ),
    );

    try {
      final response = await http.post(
        Uri.parse('http://127.0.0.1:8000/translate/$_sessionId'),
        headers: {'Content-Type': 'application/json'},
      );
      final data = json.decode(response.body);

      ScaffoldMessenger.of(context).hideCurrentSnackBar();

      if (data['success'] == true) {
        setState(() {
          _results = data['results'] ?? _results;
          _wordReportUrl = data['word_url'];
          _pdfReportUrl = data['pdf_url'];
          _isTranslated = true;
          _isTranslating = false;
          _selectedLanguage = 'id'; // Switch UI to Indonesian
        });

        final count = data['translated_count'] ?? 0;
        final total = data['total_items'] ?? 0;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✅ Translation complete! $count/$total items translated to Bahasa Indonesia'),
            backgroundColor: const Color(0xFF10B981),
            duration: const Duration(seconds: 4),
          ),
        );
      } else {
        setState(() => _isTranslating = false);
        _showError(data['error'] ?? 'Translation failed');
      }
    } catch (e) {
      ScaffoldMessenger.of(context).hideCurrentSnackBar();
      setState(() => _isTranslating = false);
      _showError('Translation error: $e');
    }
  }

  Future<void> _analyzeWithAI() async {
    if (_selectedFilePath == null) {
      _showError("Please select a file first");
      return;
    }

    try {
      setState(() {
        _isProcessing = true;
        _results = [];
        _wordReportUrl = null;
        _pdfReportUrl = null;
        _progress = 0.0;
        _progressMessage = "Menghubungkan ke server...";
        _isTranslated = false;
        _isTranslating = false;
      });

      // 1. Ambil session_id dari backend SEBELUM upload mulai
      debugPrint('Starting analysis session...');
      final startRes = await http
          .post(Uri.parse('http://127.0.0.1:8000/start'))
          .timeout(const Duration(seconds: 60));
      if (startRes.statusCode != 200) {
        _showError("Gagal memulai sesi. Pastikan backend berjalan.");
        setState(() => _isProcessing = false);
        return;
      }
      debugPrint('Start session response: ${startRes.body}');
      final startData = json.decode(startRes.body);
      final sessionId = startData['session_id'] as String;
      setState(() {
        _sessionId = sessionId;
        _progressMessage = "Uploading file...";
      });

      // 2. Polling progress di background (loop berhenti saat _isProcessing = false)
      _pollProgress(sessionId);

      // 3. Upload file — backend terima session_id + language dari header
      var request = http.MultipartRequest(
          'POST', Uri.parse('http://127.0.0.1:8000/process'));
      request.headers['X-Session-Id'] = sessionId;
      request.headers['X-Language'] = _selectedLanguage;
      request.headers['X-Direct-Translate'] = _directTranslate.toString();
      request.files
          .add(await http.MultipartFile.fromPath('file', _selectedFilePath!));

      debugPrint('Uploading file for session: $sessionId');
      var streamedRes = await request.send();
      var res = await http.Response.fromStream(streamedRes);

      if (res.statusCode == 200) {
        debugPrint('File upload response: ${res.body}');
        final data = json.decode(res.body);
        if (data['success'] == true) {
          setState(() {
            _sessionId = data['session_id'];
            _results = data['results'];
            _wordReportUrl = data['word_url'];
            _pdfReportUrl = data['pdf_url'];
            _cleanPages = List<String>.from(data['clean_pages'] ?? []);
            _showCleanView = _cleanPages.isNotEmpty;
            _totalPages = data['total_pages'] ?? 0;
            _missingChapters = List<String>.from(
                (data['missing_chapters'] ?? []).map((e) => e.toString()));
            _aiProductName = (data['ai_product_name'] ?? '') as String;
            _aiProductDesc = (data['ai_product_desc'] ?? '') as String;

            _currentPreviewPage = 0;
            _pageController = PageController(initialPage: 0);
            _progress = 1.0;
            _progressMessage = "✅ Selesai!";
            _isProcessing = false; // menghentikan _pollProgress
          });
        } else {
          _showError(data['error']);
          setState(() => _isProcessing = false);
        }
      } else {
        _showError("Server Error: ${res.statusCode}");
        setState(() => _isProcessing = false);
      }
    } catch (e) {
      _showError(e.toString());
      setState(() => _isProcessing = false);
    }
  }


  Future<void> _uploadSupplement({String? targetChapter}) async {
    if (_sessionId == null) return;
    
    try {
      FilePickerResult? result = await FilePicker.platform.pickFiles(
        type: FileType.custom,
        allowedExtensions: ['pdf', 'png', 'jpg', 'jpeg', 'docx', 'doc'],
        allowMultiple: true, // Allow multiple files!
      );

      if (result != null && result.files.isNotEmpty) {
        setState(() {
          _isProcessing = true;
          _progress = 0.0;
          _progressMessage = targetChapter != null 
              ? "Uploading file to $targetChapter..." 
              : "Uploading ${result.files.length} supplement(s)...";
        });

        var request = http.MultipartRequest('POST', Uri.parse('http://127.0.0.1:8000/supplement/$_sessionId'));
        
        if (targetChapter != null) {
          request.fields['target_chapter'] = targetChapter;
        }

        for (var file in result.files) {
          if (file.path != null) {
            request.files.add(await http.MultipartFile.fromPath('files', file.path!));
          }
        }
        
        // Start polling again
        _pollProgress(_sessionId!);
        var streamedRes = await request.send();
        var res = await http.Response.fromStream(streamedRes);

        if (res.statusCode == 200) {
          final data = json.decode(res.body);
          if (data['success'] == true) {
             setState(() {
              _results = data['results'];
              _wordReportUrl = data['word_url'];
              _pdfReportUrl = data['pdf_url'];
              
              // We don't replace clean pages, just append if backend supported it, 
              // but for now backend doesn't return new clean pages list easily without refactor.
              // So we just update the report validation side.
              
              _totalPages = data['total_pages'] ?? _totalPages;
              _missingChapters = List<String>.from(data['missing_chapters'] ?? []); // NEW
              _progress = 1.0;
              _progressMessage = "Supplement Merged!";
              _isProcessing = false;
            });
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text("Supplement merged successfully!"), backgroundColor: Colors.green)
            );
          } else {
             _showError(data['error']);
             setState(() => _isProcessing = false);
          }
        } else {
           _showError("Server Error: ${res.statusCode}");
           setState(() => _isProcessing = false);
        }
      }
    } catch (e) {
      _showError(e.toString());
      setState(() => _isProcessing = false);
    }
  }

  Future<void> _downloadReport(String? url) async {
    if (url != null) {
       await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF667eea), Color(0xFF764ba2)],
          ),
        ),
        child: Center(
          child: Container(
            constraints: const BoxConstraints(maxWidth: 1400),
            margin: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(20),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.3),
                  blurRadius: 60,
                  offset: const Offset(0, 20),
                ),
              ],
            ),
            child: Column(
              children: [
                // Header
                _buildHeader(),
                
                // Main Content
                Expanded(
                  child: Row(
                    children: [
                      // Left Panel - Upload
                      Expanded(
                        flex: 1,
                        child: _buildUploadPanel(),
                      ),
                      
                      // Right Panel - Results
                      Expanded(
                        flex: 1,
                        child: _buildResultsPanel(),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Container(
      padding: const EdgeInsets.all(20),
      width: double.infinity,
      decoration: const BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.centerLeft,
          end: Alignment.centerRight,
          colors: [Color(0xFF1E3A8A), Color(0xFF3B82F6)],
        ),
        borderRadius: BorderRadius.only(
          topLeft: Radius.circular(20),
          topRight: Radius.circular(20),
        ),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          return Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 20,
            runSpacing: 15,
            children: [
              const Text(
                '📚 Manual Book Data Normalization',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 26,
                  fontWeight: FontWeight.bold,
                ),
              ),
              Container(
                constraints: BoxConstraints(maxWidth: constraints.maxWidth),
                child: Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  alignment: WrapAlignment.end,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                decoration: BoxDecoration(
                  color: _isEngineReady ? Colors.green : Colors.orange,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  _engineStatus,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              if (_results.isNotEmpty)
                ElevatedButton.icon(
                  icon: const Icon(Icons.edit_document, color: Colors.white, size: 18),
                  label: const Text('Preview & Edit', style: TextStyle(color: Colors.white)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF8B5CF6), // Violet
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  ),
                  onPressed: () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (context) => ReportEditorPage(
                          items: _results,
                          originalFilename: _selectedFileName ?? 'document',
                          language: _selectedLanguage,
                        ),
                      ),
                    );
                  },
                ),
              if (_wordReportUrl != null)
                ElevatedButton.icon(
                  icon: const Icon(Icons.description, color: Colors.white, size: 18),
                  label: const Text('Word', style: TextStyle(color: Colors.white)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF2563EB),
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  ),
                  onPressed: () => _downloadReport(_wordReportUrl),
                ),
              if (_pdfReportUrl != null)
                ElevatedButton.icon(
                  icon: const Icon(Icons.picture_as_pdf, color: Colors.white, size: 18),
                  label: const Text('PDF', style: TextStyle(color: Colors.white)),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFDC2626),
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  ),
                  onPressed: () => _downloadReport(_pdfReportUrl),
                ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildUploadPanel() {
    return Container(
      color: const Color(0xFFF3F4F6),
      padding: const EdgeInsets.all(30),
      child: Column(
        children: [
          // Main Content Area (Preview or Upload Zone)
          Expanded(
            child: _isProcessing
                ? const SizedBox() // while processing, space used by progress below
                : _selectedFilePath == null
                    ? _buildUploadZone()
                    : _results.isNotEmpty
                        ? _buildPdfPreview()
                        : _buildFileInfo(),
          ),
          
          // Bottom Action Area (Buttons or Progress)
          const SizedBox(height: 20),
          
          if (_isProcessing)
             SizedBox(
               height: 300,
               child: _buildProcessingView()
             )
          else if (_selectedFilePath != null)
            Wrap(
              alignment: WrapAlignment.center,
              spacing: 15,
              runSpacing: 15,
              children: [
                // ── Detected Language Badge (Interactive Toggle) ──
                Tooltip(
                  message: 'Klik untuk ubah bahasa secara manual',
                  child: InkWell(
                    onTap: () {
                      setState(() => _selectedLanguage = _selectedLanguage == 'id' ? 'en' : 'id');
                      ScaffoldMessenger.of(context).hideCurrentSnackBar();
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: Text('Bahasa diubah manual: ${_selectedLanguage == "id" ? "Indonesia 🇮🇩" : "English 🇬🇧"}'),
                          duration: const Duration(seconds: 1),
                        ),
                      );
                    },
                    borderRadius: BorderRadius.circular(10),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                      decoration: BoxDecoration(
                        color: const Color(0xFFE0F2FE), // Light blue background
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: const Color(0xFF3B82F6), width: 1.5),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const Icon(
                            Icons.language,
                            color: Color(0xFF3B82F6),
                            size: 20,
                          ),
                          const SizedBox(width: 8),
                          Text(
                            _selectedLanguage == 'id' ? '🇮🇩 Bahasa Indonesia' : '🇬🇧 English',
                            style: const TextStyle(
                              color: Color(0xFF1E3A8A),
                              fontWeight: FontWeight.bold,
                              fontSize: 14,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
                // Direct Translate Toggle
                Container(
                  constraints: const BoxConstraints(maxWidth: 270),
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: Colors.grey[300]!),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.flash_on, color: Colors.orange, size: 20),
                      const SizedBox(width: 8),
                      const Expanded(
                        child: Text(
                          'Direct Translate Mode\n(Bypass OCR)', 
                          style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold)
                        ),
                      ),
                      Switch(
                        value: _directTranslate,
                        activeColor: Colors.orange,
                        onChanged: (val) {
                          setState(() => _directTranslate = val);
                        },
                      ),
                    ],
                  ),
                ),
                // Analyze with AI button (primary)
                ElevatedButton.icon(
                  onPressed: _analyzeWithAI,
                  icon: const Icon(Icons.auto_awesome, color: Colors.white),
                  label: const Text('Analyze with AI', style: TextStyle(color: Colors.white, fontSize: 16)),
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 20),
                    backgroundColor: const Color(0xFF10B981),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                ),
                // 🌐 Translate button — only visible after analysis
                if (_results.isNotEmpty)
                  ElevatedButton.icon(
                    onPressed: (_isTranslating || _isTranslated) ? null : _translateToIndonesian,
                    icon: _isTranslating
                      ? const SizedBox(
                          width: 18, height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : Icon(
                          _isTranslated ? Icons.check_circle : Icons.translate,
                          color: Colors.white,
                        ),
                    label: Text(
                      _isTranslating
                        ? 'Translating...'
                        : _isTranslated
                          ? 'Translated ✓'
                          : '🌐 Translate to ID',
                      style: const TextStyle(color: Colors.white, fontSize: 14),
                    ),
                    style: ElevatedButton.styleFrom(
                      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
                      backgroundColor: _isTranslated
                        ? const Color(0xFF059669)
                        : const Color(0xFF7C3AED),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  ),
                // Upload Another button (secondary)
                OutlinedButton.icon(
                  onPressed: _pickFile,
                  icon: const Icon(Icons.upload_file, color: Color(0xFF3B82F6)),
                  label: const Text('Change File', style: TextStyle(color: Color(0xFF3B82F6))),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 20),
                    side: const BorderSide(color: Color(0xFF3B82F6), width: 2),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }



  Widget _buildUploadZone() {
    return InkWell(
      onTap: _isEngineReady ? _pickFile : null,
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          border: Border.all(
            color: const Color(0xFF9CA3AF),
            width: 3,
            style: BorderStyle.solid,
          ),
          borderRadius: BorderRadius.circular(15),
        ),
        child: Center(
          child: SingleChildScrollView(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(
                  Icons.upload_file,
                  size: 80,
                  color: Color(0xFF9CA3AF),
                ),
                const SizedBox(height: 20),
                const Text(
                  'Upload Document',
                  style: TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 10),
                const Text(
                  'PDF, PNG, JPG, or JPEG',
                  style: TextStyle(
                    color: Color(0xFF6B7280),
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 20),
                ElevatedButton(
                  onPressed: _isEngineReady ? _pickFile : null,
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(horizontal: 40, vertical: 15),
                    backgroundColor: const Color(0xFF3B82F6),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  child: const Text(
                    'Select File',
                    style: TextStyle(fontSize: 18, color: Colors.white),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildProcessingView() {
    final pct = (_progress * 100).toInt();
    final pageInfo = _totalPages > 0
        ? 'Halaman $_currentPage / $_totalPages'
        : 'Memproses...';
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const CircularProgressIndicator(
          valueColor: AlwaysStoppedAnimation<Color>(Color(0xFF3B82F6)),
        ),
        const SizedBox(height: 24),
        Text(
          _progressMessage,
          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 8),
        Text(
          pageInfo,
          style: const TextStyle(fontSize: 13, color: Color(0xFF6B7280)),
        ),
        const SizedBox(height: 20),
        SizedBox(
          width: 320,
          child: LinearProgressIndicator(
            value: _progress,
            backgroundColor: Colors.grey[300],
            valueColor: const AlwaysStoppedAnimation<Color>(Color(0xFF3B82F6)),
            minHeight: 12,
            borderRadius: BorderRadius.circular(6),
          ),
        ),
        const SizedBox(height: 10),
        Text(
          '$pct%',
          style: const TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.bold,
            color: Color(0xFF3B82F6),
          ),
        ),
      ],
    );
  }

  Widget _buildFileInfo() {
    final isDone = _results.isNotEmpty;
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(
          isDone ? Icons.check_circle : Icons.insert_drive_file,
          size: 80,
          color: isDone ? Colors.green : Colors.blue,
        ),
        const SizedBox(height: 20),
        Text(
          isDone ? 'Processing Complete!' : 'File Selected & Ready!',
          style: TextStyle(
            fontSize: 24,
            fontWeight: FontWeight.bold,
            color: isDone ? Colors.green : Colors.blue,
          ),
        ),
        const SizedBox(height: 10),
        Text(
          _selectedFileName ?? '',
          style: const TextStyle(fontSize: 16),
          textAlign: TextAlign.center,
        ),
        if (_totalPages > 0) ...[
          const SizedBox(height: 10),
          Text(
            '$_totalPages page(s) processed',
            style: const TextStyle(
              color: Color(0xFF6B7280),
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildPdfPreview() {
    print("🖼️ Clean Pages (${_cleanPages.length}): ${_cleanPages.take(2)}");
    // 1. SHOW IMAGE CROPS (if we have clean pages from OCR/Vision)
    if (_cleanPages.isNotEmpty && _selectedFilePath != null) {
      return Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(10),
          boxShadow: [
             BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 10, offset: const Offset(0, 5))
          ]
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Column(
            children: [
               // Header (Layout Detection Preview) + Zoom Controls
               Container(
                 padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                 color: const Color(0xFF1E3A8A),  // Deep blue for layout
                 child: Row(
                   children: [
                     const Icon(Icons.grid_view_rounded, color: Colors.white, size: 20),
                     const SizedBox(width: 8),
                     Expanded(
                       child: Text(
                         "📐 LAYOUT PREVIEW (${_cleanPages.length} Segments)",
                         style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13)
                       ),
                     ),
                     // ── Zoom Controls ──
                     Container(
                       padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                       decoration: BoxDecoration(
                         color: Colors.white.withOpacity(0.2),
                         borderRadius: BorderRadius.circular(8),
                       ),
                       child: Row(
                         mainAxisSize: MainAxisSize.min,
                         children: [
                           // Zoom Out
                           InkWell(
                             onTap: () {
                               setState(() {
                                 _zoomLevel = (_zoomLevel - 0.25).clamp(_minZoom, _maxZoom);
                                 _previewZoomCtrl.value = Matrix4.identity()..scale(_zoomLevel);
                               });
                             },
                             child: const Padding(
                               padding: EdgeInsets.all(4),
                               child: Icon(Icons.remove, color: Colors.white, size: 18),
                             ),
                           ),
                           // Zoom Label
                           Padding(
                             padding: const EdgeInsets.symmetric(horizontal: 6),
                             child: Text(
                               '${(_zoomLevel * 100).round()}%',
                               style: const TextStyle(
                                 color: Colors.white,
                                 fontSize: 12,
                                 fontWeight: FontWeight.bold,
                               ),
                             ),
                           ),
                           // Zoom In
                           InkWell(
                             onTap: () {
                               setState(() {
                                 _zoomLevel = (_zoomLevel + 0.25).clamp(_minZoom, _maxZoom);
                                 _previewZoomCtrl.value = Matrix4.identity()..scale(_zoomLevel);
                               });
                             },
                             child: const Padding(
                               padding: EdgeInsets.all(4),
                               child: Icon(Icons.add, color: Colors.white, size: 18),
                             ),
                           ),
                           const SizedBox(width: 4),
                           // Reset
                           InkWell(
                             onTap: () {
                               setState(() {
                                 _zoomLevel = 1.0;
                                 _previewZoomCtrl.value = Matrix4.identity();
                               });
                             },
                             child: const Padding(
                               padding: EdgeInsets.all(4),
                               child: Icon(Icons.fit_screen, color: Colors.white, size: 18),
                             ),
                           ),
                         ],
                       ),
                     ),
                   ],
                 ),
               ),
               // Body: Zoomable Image List
               Expanded(
                 child: Container(
                   color: Colors.grey[200],
                   child: InteractiveViewer(
                     transformationController: _previewZoomCtrl,
                     minScale: _minZoom,
                     maxScale: _maxZoom,
                     onInteractionEnd: (details) {
                       // Sync zoom level with controller
                       final scale = _previewZoomCtrl.value.getMaxScaleOnAxis();
                       setState(() => _zoomLevel = scale);
                     },
                     child: ListView.builder(
                       padding: const EdgeInsets.symmetric(vertical: 20),
                       itemCount: _cleanPages.length,
                       itemBuilder: (context, index) {
                         return Column(
                           children: [
                             Container(
                               margin: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                               decoration: const BoxDecoration(
                                 color: Colors.white,
                                 boxShadow: [BoxShadow(blurRadius: 10, color: Colors.black12)]
                               ),
                               child: Image.network(
                                 _cleanPages[index],
                                 fit: BoxFit.fitWidth,
                                 width: double.infinity,
                                 filterQuality: FilterQuality.high,
                                 isAntiAlias: true,
                                 loadingBuilder: (ctx, child, loads) {
                                    if (loads == null) return child;
                                    return Container(
                                      height: 300,
                                      alignment: Alignment.center,
                                      child: const CircularProgressIndicator()
                                    );
                                 },
                                 errorBuilder: (ctx, err, stack) => Container(
                                    height: 300,
                                    alignment: Alignment.center,
                                    child: const Text("Error loading image. Check Backend Console.")
                                 ),
                               ),
                             ),
                             Padding(
                               padding: const EdgeInsets.only(bottom: 30),
                               child: Container(
                                 padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                                 decoration: BoxDecoration(
                                   color: _cleanPages[index].contains('COL_') || _cleanPages[index].contains('_c')
                                       ? const Color(0xFF059669)  // Green for column crops
                                       : Colors.black87,          // Dark for full pages
                                   borderRadius: BorderRadius.circular(20),
                                 ),
                                 child: Text(
                                   _cleanPages[index].contains('COL_') || _cleanPages[index].contains('_c')
                                       ? "Column ${index + 1} of ${_cleanPages.length}"
                                       : "Page ${index + 1} of ${_cleanPages.length}",
                                   style: const TextStyle(color: Colors.white, fontSize: 12),
                                 ),
                               ),
                             ),
                           ],
                         );
                       },
                     ),
                   ),
                 ),
               )
            ],
          ),
        ),
      );
    }

    // 2. SHOW ORIGINAL PDF (after processing, no clean pages in paddle mode)
    if (_results.isNotEmpty && _selectedFilePath != null) {
      return Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(10),
          boxShadow: [
            BoxShadow(color: Colors.black.withOpacity(0.1), blurRadius: 10, offset: const Offset(0, 5))
          ],
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Column(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 10),
                color: const Color(0xFF1E3A8A),
                child: Row(
                  children: [
                    const Icon(Icons.picture_as_pdf, color: Colors.white, size: 20),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        _selectedFileName ?? 'Document',
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: Colors.green,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Text('Processed ✓', style: TextStyle(color: Colors.white, fontSize: 11)),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: _selectedFilePath!.toLowerCase().endsWith('.docx') || _selectedFilePath!.toLowerCase().endsWith('.doc')
                    ? Container(
                        color: Colors.grey[100],
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(Icons.description, size: 80, color: Colors.blue[300]),
                            const SizedBox(height: 20),
                            const Text(
                              "Word Preview Issue",
                              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.black87),
                            ),
                            const SizedBox(height: 10),
                            Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 40),
                              child: Text(
                                "Sistem gagal merender layout visual file Word ini.\n\nTips Agar Preview Muncul:\n1. Pastikan Microsoft Word di komputer server tertutup.\n2. Pastikan tidak ada dialog 'Save As' atau aktivasi Word yang terbuka.\n3. Cara termudah: Simpan file Word Anda sebagai PDF, lalu upload kembali.\n\nAnda tetap bisa melihat hasil ekstraksi teks di panel kanan.",
                                textAlign: TextAlign.center,
                                style: TextStyle(fontSize: 14, color: Colors.black54, height: 1.5),
                              ),
                            ),
                          ],
                        ),
                      )
                    : SfPdfViewer.file(
                        File(_selectedFilePath!),
                        enableDoubleTapZooming: true,
                        canShowScrollHead: true,
                        pageLayoutMode: PdfPageLayoutMode.continuous,
                      ),
              ),
            ],
          ),
        ),
      );
    }

    // 3. SHOW PLACEHOLDER (Waiting state)
    return Container(
      decoration: BoxDecoration(
        color: Colors.grey[100],
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.grey[300]!, width: 2),
      ),
      child: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
             Icon(Icons.auto_fix_high, size: 60, color: Colors.grey[400]),
             const SizedBox(height: 20),
             Text(
               _selectedFileName != null
                 ? "Ready to Process:\n$_selectedFileName"
                 : "No Document Selected",
               textAlign: TextAlign.center,
               style: TextStyle(fontSize: 18, color: Colors.grey[600], fontWeight: FontWeight.bold),
             ),
             const SizedBox(height: 10),
             if (_selectedFileName != null)
               const Text(
                 "Click 'Analyze with AI' to extract content.",
                 textAlign: TextAlign.center,
                 style: TextStyle(color: Colors.grey),
               ),
          ],
        ),
      ),
    );
  }

  Widget _buildResultsPanel() {
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.all(30),
      child: _results.isEmpty
          ? const Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    Icons.description_outlined,
                    size: 80,
                    color: Color(0xFF9CA3AF),
                  ),
                  SizedBox(height: 20),
                  Text(
                    'No Document Processed Yet',
                    style: TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                      color: Color(0xFF9CA3AF),
                    ),
                  ),
                ],
              ),
            )
          : ListView(
              children: [
                if (_missingChapters.isNotEmpty) _buildMissingChaptersWarning(),
                const Text(
                  'Classification Results',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 20),
                ..._buildChapterSections(),
              ],
            ),
    );
  }

  List<Widget> _buildChapterSections() {
    // Group by chapter
    final Map<String, List<dynamic>> grouped = {};
    for (var item in _results) {
      final chapterId = item['chapter_id'] ?? 'Uncategorized';
      grouped.putIfAbsent(chapterId, () => []);
      grouped[chapterId]!.add(item);
    }

    final chapters = _localizedChapters;
    final firstChapterKey = _docLang == 'en' ? 'Chapter 1' : 'BAB 1';

    // Generic titles to skip when extracting product name
    final genericTitles = [
      'user manual', 'manual book', 'buku manual', 'operating manual',
      'instruction manual', 'table of contents', 'daftar isi', 'cover',
      'introduction', 'pendahuluan', 'kata pengantar', 'preface',
      'petunjuk pengguna', 'petunjuk pemakaian', 'user guide',
      'owner manual', 'service manual', 'manual pengguna', 'panduan pengguna',
      'overview', 'general', 'safety', 'peringatan', 'warning', 'tinjauan'
    ];

    bool isGeneric(String text) {
      final lower = text.toLowerCase().trim();
      return genericTitles.any((g) => lower == g || lower.startsWith(g));
    }

    bool isBrand(String text) {
      final lower = text.toLowerCase().trim();
      return lower.contains('elitech') || lower.contains('technovision') || lower.startsWith('pt.');
    }

    // ── Use AI-extracted cover info if available (clean & concise) ──
    String productName = _aiProductName.isNotEmpty 
        ? _aiProductName 
        : (_selectedFileName ?? 'Dokumen');
    String productDesc = _aiProductDesc;
    
    // Fallback: extract from chapter data only if AI didn't provide
    if (_aiProductName.isEmpty) {
      final List<Map<String, dynamic>> bab1Items = [];
      for (var item in _results) {
        if (item['chapter_id'] == firstChapterKey) {
          bab1Items.add(item);
        }
      }

      int productNameIdx = -1;
      final List<int> headingIndices = [];
      
      for (int i = 0; i < bab1Items.length; i++) {
        final type = (bab1Items[i]['type'] ?? '').toString();
        final t = (bab1Items[i]['normalized'] ?? '').toString().trim();
        if ((type == 'title' || type == 'heading') && t.length > 2 && !isGeneric(t)) {
          if (!isBrand(t)) {
             headingIndices.add(i);
          }
        }
      }

      // Prefer heading with digits (model number) as product name
      if (headingIndices.isNotEmpty) {
        int bestIdx = headingIndices.firstWhere(
          (idx) => (bab1Items[idx]['normalized'] ?? '').toString().contains(RegExp(r'\d')),
          orElse: () => headingIndices.first,
        );
        productNameIdx = bestIdx;
        productName = (bab1Items[bestIdx]['normalized'] ?? '').toString().trim();
      }

      // Extract description: next SHORT text item after product name (MAX 15 words)
      if (productDesc.isEmpty && productNameIdx >= 0 && productNameIdx < bab1Items.length - 1) {
        for (int i = productNameIdx + 1; i < bab1Items.length; i++) {
          final type = (bab1Items[i]['type'] ?? '').toString();
          if (type == 'title' || type == 'heading' || type == 'paragraph') {
            final t = (bab1Items[i]['normalized'] ?? '').toString().trim();
            final wordCount = t.split(RegExp(r'\s+')).length;
            // STRICT: Only use as description if it's SHORT (max 15 words)
            if (t.length > 3 && wordCount <= 15 && !isGeneric(t) && !isBrand(t)) {
              productDesc = t;
              break;
            }
          }
        }
      }
    }
    
    // Safety: truncate description if it's still too long somehow
    if (productDesc.length > 80) {
      productDesc = '${productDesc.substring(0, 77)}...';
    }

    var sortedKeys = chapters.keys.toList();

    return [
      // ── Cover Page Card ──────────────────────────────────
      _buildCoverCard(productName, productDesc),
      const SizedBox(height: 10),

      // ── Table of Contents Card ──────────────────────────
      _buildTocCard(chapters, grouped),
      const SizedBox(height: 10),

      // ── Chapter 1-7 ─────────────────────────────────────
      ...sortedKeys.map((key) {
        var items = grouped[key] ?? [];
        return Card(
          margin: const EdgeInsets.only(bottom: 15),
          elevation: 2,
          child: ExpansionTile(
            initiallyExpanded: items.isNotEmpty,
            title: Text(
              '$key: ${chapters[key]}',
              style: TextStyle(
                fontWeight: FontWeight.bold,
                color: items.isEmpty
                    ? Colors.grey
                    : const Color(0xFF1E3A8A),
              ),
            ),
            subtitle: Text('${items.length} item(s)'),
            children: items.isEmpty
                ? [
                    Padding(
                      padding: const EdgeInsets.all(20.0),
                      child: Center(
                        child: ElevatedButton.icon(
                          onPressed: () => _generateChapterWithAI(key, productName, productDesc),
                          icon: const Icon(Icons.auto_fix_high, color: Colors.amber),
                          label: const Text('Tulis dengan AI'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: const Color(0xFF1E3A8A),
                            foregroundColor: Colors.white,
                            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                          ),
                        ),
                      ),
                    )
                  ]
                : [
                    ...items.map((item) => EditableResultItem(
                          key: ObjectKey(item),
                          item: item,
                          docLang: _docLang,
                          onChapterChanged: (newChapter) =>
                              _updateItemChapter(item, newChapter),
                          onTextChanged: (newText) =>
                              _updateItemText(item, newText),
                          onDelete: () => _deleteItem(item),
                        )).toList(),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                      child: Row(
                        children: [
                          TextButton.icon(
                            onPressed: () {
                              // Tambah manual item kosong
                              setState(() {
                                _results.add({
                                  'chapter_id': key,
                                  'type': 'paragraph',
                                  'original': '',
                                  'normalized': '',
                                  'text_confidence': 1.0,
                                  'is_manual': true,
                                });
                              });
                            },
                            icon: const Icon(Icons.add, size: 20),
                            label: Text(_docLang == 'en' ? 'Add Item' : 'Tambah Teks'),
                            style: TextButton.styleFrom(
                              foregroundColor: const Color(0xFF3B82F6),
                              backgroundColor: const Color(0xFFEFF6FF),
                              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                          ),
                          const SizedBox(width: 10),
                          TextButton.icon(
                            onPressed: () => _uploadSupplement(targetChapter: key),
                            icon: const Icon(Icons.note_add, size: 20),
                            label: Text(_docLang == 'en' ? 'Add File' : 'Tambah File'),
                            style: TextButton.styleFrom(
                              foregroundColor: const Color(0xFF8B5CF6),
                              backgroundColor: const Color(0xFFF5F3FF),
                              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(8),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ]
          ),
        );
      }).toList(),
    ];
  }

  Widget _buildCoverCard(String productName, String productDesc) {
    return Card(
      elevation: 3,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(10),
          gradient: const LinearGradient(
            colors: [Color(0xFF1E3A8A), Color(0xFF3B82F6)],
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
          ),
        ),
        padding: const EdgeInsets.all(20),
        child: Row(
          children: [
            const Icon(Icons.book, color: Colors.white, size: 36),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    'Cover Page',
                    style: TextStyle(
                      color: Colors.white70,
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1.5,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    productName,
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 15,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  if (productDesc.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      productDesc,
                      style: const TextStyle(
                        color: Colors.white70,
                        fontSize: 12,
                      ),
                    ),
                  ],
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.white24,
                      borderRadius: BorderRadius.circular(6),
                    ),
                    child: Text(
                      _docLang == 'en' ? 'MANUAL BOOK' : 'BUKU MANUAL',
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 12,
                        letterSpacing: 2,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTocCard(
      Map<String, String> chapters, Map<String, List<dynamic>> grouped) {
    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      child: ExpansionTile(
        initiallyExpanded: true,
        leading: const Icon(Icons.format_list_bulleted,
            color: Color(0xFF1E3A8A)),
        title: Text(
          _docLang == 'en' ? 'Table of Contents' : 'Daftar Isi',
          style: const TextStyle(
            fontWeight: FontWeight.bold,
            color: Color(0xFF1E3A8A),
            fontSize: 15,
          ),
        ),
        subtitle: Text('${chapters.length} ${_docLang == 'en' ? 'Chapters' : 'BAB'}'),
        children: chapters.entries.map((entry) {
          final items = grouped[entry.key] ?? [];
          // Extract just the number from "BAB 1" or "Chapter 1"
          final numStr = entry.key.replaceAll(RegExp(r'[^0-9]'), '');
          return ListTile(
            dense: true,
            leading: Container(
              width: 32,
              height: 32,
              decoration: BoxDecoration(
                color: items.isEmpty
                    ? Colors.grey[200]
                    : const Color(0xFF1E3A8A),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Center(
                child: Text(
                  numStr,
                  style: TextStyle(
                    color: items.isEmpty ? Colors.grey : Colors.white,
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                  ),
                ),
              ),
            ),
            title: Text(
              '${entry.key}  ${entry.value}',
              style: TextStyle(
                fontSize: 12,
                color: items.isEmpty ? Colors.grey : Colors.black87,
                fontWeight:
                    items.isEmpty ? FontWeight.normal : FontWeight.w500,
              ),
            ),
            trailing: Text(
              '${items.length} item',
              style: TextStyle(
                fontSize: 11,
                color: items.isEmpty ? Colors.grey : const Color(0xFF3B82F6),
                fontWeight: FontWeight.bold,
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  void _updateItemChapter(dynamic item, String? newChapter) {
    if (newChapter != null) {
      setState(() {
        item['chapter_id'] = newChapter;
      });
    }
  }

  void _updateItemText(dynamic item, String newText) {
    // No set state needed for text controller usually, but if we want to sync
    item['normalized'] = newText;
  }
  
  void _deleteItem(dynamic item) {
    setState(() {
      _results.remove(item);
    });
  }

  Future<void> _generateChapterWithAI(String chapterId, String productName, String productDesc) async {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (BuildContext context) {
        return const Center(
          child: CircularProgressIndicator(),
        );
      },
    );

    try {
      final response = await http.post(
        Uri.parse('http://127.0.0.1:8000/generate_chapter'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'chapter_id': chapterId,
          'product_name': productName,
          'product_desc': productDesc,
          'lang': _docLang,
        }),
      );

      Navigator.pop(context); // Close loading dialog

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        if (data['success'] == true) {
          final items = data['items'] as List<dynamic>;
          setState(() {
            _results.addAll(items);
            if (_missingChapters.contains(chapterId)) {
                _missingChapters.remove(chapterId);
            }
          });
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Berhasil mengisi $chapterId dengan AI', style: const TextStyle(color: Colors.white))),
          );
        } else {
          _showError('AI Error: ${data['error']}');
        }
      } else {
        _showError('Server Error: ${response.statusCode}');
      }
    } catch (e) {
      Navigator.pop(context); // Close loading dialog
      _showError('Connection Error: $e');
    }
  }
  void _updateZoom(double newZoom) {
    if (newZoom == _zoomLevel) return;
    
    // Matriks saat ini
    final matrix = _previewZoomCtrl.value;
    
    // Karena kita tidak punya akses langsung ke ukuran layar dari widget tree ini tanpa global key,
    // kita asumsikan origin scaling berada di titik pusat (center).
    // InteractiveViewer's scale normally happens at (0,0) which causes "running" translation.
    // Kita menetralkan efek ini dengan menggeser matriks secara terbalik.
    
    // Scale rasio baru vs lama
    final scaleRatio = newZoom / _zoomLevel;

    // Geser ke tengah (perkiraan offset tengah kasar, atau biarkan widget align center secara otomatis)
    // Dengan flutter InteractiveViewer, mengubah matriks secara manual sering merepotkan (lari).
    // Cara paling aman yang tidak 'lari' adalah menggunakan InteractiveViewer bawaan:
    final newMatrix = Matrix4.identity()
      ..scale(newZoom, newZoom, 1.0);
    
    setState(() {
      _zoomLevel = newZoom;
      _previewZoomCtrl.value = newMatrix;
    });
  }

  void _zoomIn() {
    _updateZoom((_zoomLevel + 0.50).clamp(_minZoom, _maxZoom));
  }

  void _zoomOut() {
    _updateZoom((_zoomLevel - 0.50).clamp(_minZoom, _maxZoom));
  }

  void _resetZoom() {
    setState(() {
      _zoomLevel = 1.0;
      _previewZoomCtrl.value = Matrix4.identity();
    });
  }
  
  void _previousPage() {
    if (_pageController != null && _currentPreviewPage > 0) {
      _pageController!.previousPage(
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeInOut,
      );
    }
  }
  
  void _nextPage() {
    if (_pageController != null && _currentPreviewPage < _cleanPages.length - 1) {
      _pageController!.nextPage(
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeInOut,
      );
    }
  }

  Widget _buildMissingChaptersWarning() {
    return Container(
      margin: const EdgeInsets.only(bottom: 20),
      padding: const EdgeInsets.all(15),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED), // Orange/Amber bg
        border: Border.all(color: const Color(0xFFFDBA74)),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded, color: Color(0xFFEA580C), size: 30),
          const SizedBox(width: 15),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  "Incomplete Document Detected",
                  style: TextStyle(
                    color: Color(0xFF9A3412),
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  "Missing: ${_missingChapters.join(', ')}",
                  style: const TextStyle(color: Color(0xFF9A3412)),
                ),
                const SizedBox(height: 5),
                const Text(
                  "Tip: Use 'Add File' inside the chapter to upload missing parts.",
                  style: TextStyle(color: Color(0xFF9A3412), fontStyle: FontStyle.italic, fontSize: 12),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class EditableResultItem extends StatefulWidget {
  final dynamic item;
  final String docLang;
  final Function(String?) onChapterChanged;
  final Function(String) onTextChanged;
  final VoidCallback onDelete;

  const EditableResultItem({
    super.key,
    required this.item,
    required this.docLang,
    required this.onChapterChanged,
    required this.onTextChanged,
    required this.onDelete,
  });

  @override
  State<EditableResultItem> createState() => _EditableResultItemState();
}

class _EditableResultItemState extends State<EditableResultItem> {
  late TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.item['normalized'] ?? widget.item['original'] ?? '');
  }

  @override
  void didUpdateWidget(EditableResultItem oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.item != oldWidget.item) {
      final newText = widget.item['normalized'] ?? widget.item['original'] ?? '';
      if (_controller.text != newText) {
        _controller.text = newText;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    String type = widget.item['type'] ?? 'text';
    String? cropUrl = widget.item['crop_url'];

    return Container(
      padding: const EdgeInsets.all(15),
      margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.grey[300]!),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              // Type Badge
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: type == 'figure' || type == 'table' ? Colors.blue : Colors.green,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  type.toUpperCase(),
                  style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold),
                ),
              ),
              const Spacer(),
              // Delete Button
              IconButton(
                icon: const Icon(Icons.delete, color: Colors.red, size: 20),
                tooltip: 'Delete this item',
                onPressed: () {
                  showDialog(
                    context: context,
                    builder: (BuildContext context) {
                      return AlertDialog(
                        title: const Text('Delete Item?'),
                        content: Text('Are you sure you want to delete this ${type}?'),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.of(context).pop(),
                            child: const Text('Cancel'),
                          ),
                          ElevatedButton(
                            onPressed: () {
                              Navigator.of(context).pop();
                              widget.onDelete();
                            },
                            style: ElevatedButton.styleFrom(
                              backgroundColor: Colors.red,
                            ),
                            child: const Text('Delete', style: TextStyle(color: Colors.white)),
                          ),
                        ],
                      );
                    },
                  );
                },
              ),
              const SizedBox(width: 8),
              // Chapter Dropdown
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                decoration: BoxDecoration(
                  border: Border.all(color: Colors.grey[300]!),
                  borderRadius: BorderRadius.circular(5),
                ),
                child: DropdownButtonHideUnderline(
                  child: DropdownButton<String>(
                    value: widget.item['chapter_id'],
                    isDense: true,
                    items: List.generate(7, (index) {
                      String key = widget.docLang == 'en'
                          ? "Chapter ${index + 1}"
                          : "BAB ${index + 1}";
                      return DropdownMenuItem(value: key, child: Text(key, style: const TextStyle(fontSize: 12)));
                    }),
                    onChanged: widget.onChapterChanged,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          
          // Image / Table Crop
          if (cropUrl != null)
            Container(
              height: 150,
              width: double.infinity,
              margin: const EdgeInsets.only(bottom: 10),
              decoration: BoxDecoration(
                color: Colors.grey[100],
                borderRadius: BorderRadius.circular(5),
              ),
              child: Image.network(
                cropUrl,
                fit: BoxFit.contain,
                errorBuilder: (c, e, s) => const Center(child: Text("Image Error (Check Backend URL)")),
              ),
            ),
            
          // Editable Text or Rendered Table
          _buildEditorArea(),
        ],
      ),
    );
  }

  bool _isEditingTableText = false;

  bool _isMdTable(String text) {
    if (text.isEmpty) return false;
    final lines = text.trim().split('\n');
    if (lines.length < 3) return false;
    if (lines[0].contains('|') && lines[1].contains('|') && (lines[1].contains('-') || lines[1].contains('='))) {
      return true;
    }
    return false;
  }

  Widget _buildEditorArea() {
    final text = _controller.text;
    final isTable = _isMdTable(text);

    if (isTable && !_isEditingTableText) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildTableViewer(text),
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: () => setState(() => _isEditingTableText = true),
            icon: const Icon(Icons.edit, size: 16),
            label: const Text('Edit Teks Markdown'),
            style: TextButton.styleFrom(
              padding: EdgeInsets.zero,
              minimumSize: const Size(0, 0),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: _controller,
          maxLines: null,
          style: const TextStyle(fontSize: 13),
          decoration: const InputDecoration(
            isDense: true,
            border: OutlineInputBorder(),
            labelText: 'Edit Content',
          ),
          onChanged: widget.onTextChanged,
        ),
        if (isTable && _isEditingTableText) ...[
          const SizedBox(height: 8),
          TextButton.icon(
            onPressed: () => setState(() => _isEditingTableText = false),
            icon: const Icon(Icons.table_view, size: 16),
            label: const Text('Kembali ke Tabel UI'),
            style: TextButton.styleFrom(
              padding: EdgeInsets.zero,
              minimumSize: const Size(0, 0),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ),
        ]
      ],
    );
  }

  Widget _buildTableViewer(String text) {
    final lines = text.trim().split('\n');
    List<TableRow> tableRows = [];

    for (int i = 0; i < lines.length; i++) {
      final line = lines[i].trim();
      if (line.isEmpty) continue;
      // Skip the separator row: |---|---|
      if (i == 1 && (line.contains('---') || line.contains('==='))) continue;
      
      var rawCells = line.split('|');
      if (rawCells.isNotEmpty && rawCells.first.isEmpty) rawCells.removeAt(0);
      if (rawCells.isNotEmpty && rawCells.last.isEmpty) rawCells.removeLast();
      
      final cells = rawCells.map((e) => e.trim()).toList();
      
      if (cells.isNotEmpty) {
        bool isHeader = (i == 0);
        tableRows.add(TableRow(
          decoration: isHeader ? BoxDecoration(color: Colors.grey[200]) : null,
          children: cells.map((cell) => Padding(
            padding: const EdgeInsets.all(8.0),
            child: Text(
              cell,
              style: TextStyle(
                fontSize: 12,
                fontWeight: isHeader ? FontWeight.bold : FontWeight.normal,
              ),
            ),
          )).toList(),
        ));
      }
    }

    if (tableRows.isEmpty) return const SizedBox();
    
    int maxCols = 0;
    for (var r in tableRows) {
      if (r.children.length > maxCols) maxCols = r.children.length;
    }

    for (int i = 0; i < tableRows.length; i++) {
        if (tableRows[i].children.length < maxCols) {
            List<Widget> newChildren = List.from(tableRows[i].children);
            while(newChildren.length < maxCols) {
                newChildren.add(const Padding(padding: EdgeInsets.all(8.0), child: Text('')));
            }
            tableRows[i] = TableRow(decoration: tableRows[i].decoration, children: newChildren);
        } else if (tableRows[i].children.length > maxCols) {
            tableRows[i] = TableRow(decoration: tableRows[i].decoration, children: tableRows[i].children.sublist(0, maxCols));
        }
    }

    return Table(
      border: TableBorder.all(color: Colors.grey[400]!),
      defaultVerticalAlignment: TableCellVerticalAlignment.middle,
      children: tableRows,
    );
  }
}
