import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../remote_config/remote_config.dart';
import 'auth_state.dart';
import 'biometric_lock.dart';

/// Lifecycle observer for `mobile.biometric_lock` (Prompts/42 §42.6): after `biometric_timeout_minutes` in the
/// background the app is covered until local_auth succeeds (device PIN / pattern fallback is the OS prompt).
class BiometricGate extends ConsumerStatefulWidget {
  const BiometricGate({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<BiometricGate> createState() => _BiometricGateState();
}

class _BiometricGateState extends ConsumerState<BiometricGate> with WidgetsBindingObserver {
  BiometricLock? _lock;
  bool _locked = false;

  bool get _active {
    final auth = ref.read(authStateProvider);
    return BiometricLockPreference.enabled && auth.isAuthenticated && auth.hasFeature('mobile.biometric_lock');
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _lock ??= BiometricLock(timeout: ref.read(remoteConfigProvider).biometricTimeout);
    if (state == AppLifecycleState.paused) {
      _lock!.markActive();
    } else if (state == AppLifecycleState.resumed && _active && _lock!.shouldLock) {
      setState(() => _locked = true);
      _unlock();
    }
  }

  Future<void> _unlock() async {
    if (await _lock!.authenticate()) {
      _lock!.markActive();
      if (mounted) setState(() => _locked = false);
    }
  }

  @override
  Widget build(BuildContext context) => Stack(children: [
        widget.child,
        if (_locked)
          Positioned.fill(
            child: Material(
              child: Center(
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.lock_outline, size: 56),
                  const SizedBox(height: 12),
                  const Text('SeptronUniverse is locked'),
                  const SizedBox(height: 16),
                  FilledButton.icon(onPressed: _unlock, icon: const Icon(Icons.fingerprint), label: const Text('Unlock')),
                ]),
              ),
            ),
          ),
      ]);
}
