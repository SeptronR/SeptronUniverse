import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 39 parity (Prompts/39 §39.10; the full app is Phase 42): the notification centre on `/notifications/*`
/// (category chips with unread counts, mark read / all, snooze 24 h, deep links), the category × channel preference
/// matrix with policy-locked cells, quiet hours and digest, and `/portal/config` for tab labels / features.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class PortalRepository {
  PortalRepository(this._dio);

  final Dio _dio;

  Future<Map<String, dynamic>> _obj(String path, [Map<String, dynamic>? q]) async {
    final r = await _dio.get<Map<String, dynamic>>(path, queryParameters: q);
    return ((r.data?['data'] as Map?) ?? const {}).cast<String, dynamic>();
  }

  Future<Map<String, dynamic>> config() => _obj('/portal/config');
  Future<Map<String, dynamic>> counts() => _obj('/notifications/counts');
  Future<Map<String, dynamic>> preferences() => _obj('/notifications/preferences');

  Future<List<Map<String, dynamic>>> notifications(String? category) async {
    final r = await _dio.get<Map<String, dynamic>>('/notifications',
        queryParameters: {if (category != null) 'category': category, 'page_size': 50});
    return ((r.data?['data'] as List?) ?? const []).cast<Map>().map((e) => e.cast<String, dynamic>()).toList();
  }

  Future<Map<String, dynamic>> open(String id) => _obj('/notifications/$id');
  Future<void> markAll(String? category) =>
      _dio.post<void>('/notifications/mark-read', data: {'all': true, if (category != null) 'category': category});
  Future<void> snooze(String category, int hours) =>
      _dio.post<void>('/notifications/snooze', data: {'category': category, 'hours': hours});
  Future<void> savePreferences(Map<String, dynamic> body) => _dio.put<void>('/notifications/preferences', data: body);
}

final portalRepositoryProvider = Provider<PortalRepository>((ref) => PortalRepository(ref.watch(dioProvider)));
final portalConfigProvider = FutureProvider<Map<String, dynamic>>((ref) => ref.watch(portalRepositoryProvider).config());

class NotificationCentreScreen extends ConsumerStatefulWidget {
  const NotificationCentreScreen({super.key});

  @override
  ConsumerState<NotificationCentreScreen> createState() => _NotificationCentreScreenState();
}

class _NotificationCentreScreenState extends ConsumerState<NotificationCentreScreen> {
  String? _category;
  int _tick = 0;

  Future<void> _run(Future<void> Function() fn) async {
    try {
      await fn();
      setState(() => _tick++);
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.watch(portalRepositoryProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: [
          IconButton(
              tooltip: 'Mark all read', icon: const Icon(Icons.done_all), onPressed: () => _run(() => repo.markAll(_category))),
          if (_category != null)
            IconButton(
                tooltip: 'Snooze 24 h',
                icon: const Icon(Icons.notifications_paused_outlined),
                onPressed: () => _run(() => repo.snooze(_category!, 24))),
          IconButton(
              tooltip: 'Settings',
              icon: const Icon(Icons.tune),
              onPressed: () => Navigator.of(context)
                  .push(MaterialPageRoute<void>(builder: (_) => const NotificationPreferencesScreen()))),
        ],
      ),
      body: Column(children: [
        FutureBuilder<Map<String, dynamic>>(
          key: ValueKey('c$_tick'),
          future: repo.counts(),
          builder: (context, snap) {
            final by = ((snap.data?['unread_by_category'] as Map?) ?? const {}).cast<String, dynamic>();
            return SizedBox(
              height: 48,
              child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.all(6), children: [
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                      label: Text('All (${snap.data?['unread'] ?? 0})'),
                      selected: _category == null,
                      onSelected: (_) => setState(() => _category = null)),
                ),
                for (final e in by.entries)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ChoiceChip(
                        label: Text('${e.key} (${e.value})'),
                        selected: _category == e.key,
                        onSelected: (_) => setState(() => _category = e.key)),
                  ),
              ]),
            );
          },
        ),
        Expanded(
          child: FutureBuilder<List<Map<String, dynamic>>>(
            key: ValueKey('l$_tick$_category'),
            future: repo.notifications(_category),
            builder: (context, snap) {
              if (snap.hasError) return Center(child: Text(_error(snap.error!)));
              if (!snap.hasData) return const Center(child: CircularProgressIndicator());
              final rows = snap.data!;
              if (rows.isEmpty) return const Center(child: Text('Nothing here yet.'));
              return ListView.separated(
                itemCount: rows.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (_, i) {
                  final n = rows[i];
                  final read = n['is_read'] == true;
                  return ListTile(
                    title: Text('${n['title']}', style: TextStyle(fontWeight: read ? FontWeight.normal : FontWeight.w600)),
                    subtitle: Text('${n['category'] ?? 'system'} · ${n['created_at'] ?? ''}'),
                    onTap: () => _run(() async {
                      await repo.open('${n['id']}');
                    }),
                  );
                },
              );
            },
          ),
        ),
      ]),
    );
  }
}

class NotificationPreferencesScreen extends ConsumerStatefulWidget {
  const NotificationPreferencesScreen({super.key});

  @override
  ConsumerState<NotificationPreferencesScreen> createState() => _NotificationPreferencesScreenState();
}

class _NotificationPreferencesScreenState extends ConsumerState<NotificationPreferencesScreen> {
  int _tick = 0;

  Future<void> _save(Map<String, dynamic> body) async {
    try {
      await ref.read(portalRepositoryProvider).savePreferences(body);
      setState(() => _tick++);
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Notification settings')),
      body: FutureBuilder<Map<String, dynamic>>(
        key: ValueKey(_tick),
        future: ref.watch(portalRepositoryProvider).preferences(),
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final p = snap.data!;
          final cats = ((p['categories'] as List?) ?? const []).cast<Map>();
          final channels = ((p['available_channels'] as List?) ?? const []).cast<String>();
          return ListView(children: [
            ListTile(
              title: const Text('Digest'),
              trailing: DropdownButton<String>(
                value: '${p['digest'] ?? 'none'}',
                items: const ['none', 'daily', 'weekly']
                    .map((d) => DropdownMenuItem(value: d, child: Text(d)))
                    .toList(),
                onChanged: (v) => _save({'digest': v}),
              ),
            ),
            SwitchListTile(
              title: const Text('Quiet hours 22:00–07:00'),
              value: p['quiet_hours'] != null,
              onChanged: (on) => _save(on
                  ? {
                      'quiet_hours': {'from': '22:00', 'to': '07:00'}
                    }
                  : {'clear_quiet_hours': true}),
            ),
            const Divider(),
            for (final c in cats)
              ExpansionTile(
                title: Text('${c['category']}'),
                children: [
                  for (final ch in channels)
                    CheckboxListTile(
                      dense: true,
                      title: Text(ch),
                      value: ((c['channels'] as List?) ?? const []).contains(ch),
                      onChanged: ((c['locked'] as List?) ?? const []).contains(ch)
                          ? null
                          : (on) {
                              final current = ((c['channels'] as List?) ?? const []).cast<String>().toList();
                              on == true ? current.add(ch) : current.remove(ch);
                              _save({
                                'categories': [
                                  {'category': c['category'], 'channels': current}
                                ]
                              });
                            },
                    ),
                ],
              ),
          ]);
        },
      ),
    );
  }
}
