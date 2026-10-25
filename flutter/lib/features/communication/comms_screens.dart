import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 24 mobile (Prompts/24 §24.10): communication officer **Campaigns** (status, progress, pause / resume / retry —
/// no builder; that stays on the web), **Emergency broadcast** (typed `BROADCAST` confirmation; security officer),
/// every role's **Assistant** chat (opt-in gate first) and **My messages** (all channels).
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class CommsRepository {
  CommsRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<List<Map<String, dynamic>>> campaigns([String? status]) async =>
      _list(await _get('/comms/campaigns', {if (status != null) 'status': status}));
  Future<Map<String, dynamic>> report(String id) async => ((await _get('/comms/campaigns/$id/report')) as Map).cast<String, dynamic>();
  Future<void> action(String id, String action) => _post('/comms/campaigns/$id/action', {'action': action});
  Future<List<Map<String, dynamic>>> emergencyLog() async => _list(await _get('/comms/emergency/log'));
  Future<void> broadcast(Map<String, dynamic> body) => _post('/comms/emergency/broadcast', body);
  Future<void> allClear(String id, String message) => _post('/comms/emergency/$id/all-clear', {'message': message});
  Future<Map<String, dynamic>> assistantMe() async => ((await _get('/assistant/me')) as Map).cast<String, dynamic>();
  Future<void> optIn() => _post('/assistant/opt-in', {'accepted': true});
  Future<Map<String, dynamic>> chat(String? conversationId, String message) async =>
      ((await _post('/assistant/chat', {'conversation_id': conversationId, 'message': message})) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> myMessages([String? channel]) async =>
      _list(await _get('/comms/me/messages', {if (channel != null) 'channel': channel}));
}

final commsRepositoryProvider = Provider<CommsRepository>((ref) => CommsRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

String _when(dynamic iso) {
  final d = DateTime.tryParse('${iso ?? ''}')?.toLocal();
  if (d == null) return '';
  return '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')} '
      '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

// ---- campaigns (communication officer) ---------------------------------------------------------------------------------------
class CampaignsScreen extends ConsumerStatefulWidget {
  const CampaignsScreen({super.key});

  @override
  ConsumerState<CampaignsScreen> createState() => _CampaignsScreenState();
}

class _CampaignsScreenState extends ConsumerState<CampaignsScreen> {
  String? _status;
  late Future<List<Map<String, dynamic>>> _f = ref.read(commsRepositoryProvider).campaigns();

  void _reload() => setState(() => _f = ref.read(commsRepositoryProvider).campaigns(_status));

  Future<void> _act(Map<String, dynamic> c, String action) async {
    try {
      await ref.read(commsRepositoryProvider).action('${c['id']}', action);
      if (mounted) _snack(context, '${c['name']}: $action');
      _reload();
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  Future<void> _report(Map<String, dynamic> c) async {
    try {
      final r = await ref.read(commsRepositoryProvider).report('${c['id']}');
      if (!mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        builder: (_) => ListView(padding: const EdgeInsets.all(16), shrinkWrap: true, children: [
          Text('${c['name']}', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 8),
          for (final k in ['sent', 'delivered', 'read', 'failed', 'queued', 'deferred']) ListTile(dense: true, title: Text(k), trailing: Text('${r[k] ?? 0}')),
        ]),
      );
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  List<String> _actionsFor(String status) => switch (status) {
        'sending' => ['pause'],
        'paused' => ['resume', 'cancel'],
        'sent' || 'failed' => ['retry_failed'],
        'scheduled' || 'approved' => ['cancel'],
        _ => const [],
      };

  @override
  Widget build(BuildContext context) {
    const statuses = ['draft', 'pending_approval', 'approved', 'scheduled', 'sending', 'paused', 'sent', 'failed'];
    return Scaffold(
      appBar: AppBar(title: const Text('Campaigns')),
      body: Column(children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Row(children: [
            for (final s in [null, ...statuses])
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text(s ?? 'all'),
                  selected: _status == s,
                  onSelected: (_) {
                    _status = s;
                    _reload();
                  },
                ),
              ),
          ]),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async => _reload(),
            child: FutureBuilder<List<Map<String, dynamic>>>(
              future: _f,
              builder: (context, snap) {
                if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
                if (!snap.hasData) return const Center(child: CircularProgressIndicator());
                final rows = snap.data!;
                if (rows.isEmpty) return ListView(children: const [Padding(padding: EdgeInsets.all(16), child: Text('No campaigns'))]);
                return ListView.builder(
                  itemCount: rows.length,
                  itemBuilder: (_, i) {
                    final c = rows[i];
                    final total = (c['total_recipients'] as num?) ?? 0;
                    final sent = (c['sent_count'] as num?) ?? 0;
                    final status = '${c['status']}';
                    return Card(
                      child: Padding(
                        padding: const EdgeInsets.all(12),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Row(children: [
                            if (c['is_emergency'] == true) const Icon(Icons.warning_amber, color: Colors.red, size: 18),
                            Expanded(child: Text('${c['name']}', style: Theme.of(context).textTheme.titleSmall)),
                            Chip(label: Text(status), visualDensity: VisualDensity.compact),
                          ]),
                          Text('${(c['channels'] as List?)?.join(', ') ?? ''} · ${_when(c['scheduled_at'] ?? c['created_at'])}'),
                          if (total > 0) ...[
                            const SizedBox(height: 6),
                            LinearProgressIndicator(value: (sent / total).clamp(0, 1).toDouble()),
                            Text('$sent / $total sent · ${c['failed_count'] ?? 0} failed'),
                          ],
                          Wrap(spacing: 8, children: [
                            TextButton(onPressed: () => _report(c), child: const Text('Report')),
                            for (final a in _actionsFor(status)) TextButton(onPressed: () => _act(c, a), child: Text(a.replaceAll('_', ' '))),
                          ]),
                        ]),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ),
      ]),
    );
  }
}

// ---- emergency broadcast (security officer) -----------------------------------------------------------------------------------
class EmergencyBroadcastScreen extends ConsumerStatefulWidget {
  const EmergencyBroadcastScreen({super.key});

  @override
  ConsumerState<EmergencyBroadcastScreen> createState() => _EmergencyBroadcastScreenState();
}

class _EmergencyBroadcastScreenState extends ConsumerState<EmergencyBroadcastScreen> {
  final _message = TextEditingController();
  final _confirm = TextEditingController();
  String _type = 'security';
  bool _drill = false;
  bool _busy = false;
  late Future<List<Map<String, dynamic>>> _log = ref.read(commsRepositoryProvider).emergencyLog();

  Future<void> _send() async {
    if (_confirm.text.trim() != 'BROADCAST') {
      _snack(context, 'Type BROADCAST to confirm');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(commsRepositoryProvider).broadcast({
        'alert_type': _type,
        'message': _message.text.trim(),
        'audience': 'all',
        'drill': _drill,
        'confirm': _confirm.text.trim(),
      });
      _message.clear();
      _confirm.clear();
      if (mounted) _snack(context, 'Broadcast sent');
      setState(() => _log = ref.read(commsRepositoryProvider).emergencyLog());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _allClear(Map<String, dynamic> row) async {
    final c = TextEditingController(text: 'All clear. Normal activity may resume.');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('All clear'),
        content: TextField(controller: c, maxLines: 3),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Send'))],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(commsRepositoryProvider).allClear('${row['campaign_id'] ?? row['id']}', c.text);
      setState(() => _log = ref.read(commsRepositoryProvider).emergencyLog());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Emergency broadcast')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        DropdownButtonFormField<String>(
          value: _type,
          decoration: const InputDecoration(labelText: 'Alert type'),
          items: [for (final t in ['security', 'fire', 'medical', 'weather', 'sos', 'other']) DropdownMenuItem(value: t, child: Text(t))],
          onChanged: (v) => setState(() => _type = v ?? 'security'),
        ),
        TextField(controller: _message, maxLines: 4, decoration: const InputDecoration(labelText: 'Message (all channels, quiet hours ignored)')),
        SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Drill (marked [DRILL])'), value: _drill, onChanged: (v) => setState(() => _drill = v)),
        TextField(controller: _confirm, decoration: const InputDecoration(labelText: 'Type BROADCAST to confirm')),
        const SizedBox(height: 12),
        FilledButton.icon(
          style: FilledButton.styleFrom(backgroundColor: Colors.red),
          icon: const Icon(Icons.campaign),
          label: const Text('Send to everyone'),
          onPressed: _busy ? null : _send,
        ),
        const Divider(height: 32),
        Text('Incident log', style: Theme.of(context).textTheme.titleMedium),
        FutureBuilder<List<Map<String, dynamic>>>(
          future: _log,
          builder: (context, snap) {
            if (snap.hasError) return Text(_error(snap.error!));
            if (!snap.hasData) return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
            return Column(children: [
              for (final r in snap.data!)
                ListTile(
                  leading: const Icon(Icons.warning_amber, color: Colors.red),
                  title: Text('${r['message'] ?? r['name'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis),
                  subtitle: Text('${r['alert_type'] ?? ''} · ${_when(r['at'])}${r['all_clear_at'] != null ? ' · all clear' : ''}'),
                  trailing: r['all_clear_at'] == null ? TextButton(onPressed: () => _allClear(r), child: const Text('All clear')) : null,
                ),
            ]);
          },
        ),
      ]),
    );
  }
}

// ---- assistant (all roles, opt-in) --------------------------------------------------------------------------------------------
class AssistantScreen extends ConsumerStatefulWidget {
  const AssistantScreen({super.key});

  @override
  ConsumerState<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends ConsumerState<AssistantScreen> {
  late Future<Map<String, dynamic>> _me = ref.read(commsRepositoryProvider).assistantMe();
  final _input = TextEditingController();
  final List<Map<String, dynamic>> _turns = [];
  String? _conversationId;
  bool _busy = false;

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    setState(() {
      _turns.add({'role': 'user', 'text': text});
      _busy = true;
    });
    _input.clear();
    try {
      final r = await ref.read(commsRepositoryProvider).chat(_conversationId, text);
      _conversationId = '${r['conversation_id']}';
      setState(() => _turns.add({'role': 'assistant', 'text': r['reply'], 'citations': r['citations'], 'links': r['links']}));
    } catch (e) {
      setState(() => _turns.add({'role': 'error', 'text': _error(e)}));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _optIn() => Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.smart_toy_outlined, size: 48),
          const SizedBox(height: 12),
          const Text('The assistant answers from your own records (attendance, dues, timetable, results) with read-only tools. '
              'Your questions are logged for audit. It never makes changes for you.'),
          const SizedBox(height: 16),
          FilledButton(
            onPressed: () async {
              try {
                await ref.read(commsRepositoryProvider).optIn();
                setState(() => _me = ref.read(commsRepositoryProvider).assistantMe());
              } catch (e) {
                if (mounted) _snack(context, _error(e));
              }
            },
            child: const Text('I agree — turn on'),
          ),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Assistant')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _me,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final me = snap.data!;
          if (me['enabled'] != true || me['allowed'] != true) {
            return const Padding(padding: EdgeInsets.all(16), child: Text('The assistant is not available for your account.'));
          }
          if (me['opted_in'] != true) return _optIn();
          return Column(children: [
            Expanded(
              child: ListView.builder(
                padding: const EdgeInsets.all(12),
                itemCount: _turns.length,
                itemBuilder: (_, i) {
                  final t = _turns[i];
                  final mine = t['role'] == 'user';
                  final cites = ((t['citations'] as List?) ?? const []).cast<dynamic>();
                  final links = ((t['links'] as List?) ?? const []).cast<dynamic>();
                  return Align(
                    alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
                    child: Card(
                      color: mine ? Theme.of(context).colorScheme.primaryContainer : (t['role'] == 'error' ? Colors.red.shade50 : null),
                      child: Padding(
                        padding: const EdgeInsets.all(10),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text('${t['text']}'),
                          if (cites.isNotEmpty) Text('Sources: ${cites.join(', ')}', style: Theme.of(context).textTheme.bodySmall),
                          for (final l in links) Text('→ ${(l as Map)['label'] ?? l['url']}', style: Theme.of(context).textTheme.bodySmall),
                        ]),
                      ),
                    ),
                  );
                },
              ),
            ),
            if (_busy) const LinearProgressIndicator(),
            SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: Row(children: [
                  Expanded(child: TextField(controller: _input, onSubmitted: (_) => _send(), decoration: const InputDecoration(hintText: 'Ask about your attendance, dues, timetable…'))),
                  IconButton(icon: const Icon(Icons.send), onPressed: _busy ? null : _send),
                ]),
              ),
            ),
          ]);
        },
      ),
    );
  }
}

