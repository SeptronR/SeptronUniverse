import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 37 mobile (Prompts/37 §37.10). Institution admin / registrar (More): **Audit** — read-only explorer list with
/// a row detail (masked diff), security **anomalies** (acknowledge with a note) and **effective settings** (read-only;
/// no settings editing on mobile). COE: **Exam audit** summary card per session (section counts, open gaps). Scope,
/// masking and decode visibility are the API's.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

List<Map<String, dynamic>> _list(dynamic data) {
  final items = data is Map ? (data['items'] ?? data['data']) : data;
  return ((items as List?) ?? const []).cast<Map>().map((e) => e.cast<String, dynamic>()).toList();
}

class AuditRepository {
  AuditRepository(this._dio);

  final Dio _dio;

  Future<List<Map<String, dynamic>>> rows({String? module}) async {
    final r = await _dio.get<Map<String, dynamic>>('/audit-logs', queryParameters: {
      'page_size': 50,
      if (module != null && module.isNotEmpty) 'module': module,
    });
    return _list(r.data?['data']);
  }

  Future<Map<String, dynamic>> detail(String id) async {
    final r = await _dio.get<Map<String, dynamic>>('/audit-logs/$id');
    return ((r.data?['data'] as Map?) ?? const {}).cast<String, dynamic>();
  }

  Future<List<Map<String, dynamic>>> anomalies() async {
    final r = await _dio.get<Map<String, dynamic>>('/security/anomalies', queryParameters: {'active': true});
    return _list(r.data?['data']);
  }

  Future<void> acknowledge(String id, String note) =>
      _dio.post<void>('/security/anomalies/$id/acknowledge', data: {'note': note});

  Future<List<Map<String, dynamic>>> effective() async {
    final r = await _dio.get<Map<String, dynamic>>('/settings/effective');
    return _list(r.data?['data']);
  }

  Future<List<Map<String, dynamic>>> sessions() async {
    final r = await _dio.get<Map<String, dynamic>>('/exam-sessions', queryParameters: {'size': 20});
    return _list(r.data?['data']);
  }

  Future<Map<String, dynamic>> examSummary(String id) async {
    final r = await _dio.get<Map<String, dynamic>>('/exams/$id/audit/summary');
    return ((r.data?['data'] as Map?) ?? const {}).cast<String, dynamic>();
  }
}

final auditRepositoryProvider = Provider<AuditRepository>((ref) => AuditRepository(ref.watch(dioProvider)));

class AuditHubScreen extends ConsumerWidget {
  const AuditHubScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Audit & security'),
          bottom: const TabBar(tabs: [Tab(text: 'Audit'), Tab(text: 'Anomalies'), Tab(text: 'Settings')]),
        ),
        body: const TabBarView(children: [_AuditList(), _Anomalies(), _EffectiveSettings()]),
      ),
    );
  }
}

class _AuditList extends ConsumerStatefulWidget {
  const _AuditList();

  @override
  ConsumerState<_AuditList> createState() => _AuditListState();
}

class _AuditListState extends ConsumerState<_AuditList> {
  String _module = '';
  late Future<List<Map<String, dynamic>>> _future = _load();

  Future<List<Map<String, dynamic>>> _load() => ref.read(auditRepositoryProvider).rows(module: _module);

  @override
  Widget build(BuildContext context) {
    return Column(children: [
      Padding(
        padding: const EdgeInsets.all(8),
        child: TextField(
          decoration: const InputDecoration(labelText: 'Module filter', prefixIcon: Icon(Icons.filter_alt_outlined)),
          onSubmitted: (v) => setState(() {
            _module = v.trim();
            _future = _load();
          }),
        ),
      ),
      Expanded(
        child: FutureBuilder<List<Map<String, dynamic>>>(
          future: _future,
          builder: (context, snap) {
            if (snap.hasError) return Center(child: Text(_error(snap.error!)));
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final rows = snap.data!;
            if (rows.isEmpty) return const Center(child: Text('No audit rows in the last 30 days'));
            return RefreshIndicator(
              onRefresh: () async => setState(() => _future = _load()),
              child: ListView.separated(
                itemCount: rows.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (_, i) {
                  final r = rows[i];
                  final user = (r['user'] as Map?)?['name'] ?? '—';
                  return ListTile(
                    dense: true,
                    title: Text('${r['summary']}'),
                    subtitle: Text('${r['module']}:${r['action']} · $user · ${r['occurred_at']}'),
                    trailing: r['impersonator'] != null ? const Icon(Icons.warning_amber, color: Colors.red) : null,
                    onTap: () => _detail(context, '${r['id']}'),
                  );
                },
              ),
            );
          },
        ),
      ),
    ]);
  }

