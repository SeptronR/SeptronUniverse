import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app.dart';
import '../../core/session/academic_session.dart';
import '../../l10n/app_localizations.dart';

/// App settings (Prompts/03 §03.10 `features/settings`): language, theme mode and the college in use.
/// No institution settings are edited on mobile in this phase.
class AppSettingsScreen extends ConsumerWidget {
  const AppSettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final mode = ref.watch(themeModeProvider);
    final locale = ref.watch(localeProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        children: [
          const ListTile(title: Text('Theme')),
          for (final m in ThemeMode.values)
            RadioListTile<ThemeMode>(
              value: m,
              groupValue: mode,
              title: Text(switch (m) {
                ThemeMode.system => 'System',
                ThemeMode.light => 'Light',
                ThemeMode.dark => 'Dark',
              }),
              onChanged: (v) => ref.read(themeModeProvider.notifier).state = v ?? ThemeMode.system,
            ),
          const Divider(),
          const ListTile(title: Text('Language')),
          RadioListTile<String?>(
            value: null,
            groupValue: locale?.languageCode,
            title: const Text('Device default'),
            onChanged: (_) => ref.read(localeProvider.notifier).state = null,
          ),
          for (final l in AppLocalizations.supportedLocales)
            RadioListTile<String?>(
              value: l.languageCode,
              groupValue: locale?.languageCode,
              title: Text(l.toLanguageTag()),
              onChanged: (_) => ref.read(localeProvider.notifier).state = l,
            ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.apartment_outlined),
            title: const Text('College'),
            subtitle: const CurrentTermChip(),
            onTap: () => showCollegePicker(context, ref),
          ),
        ],
      ),
    );
  }
}
