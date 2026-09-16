import 'package:flutter/material.dart';

import 'tokens.dart';

/// Material 3 light/dark themes from the shared tokens; institution branding (logo, primary) overrides `themeKey`
/// through `institutionThemeProvider` in Phase 42.
class AppTheme {
  AppTheme._();

  static ThemeData light({String themeKey = 'indigo', Color? brandPrimary}) {
    final brand = Tokens.themes[themeKey] ?? Tokens.themes['indigo']!;
    final primary = brandPrimary ?? brand.primary;
    final scheme = ColorScheme.fromSeed(
        seedColor: primary, primary: primary, brightness: Brightness.light);
    return _base(scheme).copyWith(
      scaffoldBackgroundColor: Tokens.backgroundLight,
      cardTheme: const CardThemeData(
          color: Tokens.surfaceLight, elevation: 0, margin: EdgeInsets.zero),
      dividerColor: Tokens.borderLight,
    );
  }

  static ThemeData dark({String themeKey = 'indigo', Color? brandPrimary}) {
    final brand = Tokens.themes[themeKey] ?? Tokens.themes['indigo']!;
    final primary = brandPrimary ?? brand.primary;
    final scheme = ColorScheme.fromSeed(
        seedColor: primary, primary: primary, brightness: Brightness.dark);
    return _base(scheme).copyWith(
      scaffoldBackgroundColor: Tokens.backgroundDark,
      cardTheme: const CardThemeData(
          color: Tokens.surfaceDark, elevation: 0, margin: EdgeInsets.zero),
      dividerColor: Tokens.borderDark,
    );
  }

  static ThemeData _base(ColorScheme scheme) => ThemeData(
        useMaterial3: true,
        colorScheme: scheme,
        visualDensity: VisualDensity.standard,
        inputDecorationTheme: InputDecorationTheme(
          border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(Tokens.radius)),
          isDense: true,
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(Tokens.radius)),
          ),
        ),
        navigationBarTheme: const NavigationBarThemeData(
            labelBehavior: NavigationDestinationLabelBehavior.alwaysShow),
      );
}
