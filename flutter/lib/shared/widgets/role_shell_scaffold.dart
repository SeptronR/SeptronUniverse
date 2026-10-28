import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/auth/auth_state.dart';
import '../../core/router/role_shells.dart';
import '../../core/session/academic_session.dart';
import '../../l10n/app_localizations.dart';
import '../../features/privacy/privacy_screens.dart';
import 'sync_status.dart';

/// Role shell: bottom NavigationBar (≤ 5 tabs from role_shells.dart) + offline/read-only banners.
/// Phase 42 adds the tab-specific FAB and the app bar chips (college/term, search, notifications, profile).
class RoleShellScaffold extends ConsumerWidget {
  const RoleShellScaffold(
      {super.key, required this.location, required this.child});

  final String location;
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authStateProvider);
    final l10n = AppLocalizations.of(context);
    final tabs = tabsForRole(auth.primaryRole)
        .where((t) => t.feature == null || auth.hasFeature(t.feature!))
        .where((t) {
      return t.permission == null || auth.canSpec(t.permission!);
    }).toList();
    final index = tabs
        .indexWhere((t) => location.startsWith(t.route))
        .clamp(0, tabs.length - 1);

    return Scaffold(
      body: Column(
        children: [
          // Phase 42 — offline / queued writes / read-only state (tap → sync status sheet)
          const OfflineBanner(),
          // Phase 03: current term chip (tap → college picker for multi-college users)
          if (auth.isAuthenticated)
            const SafeArea(
              bottom: false,
              child: Padding(
                padding: EdgeInsets.fromLTRB(12, 4, 12, 0),
                child: Align(
                    alignment: Alignment.centerLeft, child: CurrentTermChip()),
              ),
            ),
          Expanded(child: ConsentBannerGate(child: child)),
        ],
      ),
      bottomNavigationBar: tabs.length < 2
          ? null
          : NavigationBar(
              selectedIndex: index,
              onDestinationSelected: (i) => context.go(tabs[i].route),
              destinations: [
                for (final t in tabs)
                  NavigationDestination(
                      icon: Icon(t.icon), label: _label(l10n, t.titleKey)),
              ],
            ),
    );
  }

  String _label(AppLocalizations l10n, String key) => switch (key) {
        'home' => l10n.home,
        'more' => l10n.more,
        'approvals' => l10n.approvals,
        'notifications' => l10n.notifications,
        'profile' => l10n.profile,
        _ => humanizeKey(key),
      };
}

/// Tab / tile label for keys without an ARB entry yet: `outPasses` → "Out passes".
String humanizeKey(String key) {
  final spaced = key.replaceAllMapped(RegExp('([a-z])([A-Z])'), (m) => '${m[1]} ${m[2]!.toLowerCase()}').replaceAll('_', ' ');
  return spaced.isEmpty ? key : '${spaced[0].toUpperCase()}${spaced.substring(1)}';
}
