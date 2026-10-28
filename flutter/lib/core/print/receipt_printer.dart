import 'package:esc_pos_utils_plus/esc_pos_utils_plus.dart';
import 'package:print_bluetooth_thermal/print_bluetooth_thermal.dart';

/// ESC/POS thermal receipts (Prompts/42 §42.6 `print/`, feature `fees.thermal_receipts`): 58 / 80 mm templates,
/// Bluetooth printer pairing via the OS, QR of the receipt verification link.
class ReceiptLine {
  const ReceiptLine(this.label, this.amount);

  final String label;
  final String amount;
}

class ReceiptData {
  const ReceiptData({
    required this.institution,
    required this.receiptNo,
    required this.date,
    required this.student,
    required this.lines,
    required this.total,
    required this.mode,
    this.verifyUrl,
    this.footer,
  });

  final String institution;
  final String receiptNo;
  final String date;
  final String student;
  final List<ReceiptLine> lines;
  final String total;
  final String mode;
  final String? verifyUrl;
  final String? footer;
}

class ReceiptPrinter {
  static Future<List<BluetoothInfo>> pairedPrinters() => PrintBluetoothThermal.pairedBluetooths;

  static Future<List<int>> build(ReceiptData r, {bool wide = false}) async {
    final profile = await CapabilityProfile.load();
    final g = Generator(wide ? PaperSize.mm80 : PaperSize.mm58, profile);
    final bytes = <int>[
      ...g.text(r.institution, styles: const PosStyles(align: PosAlign.center, bold: true, height: PosTextSize.size2)),
      ...g.text('FEE RECEIPT', styles: const PosStyles(align: PosAlign.center, bold: true)),
      ...g.hr(),
      ...g.text('No: ${r.receiptNo}'),
      ...g.text('Date: ${r.date}'),
      ...g.text('Student: ${r.student}'),
      ...g.hr(),
      for (final l in r.lines)
        ...g.row([
          PosColumn(text: l.label, width: 8),
          PosColumn(text: l.amount, width: 4, styles: const PosStyles(align: PosAlign.right)),
        ]),
      ...g.hr(),
      ...g.row([
        PosColumn(text: 'TOTAL', width: 6, styles: const PosStyles(bold: true)),
        PosColumn(text: r.total, width: 6, styles: const PosStyles(align: PosAlign.right, bold: true)),
      ]),
      ...g.text('Mode: ${r.mode}'),
      if (r.verifyUrl != null) ...[...g.feed(1), ...g.qrcode(r.verifyUrl!)],
      if (r.footer != null) ...g.text(r.footer!, styles: const PosStyles(align: PosAlign.center)),
      ...g.feed(2),
      ...g.cut(),
    ];
    return bytes;
  }

  /// Connects (if needed) and prints; returns false when the printer is unreachable.
  static Future<bool> printTo(String mac, ReceiptData r, {bool wide = false}) async {
    if (!await PrintBluetoothThermal.connectionStatus) {
      final ok = await PrintBluetoothThermal.connect(macPrinterAddress: mac);
      if (!ok) return false;
    }
    return PrintBluetoothThermal.writeBytes(await build(r, wide: wide));
  }
}
