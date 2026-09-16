import 'package:flutter/material.dart';

/// Design tokens shared with the web app (frontend/src/styles/tokens.json). Step 600 = AA-safe primary.
class BrandTheme {
  const BrandTheme(
      {required this.name,
      required this.primary,
      required this.primaryDark,
      required this.tint});

  final String name;
  final Color primary;
  final Color primaryDark;
  final Color tint;
}

class Tokens {
  Tokens._();

  static const themes = <String, BrandTheme>{
    'indigo': BrandTheme(
        name: 'Indigo',
        primary: Color(0xFF4F46E5),
        primaryDark: Color(0xFF4338CA),
        tint: Color(0xFFEEF2FF)),
    'ocean': BrandTheme(
        name: 'Ocean',
        primary: Color(0xFF0891B2),
        primaryDark: Color(0xFF0E7490),
        tint: Color(0xFFECFEFF)),
    'grove': BrandTheme(
        name: 'Grove',
        primary: Color(0xFF16A34A),
        primaryDark: Color(0xFF15803D),
        tint: Color(0xFFF0FDF4)),
    'sunset': BrandTheme(
        name: 'Sunset',
        primary: Color(0xFFEA580C),
        primaryDark: Color(0xFFC2410C),
        tint: Color(0xFFFFF7ED)),
    'plum': BrandTheme(
        name: 'Plum',
        primary: Color(0xFFC026D3),
        primaryDark: Color(0xFFA21CAF),
        tint: Color(0xFFFDF4FF)),
  };

  static const backgroundLight = Color(0xFFF8FAFC);
  static const surfaceLight = Color(0xFFFFFFFF);
  static const backgroundDark = Color(0xFF020617);
  static const surfaceDark = Color(0xFF0F172A);
  static const mutedLight = Color(0xFF64748B);
  static const mutedDark = Color(0xFF94A3B8);
  static const borderLight = Color(0xFFE2E8F0);
  static const borderDark = Color(0xFF334155);

  static const chartLight = [
    Color(0xFF4F46E5),
    Color(0xFF0891B2),
    Color(0xFF16A34A),
    Color(0xFFEA580C),
    Color(0xFFC026D3),
    Color(0xFF64748B)
  ];
  static const chartDark = [
    Color(0xFF818CF8),
    Color(0xFF22D3EE),
    Color(0xFF4ADE80),
    Color(0xFFFB923C),
    Color(0xFFE879F9),
    Color(0xFF94A3B8)
  ];

  static const radius = 8.0;
}
