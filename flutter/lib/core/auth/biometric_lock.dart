import 'package:local_auth/local_auth.dart';

/// Biometric gate on resume after a timeout (feature `mobile.biometric_lock`); Phase 42 wires the lifecycle observer.
class BiometricLock {
  BiometricLock(
      {LocalAuthentication? auth, this.timeout = const Duration(minutes: 5)})
      : _auth = auth ?? LocalAuthentication();

  final LocalAuthentication _auth;
  final Duration timeout;
  DateTime? _lastActive;

  void markActive() => _lastActive = DateTime.now();

  bool get shouldLock =>
      _lastActive != null && DateTime.now().difference(_lastActive!) > timeout;

  Future<bool> authenticate({String reason = 'Unlock SeptronUniverse'}) async {
    try {
      if (!await _auth.canCheckBiometrics && !await _auth.isDeviceSupported()) {
        return true;
      }
      return await _auth.authenticate(localizedReason: reason);
    } catch (_) {
      return false;
    }
  }
}
