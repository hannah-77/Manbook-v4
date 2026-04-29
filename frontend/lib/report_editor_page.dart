import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:url_launcher/url_launcher.dart';
import 'dart:io';
import 'visual_crop_editor.dart';

class ReportEditorPage extends StatefulWidget {
  final List<dynamic> items;
  final String originalFilename;
  final String language; // 'id' or 'en'
  final String? aiProductName;
  final String? aiProductDesc;

  const ReportEditorPage({
    super.key,
    required this.items,
    required this.originalFilename,
    this.language = 'id',
    this.aiProductName,
    this.aiProductDesc,
  });

  @override
  State<ReportEditorPage> createState() => _ReportEditorPageState();
}

class _ReportEditorPageState extends State<ReportEditorPage> {
  late List<dynamic> _items;
  bool _isGenerating = false;
  String? _pdfUrl;
  bool _showOriginalPreview = false;

  bool _showQualityBanner = true;
  String? _customProductName;
  String? _customProductDesc;

  // ── AI Completeness Tracker ──
  Map<String, Map<String, dynamic>> _completenessResults = {};
  Map<String, bool> _isLoadingCompleteness = {};

  // ── Confidence Highlight Toggle ──
  bool _showConfidenceHighlight = true;

  // ── Zoom ──
  double _zoomLevel = 1.0;
  static const double _zoomMin = 0.4;
  static const double _zoomMax = 3.0;
  static const double _zoomStep = 0.2;

  static const Color _primaryBlue = Color(0xFF1E3A8A);
  static const Color _lightBlue  = Color(0xFF3B82F6);
  static const Color _textGray   = Color(0xFF6B7280);

  // ── Language: uses explicit user selection ──
  String get _docLang => widget.language;

  Map<String, String> get _chapters {
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
    _items = List<dynamic>.from(
        widget.items.map((x) {
          final m = Map<String, dynamic>.from(x);
          // Ensure highlights is always a List (backend may send null)
          if (m['highlights'] == null) m['highlights'] = [];
          return m;
        }));
    
    // Initialize cover info from AI extraction (if available)
    if (widget.aiProductName != null && widget.aiProductName!.isNotEmpty) {
      _customProductName = widget.aiProductName;
    }
    if (widget.aiProductDesc != null && widget.aiProductDesc!.isNotEmpty) {
      _customProductDesc = widget.aiProductDesc;
    }
  }

  @override
  void dispose() {
    super.dispose();
  }

  void _zoomIn() {
    setState(() {
      _zoomLevel = (_zoomLevel + _zoomStep).clamp(_zoomMin, _zoomMax);
    });
  }

  void _zoomOut() {
    setState(() {
      _zoomLevel = (_zoomLevel - _zoomStep).clamp(_zoomMin, _zoomMax);
    });
  }

  void _zoomReset() {
    setState(() {
      _zoomLevel = 1.0;
    });
  }