// ---- my messages (all roles) -------------------------------------------------------------------------------------------------
class MyMessagesScreen extends ConsumerStatefulWidget {
  const MyMessagesScreen({super.key});

  @override
  ConsumerState<MyMessagesScreen> createState() => _MyMessagesScreenState();
}

class _MyMessagesScreenState extends ConsumerState<MyMessagesScreen> {
  String? _channel;
  late Future<List<Map<String, dynamic>>> _f = ref.read(commsRepositoryProvider).myMessages();

  static const _icons = {'sms': Icons.sms_outlined, 'email': Icons.email_outlined, 'whatsapp': Icons.chat_outlined, 'push': Icons.notifications_outlined, 'in_app': Icons.inbox_outlined};

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My messages')),
      body: Column(children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Row(children: [
            for (final c in [null, ..._icons.keys])
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text(c ?? 'all'),
                  selected: _channel == c,
                  onSelected: (_) => setState(() {
                    _channel = c;
                    _f = ref.read(commsRepositoryProvider).myMessages(c);
                  }),
                ),
              ),
          ]),
        ),
        Expanded(
          child: RefreshIndicator(
            onRefresh: () async => setState(() => _f = ref.read(commsRepositoryProvider).myMessages(_channel)),
            child: FutureBuilder<List<Map<String, dynamic>>>(
              future: _f,
              builder: (context, snap) {
                if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
                if (!snap.hasData) return const Center(child: CircularProgressIndicator());
                final rows = snap.data!;
                if (rows.isEmpty) return ListView(children: const [Padding(padding: EdgeInsets.all(16), child: Text('No messages'))]);
                return ListView.separated(
                  itemCount: rows.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (_, i) {
                    final m = rows[i];
                    return ListTile(
                      leading: Icon(_icons[m['channel']] ?? Icons.message_outlined),
                      title: Text('${m['subject'] ?? m['event_type'] ?? m['channel']}'),
                      subtitle: Text('${m['body_preview'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis),
                      trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                        Text(_when(m['created_at']), style: Theme.of(context).textTheme.bodySmall),
                        Text('${m['status']}', style: Theme.of(context).textTheme.bodySmall),
                      ]),
                    );
                  },
                );
              },
            ),
          ),
        ),
      ]),
    );
  }
}
