import 'package:flutter/material.dart';
import 'package:qr_flutter/qr_flutter.dart';

/// `QRCodeCard`: ID card / hall ticket / mess / event ticket QR — renders from cached data, so it works offline.
class QRCodeCard extends StatelessWidget {
  const QRCodeCard({super.key, required this.data, required this.title, this.subtitle, this.size = 220});

  final String data;
  final String title;
  final String? subtitle;
  final double size;

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            if (subtitle != null) Text(subtitle!, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            Semantics(
              label: 'QR code for $title',
              child: QrImageView(data: data, size: size, backgroundColor: Colors.white),
            ),
          ]),
        ),
      );
}
