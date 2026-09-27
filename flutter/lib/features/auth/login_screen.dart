import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/constants.dart';
import '../../core/network/api_exception.dart';
import '../../core/router/routes.dart';
import 'auth_repository.dart';

/// Sign-in screen: password (with the MFA step) and OTP tabs (Prompts/02 §02.10).
/// A forced password change routes to `/app/profile/password`; MFA enrolment to `/app/profile/mfa`.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(length: 2, vsync: this);
  final _identifier = TextEditingController();
  final _password = TextEditingController();
  final _mfaCode = TextEditingController();
  final _phone = TextEditingController();
  final _otp = TextEditingController();
  bool _busy = false;
  bool _mfaRequired = false;
  bool _otpSent = false;
  String? _error;
  String? _mfaSetupToken;

  @override
  void dispose() {
    _tabs.dispose();
    _identifier.dispose();
    _password.dispose();
    _mfaCode.dispose();
    _phone.dispose();
    _otp.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _loginWithPassword() => _run(() async {
        final repo = ref.read(authRepositoryProvider);
        final outcome = await repo.login(
          identifier: _identifier.text.trim(),
          password: _password.text,
          mfaCode: _mfaCode.text.trim().isEmpty ? null : _mfaCode.text.trim(),
          deviceLabel: 'Mobile app',
        );
        if (!mounted) return;
        if (outcome.mfaRequired) {
          setState(() {
            _mfaRequired = true;
            _mfaSetupToken = outcome.mfaSetupToken;
            _error = outcome.mfaSetupRequired
                ? 'Your role requires multi-factor authentication — set it up to continue'
                : 'Enter the code from your authenticator app';
          });
          if (outcome.mfaSetupRequired && outcome.mfaSetupToken != null) {
            context.go('${AppRoutes.profile}/mfa',
                extra: outcome.mfaSetupToken);
          }
          return;
        }
        _afterLogin(outcome.state!.mustChangePassword);
      });

  Future<void> _sendOtp() => _run(() async {
        await ref
            .read(authRepositoryProvider)
            .sendOtp(phone: _phone.text.trim());
        if (mounted) setState(() => _otpSent = true);
      });

  Future<void> _verifyOtp() => _run(() async {
        await ref
            .read(authRepositoryProvider)
            .verifyOtp(phone: _phone.text.trim(), code: _otp.text.trim());
        _afterLogin(false);
      });

  void _afterLogin(bool mustChangePassword) {
    if (!mounted) return;
    context.go(
        mustChangePassword ? '${AppRoutes.profile}/password' : AppRoutes.home);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.school_outlined,
                      size: 48, color: theme.colorScheme.primary),
                  const SizedBox(height: 8),
                  Text(kAppName, style: theme.textTheme.headlineSmall),
                  const SizedBox(height: 16),
                  TabBar(
                    controller: _tabs,
                    tabs: const [
                      Tab(text: 'Password'),
                      Tab(text: 'One-time code')
                    ],
                  ),
                  const SizedBox(height: 16),
                  SizedBox(
                    height: 280,
                    child: TabBarView(
                      controller: _tabs,
                      children: [_passwordTab(), _otpTab()],
                    ),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 8),
                    Text(_error!,
                        style: TextStyle(color: theme.colorScheme.error)),
                  ],
                  if (_mfaSetupToken != null)
                    TextButton(
                      onPressed: () => context.go('${AppRoutes.profile}/mfa',
                          extra: _mfaSetupToken),
                      child: const Text('Set up multi-factor authentication'),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _passwordTab() => Column(
        children: [
          TextField(
            controller: _identifier,
            autofillHints: const [AutofillHints.username],
            decoration:
                const InputDecoration(labelText: 'Username, email or phone'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _password,
            obscureText: true,
            autofillHints: const [AutofillHints.password],
            decoration: const InputDecoration(labelText: 'Password'),
          ),
          if (_mfaRequired) ...[
            const SizedBox(height: 12),
            TextField(
              controller: _mfaCode,
              keyboardType: TextInputType.number,
              decoration:
                  const InputDecoration(labelText: 'Authenticator code'),
            ),
          ],
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _busy ? null : _loginWithPassword,
            child: _busy
                ? const CircularProgressIndicator.adaptive()
                : const Text('Sign in'),
          ),
        ],
      );

  Widget _otpTab() => Column(
        children: [
          TextField(
            controller: _phone,
            keyboardType: TextInputType.phone,
            decoration:
                const InputDecoration(labelText: 'Registered phone number'),
          ),
          if (_otpSent) ...[
            const SizedBox(height: 12),
            TextField(
              controller: _otp,
              keyboardType: TextInputType.number,
              maxLength: 6,
              decoration: const InputDecoration(labelText: '6-digit code'),
            ),
          ],
          const SizedBox(height: 16),
          FilledButton(
            onPressed: _busy ? null : (_otpSent ? _verifyOtp : _sendOtp),
            child: Text(_otpSent ? 'Sign in' : 'Send code'),
          ),
        ],
      );
}
