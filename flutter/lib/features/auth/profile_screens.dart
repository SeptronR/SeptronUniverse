import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/auth/auth_state.dart';
import '../../core/auth/biometric_lock.dart';
import '../../core/network/api_exception.dart';
import 'auth_repository.dart';

/// Forced password change (`must_change_password`) — every other route answers 403 until this succeeds.
class ChangePasswordScreen extends ConsumerStatefulWidget {
  const ChangePasswordScreen({super.key});

  @override
  ConsumerState<ChangePasswordScreen> createState() =>
      _ChangePasswordScreenState();
}

class _ChangePasswordScreenState extends ConsumerState<ChangePasswordScreen> {
  final _current = TextEditingController();
  final _next = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Change password')),
        body: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            children: [
              const Text(
                  'At least 10 characters with 3 of 4 character classes; the last 5 cannot be reused.'),
              const SizedBox(height: 12),
              TextField(
                controller: _current,
                obscureText: true,
                decoration:
                    const InputDecoration(labelText: 'Current password'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _next,
                obscureText: true,
                decoration: const InputDecoration(labelText: 'New password'),
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!,
                    style:
                        TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _busy
                    ? null
                    : () async {
                        setState(() {
                          _busy = true;
                          _error = null;
                        });
                        final navigator = Navigator.of(context);
                        try {
                          await ref.read(authRepositoryProvider).changePassword(
                              currentPassword: _current.text,
                              newPassword: _next.text);
                          if (!mounted) return;
                          navigator.maybePop();
                        } on ApiException catch (e) {
                          setState(() => _error = e.message);
                        } finally {
                          if (mounted) setState(() => _busy = false);
                        }
                      },
                child: const Text('Change password'),
              ),
            ],
          ),
        ),
      );
}

/// TOTP enrolment: QR + secret, confirm with a code, recovery codes. Accepts the limited `mfa_setup` token issued
/// with `403 MFA_REQUIRED` so a user whose role demands MFA can enrol before holding a session.
class MfaSetupScreen extends ConsumerStatefulWidget {
  const MfaSetupScreen({super.key, this.setupToken});

  final String? setupToken;

  @override
  ConsumerState<MfaSetupScreen> createState() => _MfaSetupScreenState();
}

class _MfaSetupScreenState extends ConsumerState<MfaSetupScreen> {
  final _code = TextEditingController();
  Map<String, dynamic>? _setup;
  List<String>? _recoveryCodes;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaitedStart();
  }

  void unawaitedStart() {
    Future<void>.microtask(() async {
      try {
        final setup = await ref
            .read(authRepositoryProvider)
            .mfaSetup(setupToken: widget.setupToken);
        if (mounted) setState(() => _setup = setup);
      } on ApiException catch (e) {
        if (mounted) setState(() => _error = e.message);
      }
    });
  }

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final qr = _setup?['qr_png_base64'] as String?;
    return Scaffold(
      appBar: AppBar(title: const Text('Multi-factor authentication')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (_recoveryCodes != null) ...[
              const Text(
                  'Store these recovery codes safely — each works once.'),
              const SizedBox(height: 8),
              ..._recoveryCodes!.map((c) =>
                  Text(c, style: const TextStyle(fontFamily: 'monospace'))),
            ] else ...[
              if (qr != null)
                Center(child: Image.memory(base64Decode(qr), height: 180)),
              if (_setup?['secret'] != null) ...[
                const SizedBox(height: 8),
                SelectableText('Secret: ${_setup!['secret']}'),
              ],
              const SizedBox(height: 12),
              TextField(
                controller: _code,
                keyboardType: TextInputType.number,
                decoration:
                    const InputDecoration(labelText: 'Code from the app'),
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!,
                    style:
                        TextStyle(color: Theme.of(context).colorScheme.error)),
              ],
              const SizedBox(height: 16),
              FilledButton(
                onPressed: _busy
                    ? null
                    : () async {
                        setState(() {
                          _busy = true;
                          _error = null;
                        });
                        try {
                          final codes = await ref
                              .read(authRepositoryProvider)
                              .mfaConfirm(_code.text.trim(),
                                  setupToken: widget.setupToken);
                          if (mounted) setState(() => _recoveryCodes = codes);
                        } on ApiException catch (e) {
                          setState(() => _error = e.message);
                        } finally {
                          if (mounted) setState(() => _busy = false);
                        }
                      },
                child: const Text('Confirm'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Active sessions with revoke, plus the biometric-lock preference (`mobile.biometric_lock`).
class SessionsScreen extends ConsumerStatefulWidget {
  const SessionsScreen({super.key});

  @override
  ConsumerState<SessionsScreen> createState() => _SessionsScreenState();
}

class _SessionsScreenState extends ConsumerState<SessionsScreen> {
  late Future<List<Map<String, dynamic>>> _future =
      ref.read(authRepositoryProvider).sessions();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Sessions')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: _future,
          builder: (context, snapshot) {
            if (!snapshot.hasData) {
              return const Center(child: CircularProgressIndicator.adaptive());
            }
            final rows = snapshot.data!;
            return ListView.separated(
              itemCount: rows.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (context, i) {
                final s = rows[i];
                final current = s['current'] == true;
                return ListTile(
                  title: Text(
                      '${s['device_label'] ?? 'Unknown device'}${current ? ' (this device)' : ''}'),
                  subtitle: Text(
                      '${s['platform'] ?? '—'} · ${s['ip_masked'] ?? '—'}'),
                  trailing: current
                      ? null
                      : TextButton(
                          onPressed: () async {
                            await ref
                                .read(authRepositoryProvider)
                                .revokeSession(s['id'] as String);
                            setState(() => _future =
                                ref.read(authRepositoryProvider).sessions());
                          },
                          child: const Text('Revoke'),
                        ),
                );
              },
            );
          },
        ),
      );
}

/// Profile home: identity, roles and the links to password, MFA, sessions and the biometric lock.
class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authStateProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('My profile')),
      body: ListView(
        children: [
          ListTile(
            title: Text(auth.displayName ?? '—'),
            subtitle: Text(auth.roles.join(', ')),
            leading: const CircleAvatar(child: Icon(Icons.person_outline)),
          ),
          const Divider(height: 1),
          ListTile(
            leading: const Icon(Icons.password_outlined),
            title: const Text('Change password'),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                  builder: (_) => const ChangePasswordScreen()),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.shield_outlined),
            title: const Text('Multi-factor authentication'),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const MfaSetupScreen()),
            ),
          ),
          ListTile(
            leading: const Icon(Icons.devices_outlined),
            title: const Text('Sessions'),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const SessionsScreen()),
            ),
          ),
          SwitchListTile(
            secondary: const Icon(Icons.fingerprint),
            title: const Text('Biometric lock'),
            subtitle: const Text(
                'Ask for biometrics after 5 minutes in the background'),
            value: BiometricLockPreference.enabled,
            onChanged: (v) => BiometricLockPreference.enabled = v,
          ),
          const Divider(height: 1),
          ListTile(
            leading: const Icon(Icons.logout),
            title: const Text('Sign out'),
            onTap: () => ref.read(authRepositoryProvider).logout(),
          ),
        ],
      ),
    );
  }
}
