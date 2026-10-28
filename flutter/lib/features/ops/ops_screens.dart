import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/config/env.dart';
import '../../core/providers.dart';

/// Phase 44 mobile (Prompts/44 §44.10): super admin / support — ops overview card (version, queues, alerts, backup age)
/// and the incident list with update / resolve (support agents read; the API refuses their writes).
final opsOverviewProvider = FutureProvider.autoDispose<Map<String, dynamic>>((ref) async {
  final r = await ref.watch(dioProvider).get<Map<String, dynamic>>('/platform/ops/overview');
  return ((r.data?['data'] as Map?) ?? const {}).cast<String, dynamic>();
});

final opsIncidentsProvider = FutureProvider.autoDispose<List<Map<String, dynamic>>>((ref) async {
  final r = await ref.watch(dioProvider).get<Map<String, dynamic>>('/platform/ops/incidents');
  return ((r.data?['data'] as List?) ?? const []).cast<Map<dynamic, dynamic>>().map((e) => e.cast<String, dynamic>()).toList();
});

class OpsScreen extends ConsumerWidget {
  const OpsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final overview = ref.watch(opsOverviewProvider);
    final incidents = ref.watch(opsIncidentsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Operations'), actions: [
        IconButton(
          tooltip: 'Status page',
          icon: const Icon(Icons.open_in_new),
          onPressed: () => launchUrl(Uri.parse(Env.apiUrl.replaceFirst('/api/v1', '/status')), mode: LaunchMode.externalApplication),
        ),
      ]),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(opsOverviewProvider);
          ref.invalidate(opsIncidentsProvider);
        },
        child: ListView(padding: const EdgeInsets.all(12), children: [
          overview.when(
            loading: () => const LinearProgressIndicator(),
            error: (e, _) => Text('$e'),
            data: (o) {
              final queues = ((o['queues'] as List?) ?? const []).cast<Map<dynamic, dynamic>>();
              final alerts = ((o['alerts_active'] as List?) ?? const []).length;
              final backup = (o['backups'] as Map?)?['age_min'];
              return Card(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('${o['env']} · ${o['version']} · head ${(o['migrations'] as Map?)?['head']}',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 8),
                    Text('Active alerts: $alerts · backup age: ${backup ?? 'none'} min'),
                    Text('Outbox lag: ${(o['outbox'] as Map?)?['lag_s']} s'),
                    const SizedBox(height: 8),
                    Wrap(spacing: 6, runSpacing: 6, children: [
                      for (final q in queues)
                        Chip(
                          avatar: Icon(q['worker_alive'] == true ? Icons.check_circle : Icons.error_outline, size: 16),
                          label: Text('${q['name']} ${q['depth']}'),
                        ),
                    ]),
                  ]),
                ),
              );
            },
          ),
          const SizedBox(height: 12),
          Text('Incidents', style: Theme.of(context).textTheme.titleMedium),
          ...incidents.when(
            loading: () => [const LinearProgressIndicator()],
            error: (e, _) => [Text('$e')],
            data: (list) => [
              for (final i in list)
                ListTile(
                  leading: Icon(i['state'] == 'resolved' ? Icons.check_circle : Icons.warning_amber),
                  title: Text('${i['title']}'),
                  subtitle: Text('${i['state']} · ${((i['updates'] as List?) ?? const []).length} update(s)'),
                  trailing: i['state'] == 'resolved'
                      ? null
                      : TextButton(
                          onPressed: () async {
                            try {
                              await ref.read(dioProvider).post<void>('/platform/ops/incidents/${i['id']}/resolve',
                                  data: {'state': 'resolved', 'message': 'Resolved from the mobile app'});
                              ref.invalidate(opsIncidentsProvider);
                            } catch (e) {
                              if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
                            }
                          },
                          child: const Text('Resolve'),
                        ),
                ),
            ],
          ),
        ]),
      ),
    );
  }
}
