import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 43 mobile (Prompts/43 §43.10): consent banner on first sign-in / notice change, Profile › Privacy (consents,
/// raise a data request, verify identity, download), guardian toggles for minor wards.
final consentBannerProvider = FutureProvider.autoDispose<Map<String, dynamic>?>((ref) async {
  try {
    final r = await ref.watch(dioProvider).get<Map<String, dynamic>>('/privacy/consent-banner');
    return (r.data?['data'] as Map?)?.cast<String, dynamic>();
  } catch (_) {
    return null; // platform users / feature off: no banner
  }
});

final myDsrsProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final r = await ref.watch(dioProvider).get<Map<String, dynamic>>('/data-subject-requests/me');
  return ((r.data?['data'] as List?) ?? const []).cast<Map>().map((e) => e.cast<String, dynamic>()).toList();
});

String _label(String key) => key.replaceAll('_', ' ');

/// Wrap the shell body: shows the consent sheet once per session when `requires_update`.
class ConsentBannerGate extends ConsumerStatefulWidget {
  const ConsentBannerGate({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<ConsentBannerGate> createState() => _ConsentBannerGateState();
}

class _ConsentBannerGateState extends ConsumerState<ConsentBannerGate> {
  bool _shown = false;

  @override
  Widget build(BuildContext context) {
    ref.listen(consentBannerProvider, (_, next) {
      final data = next.valueOrNull;
      if (_shown || data == null || data['requires_update'] != true) return;
      _shown = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          isDismissible: false,
          builder: (_) => FractionallySizedBox(heightFactor: 0.85, child: _ConsentSheet(data: data)),
        );
      });
    });
    ref.watch(consentBannerProvider);
    return widget.child;
  }
}

class _ConsentSheet extends ConsumerStatefulWidget {
  const _ConsentSheet({required this.data});

  final Map<String, dynamic> data;

  @override
  ConsumerState<_ConsentSheet> createState() => _ConsentSheetState();
}

class _ConsentSheetState extends ConsumerState<_ConsentSheet> {
  late final List<Map<String, dynamic>> _purposes =
      ((widget.data['purposes'] as List?) ?? const []).cast<Map>().map((e) => e.cast<String, dynamic>()).toList();
  late final Map<String, bool> _grants = {
    for (final p in _purposes)
      '${p['key']}': p['mandatory'] == true || ((widget.data['current'] as Map?)?['${p['key']}'] == true),
  };
  bool _busy = false;

  bool get _minor => widget.data['is_minor'] == true;

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      final grants = _minor ? {for (final p in _purposes.where((p) => p['mandatory'] == true)) '${p['key']}': true} : _grants;
      await ref.read(dioProvider).post<void>('/consents/bulk', data: {'grants': grants, 'notice_version': widget.data['notice_version']});
      if (mounted) Navigator.of(context).pop();
      ref.invalidate(consentBannerProvider);
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Column(children: [
          ListTile(
            title: const Text('Your privacy choices'),
            subtitle: Text('DPDP Act 2023 notice v${widget.data['notice_version']}. Change these any time in Profile › Privacy.'),
          ),
          if (_minor)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: Text('You are under 18 — your parent or guardian records the optional choices.'),
            ),
          Expanded(
            child: ListView(children: [
              for (final p in _purposes)
                SwitchListTile(
                  value: _grants['${p['key']}'] ?? false,
                  onChanged: p['mandatory'] == true || _minor ? null : (v) => setState(() => _grants['${p['key']}'] = v),
                  title: Text(_label('${p['key']}') + (p['mandatory'] == true ? ' (required)' : '')),
                  subtitle: Text('${(p['texts'] as Map?)?['en'] ?? ''}'),
                ),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(width: double.infinity, child: FilledButton(onPressed: _busy ? null : _save, child: const Text('Save choices'))),
          ),
        ]),
      );
}

class PrivacyScreen extends ConsumerWidget {
  const PrivacyScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final banner = ref.watch(consentBannerProvider);
    final dsrs = ref.watch(myDsrsProvider);
    final dio = ref.read(dioProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Privacy')),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: const Text('Data request'),
        onPressed: () async {
          final type = await showDialog<String>(
            context: context,
            builder: (ctx) => SimpleDialog(title: const Text('Request type'), children: [
              for (final t in const ['access', 'export', 'correction', 'erasure'])
                SimpleDialogOption(onPressed: () => Navigator.pop(ctx, t), child: Text(t)),
            ]),
          );
          if (type == null) return;
          await dio.post<void>('/data-subject-requests', data: {'request_type': type});
          ref.invalidate(myDsrsProvider);
        },
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(consentBannerProvider);
          ref.invalidate(myDsrsProvider);
        },
        child: ListView(children: [
          const ListTile(title: Text('Consents', style: TextStyle(fontWeight: FontWeight.bold))),
          ...banner.when(
            loading: () => [const LinearProgressIndicator()],
            error: (e, _) => [ListTile(title: Text('$e'))],
            data: (b) => b == null
                ? [const ListTile(title: Text('Not available'))]
                : [
                    for (final p in ((b['purposes'] as List?) ?? const []).cast<Map>())
                      SwitchListTile(
                        value: p['mandatory'] == true || (b['current'] as Map?)?['${p['key']}'] == true,
                        onChanged: p['mandatory'] == true || b['is_minor'] == true
                            ? null
                            : (v) async {
                                await dio.post<void>('/consents/bulk', data: {'grants': {'${p['key']}': v}, 'notice_version': b['notice_version']});
                                ref.invalidate(consentBannerProvider);
                              },
                        title: Text(_label('${p['key']}')),
                        subtitle: Text('${(p['texts'] as Map?)?['en'] ?? ''}'),
                      ),
                  ],
          ),
          const Divider(),
          const ListTile(title: Text('My data requests', style: TextStyle(fontWeight: FontWeight.bold))),
          ...dsrs.when(
            loading: () => [const LinearProgressIndicator()],
            error: (e, _) => [ListTile(title: Text('$e'))],
            data: (list) => [
              for (final r in list)
                ListTile(
                  title: Text('${r['request_type']} · ${r['status']}'),
                  subtitle: Text('Due ${r['due_at'] ?? '—'}'),
                  trailing: r['identity_verified'] == true || const ['completed', 'rejected'].contains(r['status'])
                      ? null
                      : TextButton(
                          onPressed: () async {
                            final ctrl = TextEditingController();
                            final otp = await showDialog<String>(
                              context: context,
                              builder: (ctx) => AlertDialog(
                                title: const Text('Verification code'),
                                content: TextField(controller: ctrl, keyboardType: TextInputType.number),
                                actions: [TextButton(onPressed: () => Navigator.pop(ctx, ctrl.text), child: const Text('Verify'))],
                              ),
                            );
                            if (otp == null || otp.isEmpty) return;
                            await dio.post<void>('/data-subject-requests/${r['id']}/identity', data: {'method': 'otp', 'otp': otp});
                            ref.invalidate(myDsrsProvider);
                          },
                          child: const Text('Verify'),
                        ),
                ),
            ],
          ),
        ]),
      ),
    );
  }
}
