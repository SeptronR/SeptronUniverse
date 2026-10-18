import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/offline/cache_repository.dart';
import '../../core/providers.dart';

/// Phase 10 mobile (Prompts/10 §10.10): **My timetable** (student / faculty — week or day, cached offline for 24 h),
/// **Today's sessions** (faculty home card → attendance in Phase 11) and **Substitutions** (faculty requests, HOD
/// approvals with an availability-aware substitute picker). Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) {
      return '${(data['error'] as Map)['message']}';
    }
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _hm(Object? t) => t == null ? '' : '$t'.substring(0, 5);

class TimetableRepository {
  TimetableRepository(this._dio, this._cache);

  final Dio _dio;
  final CacheRepository _cache;

  Options get _once => Options(headers: {
        'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()
      });

  /// ``/timetables/me`` with a 24 h offline fallback: the last good answer is served when the request fails.
  Future<({Map<String, dynamic> view, bool cached})> myWeek(String week) async {
    final key = 'timetable:me:$week';
    try {
      final res = await _dio.get<Map<String, dynamic>>('/timetables/me',
          queryParameters: {'week': week});
      final data = (res.data?['data'] as Map).cast<String, dynamic>();
      await _cache.write(key, jsonEncode(data), ttl: const Duration(hours: 24));
      return (view: data, cached: false);
    } catch (e) {
      final hit = await _cache.read(key);
      if (hit != null &&
          DateTime.now().difference(hit.fetchedAt).inSeconds < hit.ttlSeconds) {
        return (
          view: (jsonDecode(hit.json) as Map).cast<String, dynamic>(),
          cached: true
        );
      }
      rethrow;
    }
  }

  Future<List<Map<String, dynamic>>> _list(String path,
      [Map<String, dynamic>? q]) async {
    final res = await _dio.get<Map<String, dynamic>>(path, queryParameters: q);
    return ((res.data?['data'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> today() => _list('/class-sessions/today');
  Future<List<Map<String, dynamic>>> substitutions(String? status) =>
      _list('/substitutions', {if (status != null) 'status': status});
  Future<List<Map<String, dynamic>>> candidates(String id) =>
      _list('/substitutions/$id/candidates');
  Future<void> approve(String id, String staffId) => _dio.post(
      '/substitutions/$id/approve',
      data: {'substitute_staff_id': staffId},
      options: _once);
  Future<void> reject(String id) =>
      _dio.post('/substitutions/$id/reject', data: {}, options: _once);
  Future<void> request(String entryId, String date, String? reason) =>
      _dio.post('/substitutions',
          data: {'entry_id': entryId, 'on_date': date, 'reason': reason},
          options: _once);
}

final _cache = CacheRepository();
final timetableRepositoryProvider = Provider<TimetableRepository>(
    (ref) => TimetableRepository(ref.watch(dioProvider), _cache));

String _iso(DateTime d) => d.toIso8601String().substring(0, 10);

class MyTimetableScreen extends ConsumerStatefulWidget {
  const MyTimetableScreen({super.key});

  @override
  ConsumerState<MyTimetableScreen> createState() => _MyTimetableState();
}

class _MyTimetableState extends ConsumerState<MyTimetableScreen> {
  DateTime _week = DateTime.now();
  bool _dayView = true;
  int _day = DateTime.now().weekday;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Timetable'),
        actions: [
          IconButton(
              icon: Icon(_dayView ? Icons.view_week : Icons.view_day),
              tooltip: _dayView ? 'Week' : 'Day',
              onPressed: () => setState(() => _dayView = !_dayView)),
        ],
      ),
      body: FutureBuilder(
        future: ref.read(timetableRepositoryProvider).myWeek(_iso(_week)),
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final view = snap.data!.view;
          final days =
              ((view['days'] as List?) ?? const []).cast<Map<String, dynamic>>();
          final shown = _dayView
              ? days.where((d) => d['day_of_week'] == _day).toList()
              : days;
          return Column(children: [
            if (snap.data!.cached)
              const MaterialBanner(
                  content: Text('Offline — showing the cached week'),
                  actions: [SizedBox.shrink()]),
            Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              IconButton(
                  icon: const Icon(Icons.chevron_left),
                  onPressed: () => setState(() => _week =
                      _week.subtract(Duration(days: _dayView ? 1 : 7)))),
              Text(_dayView
                  ? '${['', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][_day]} · week ${view['iso_week']}'
                  : 'Week of ${view['week_start']}'),
              IconButton(
                  icon: const Icon(Icons.chevron_right),
                  onPressed: () => setState(() =>
                      _week = _week.add(Duration(days: _dayView ? 1 : 7)))),
            ]),
            Expanded(
              child: ListView(children: [
                for (final d in shown) ...[
                  if (!_dayView)
                    Padding(
                        padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                        child: Text('${d['label']} ${d['date'] ?? ''}',
                            style: Theme.of(context).textTheme.titleSmall)),
                  for (final s in ((d['slots'] as List?) ?? const [])
                      .cast<Map<String, dynamic>>())
                    for (final e in ((s['entries'] as List?) ?? const [])
                        .cast<Map<String, dynamic>>())
                      ListTile(
                        dense: true,
                        leading: Text(
                            '${_hm(s['start_time'])}\n${_hm(e['end_time'] ?? s['end_time'])}'),
                        title: Text('${e['course_code']} · ${e['course_title'] ?? ''}'),
                        subtitle: Text([e['staff_name'], e['room_code'], e['session_type']]
                            .where((x) => x != null)
                            .join(' · ')),
                      ),
                ],
              ]),
            ),
          ]);
        },
      ),
    );
  }

  @override
  void didUpdateWidget(covariant MyTimetableScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    _day = _week.weekday;
  }
}

