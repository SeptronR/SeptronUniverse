import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 38 mobile (Prompts/38 §38.10), read-mostly. Super admin / support agent: **Platform** hub — institutions
/// (status chips), health (retry), support tickets (reply), announcements. Institution admin (More): **Support**
/// (raise / reply) and **Billing** (subscription status, invoices, usage). Banners and the suspended screen come
/// from `/auth/me` `banners` and the 403 `INSTITUTION_SUSPENDED` answer; masking and permissions are the API's.
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

class SaasRepository {
  SaasRepository(this._dio);

  final Dio _dio;

  Future<List<Map<String, dynamic>>> _get(String path, [Map<String, dynamic>? q]) async {
    final r = await _dio.get<Map<String, dynamic>>(path, queryParameters: q);
    return _list(r.data?['data']);
  }

  Future<List<Map<String, dynamic>>> institutions() => _get('/platform/institutions');
  Future<List<Map<String, dynamic>>> health() => _get('/platform/health');
  Future<List<Map<String, dynamic>>> announcements() => _get('/platform/announcements/active');
  Future<List<Map<String, dynamic>>> tickets() => _get('/support/tickets');
  Future<List<Map<String, dynamic>>> invoices() => _get('/billing/invoices');

  Future<Map<String, dynamic>> subscription() async {
    final r = await _dio.get<Map<String, dynamic>>('/billing/subscription');
    return ((r.data?['data'] as Map?) ?? const {}).cast<String, dynamic>();
  }

  Future<Map<String, dynamic>> ticket(String id) async {
    final r = await _dio.get<Map<String, dynamic>>('/support/tickets/$id');
    return ((r.data?['data'] as Map?) ?? const {}).cast<String, dynamic>();
  }

  Future<void> retry(String connectionId) =>
      _dio.post<void>('/platform/health/retry', data: {'connection_ids': [connectionId]});

  Future<void> reply(String id, String text) => _dio.post<void>('/support/tickets/$id/reply', data: {'text': text});

  Future<void> raise(String subject, String description, String priority, String category) =>
      _dio.post<void>('/support/tickets',
          data: {'subject': subject, 'description': description, 'priority': priority, 'category': category});
}

final saasRepositoryProvider = Provider<SaasRepository>((ref) => SaasRepository(ref.watch(dioProvider)));

Widget _async(Future<List<Map<String, dynamic>>> future, Widget Function(Map<String, dynamic>) tile) {
  return FutureBuilder<List<Map<String, dynamic>>>(
    future: future,
    builder: (context, snap) {
      if (snap.hasError) return Center(child: Text(_error(snap.error!)));
      if (!snap.hasData) return const Center(child: CircularProgressIndicator());
      final rows = snap.data!;
      if (rows.isEmpty) return const Center(child: Text('Nothing to show.'));
      return ListView.separated(
        itemCount: rows.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (_, i) => tile(rows[i]),
      );
    },
  );
}

Color _statusColor(String? s) => switch (s) {
      'active' || 'healthy' || 'paid' || 'resolved' || 'closed' => Colors.green,
      'suspended' || 'failed' || 'overdue' || 'expired' => Colors.red,
      'grace' || 'degraded' || 'waiting' || 'trial' => Colors.orange,
      _ => Colors.blueGrey,
    };

Widget _chip(String? s) => Chip(
      label: Text(s ?? '—', style: const TextStyle(fontSize: 11, color: Colors.white)),
      backgroundColor: _statusColor(s),
      visualDensity: VisualDensity.compact,
    );

/// Super admin / support agent hub.
class PlatformHubScreen extends ConsumerStatefulWidget {
  const PlatformHubScreen({super.key});

  @override
  ConsumerState<PlatformHubScreen> createState() => _PlatformHubScreenState();
}

class _PlatformHubScreenState extends ConsumerState<PlatformHubScreen> {
  int _tick = 0;

  @override
  Widget build(BuildContext context) {
    final repo = ref.watch(saasRepositoryProvider);
    return DefaultTabController(
      length: 4,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Platform'),
          bottom: const TabBar(isScrollable: true, tabs: [
            Tab(text: 'Institutions'),
            Tab(text: 'Health'),
            Tab(text: 'Support'),
            Tab(text: 'Announcements'),
          ]),
        ),
        body: TabBarView(key: ValueKey(_tick), children: [
          _async(
              repo.institutions(),
              (r) => ListTile(
                    title: Text('${r['name']}'),
                    subtitle: Text('${r['plan'] ?? '—'} · ${r['students_active']} students · health ${r['health']}'),
                    trailing: _chip(r['status'] as String?),
                  )),
          _async(
              repo.health(),
              (r) => ListTile(
                    title: Text('${(r['institution'] as Map?)?['name'] ?? ''} · ${r['provider']}'),
                    subtitle: Text('${r['capability']} · ${r['last_error'] ?? 'ok'}'),
                    trailing: IconButton(
                      icon: const Icon(Icons.refresh),
                      tooltip: 'Retry',
                      onPressed: () async {
                        try {
                          await repo.retry('${r['connection_id']}');
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Probe queued')));
                          }
                        } catch (e) {
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
                          }
                        }
                      },
                    ),
                    leading: _chip(r['status'] as String?),
                  )),
          _tickets(repo),
          _async(repo.announcements(),
              (r) => ListTile(title: Text('${r['title']}'), subtitle: Text('${r['body']}'))),
        ]),
        floatingActionButton: FloatingActionButton.small(
          onPressed: () => setState(() => _tick++),
          child: const Icon(Icons.refresh),
        ),
      ),
    );
  }

  Widget _tickets(SaasRepository repo) => _async(
      repo.tickets(),
      (r) => ListTile(
            title: Text('${r['ticket_number']} · ${r['subject']}'),
            subtitle: Text('${(r['institution'] as Map?)?['name'] ?? ''} · ${r['priority']}${r['breached'] == true ? ' · SLA breached' : ''}'),
            trailing: _chip(r['status'] as String?),
            onTap: () => Navigator.of(context)
                .push(MaterialPageRoute<void>(builder: (_) => TicketScreen(ticketId: '${r['id']}'))),
          ));
}

