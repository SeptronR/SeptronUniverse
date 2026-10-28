import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// `SafeScreen` (Prompts/42 §42.6): blocks screenshots / screen recording while marks, valuation and PII screens are
/// visible — Android `FLAG_SECURE`, iOS secure-field overlay — through the `septron/secure_screen` channel
/// implemented in `MainActivity.kt` / `AppDelegate.swift` (see `flutter/README.md` §Native hooks). On platforms
/// without the hook the call is a no-op, and the content is still blurred while the app is in the switcher.
class SafeScreen extends StatefulWidget {
  const SafeScreen({super.key, required this.child, this.enabled = true});

  final Widget child;
  final bool enabled;

  static const _channel = MethodChannel('septron/secure_screen');

  static Future<void> set(bool secure) async {
    if (kIsWeb) return;
    try {
      await _channel.invokeMethod<void>(secure ? 'enable' : 'disable');
    } on MissingPluginException {
      // native hook not compiled in (development build)
    } on PlatformException {
      // ignore
    }
  }

  @override
  State<SafeScreen> createState() => _SafeScreenState();
}

class _SafeScreenState extends State<SafeScreen> with WidgetsBindingObserver {
  bool _obscured = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (widget.enabled) SafeScreen.set(true);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!widget.enabled) return;
    setState(() => _obscured = state != AppLifecycleState.resumed);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    if (widget.enabled) SafeScreen.set(false);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Stack(children: [
        widget.child,
        if (_obscured) const Positioned.fill(child: ColoredBox(color: Colors.black)),
      ]);
}
