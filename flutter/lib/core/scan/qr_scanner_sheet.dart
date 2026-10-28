import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

/// `QRScannerSheet` (Prompts/42 §42.6 `scan/`): camera scanner with torch and gallery import; library mode adds
/// 1-D barcode formats. Returns the first raw value (or null when dismissed).
class QRScannerSheet extends StatefulWidget {
  const QRScannerSheet({super.key, this.title = 'Scan', this.barcodes = false});

  final String title;
  final bool barcodes;

  static Future<String?> show(BuildContext context, {String title = 'Scan', bool barcodes = false}) =>
      showModalBottomSheet<String>(
        context: context,
        isScrollControlled: true,
        builder: (_) => FractionallySizedBox(heightFactor: 0.85, child: QRScannerSheet(title: title, barcodes: barcodes)),
      );

  @override
  State<QRScannerSheet> createState() => _QRScannerSheetState();
}

class _QRScannerSheetState extends State<QRScannerSheet> {
  late final MobileScannerController _controller = MobileScannerController(
    formats: widget.barcodes
        ? const [BarcodeFormat.qrCode, BarcodeFormat.code128, BarcodeFormat.code39, BarcodeFormat.ean13]
        : const [BarcodeFormat.qrCode],
  );
  bool _done = false;

  void _found(String? value) {
    if (_done || value == null || value.isEmpty) return;
    _done = true;
    Navigator.of(context).pop(value);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        ListTile(
          title: Text(widget.title),
          trailing: Row(mainAxisSize: MainAxisSize.min, children: [
            IconButton(tooltip: 'Torch', icon: const Icon(Icons.flashlight_on), onPressed: _controller.toggleTorch),
            IconButton(
              tooltip: 'From gallery',
              icon: const Icon(Icons.photo_library),
              onPressed: () async {
                final img = await ImagePicker().pickImage(source: ImageSource.gallery);
                if (img == null) return;
                final capture = await _controller.analyzeImage(img.path);
                _found(capture?.barcodes.firstOrNull?.rawValue);
              },
            ),
            IconButton(tooltip: 'Close', icon: const Icon(Icons.close), onPressed: () => Navigator.of(context).pop()),
          ]),
        ),
        Expanded(
          child: MobileScanner(
            controller: _controller,
            onDetect: (capture) => _found(capture.barcodes.firstOrNull?.rawValue),
          ),
        ),
      ]);
}
