import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 41 mobile (Prompts/41 §41.10): read-only integration health for the institution admin — capability, provider,
/// status and last error, with a "test" action per connection. Configuration stays on the web.
final integrationsHealthProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final r = await ref.watch(dioProvider).get<Map<String, dynamic>>('/integrations/capabilities');
  return ((r.data?['data'] as List?) ?? const []).cast<Map<dynamic, dynamic>>().map((e) => e.cast<String, dynamic>()).toList();
});

class IntegrationsHealthScreen extends ConsumerWidget {
  const IntegrationsHealthScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final caps = ref.watch(integrationsHealthProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Integrations')),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(integrationsHealthProvider),
        child: caps.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text('$e'))]),
          data: (list) => ListView.separated(
            itemCount: list.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (context, i) {
              final c = list[i];
              final ok = c['status'] == 'active';
              final id = c['connection_id'] as String?;
              return ListTile(
                leading: Icon(ok ? Icons.check_circle : Icons.error_outline, color: ok ? Colors.green : Colors.orange),
                title: Text('${c['name']}'),
                subtitle: Text([c['provider'] ?? 'not connected', if (c['last_error'] != null) '${c['last_error']}'].join(' · ')),
                trailing: id == null
                    ? null
                    : TextButton(
                        onPressed: () async {
                          final messenger = ScaffoldMessenger.of(context);
                          try {
                            final r = await ref.read(dioProvider).post<Map<String, dynamic>>('/integrations/connections/$id/test', data: {'action': 'ping'});
                            final d = (r.data?['data'] as Map?) ?? const {};
                            messenger.showSnackBar(SnackBar(content: Text('${d['detail']} · ${d['latency_ms']} ms')));
                          } catch (e) {
                            messenger.showSnackBar(SnackBar(content: Text('$e')));
                          }
                          ref.invalidate(integrationsHealthProvider);
                        },
                        child: const Text('Test'),
                      ),
              );
            },
          ),
        ),
      ),
    );
  }
}
