import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../shared/widgets/placeholder_screen.dart';
import '../../shared/widgets/role_shell_scaffold.dart';
import '../auth/auth_events.dart';
import '../auth/auth_state.dart';
import '../auth/session.dart';
import 'deeplinks.dart';
import 'routes.dart';
import 'screen_registry.dart';

/// go_router with redirects: unauth → /login; role shell; permission + feature gate per registered screen.
/// The read-only banner is rendered by [RoleShellScaffold]. Phase 42 completes login/picker/splash screens.
final routerProvider = Provider<GoRouter>((ref) {
  final refresh = _RouterRefresh(ref);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: AppRoutes.splash,
    refreshListenable: refresh,
    redirect: (context, state) {
      final session = ref.read(sessionProvider);
      final auth = ref.read(authStateProvider);
      final loc = state.matchedLocation;
      final isPublic = loc == AppRoutes.login ||
          loc.startsWith('/verify/') ||
          loc.startsWith('/apply/');
      if (!session.isAuthenticated && !isPublic) {
        if (loc.startsWith('/app/')) {
          PendingDeepLink.pending = DeepLink(state.uri.toString());
        }
        return AppRoutes.login;
      }
      if (session.isAuthenticated &&
          (loc == AppRoutes.login || loc == AppRoutes.splash)) {
        final pending = PendingDeepLink.pending;
        PendingDeepLink.pending = null;
        return pending?.location ?? AppRoutes.home;
      }
      if (loc.startsWith('/app/')) {
        final entry = ScreenRegistry.lookup(loc);
        if (entry != null && !_allowed(entry, auth)) {
          return AppRoutes.placeholder;
        }
      }
      return null;
    },
    routes: [
      GoRoute(
          path: AppRoutes.splash,
          builder: (_, __) =>
              const PlaceholderScreen(title: 'SeptronUniverse')),
      GoRoute(
          path: AppRoutes.login,
          builder: (_, __) => const PlaceholderScreen(title: 'Sign in')),
      GoRoute(
          path: AppRoutes.verify,
          builder: (_, s) =>
              PlaceholderScreen(title: 'Verify ${s.pathParameters['token']}')),
      GoRoute(
          path: AppRoutes.apply,
          builder: (_, s) =>
              PlaceholderScreen(title: 'Apply ${s.pathParameters['cycle']}')),
      ShellRoute(
        builder: (context, state, child) =>
            RoleShellScaffold(location: state.matchedLocation, child: child),
        routes: [
          GoRoute(
            path: '/app/:module/:screen',
            builder: (context, state) => ScreenRegistry.build(
                context, state.matchedLocation, state.pathParameters),
          ),
          GoRoute(
            path: '/app/:module',
            builder: (context, state) => ScreenRegistry.build(
                context, state.matchedLocation, state.pathParameters),
          ),
        ],
      ),
    ],
    errorBuilder: (_, state) =>
        PlaceholderScreen(title: state.uri.toString(), notFound: true),
  );
});

bool _allowed(ScreenEntry entry, AuthState auth) {
  if (entry.roles.isNotEmpty &&
      !entry.roles.any(auth.roles.contains) &&
      !auth.isSuperAdmin) {
    return false;
  }
  if (entry.feature != null && !auth.hasFeature(entry.feature!)) return false;
  if (entry.permission != null) {
    final parts = entry.permission!.split(':');
    if (!auth.can(parts[0], parts.length > 1 ? parts[1] : 'view')) return false;
  }
  return true;
}

/// Re-evaluates redirects when the session, the principal or a force-logout event changes.
class _RouterRefresh extends ChangeNotifier {
  _RouterRefresh(Ref ref) {
    _subs.add(ref.listen(sessionProvider, (_, __) => notifyListeners()));
    _subs.add(ref.listen(authStateProvider, (_, __) => notifyListeners()));
    _logout = AuthEvents.instance.forceLogoutStream.listen((_) async {
      await ref.read(sessionProvider.notifier).clear();
      notifyListeners();
    });
  }

  final List<ProviderSubscription<Object?>> _subs = [];
  late final StreamSubscription<String> _logout;

  @override
  void dispose() {
    for (final s in _subs) {
      s.close();
    }
    _logout.cancel();
    super.dispose();
  }
}