  Widget _buildLegendDot(Color color, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 10, height: 10,
          decoration: BoxDecoration(
            color: color,
            borderRadius: BorderRadius.circular(2),
          ),
        ),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(fontSize: 9.5, color: Colors.blueGrey)),
      ],
    );
  }

  // ─────────────────────────────────────────────────────────────────
  // Evaluasi Kelengkapan Bab dengan AI
  // ─────────────────────────────────────────────────────────────────
  Future<void> _checkChapterCompleteness(String chapterId, List<dynamic> chapterItems) async {
    setState(() => _isLoadingCompleteness[chapterId] = true);
    try {
      final response = await http.post(
        Uri.parse('http://127.0.0.1:8000/check_chapter_completeness'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'chapter_id': chapterId,
          'items': chapterItems,
          'lang': widget.language,
        }),
      );

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        if (data['success'] == true) {
          setState(() {
            _completenessResults[chapterId] = {
              'score': data['score'],
              'analysis': data['analysis'],
            };
          });
        } else {
          _showError(data['error'] ?? 'Gagal mengecek kelengkapan');
        }
      } else {
         _showError('Terjadi kesalahan sistem (${response.statusCode})');
      }
    } catch (e) {
      _showError('Tidak dapat menyambung ke server untuk cek kelengkapan');
    } finally {
      setState(() => _isLoadingCompleteness[chapterId] = false);
    }
  }

  // ─────────────────────────────────────────────────────────────────
  // Generate Report
  // ─────────────────────────────────────────────────────────────────
  Future<void> _generateReport() async {
    setState(() => _isGenerating = true);
    try {
      final response = await http.post(
        Uri.parse('http://127.0.0.1:8000/generate_custom_report'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'items': _items,
          'filename': widget.originalFilename,
          'lang': widget.language,
          'custom_product_name': _customProductName,
          'custom_product_desc': _customProductDesc,
        }),
      );
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        if (data['success'] == true) {
          if (data['word_url'] != null) launchUrl(Uri.parse(data['word_url']));
          setState(() {
            _pdfUrl = data['pdf_url'];
          });
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text(data['pdf_url'] != null ? 'Word & PDF exported!' : 'Word exported! (PDF conversion not available)')),
            );
          }
        } else {
          _showError('Backend error: ${data['error']}');
        }
      } else {
        _showError('Server error: ${response.statusCode}');
      }
    } catch (e) {
      _showError('Connection error: $e');
    } finally {
      if (mounted) setState(() => _isGenerating = false);
    }
  }

  void _showError(String message) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(message), backgroundColor: Colors.red),
      );
    }
  }

  void _updateItemText(int index, String newText) {
    setState(() {
      _items[index]['normalized'] = newText;
      // Clear stale highlights after manual edit
      _items[index]['highlights'] = [];
    });
  }

  void _deleteItem(int index) {
    setState(() => _items.removeAt(index));
  }

  // ─────────────────────────────────────────────────────────────────
  // Edit dialog (tap on any element to edit text + type)
  // ─────────────────────────────────────────────────────────────────
  void _showEditDialog(int index) {
    final ctrl = TextEditingController(text: _items[index]['normalized'] ?? '');
    String selectedType = (_items[index]['type'] ?? 'paragraph').toString();
    // Only allow switching between text types  
    final isVisual = selectedType == 'table' || selectedType == 'figure';

    showDialog(
      context: context,
      builder: (_) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: Row(
            children: [
              Expanded(
                child: Text(
                  'Edit ${selectedType.toUpperCase()}',
                  style: const TextStyle(color: _primaryBlue, fontWeight: FontWeight.bold),
                ),
              ),
              // Delete button
              IconButton(
                icon: const Icon(Icons.delete_outline, color: Colors.red),
                tooltip: 'Hapus elemen ini',
                onPressed: () {
                  Navigator.pop(ctx);
                  _deleteItem(index);
                },
              ),
            ],
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Type selector (only for text types)
              if (!isVisual) ...[
                Row(
                  children: [
                    const Text('Tipe: ', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
                    const SizedBox(width: 8),
                    ChoiceChip(
                      label: const Text('Paragraph'),
                      selected: selectedType == 'paragraph',
                      selectedColor: _lightBlue.withAlpha(60),
                      onSelected: (_) => setDialogState(() => selectedType = 'paragraph'),
                    ),
                    const SizedBox(width: 8),
                    ChoiceChip(
                      label: const Text('Heading'),
                      selected: selectedType == 'heading' || selectedType == 'title',
                      selectedColor: _lightBlue.withAlpha(60),
                      onSelected: (_) => setDialogState(() => selectedType = 'heading'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
              ],
              TextField(
                controller: ctrl,
                maxLines: null,
                minLines: 3,
                decoration: const InputDecoration(border: OutlineInputBorder()),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Batal'),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _primaryBlue),
              onPressed: () {
                setState(() {
                  _items[index]['normalized'] = ctrl.text;
                  if (!isVisual) _items[index]['type'] = selectedType;
                  // Clear highlights — user has manually reviewed the text
                  _items[index]['highlights'] = [];
                });
                Navigator.pop(ctx);
              },
              child: const Text('Simpan', style: TextStyle(color: Colors.white)),
            ),
          ],
        ),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────
  // Add Text dialog — lets user add missing text as paragraph/heading
  // ─────────────────────────────────────────────────────────────────
  void _showAddTextDialog(String chapterId) {
    final textCtrl = TextEditingController();
    String selectedType = 'paragraph';

    showDialog(
      context: context,
      builder: (_) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text(
            'Tambah Teks',
            style: TextStyle(color: _primaryBlue, fontWeight: FontWeight.bold),
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Type selector
              Row(
                children: [
                  const Text('Tipe: ', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
                  const SizedBox(width: 8),
                  ChoiceChip(
                    label: const Text('Paragraph'),
                    selected: selectedType == 'paragraph',
                    selectedColor: _lightBlue.withAlpha(60),
                    onSelected: (_) => setDialogState(() => selectedType = 'paragraph'),
                  ),
                  const SizedBox(width: 8),
                  ChoiceChip(
                    label: const Text('Heading'),
                    selected: selectedType == 'heading',
                    selectedColor: _lightBlue.withAlpha(60),
                    onSelected: (_) => setDialogState(() => selectedType = 'heading'),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextField(
                controller: textCtrl,
                maxLines: null,
                minLines: 3,
                decoration: const InputDecoration(
                  border: OutlineInputBorder(),
                  hintText: 'Ketik teks yang hilang di sini...',
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Batal'),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _primaryBlue),
              onPressed: () {
                if (textCtrl.text.trim().isEmpty) return;
                setState(() {
                  _items.add({
                    'type': selectedType,
                    'normalized': textCtrl.text.trim(),
                    'original': textCtrl.text.trim(),
                    'chapter_id': chapterId,
                    'chapter_title': _chapters[chapterId] ?? '',
                    'has_typo': false,
                    'text_confidence': 1.0,
                    'typos': [],
                    'match_score': 100,
                  });
                });
                Navigator.pop(ctx);
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text('${selectedType == 'heading' ? 'Heading' : 'Paragraf'} ditambahkan ke $chapterId'),
                    backgroundColor: Colors.green,
                    duration: const Duration(seconds: 2),
                  ),
                );
              },
              child: const Text('Tambah', style: TextStyle(color: Colors.white)),
            ),
          ],
        ),
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────
  // Confidence Accuracy Widget
  // ─────────────────────────────────────────────────────────────────
  double get _accuracy {
    if (_items.isEmpty) return 0.0;
    double totalConf = 0.0;
    int count = 0;
    for (var item in _items) {
      if (item['type'] == 'table' || item['type'] == 'figure') continue;
      final conf = item['text_confidence'];
      if (conf != null && conf is num) {
        totalConf += conf;
        count++;
      }
    }
    if (count == 0) return 1.0;
    return totalConf / count;
  }

  Widget _buildConfidenceScoreWidget() {
    if (!_showQualityBanner) return const SizedBox.shrink();

    double conf = _accuracy;
    int accPercent = (conf * 100).round();
    
    Color boxColor;
    Color iconColor;
    String statusTitle;
    IconData iconData;

    if (accPercent >= 95) {
      boxColor = Colors.green.shade50;
      iconColor = Colors.green.shade700;
      statusTitle = "Sangat Akurat";
      iconData = Icons.check_circle;
    } else if (accPercent >= 85) {
      boxColor = Colors.yellow.shade50;
      iconColor = Colors.orange.shade700;
      statusTitle = "Cukup Akurat";
      iconData = Icons.info_outline;
    } else if (accPercent >= 70) {
      boxColor = Colors.orange.shade50;
      iconColor = Colors.deepOrange.shade700;
      statusTitle = "Perlu Dicek";
      iconData = Icons.warning_amber_rounded;
    } else {
      boxColor = Colors.red.shade50;
      iconColor = Colors.red.shade700;
      statusTitle = "Kurang Akurat";
      iconData = Icons.error_outline;
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 24),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: boxColor,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: iconColor.withOpacity(0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Icon(iconData, color: iconColor, size: 28),
          const SizedBox(width: 16),
          Expanded(
            child: Text(
              "Kualitas Hasil Scan: $accPercent% ($statusTitle)",
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.bold,
                color: iconColor,
              ),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.close),
            color: iconColor,
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(),
            onPressed: () {
              setState(() {
                _showQualityBanner = false;
              });
            },
          ),
        ],
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────
  // Build
  // ─────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    // Group by chapter
    final Map<String, List<MapEntry<int, dynamic>>> grouped = {};
    for (int i = 0; i < _items.length; i++) {
      // Skip items marked as cover page elements — they only appear on cover simulation
      if (_items[i]['is_cover'] == true) continue;
      final key = _items[i]['chapter_id'] ?? (_docLang == 'en' ? 'Chapter 1' : 'BAB 1');
      grouped.putIfAbsent(key, () => []);
      grouped[key]!.add(MapEntry(i, _items[i]));
    }

    return Scaffold(
      backgroundColor: const Color(0xFFE5E7EB),
      appBar: AppBar(
        backgroundColor: _primaryBlue,
        foregroundColor: Colors.white,
        title: const Text('Preview & Edit — Manual Book',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        actions: [
          // ── Zoom Controls ──────────────────────────────────────
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              IconButton(
                icon: const Icon(Icons.zoom_out, color: Colors.white, size: 20),
                tooltip: 'Zoom Out',
                onPressed: _zoomLevel > _zoomMin ? _zoomOut : null,
              ),
              GestureDetector(
                onTap: _zoomReset,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.white24,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    '${(_zoomLevel * 100).round()}%',
                    style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold),
                  ),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.zoom_in, color: Colors.white, size: 20),
                tooltip: 'Zoom In',
                onPressed: _zoomLevel < _zoomMax ? _zoomIn : null,
              ),
              const SizedBox(width: 4),
            ],
          ),
          // ── Original Preview Toggle ──────────────────────────
          IconButton(
            icon: Icon(
              _showOriginalPreview ? Icons.vertical_split : Icons.check_box_outline_blank,
              color: _showOriginalPreview ? Colors.white : Colors.white54,
              size: 20,
            ),
            tooltip: _showOriginalPreview ? 'Tutup Preview Asli' : 'Bandingkan Dokumen',
            onPressed: () {
              setState(() => _showOriginalPreview = !_showOriginalPreview);
            },
          ),
          
          // ── Confidence Highlight Toggle ──────────────────────────
          IconButton(
            icon: Icon(
              _showConfidenceHighlight ? Icons.highlight : Icons.highlight_off,
              color: _showConfidenceHighlight ? Colors.amber[300] : Colors.white54,
              size: 20,
            ),
            tooltip: _showConfidenceHighlight ? 'Sembunyikan Confidence' : 'Tampilkan Confidence',
            onPressed: () {
              setState(() => _showConfidenceHighlight = !_showConfidenceHighlight);
            },
          ),
          // ── Export Buttons ──────────────────────────────────────
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            child: ElevatedButton.icon(
              onPressed: _isGenerating ? null : _generateReport,
              icon: _isGenerating
                  ? const SizedBox(
                      width: 18, height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: _primaryBlue))
                  : const Icon(Icons.download, size: 18),
              label: Text(_isGenerating ? 'Generating...' : 'Export Word & PDF'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Colors.white,
                foregroundColor: _primaryBlue,
              ),
            ),
          ),
          // ── Download PDF (appears after generation) ─────────────
          if (_pdfUrl != null)
            Padding(
              padding: const EdgeInsets.only(right: 16, top: 8, bottom: 8),
              child: ElevatedButton.icon(
                onPressed: () => launchUrl(Uri.parse(_pdfUrl!)),
                icon: const Icon(Icons.picture_as_pdf, size: 18),
                label: const Text('Download PDF'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.red[600],
                  foregroundColor: Colors.white,
                ),
              ),
            ),
        ],
      ),
      body: SingleChildScrollView(
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Transform.scale(
            scale: _zoomLevel,
            alignment: Alignment.topCenter,
            child: SizedBox(
              // Lebar minimum sesuai kertas A4 + padding, disesuaikan dengan zoom
              width: (794 + 48) * _zoomLevel < MediaQuery.of(context).size.width
                  ? MediaQuery.of(context).size.width / _zoomLevel
                  : 794 + 48,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // ── Extracted Editor ──
                  Expanded(
                    flex: _showOriginalPreview ? 1 : 100, // Takes up appropriate space
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        children: [
                          // ── Confidence Score Dashboard ──────────────────────────────
                    _buildConfidenceScoreWidget(),

                    // ── Confidence Legend ──────────────────────────────
                    if (_showConfidenceHighlight)
                      Container(
                        margin: const EdgeInsets.only(bottom: 16),
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                        decoration: BoxDecoration(
                          color: Colors.blueGrey[50],
                          borderRadius: BorderRadius.circular(8),
                          border: Border.all(color: Colors.blueGrey[200]!),
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Icon(Icons.info_outline, size: 14, color: Colors.blueGrey),
                            const SizedBox(width: 8),
                            const Text('Confidence: ', style: TextStyle(fontSize: 10, fontWeight: FontWeight.bold, color: Colors.blueGrey)),
                            _buildLegendDot(const Color(0xFF22C55E), '> 90% (Baik)'),
                            const SizedBox(width: 12),
                            _buildLegendDot(const Color(0xFFF59E0B), '70-90% (Cek Ulang)'),
                            const SizedBox(width: 12),
                            _buildLegendDot(const Color(0xFFEF4444), '< 70% (Periksa!)'),
                          ],
                        ),
                      ),

                    // ── Cover Page Simulation ──────────────────────────────
                    _buildPageWrapper([
                      _buildCoverSimulation(grouped),
                    ]),
                    const SizedBox(height: 24),

                    // ── Daftar Isi Simulation ──────────────────────────────
                    _buildPageWrapper([
                      _buildTocSimulation(),
                    ]),
                    const SizedBox(height: 24),

                    // ── BAB Pages ─────────────────────────────────────────
                    ..._chapters.keys.map((babId) {
                      final items = grouped[babId] ?? [];
                      return Column(children: [
                        _buildPageWrapper([
                          _buildChapterHeader(babId, items),
                          const SizedBox(height: 16),
                          if (items.isEmpty)
                            Padding(
                              padding: const EdgeInsets.symmetric(vertical: 20),
                              child: Text(
                                '[ Tidak ada konten terdeteksi pada bab ini ]',
                                style: TextStyle(color: Colors.grey[400], fontStyle: FontStyle.italic),
                                textAlign: TextAlign.center,
                              ),
                            )
                          else
                            ...items.map((e) => _buildDocumentItem(e.key, e.value)),
                          // ── Add Text Button ──
                          const SizedBox(height: 8),
                          Center(
                            child: TextButton.icon(
                              onPressed: () => _showAddTextDialog(babId),
                              icon: const Icon(Icons.add_circle_outline, size: 18, color: Color(0xFF3B82F6)),
                              label: const Text(
                                'Tambah Teks',
                                style: TextStyle(color: Color(0xFF3B82F6), fontSize: 12),
                              ),
                            ),
                          ),
                        ]),
                      ]);
                    }).toList(),
                  ],
                ),
              ),
            ),
            
            // ── Original PDF View (Side by side) ──
            if (_showOriginalPreview) ...[
              const SizedBox(width: 24),
              Expanded(
                flex: 1,
                child: Padding(
                  padding: const EdgeInsets.only(top: 24, bottom: 24, right: 24),
                  child: Container(
                    decoration: BoxDecoration(
                      color: Colors.white,
                      border: Border.all(color: Colors.grey[300]!),
                      boxShadow: [
                        BoxShadow(
                          color: Colors.black.withOpacity(0.15),
                          blurRadius: 12,
                          offset: const Offset(0, 4),
                        ),
                      ],
                    ),
                    height: MediaQuery.of(context).size.height * 0.85,
                    child: const Center(
                      child: Text(
                        '(Gunakan window file asli untuk membandingkan secara akurat)',
                        style: TextStyle(color: Colors.grey, fontStyle: FontStyle.italic),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ),
                ),
              )
            ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }


  // ─────────────────────────────────────────────────────────────────
  // Page wrapper (white sheet with shadow)
  // ─────────────────────────────────────────────────────────────────
  Widget _buildPageWrapper(List<Widget> children) {
    return Container(
      width: 794, // A4 ~794px at 96dpi
      constraints: const BoxConstraints(minHeight: 400),
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.15),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      padding: const EdgeInsets.fromLTRB(72, 60, 56, 60), // ~A4 margins
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: children,
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────
  void _editCoverDialog(String currentName, String currentDesc) {
    TextEditingController nameCtrl = TextEditingController(text: currentName);
    TextEditingController descCtrl = TextEditingController(text: currentDesc);
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Edit Cover Page'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameCtrl,
              decoration: const InputDecoration(labelText: 'Nama Produk / Judul'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: descCtrl,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'Deskripsi Produk',
                hintText: 'Contoh: Pengukur Panjang Badan Bayi...',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Batal'),
          ),
          ElevatedButton(
            onPressed: () {
              setState(() {
                _customProductName = nameCtrl.text;
                _customProductDesc = descCtrl.text;
              });
              Navigator.pop(context);
            },
            child: const Text('Simpan'),
          ),
        ],
      )
    );
  }

  // Cover simulation
  // ─────────────────────────────────────────────────────────────────
  Widget _buildCoverSimulation(Map<String, List<MapEntry<int, dynamic>>> grouped) {
    // Generic titles that should NOT be used as product name
    final genericTitles = [
      'user manual', 'manual book', 'buku manual', 'operating manual',
      'instruction manual', 'owner manual', 'service manual',
      'table of contents', 'daftar isi', 'cover', 'introduction',
      'pendahuluan', 'kata pengantar', 'preface',
      'petunjuk pengguna', 'petunjuk pemakaian', 'user guide',
      'manual pengguna', 'panduan pengguna',
    ];

    bool isGenericTitle(String text) {
      final lower = text.toLowerCase().trim();
      return genericTitles.any((g) => lower == g || lower.startsWith(g));
    }

    bool isBrandTitle(String text) {
      final lower = text.toLowerCase().trim();
      return lower.contains('elitech') || lower.contains('technovision') || lower.startsWith('pt.');
    }

    String productName = widget.originalFilename;
    String productDesc = '';

    if (_customProductName != null) {
      productName = _customProductName!;
    } else {
      // Extract product name from filename
      RegExp regExp = RegExp(r'(?:buku manual|manual book|user manual)\s+([a-zA-Z0-9\-]+)', caseSensitive: false);
      Match? match = regExp.firstMatch(productName);
      if (match != null && match.groupCount >= 1) {
        productName = match.group(1)!;
      } else {
        productName = productName.split('.').first; 
        if (productName.length > 15) {
           productName = productName.substring(0, 15);
        }
      }

      // Extract from BAB 1 items — prefer headings with digits (model numbers)
      final firstChapterKey = _docLang == 'en' ? 'Chapter 1' : 'BAB 1';
      final List<Map<String, dynamic>> bab1Items = [];
      for (int i = 0; i < _items.length; i++) {
        // Hanya tarik teks yang benar-benar ditandai sebagai cover sheet
        if (_items[i]['chapter_id'] == firstChapterKey && _items[i]['is_cover'] == true) {
          bab1Items.add(_items[i]);
        }
      }

      int productNameIdx = -1;
      final List<int> headingIndices = [];
      
      for (int i = 0; i < bab1Items.length; i++) {
        final type = (bab1Items[i]['type'] ?? '').toString();
        final text = (bab1Items[i]['normalized'] ?? '').toString().trim();
        if ((type == 'title' || type == 'heading') && text.length > 2 && !isGenericTitle(text)) {
          if (!isBrandTitle(text)) {
             headingIndices.add(i);
          }
        }
      }

      // Prefer heading containing digits (model number)
      if (headingIndices.isNotEmpty) {
        int bestIdx = headingIndices.firstWhere(
          (idx) => (bab1Items[idx]['normalized'] ?? '').toString().contains(RegExp(r'\d')),
          orElse: () => headingIndices.first,
        );
        productNameIdx = bestIdx;
        productName = (bab1Items[bestIdx]['normalized'] ?? '').toString().trim();
      }

      // Extract description: next text item after product name
      if (productNameIdx >= 0 && productNameIdx < bab1Items.length - 1) {
        for (int i = productNameIdx + 1; i < bab1Items.length; i++) {
          final type = (bab1Items[i]['type'] ?? '').toString();
          if (type == 'title' || type == 'heading' || type == 'paragraph') {
            final text = (bab1Items[i]['normalized'] ?? '').toString().trim();
            if (text.length > 3 && !isGenericTitle(text) && !isBrandTitle(text)) {
              productDesc = text;
              break;
            }
          }
        }
      }
    }

    // Apply custom description override
    if (_customProductDesc != null) {
      productDesc = _customProductDesc!;
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 40),
        // Nama produk kiri atas (dengan tombol Edit)
        Row(
           crossAxisAlignment: CrossAxisAlignment.start,
           children: [
             Expanded(
               child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                     Text(productName,
                         style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.black)),
                     if (productDesc.isNotEmpty) ...[
                       const SizedBox(height: 8),
                       Text(productDesc,
                           style: const TextStyle(fontSize: 13, color: Color(0xFF444444))),
                     ],
                  ]
               )
             ),
             Container(
               margin: const EdgeInsets.only(left: 8),
               child: IconButton(
                 icon: const Icon(Icons.edit, color: Colors.grey),
                 tooltip: "Edit Cover",
                 onPressed: () => _editCoverDialog(productName, productDesc),
               ),
             ),
           ]
        ),
        const SizedBox(height: 120),
        // BUKU MANUAL / MANUAL BOOK center
        Center(
          child: Text(
            _docLang == 'en' ? 'MANUAL BOOK' : 'BUKU MANUAL',
            style: const TextStyle(fontSize: 28, fontWeight: FontWeight.bold, color: Colors.black),
          ),
        ),

      ],
    );
  }

  // ─────────────────────────────────────────────────────────────────
  // TOC simulation
  // ─────────────────────────────────────────────────────────────────
  Widget _buildTocSimulation() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(_docLang == 'en' ? 'TABLE OF CONTENTS' : 'DAFTAR ISI',
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: _primaryBlue)),
        const Divider(color: Color(0xFF1E3A8A), thickness: 1.5),
        const SizedBox(height: 12),
        ..._chapters.entries.map((e) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(
            children: [
              Text('${e.key}   ', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13)),
              Expanded(child: Text(e.value, style: const TextStyle(fontSize: 13))),
              Text('...', style: TextStyle(color: Colors.grey[400])),
              const SizedBox(width: 8),
              Text('${3 + _chapters.keys.toList().indexOf(e.key) * 2}',
                  style: TextStyle(color: _primaryBlue, fontWeight: FontWeight.bold, fontSize: 13)),
            ],
          ),
        )).toList(),
      ],
    );
  }

  // ─────────────────────────────────────────────────────────────────
  // Chapter divider
  // ─────────────────────────────────────────────────────────────────
  Widget _buildChapterHeader(String babId, List<MapEntry<int, dynamic>> entries) {
    final title = _chapters[babId] ?? babId;
    final bool isLoading = _isLoadingCompleteness[babId] ?? false;
    final Map<String, dynamic>? result = _completenessResults[babId];
    
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: _primaryBlue,
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(
            child: Text(
              '  $babId: $title',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 14,
                fontWeight: FontWeight.bold,
              ),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          // ── Completeness Status ──
          if (isLoading)
            const SizedBox(
              width: 14, height: 14,
              child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2),
            )
          else if (result != null)
            InkWell(
              onTap: () {
                showDialog(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    title: const Text('💡 AI Completeness Analysis', style: TextStyle(fontSize: 16)),
                    content: Text(result['analysis'].toString(), style: const TextStyle(fontSize: 13, height: 1.5)),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Tutup'))
                    ]
                  ),
                );
              },
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: (result['score'] as num) >= 95 ? Colors.green[600] : Colors.orange[700],
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  children: [
                    Text(
                      'Kelengkapan: ${result['score']}%',
                      style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(width: 4),
                    const Icon(Icons.info_outline, color: Colors.white, size: 12),
                  ]
                ),
              ),
            )
          else
            TextButton.icon(
              onPressed: () {
                final chapterItems = entries.map((e) => e.value).toList();
                _checkChapterCompleteness(babId, chapterItems);
              },
              icon: const Icon(Icons.auto_awesome, color: Colors.white, size: 14),
              label: const Text('Cek AI', style: TextStyle(color: Colors.white, fontSize: 11)),
              style: TextButton.styleFrom(
                backgroundColor: Colors.white.withOpacity(0.15),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                minimumSize: Size.zero,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              ),
            ),
        ],
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────
  // Document item — renders each element in Word-like style
  // ─────────────────────────────────────────────────────────────────
  // ─────────────────────────────────────────────────────────────────
  // Semi-automated correction: apply a suggestion for a highlighted word
  // ─────────────────────────────────────────────────────────────────
  void _applyHighlightSuggestion(int itemIndex, Map<String, dynamic> highlight, String chosenWord) {
    setState(() {
      final currentText = (_items[itemIndex]['normalized'] ?? '').toString();
      // Replace the corrected word (case-insensitive) with the chosen suggestion
      final corrected  = (highlight['corrected'] ?? '').toString();
      if (corrected.isEmpty) return;

      final updated = currentText.replaceFirst(
        RegExp(r'\b' + RegExp.escape(corrected) + r'\b', caseSensitive: false),
        chosenWord,
      );
      _items[itemIndex]['normalized'] = updated;

      // Remove this highlight from the list
      final highlights = List<dynamic>.from(_items[itemIndex]['highlights'] ?? []);
      highlights.removeWhere((h) =>
          h is Map && h['corrected']?.toString().toLowerCase() == corrected.toLowerCase());
      _items[itemIndex]['highlights'] = highlights;
    });
  }

  // ─────────────────────────────────────────────────────────────────
  // RichText rendering with red-underline highlights + tap-to-suggest popup
  // ─────────────────────────────────────────────────────────────────
  Widget _buildHighlightedText(int index, String text, dynamic item,
      {TextStyle? baseStyle, TextAlign align = TextAlign.start}) {
    final effectiveStyle = baseStyle ??
        const TextStyle(fontSize: 11.5, height: 1.35, color: Colors.black87);

    final List<dynamic> highlights = List<dynamic>.from(item['highlights'] ?? []);
    if (highlights.isEmpty) {
      return Text(text, style: effectiveStyle, textAlign: align);
    }

    // Build a sorted, non-overlapping list of highlight ranges
    final List<Map<String, dynamic>> sorted = highlights
        .whereType<Map>()
        .map((h) => Map<String, dynamic>.from(h))
        .where((h) {
          final s = h['start'] as int? ?? 0;
          final e = h['end'] as int? ?? 0;
          return s >= 0 && e > s && e <= text.length;
        })
        .toList()
      ..sort((a, b) => (a['start'] as int).compareTo(b['start'] as int));

    // Build TextSpan list
    final List<InlineSpan> spans = [];
    int cursor = 0;

    for (final hl in sorted) {
      final int hlStart  = hl['start'] as int;
      final int hlEnd    = hl['end'] as int;
      final String hlWord = text.substring(hlStart, hlEnd);
      final List<String> suggestions = List<String>.from(hl['suggestions'] ?? []);
      final String corrected = (hl['corrected'] ?? hlWord).toString();

      // Plain text before this highlight
      if (cursor < hlStart) {
        spans.add(TextSpan(
          text: text.substring(cursor, hlStart),
          style: effectiveStyle,
        ));
      }

      // Highlighted word — red dashed underline, tappable
      spans.add(
        WidgetSpan(
          alignment: PlaceholderAlignment.baseline,
          baseline: TextBaseline.alphabetic,
          child: GestureDetector(
            onTapDown: (TapDownDetails details) async {
              // Build menu items: suggestions + keep + edit manually
              final menuItems = <PopupMenuEntry<String>>[
                PopupMenuItem<String>(
                  enabled: false,
                  height: 28,
                  child: Text(
                    '"$hlWord" → dikoreksi ke "$corrected"',
                    style: const TextStyle(
                        fontSize: 11,
                        color: Colors.black54,
                        fontStyle: FontStyle.italic),
                  ),
                ),
                const PopupMenuDivider(),
                // Keep the auto-corrected word
                PopupMenuItem<String>(
                  value: '__keep__',
                  height: 34,
                  child: Row(children: [
                    const Icon(Icons.check_circle_outline, size: 16, color: Colors.green),
                    const SizedBox(width: 8),
                    Text('Pakai "$corrected" (auto)', style: const TextStyle(fontSize: 12)),
                  ]),
                ),
                // Each suggestion
                ...suggestions.map((s) => PopupMenuItem<String>(
                  value: s,
                  height: 34,
                  child: Row(children: [
                    const Icon(Icons.swap_horiz, size: 16, color: _lightBlue),
                    const SizedBox(width: 8),
                    Text('Ganti dengan "$s"', style: const TextStyle(fontSize: 12)),
                  ]),
                )),
                const PopupMenuDivider(),
                // Edit manually
                PopupMenuItem<String>(
                  value: '__edit__',
                  height: 34,
                  child: const Row(children: [
                    Icon(Icons.edit_outlined, size: 16, color: _textGray),
                    SizedBox(width: 8),
                    Text('Edit manual...', style: TextStyle(fontSize: 12)),
                  ]),
                ),
              ];

              final RenderBox overlay = Overlay.of(context)
                  .context
                  .findRenderObject() as RenderBox;
              final result = await showMenu<String>(
                context: context,
                position: RelativeRect.fromRect(
                  details.globalPosition & const Size(1, 1),
                  Offset.zero & overlay.size,
                ),
                items: menuItems,
                elevation: 8,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(8)),
              );

              if (result == null) return;
              if (result == '__keep__') {
                _applyHighlightSuggestion(index, hl, corrected);
              } else if (result == '__edit__') {
                _showEditDialog(index);
              } else {
                _applyHighlightSuggestion(index, hl, result);
              }
            },
            child: Text(
              hlWord,
              style: effectiveStyle.copyWith(
                decoration: TextDecoration.underline,
                decorationColor: Colors.red,
                decorationStyle: TextDecorationStyle.wavy,
                decorationThickness: 2.0,
                color: Colors.black87,
              ),
            ),
          ),
        ),
      );

      cursor = hlEnd;
    }

    // Remaining plain text
    if (cursor < text.length) {
      spans.add(TextSpan(
        text: text.substring(cursor),
        style: effectiveStyle,
      ));
    }

    return Text.rich(
      TextSpan(children: spans),
      textAlign: align,
    );
  }

  Widget _buildDocumentItem(int index, dynamic item) {
    final type = (item['type'] ?? 'text').toString();
    final text = (item['normalized'] ?? '').toString();
    final hasTypo = item['has_typo'] == true;

    // ── Confidence-based coloring ──
    final double confidence = (item['text_confidence'] is num)
        ? (item['text_confidence'] as num).toDouble()
        : 1.0;

    // Stabilo color: no highlight > 0.90, yellow 0.70-0.90, pink < 0.70
    Color? stabiloColor;
    if (_showConfidenceHighlight && type != 'figure' && type != 'table') {
      if (confidence < 0.70) {
        stabiloColor = const Color(0x40EF4444); // light red/pink
      } else if (confidence < 0.90) {
        stabiloColor = const Color(0x40F59E0B); // light yellow
      }
      // >= 0.90: no stabilo (text is fine)
    }

    return GestureDetector(
      onTap: () => _showEditDialog(index),
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _buildItemContent(index, type, text, item, hasTypo, stabiloColor: stabiloColor),
            // ── Confidence badge (small) ──
            if (_showConfidenceHighlight &&
                type != 'figure' && type != 'table' &&
                confidence < 0.90)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  'OCR confidence: ${(confidence * 100).toStringAsFixed(0)}%',
                  style: TextStyle(
                    fontSize: 9,
                    color: confidence < 0.70 ? Colors.red[600] : Colors.orange[700],
                    fontStyle: FontStyle.italic,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildItemContent(int index, String type, String text, dynamic item, bool hasTypo, {Color? stabiloColor}) {
    // ── Heading / Title ──
    if (type == 'title' || type == 'heading') {
      return Padding(
        padding: const EdgeInsets.only(top: 16, bottom: 6),
        child: _buildHighlightedText(
          index,
          text,
          item,
          baseStyle: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.bold,
            color: _primaryBlue,
            backgroundColor: stabiloColor,
          ),
        ),
      );
    }

    // ── Figure / Table ──
    if (type == 'figure' || type == 'table') {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Column(
          children: [
            // Label & Action
            Row(children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: _primaryBlue,
                  borderRadius: BorderRadius.circular(3),
                ),
                child: Text(
                  '[ ${type.toUpperCase()} ]',
                  style: const TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold),
                ),
              ),
              const SizedBox(width: 8),
              InkWell(
                onTap: () => _showEditCropDialog(index),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: Colors.orange[600],
                    borderRadius: BorderRadius.circular(3),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.crop, color: Colors.white, size: 12),
                      SizedBox(width: 4),
                      Text('Edit Crop', style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold)),
                    ],
                  ),
                ),
              ),
            ]),
            const SizedBox(height: 6),
            // Image
            if (item['crop_local'] != null)
              Container(
                decoration: BoxDecoration(border: Border.all(color: Colors.grey[300]!)),
                constraints: const BoxConstraints(maxWidth: 180, maxHeight: 200),
                child: Image.file(
                  File(item['crop_local']),
                  fit: BoxFit.contain,
                  errorBuilder: (_, __, ___) => const Padding(
                    padding: EdgeInsets.all(20),
                    child: Text('[Gambar tidak tersedia]', style: TextStyle(color: Colors.grey)),
                  ),
                ),
              ),
            // Teks untuk Figure/Table biasanya berisi kode data (seperti Markdown tabel atau placeholder [FIGURE]).
            // Jangan tampilkan sebagai caption karena akan membuat UI berantakan.
            if (text.isNotEmpty && type != 'table' && type != 'figure' && !text.contains('[TABLE') && !text.contains('[FIGURE')) ...[
              const SizedBox(height: 6),
              Text(text,
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 10, fontStyle: FontStyle.italic, color: _textGray)),
            ],
          ],
        ),
      );
    }

    // ── Body Text — with stabilo highlight ──
    final List<dynamic> highlights = List<dynamic>.from(item['highlights'] ?? []);
    final bool hasHighlights = highlights.isNotEmpty;

    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildHighlightedText(
            index,
            text,
            item,
            align: TextAlign.justify,
            baseStyle: TextStyle(
              fontSize: 11.5,
              height: 1.35,
              color: Colors.black87,
              backgroundColor: stabiloColor,
            ),
          ),
          // ── Highlight legend (shown only when there are uncertain words) ──
          if (hasHighlights)
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Row(
                children: [
                  Container(
                    width: 14,
                    height: 2,
                    decoration: const BoxDecoration(
                      color: Colors.red,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    '${highlights.length} kata meragukan — tap kata bergaris merah untuk pilih koreksi',
                    style: TextStyle(
                        fontSize: 9.5,
                        color: Colors.red[700],
                        fontStyle: FontStyle.italic),
                  ),
                ],
              ),
            )
          // ── Fallback: generic OCR confidence warning ──
          else if (hasTypo ||
              (item['text_confidence'] != null &&
                  (item['text_confidence'] as num) < 0.85))
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                '⚠ OCR confidence rendah. Periksa apakah ada salah eja. (Tap untuk edit)',
                style: TextStyle(
                    fontSize: 10,
                    color: Colors.deepOrange[700],
                    fontStyle: FontStyle.italic),
              ),
            ),
        ],
      ),
    );
  }

  // ─────────────────────────────────────────────────────────────────
  // UI Re-crop Gambar (Figure / Table)
  // ─────────────────────────────────────────────────────────────────
  void _showEditCropDialog(int index) {
    final item = _items[index];
    
    // Determine source image: prefer source_image_local, fallback to crop_local
    final String? sourceImg = (item['source_image_local'] as String?) ?? (item['crop_local'] as String?);
    final bool hasSource = sourceImg != null && sourceImg.isNotEmpty;
    
    // Original bbox or default
    final rawBbox = item['bbox'];
    List<double> currentBbox = rawBbox != null 
        ? List<double>.from((rawBbox as List).map((e) => (e is num) ? e.toDouble() : 0.0))
        : [0.0, 0.0, 0.0, 0.0];
    
    bool isProcessing = false;

    showDialog(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              title: const Text('Edit Pemotongan Manual', style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
              content: isProcessing 
                 ? const SizedBox(
                     height: 300, width: 500,
                     child: Center(child: CircularProgressIndicator())
                   )
                 : SizedBox(
                   width: 800, // dialog width
                   height: 500, // dialog height
                   child: Column(
                     children: [
                       if (!hasSource)
                         Container(
                           padding: const EdgeInsets.all(10),
                           margin: const EdgeInsets.only(bottom: 12),
                           decoration: BoxDecoration(
                             color: Colors.orange[50],
                             border: Border.all(color: Colors.orange),
                             borderRadius: BorderRadius.circular(6),
                           ),
                           child: const Row(
                             children: [
                               Icon(Icons.warning_amber, color: Colors.orange, size: 18),
                               SizedBox(width: 8),
                               Expanded(child: Text(
                                 'Source image tidak tersedia. Scan ulang dokumen untuk mengaktifkan manual crop.',
                                 style: TextStyle(fontSize: 11, color: Colors.orange),
                               )),
                             ],
                           ),
                         ),
                       const Text(
                         'Geser kotak biru di bawah untuk menentukan area gambar.', 
                         style: TextStyle(fontSize: 12, color: Colors.grey),
                       ),
                       const SizedBox(height: 16),
                       if (hasSource)
                         Expanded(
                           child: Container(
                             decoration: BoxDecoration(
                               border: Border.all(color: Colors.grey[300]!),
                               color: Colors.grey[100],
                             ),
                             child: VisualCropEditor(
                               imagePath: sourceImg,
                               initialBbox: currentBbox,
                               onCropUpdate: (val) {
                                 currentBbox = val;
                               },
                             ),
                           ),
                         ),
                     ],
                   ),
                 ),
              actions: [
                TextButton(
                  onPressed: isProcessing ? null : () => Navigator.pop(context),
                  child: const Text('Batal'),
                ),
                ElevatedButton(
                  onPressed: (isProcessing || !hasSource) ? null : () async {
                    setDialogState(() => isProcessing = true);
                    
                    final nx1 = currentBbox[0].toInt();
                    final ny1 = currentBbox[1].toInt();
                    final nx2 = currentBbox[2].toInt();
                    final ny2 = currentBbox[3].toInt();
                    
                    try {
                      final res = await http.post(
                        Uri.parse('http://127.0.0.1:8000/recrop'),
                        headers: {'Content-Type': 'application/json'},
                        body: json.encode({
                          "source_image_local": sourceImg,
                          "bbox": [nx1, ny1, nx2, ny2],
                          "element_type": item['type'] ?? 'figure'
                        })
                      );
                      
                      final data = json.decode(res.body);
                      if (data['success'] == true) {
                         setState(() {
                             item['crop_url'] = data['crop_url'];
                             item['crop_local'] = data['crop_local'];
                             item['bbox'] = [nx1, ny1, nx2, ny2]; 
                         });
                         if (context.mounted) {
                           Navigator.pop(context);
                           ScaffoldMessenger.of(context).showSnackBar(
                             const SnackBar(content: Text('Gambar berhasil dipotong ulang!'), backgroundColor: Colors.green)
                           );
                         }
                      } else {
                         if (context.mounted) {
                           ScaffoldMessenger.of(context).showSnackBar(
                             SnackBar(content: Text('Gagal: ${data['error']}'), backgroundColor: Colors.red)
                           );
                         }
                         setDialogState(() => isProcessing = false);
                      }
                    } catch(e) {
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          SnackBar(content: Text('Error: $e'), backgroundColor: Colors.red)
                        );
                      }
                      setDialogState(() => isProcessing = false);
                    }
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: hasSource ? _primaryBlue : Colors.grey,
                  ),
                  child: Text(
                    hasSource ? 'Simpan Potongan' : 'Tidak tersedia',
                    style: const TextStyle(color: Colors.white),
                  ),
                ),
              ],
            );
          }
        );
      }
    );
  }
}

