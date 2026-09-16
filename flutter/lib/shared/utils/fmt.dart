import 'package:intl/intl.dart';

/// Formatting helpers: money in paise, institution-local dates, locale-aware numbers.
class Fmt {
  Fmt._();

  static String money(int? paise,
      {String locale = 'en_IN', String symbol = '\u20B9'}) {
    if (paise == null) return '\u2014';
    final f =
        NumberFormat.currency(locale: locale, symbol: symbol, decimalDigits: 2);
    return f.format(paise / 100);
  }

  static String number(num? n, {String locale = 'en_IN'}) =>
      n == null ? '\u2014' : NumberFormat.decimalPattern(locale).format(n);

  static String date(DateTime? d, {String pattern = 'dd MMM yyyy'}) =>
      d == null ? '\u2014' : DateFormat(pattern).format(d);

  static String dateTime(DateTime? d) =>
      date(d?.toLocal(), pattern: 'dd MMM yyyy, HH:mm');

  static String percent(num? n, {int digits = 1}) =>
      n == null ? '\u2014' : '${n.toStringAsFixed(digits)}%';

  /// Academic DATE columns arrive as `YYYY-MM-DD`; parse without timezone shifts.
  static DateTime? isoDate(String? s) =>
      s == null || s.isEmpty ? null : DateTime.tryParse(s);

  static String titleCase(String? s) => (s ?? '')
      .replaceAll(RegExp('[_-]+'), ' ')
      .split(' ')
      .map((w) => w.isEmpty ? w : '${w[0].toUpperCase()}${w.substring(1)}')
      .join(' ');
}
