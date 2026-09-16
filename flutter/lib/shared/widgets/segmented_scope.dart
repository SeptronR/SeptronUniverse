import 'package:flutter/material.dart';

import '../../core/auth/auth_state.dart';

/// Mine | Dept | College | All control driven by `meta.visibility`; hidden when only one scope is available.
class SegmentedScope extends StatelessWidget {
  const SegmentedScope(
      {super.key,
      required this.visibility,
      required this.value,
      required this.onChanged});

  final VisibilityMeta visibility;
  final String value;
  final ValueChanged<String> onChanged;

  static const _order = [
    'self',
    'own',
    'department',
    'faculty',
    'college',
    'all'
  ];
  static const _labels = {
    'self': 'Mine',
    'own': 'Mine',
    'department': 'Dept',
    'faculty': 'Faculty',
    'college': 'College',
    'all': 'All',
  };

  @override
  Widget build(BuildContext context) {
    final tabs = <String>[];
    if (visibility.self) tabs.add('self');
    for (final s in _order) {
      if (visibility.scopes.contains(s) && !tabs.contains(s)) tabs.add(s);
    }
    if (tabs.length <= 1) return const SizedBox.shrink();
    return SegmentedButton<String>(
      segments: [
        for (final s in tabs)
          ButtonSegment(value: s, label: Text(_labels[s] ?? s))
      ],
      selected: {tabs.contains(value) ? value : tabs.first},
      onSelectionChanged: (sel) => onChanged(sel.first),
      showSelectedIcon: false,
    );
  }
}