/// Ticket thread with a reply box (both sides).
class TicketScreen extends ConsumerStatefulWidget {
  const TicketScreen({super.key, required this.ticketId});

  final String ticketId;

  @override
  ConsumerState<TicketScreen> createState() => _TicketScreenState();
}

class _TicketScreenState extends ConsumerState<TicketScreen> {
  final _text = TextEditingController();
  late Future<Map<String, dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _future = ref.read(saasRepositoryProvider).ticket(widget.ticketId);
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final repo = ref.read(saasRepositoryProvider);
    try {
      await repo.reply(widget.ticketId, _text.text.trim());
      _text.clear();
      setState(() => _future = repo.ticket(widget.ticketId));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ticket')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final t = snap.data!;
          final messages = _list(t['messages']);
          return Column(children: [
            ListTile(title: Text('${t['ticket_number']} · ${t['subject']}'), subtitle: Text('${t['description'] ?? ''}')),
            Expanded(
              child: ListView(
                children: messages
                    .map((m) => ListTile(
                          dense: true,
                          tileColor: m['internal'] == true ? Colors.amber.withValues(alpha: 0.15) : null,
                          title: Text('${m['text']}'),
                          subtitle: Text('${(m['by'] as Map?)?['name'] ?? 'system'} · ${m['at']}'),
                        ))
                    .toList(),
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(8),
              child: Row(children: [
                Expanded(child: TextField(controller: _text, decoration: const InputDecoration(hintText: 'Reply…'))),
                IconButton(icon: const Icon(Icons.send), onPressed: _send),
              ]),
            ),
          ]);
        },
      ),
    );
  }
}

/// Institution admin: support tickets (raise / reply).
class TenantSupportScreen extends ConsumerStatefulWidget {
  const TenantSupportScreen({super.key});

  @override
  ConsumerState<TenantSupportScreen> createState() => _TenantSupportScreenState();
}

class _TenantSupportScreenState extends ConsumerState<TenantSupportScreen> {
  int _tick = 0;

  Future<void> _raise() async {
    final subject = TextEditingController();
    final description = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Raise a ticket'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(controller: subject, decoration: const InputDecoration(labelText: 'Subject')),
          TextField(controller: description, maxLines: 4, decoration: const InputDecoration(labelText: 'Description')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Raise')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(saasRepositoryProvider).raise(subject.text.trim(), description.text.trim(), 'normal', 'other');
      setState(() => _tick++);
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.watch(saasRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Support')),
      floatingActionButton: FloatingActionButton(onPressed: _raise, child: const Icon(Icons.add)),
      body: KeyedSubtree(
        key: ValueKey(_tick),
        child: _async(
            repo.tickets(),
            (r) => ListTile(
                  title: Text('${r['ticket_number']} · ${r['subject']}'),
                  subtitle: Text('${r['priority']}'),
                  trailing: _chip(r['status'] as String?),
                  onTap: () => Navigator.of(context)
                      .push(MaterialPageRoute<void>(builder: (_) => TicketScreen(ticketId: '${r['id']}'))),
                )),
      ),
    );
  }
}

/// Institution admin: subscription status, invoices, usage vs limits.
class TenantBillingScreen extends ConsumerWidget {
  const TenantBillingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.watch(saasRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Billing')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: repo.subscription(),
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final s = snap.data!;
          final plan = (s['plan'] as Map?) ?? const {};
          final usage = ((s['usage_vs_limits'] as Map?) ?? const {}).cast<String, dynamic>();
          final invoices = _list(s['invoices']);
          return ListView(children: [
            ListTile(
              title: Text('${plan['name'] ?? 'No plan'}'),
              subtitle: Text('Ends ${s['ends_on'] ?? '—'}${s['grace_until'] != null ? ' · grace until ${s['grace_until']}' : ''}'),
              trailing: _chip(s['status'] as String?),
            ),
            for (final k in ['students', 'staff', 'storage_gb', 'sms'])
              ListTile(
                dense: true,
                title: Text(k),
                trailing: Text('${(usage[k] as Map?)?['used'] ?? 0} / ${(usage[k] as Map?)?['limit'] ?? '∞'}'),
              ),
            const Divider(),
            for (final i in invoices)
              ListTile(
                title: Text('${i['number']}'),
                subtitle: Text('${i['period']} · due ${i['due_on']}'),
                trailing: _chip(i['status'] as String?),
              ),
          ]);
        },
      ),
    );
  }
}