  Future<void> _detail(BuildContext context, String id) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => FutureBuilder<Map<String, dynamic>>(
        future: ref.read(auditRepositoryProvider).detail(id),
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const SizedBox(height: 160, child: Center(child: CircularProgressIndicator()));
          final d = snap.data!;
          final diff = ((d['diff'] as List?) ?? const []).cast<Map>();
          return SafeArea(
            child: ListView(padding: const EdgeInsets.all(16), shrinkWrap: true, children: [
              Text('${d['module']}:${d['action']}', style: Theme.of(context).textTheme.titleMedium),
              Text('${d['summary']}'),
              const SizedBox(height: 8),
              for (final x in diff)
                ListTile(
                  dense: true,
                  title: Text('${x['field']}${x['masked'] == true ? ' (masked)' : ''}'),
                  subtitle: Text('${x['old'] ?? '—'} → ${x['new'] ?? '—'}'),
                ),
              if (diff.isEmpty) const Text('No field changes recorded'),
            ]),
          );
        },
      ),
    );
  }
}

class _Anomalies extends ConsumerStatefulWidget {
  const _Anomalies();

  @override
  ConsumerState<_Anomalies> createState() => _AnomaliesState();
}

class _AnomaliesState extends ConsumerState<_Anomalies> {
  late Future<List<Map<String, dynamic>>> _future = ref.read(auditRepositoryProvider).anomalies();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Map<String, dynamic>>>(
      future: _future,
      builder: (context, snap) {
        if (snap.hasError) return Center(child: Text(_error(snap.error!)));
        if (!snap.hasData) return const Center(child: CircularProgressIndicator());
        final rows = snap.data!;
        if (rows.isEmpty) return const Center(child: Text('No open anomaly alerts'));
        return ListView(children: [
          for (final a in rows)
            Card(
              child: ListTile(
                leading: const Icon(Icons.gpp_maybe_outlined, color: Colors.orange),
                title: Text('${a['rule']} · ${a['count']}'),
                subtitle: Text('first seen ${a['first_seen']}'),
                trailing: TextButton(onPressed: () => _ack(context, '${a['id']}'), child: const Text('Acknowledge')),
              ),
            ),
        ]);
      },
    );
  }

  Future<void> _ack(BuildContext context, String id) async {
    final ctrl = TextEditingController();
    final messenger = ScaffoldMessenger.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Acknowledge alert'),
        content: TextField(controller: ctrl, decoration: const InputDecoration(labelText: 'Note')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Acknowledge')),
        ],
      ),
    );
    if (ok != true || ctrl.text.trim().length < 2) return;
    try {
      await ref.read(auditRepositoryProvider).acknowledge(id, ctrl.text.trim());
      setState(() => _future = ref.read(auditRepositoryProvider).anomalies());
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }
}

class _EffectiveSettings extends ConsumerWidget {
  const _EffectiveSettings();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return FutureBuilder<List<Map<String, dynamic>>>(
      future: ref.read(auditRepositoryProvider).effective(),
      builder: (context, snap) {
        if (snap.hasError) return Center(child: Text(_error(snap.error!)));
        if (!snap.hasData) return const Center(child: CircularProgressIndicator());
        final rows = snap.data!;
        return ListView.builder(
          itemCount: rows.length,
          itemBuilder: (_, i) {
            final s = rows[i];
            return ListTile(
              dense: true,
              title: Text('${s['key']}'),
              subtitle: Text('${s['value'] ?? '—'}'),
              trailing: Chip(label: Text('${s['source']}'), visualDensity: VisualDensity.compact),
            );
          },
        );
      },
    );
  }
}

/// COE: one summary card per exam session (section counts, open gaps, days to publication).
class ExamAuditSummaryScreen extends ConsumerWidget {
  const ExamAuditSummaryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(auditRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Exam audit')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: repo.sessions(),
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          return ListView(children: [
            for (final s in snap.data!)
              FutureBuilder<Map<String, dynamic>>(
                future: repo.examSummary('${s['id']}'),
                builder: (context, sum) {
                  final d = sum.data;
                  final counts = ((d?['sections'] as Map?) ?? const {}).cast<String, dynamic>();
                  return Card(
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${s['name']}', style: Theme.of(context).textTheme.titleSmall),
                        if (sum.hasError) Text(_error(sum.error!)),
                        if (d != null)
                          Wrap(spacing: 6, runSpacing: 4, children: [
                            for (final e in counts.entries) Chip(label: Text('${e.key}: ${e.value}')),
                            Chip(
                              label: Text('gaps: ${d['open_gaps']}'),
                              backgroundColor: (d['open_gaps'] ?? 0) == 0 ? null : Colors.red.shade100,
                            ),
                          ]),
                      ]),
                    ),
                  );
                },
              ),
          ]);
        },
      ),
    );
  }
}