/// Home card / screen: the faculty member's (or student's) sessions today.
class TodaySessionsScreen extends ConsumerWidget {
  const TodaySessionsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text("Today's sessions")),
      body: const TodaySessionsCard(),
    );
  }
}

class TodaySessionsCard extends ConsumerWidget {
  const TodaySessionsCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return FutureBuilder<List<Map<String, dynamic>>>(
      future: ref.read(timetableRepositoryProvider).today(),
      builder: (context, snap) {
        if (snap.hasError) return ListTile(title: Text(_error(snap.error!)));
        if (!snap.hasData) return const LinearProgressIndicator();
        final rows = snap.data!;
        if (rows.isEmpty) {
          return const ListTile(title: Text('No classes today.'));
        }
        return Column(children: [
          for (final s in rows)
            ListTile(
              leading: Text('${_hm(s['start_time'])}\n${_hm(s['end_time'])}'),
              title: Text('${s['course_code']} ${s['section_name'] ?? ''}'),
              subtitle: Text(
                  '${s['room_code'] ?? '—'} · ${s['status']} · attendance ${s['attendance_status']}'),
              trailing: s['substituted'] == true
                  ? const Chip(label: Text('sub'))
                  : null,
            ),
        ]);
      },
    );
  }
}

class SubstitutionsScreen extends ConsumerStatefulWidget {
  const SubstitutionsScreen({super.key});

  @override
  ConsumerState<SubstitutionsScreen> createState() => _SubstitutionsState();
}

class _SubstitutionsState extends ConsumerState<SubstitutionsScreen> {
  String? _status = 'requested';

  Future<void> _approve(Map<String, dynamic> s) async {
    final repo = ref.read(timetableRepositoryProvider);
    final cands = await repo.candidates('${s['id']}');
    if (!mounted) return;
    final pick = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => ListView(children: [
        for (final c in cands)
          ListTile(
            enabled: c['free'] == true,
            title: Text('${c['name']}'),
            subtitle: Text(c['free'] == true
                ? 'free${c['teaches_offering'] == true ? ' · teaches it' : ''}'
                : (c['on_leave'] == true ? 'on leave' : 'busy')),
            onTap: () => Navigator.pop(ctx, '${c['staff_id']}'),
          ),
      ]),
    );
    if (pick == null) return;
    try {
      await repo.approve('${s['id']}', pick);
      setState(() {});
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(_error(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(timetableRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Substitutions'), actions: [
        PopupMenuButton<String?>(
          onSelected: (v) => setState(() => _status = v),
          itemBuilder: (_) => const [
            PopupMenuItem(value: 'requested', child: Text('Requested')),
            PopupMenuItem(value: 'approved', child: Text('Approved')),
            PopupMenuItem(value: null, child: Text('All')),
          ],
        ),
      ]),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: repo.substitutions(_status),
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final rows = snap.data!;
          if (rows.isEmpty) return const Center(child: Text('Nothing here.'));
          return ListView.separated(
            itemCount: rows.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (_, i) {
              final s = rows[i];
              return ListTile(
                title: Text('${s['course_code']} · ${s['on_date']} ${s['slot_name'] ?? ''}'),
                subtitle: Text(
                    '${s['staff_name'] ?? ''} → ${s['substitute_name'] ?? '?'} · ${s['source'] == 'leave_auto' ? 'from leave' : 'manual'}'),
                trailing: s['status'] == 'requested'
                    ? Row(mainAxisSize: MainAxisSize.min, children: [
                        IconButton(
                            icon: const Icon(Icons.check),
                            onPressed: () => _approve(s)),
                        IconButton(
                            icon: const Icon(Icons.close),
                            onPressed: () async {
                              await repo.reject('${s['id']}');
                              setState(() {});
                            }),
                      ])
                    : Text('${s['status']}'),
              );
            },
          );
        },
      ),
    );
  }
}
