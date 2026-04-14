import 'package:flutter/material.dart';
import 'dart:io';
import 'dart:ui' as ui;

class VisualCropEditor extends StatefulWidget {
  final String imagePath;
  final List<double> initialBbox; // [x1, y1, x2, y2]
  final ValueChanged<List<double>> onCropUpdate;

  const VisualCropEditor({
    Key? key,
    required this.imagePath,
    required this.initialBbox,
    required this.onCropUpdate,
  }) : super(key: key);

  @override
  State<VisualCropEditor> createState() => _VisualCropEditorState();
}

class _VisualCropEditorState extends State<VisualCropEditor> {
  ui.Image? _image;
  late double x1, y1, x2, y2;

  @override
  void initState() {
    super.initState();
    x1 = widget.initialBbox[0];
    y1 = widget.initialBbox[1];
    x2 = widget.initialBbox[2];
    y2 = widget.initialBbox[3];
    _loadImage();
  }

  Future<void> _loadImage() async {
    try {
      final bytes = await File(widget.imagePath).readAsBytes();
      final codec = await ui.instantiateImageCodec(bytes);
      final frame = await codec.getNextFrame();
      if (mounted) {
        setState(() {
          _image = frame.image;
          // Set to 10% defaults if zero-sized input
          if (x1 == 0 && y1 == 0 && x2 == 0 && y2 == 0) {
            x1 = _image!.width * 0.1;
            y1 = _image!.height * 0.1;
            x2 = _image!.width * 0.9;
            y2 = _image!.height * 0.9;
            _notify();
          }
        });
      }
    } catch (e) {
      print("VisualCropEditor err: $e");
    }
  }

  void _notify() {
    widget.onCropUpdate([x1, y1, x2, y2]);
  }

  Widget _buildHandle(double left, double top, Function(double, double) onDrag) {
    return Positioned(
      left: left - 20, // center large hit area
      top: top - 20,
      child: GestureDetector(
        onPanUpdate: (det) => onDrag(det.delta.dx, det.delta.dy),
        behavior: HitTestBehavior.opaque,
        child: Container(
          width: 40,
          height: 40,
          alignment: Alignment.center,
          child: Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: Colors.white,
              shape: BoxShape.circle,
              border: Border.all(color: Colors.blue, width: 1.5),
              boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 2)],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_image == null) {
      return const Center(child: CircularProgressIndicator());
    }

    final double w = _image!.width.toDouble();
    final double h = _image!.height.toDouble();

    return LayoutBuilder(
      builder: (context, constraints) {
        final double fitWidth = constraints.maxWidth;
        final double fitHeight = constraints.maxHeight;
        if (fitWidth <= 0 || fitHeight <= 0) return const SizedBox.shrink();

        final double scaleX = fitWidth / w;
        final double scaleY = fitHeight / h;
        final double scale = scaleX < scaleY ? scaleX : scaleY; // BoxFit.contain

        final double displayW = w * scale;
        final double displayH = h * scale;

        final double dx1 = x1 * scale;
        final double dy1 = y1 * scale;
        final double dx2 = x2 * scale;
        final double dy2 = y2 * scale;

        void updateCoord(Function() update) {
          setState(update);
          _notify();
        }

        return InteractiveViewer(
          maxScale: 10.0,
          minScale: 0.5,
          boundaryMargin: const EdgeInsets.all(50),
          child: Center(
            child: SizedBox(
              width: displayW,
              height: displayH,
              child: Stack(
              clipBehavior: Clip.none,
              children: [
                // 1. The Image
                Positioned.fill(
                  child: RawImage(image: _image, fit: BoxFit.fill),
                ),
                
                // 2. Dimmed Overlay
                Positioned.fill(
                  child: CustomPaint(
                    painter: _MaskPainter(dx1, dy1, dx2, dy2),
                  ),
                ),

                // 3. The Draggable Box
                Positioned(
                  left: dx1,
                  top: dy1,
                  width: dx2 - dx1,
                  height: dy2 - dy1,
                  child: GestureDetector(
                    onPanUpdate: (det) {
                      final dx = det.delta.dx / scale;
                      final dy = det.delta.dy / scale;
                      
                      // clamp move bounds
                      final moveX = dx.clamp(-x1, w - x2);
                      final moveY = dy.clamp(-y1, h - y2);

                      updateCoord(() {
                        x1 += moveX;
                        x2 += moveX;
                        y1 += moveY;
                        y2 += moveY;
                      });
                    },
                    child: Container(
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.blueAccent, width: 2),
                        color: Colors.blueAccent.withOpacity(0.1),
                      ),
                    ),
                  ),
                ),

                // 4. Handles
                // Top-Left
                _buildHandle(dx1, dy1, (dx, dy) {
                  updateCoord(() {
                    x1 = (x1 + dx / scale).clamp(0, x2 - 20);
                    y1 = (y1 + dy / scale).clamp(0, y2 - 20);
                  });
                }),
                // Top-Right
                _buildHandle(dx2, dy1, (dx, dy) {
                  updateCoord(() {
                    x2 = (x2 + dx / scale).clamp(x1 + 20, w);
                    y1 = (y1 + dy / scale).clamp(0, y2 - 20);
                  });
                }),
                // Bottom-Left
                _buildHandle(dx1, dy2, (dx, dy) {
                  updateCoord(() {
                    x1 = (x1 + dx / scale).clamp(0, x2 - 20);
                    y2 = (y2 + dy / scale).clamp(y1 + 20, h);
                  });
                }),
                // Bottom-Right
                _buildHandle(dx2, dy2, (dx, dy) {
                  updateCoord(() {
                    x2 = (x2 + dx / scale).clamp(x1 + 20, w);
                    y2 = (y2 + dy / scale).clamp(y1 + 20, h);
                  });
                }),
              ],
            ),
          ),
          ),
        );
      },
    );
  }
}

class _MaskPainter extends CustomPainter {
  final double x1, y1, x2, y2;
  _MaskPainter(this.x1, this.y1, this.x2, this.y2);

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = Colors.black.withOpacity(0.5);
    // Draw 4 rectangles around the cut out hole
    // Top
    canvas.drawRect(Rect.fromLTRB(0, 0, size.width, y1), paint);
    // Bottom
    canvas.drawRect(Rect.fromLTRB(0, y2, size.width, size.height), paint);
    // Left
    canvas.drawRect(Rect.fromLTRB(0, y1, x1, y2), paint);
    // Right
    canvas.drawRect(Rect.fromLTRB(x2, y1, size.width, y2), paint);
  }

  @override
  bool shouldRepaint(_MaskPainter old) => 
    x1 != old.x1 || y1 != old.y1 || x2 != old.x2 || y2 != old.y2;
}
