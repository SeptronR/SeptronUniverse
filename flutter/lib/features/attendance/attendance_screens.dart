import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/offline/cache_repository.dart';
import '../../core/providers.dart';

/// Phase 11 mobile (Prompts/11 §11.10): faculty **Attendance** (today's sessions → tap-mark grid with large targets,
/// all present, QR projector mode, finalize, offline queue synced through ``/attendance/offline-batch`` with
/// per-item conflict results), student / parent **Attendance** (per-course rings, shortfall calculator, QR check-in by
/// code, OD request) and HOD **Condonations** (recommend). Rules and visibility live in the API.
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

const _cycle = ['present', 'absent', 'late', 'on_duty', 'leave', 'medical', 'exempt'];
const _short = {
  'present': 'P',
  'absent': 'A',
  'late': 'L',
  'on_duty': 'OD',
  'leave': 'LV',
  'medical': 'M',
  'exempt': 'EX'
};
Color _markColor(String? m) => switch (m) {
      'present' => Colors.green.shade100,
      'late' => Colors.amber.shade100,
      'absent' => Colors.red.shade100,
      'on_duty' => Colors.blue.shade100,
      null => Colors.white,
      _ => Colors.grey.shade200,
    };
Color _bandColor(String band) => switch (band) {
      'eligible' => Colors.green,
      'condonable' => Colors.orange,
      'not_eligible' => Colors.red,
      _ => Colors.blue,
    };

class AttendanceRepository {
  AttendanceRepository(this._dio, this._cache);

  final Dio _dio;
  final CacheRepository _cache;
  static const _queueKey = 'attendance:offline-queue';

  Options get _once => Options(headers: {
        'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()
      });

  Future<Map<String, dynamic>> _get(String path, [Map<String, dynamic>? q]) async {
    final res = await _dio.get<Map<String, dynamic>>(path, queryParameters: q);
    return res.data ?? const {};
  }

  Future<List<Map<String, dynamic>>> today() async =>
      (((await _get('/class-sessions/today'))['data'] as List?) ?? const []).cast<Map<String, dynamic>>();
  Future<Map<String, dynamic>> sheet(String id) async =>
      ((await _get('/class-sessions/$id/attendance'))['data'] as Map).cast<String, dynamic>();
  Future<Map<String, dynamic>> mark(String id, Map<String, dynamic> body) async =>
      ((await _dio.post<Map<String, dynamic>>('/class-sessions/$id/attendance', data: body, options: _once)).data?['data']
              as Map)
          .cast<String, dynamic>();
  Future<void> finalize(String id) => _dio.post('/class-sessions/$id/finalize', data: {}, options: _once);
  Future<Map<String, dynamic>> issueQr(String id) async =>
      ((await _dio.post<Map<String, dynamic>>('/class-sessions/$id/qr', options: _once)).data?['data'] as Map)
          .cast<String, dynamic>();
  Future<Map<String, dynamic>> qrCheckin(String token) async =>
      ((await _dio.post<Map<String, dynamic>>('/attendance/qr-checkin', data: {'token': token}, options: _once))
              .data?['data'] as Map)
          .cast<String, dynamic>();
  Future<Map<String, dynamic>> mySummary(String? wardId) async =>
      ((await _get('/attendance/summary/me', {if (wardId != null) 'ward_id': wardId}))['data'] as Map)
          .cast<String, dynamic>();
  Future<void> applyOd(Map<String, dynamic> body) => _dio.post('/on-duty', data: body, options: _once);
  Future<List<Map<String, dynamic>>> condonations() async =>
      (((await _get('/condonations', {'status': 'requested'}))['data'] as List?) ?? const [])
          .cast<Map<String, dynamic>>();
  Future<void> recommend(String id) => _dio.post('/condonations/$id/recommend', data: {}, options: _once);

  // ---- offline queue ------------------------------------------------------------------------------------------------
  Future<List<Map<String, dynamic>>> queued() async {
    final hit = await _cache.read(_queueKey);
    return hit == null ? [] : (jsonDecode(hit.json) as List).cast<Map<String, dynamic>>();
  }

  Future<void> enqueue(String sessionId, Map<String, dynamic> body) async {
    final q = await queued();
    q.add({'client_id': '${DateTime.now().microsecondsSinceEpoch}', 'session_id': sessionId, ...body});
    await _cache.write(_queueKey, jsonEncode(q), ttl: const Duration(days: 7));
  }

  /// Sends the queue as one batch; returns the per-item results (conflicts such as RECORD_LOCKED stay visible).
  Future<List<Map<String, dynamic>>> sync() async {
    final q = await queued();
    if (q.isEmpty) return [];
    final res = await _dio.post<Map<String, dynamic>>('/attendance/offline-batch',
        data: {'idempotency_key': 'm-${q.first['client_id']}-${q.length}', 'items': q}, options: _once);
    await _cache.write(_queueKey, jsonEncode([]), ttl: const Duration(days: 7));
    return (((res.data?['data'] as Map?)?['items'] as List?) ?? const []).cast<Map<String, dynamic>>();
  }
}

final attendanceRepositoryProvider =
    Provider<AttendanceRepository>((ref) => AttendanceRepository(ref.watch(dioProvider), ref.watch(cacheRepositoryProvider)));

// ---- faculty -------------------------------------------------------------------------------------------------------------
class FacultyAttendanceScreen extends ConsumerStatefulWidget {
  const FacultyAttendanceScreen({super.key});

  @override
  ConsumerState<FacultyAttendanceScreen> createState() => _FacultyAttendanceState();
}

class _FacultyAttendanceState extends ConsumerState<FacultyAttendanceScreen> {
  int _pending = 0;

  @override
  void initState() {
    super.initState();
    ref.read(attendanceRepositoryProvider).queued().then((q) => mounted ? setState(() => _pending = q.length) : null);
  }

  Future<void> _sync() async {
    try {
      final results = await ref.read(attendanceRepositoryProvider).sync();
      if (!mounted) return;
      setState(() => _pending = 0);
      final conflicts = results.where((r) => r['ok'] != true).toList();
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          title: Text(conflicts.isEmpty ? 'Synced' : '${conflicts.length} conflict(s)'),
          content: Text(conflicts.isEmpty
              ? '${results.length} session(s) uploaded.'
              : conflicts.map((c) => '${c['code']}: ${c['message']}').join('\n')),
          actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
        ),
      );
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Attendance'), actions: [
        if (_pending > 0)
          TextButton.icon(onPressed: _sync, icon: const Icon(Icons.cloud_upload), label: Text('Sync $_pending')),
      ]),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: ref.read(attendanceRepositoryProvider).today(),
        builder: (context, snap) {
          if (snap.hasError) return ListTile(title: Text(_error(snap.error!)));
          if (!snap.hasData) return const LinearProgressIndicator();
          final rows = snap.data!.where((s) => s['status'] != 'cancelled').toList();
          if (rows.isEmpty) return const ListTile(title: Text('No classes today.'));
          return ListView(children: [
            for (final s in rows)
              Card(
                child: ListTile(
                  leading: Text('${_hm(s['start_time'])}\n${_hm(s['end_time'])}'),
                  title: Text('${s['course_code']} ${s['section_name'] ?? ''}'),
                  subtitle: Text('${s['room_code'] ?? '—'} · attendance ${s['attendance_status']}'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () async {
                    await Navigator.of(context).push(MaterialPageRoute<void>(
                        builder: (_) => MarkingScreen(sessionId: '${s['id']}', title: '${s['course_code']}')));
                    final q = await ref.read(attendanceRepositoryProvider).queued();
                    if (mounted) setState(() => _pending = q.length);
                  },
                ),
              ),
          ]);
        },
      ),
    );
  }
}

class MarkingScreen extends ConsumerStatefulWidget {
  const MarkingScreen({super.key, required this.sessionId, required this.title});
  final String sessionId;
  final String title;

  @override
  ConsumerState<MarkingScreen> createState() => _MarkingState();
}

class _MarkingState extends ConsumerState<MarkingScreen> {
  Map<String, dynamic>? _sheet;
  final Map<String, String> _marks = {};
  Object? _err;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final s = await ref.read(attendanceRepositoryProvider).sheet(widget.sessionId);
      _marks.clear();
      for (final r in (s['roster'] as List).cast<Map<String, dynamic>>()) {
        final m = r['status'] ?? r['prefill'];
        if (m != null) _marks['${r['student_program_enrollment_id']}'] = '$m';
      }
      setState(() => _sheet = s);
    } catch (e) {
      setState(() => _err = e);
    }
  }

  Map<String, dynamic> get _body => {
        'marks': [
          for (final e in _marks.entries) {'student_program_enrollment_id': e.key, 'status': e.value}
        ],
        'mark_rest_as': 'present',
        'source': 'manual',
      };

  Future<void> _save() async {
    setState(() => _busy = true);
    final repo = ref.read(attendanceRepositoryProvider);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final r = await repo.mark(widget.sessionId, _body);
      messenger.showSnackBar(SnackBar(content: Text('Saved: ${r['created']} new, ${r['updated']} changed')));
      await _load();
    } on DioException catch (e) {
      if (e.response == null) {
        await repo.enqueue(widget.sessionId, _body);
        messenger.showSnackBar(const SnackBar(content: Text('Offline — queued for sync')));
      } else {
        messenger.showSnackBar(SnackBar(content: Text(_error(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _finalize() async {
    try {
      await ref.read(attendanceRepositoryProvider).finalize(widget.sessionId);
      await _load();
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _sheet;
    final locked = s?['attendance_status'] == 'finalized' || s?['can_mark'] != true;
    return Scaffold(
      appBar: AppBar(title: Text(widget.title), actions: [
        if (s != null && !locked)
          IconButton(
              tooltip: 'QR mode',
              icon: const Icon(Icons.qr_code),
              onPressed: () => Navigator.of(context)
                  .push(MaterialPageRoute<void>(builder: (_) => QrProjectorScreen(sessionId: widget.sessionId)))),
        if (s != null && s['attendance_status'] == 'taken')
          IconButton(tooltip: 'Finalize', icon: const Icon(Icons.lock), onPressed: _finalize),
      ]),
      body: _err != null
          ? ListTile(title: Text(_error(_err!)))
          : s == null
              ? const LinearProgressIndicator()
              : GridView.count(
                  crossAxisCount: 3,
                  padding: const EdgeInsets.all(8),
                  childAspectRatio: 1.1,
                  children: [
                    for (final r in (s['roster'] as List).cast<Map<String, dynamic>>())
                      Builder(builder: (_) {
                        final id = '${r['student_program_enrollment_id']}';
                        final m = _marks[id];
                        return InkWell(
                          onTap: locked
                              ? null
                              : () => setState(() =>
                                  _marks[id] = _cycle[(_cycle.indexOf(m ?? 'absent') + 1) % _cycle.length]),
                          child: Card(
                            color: _markColor(m),
                            child: Padding(
                              padding: const EdgeInsets.all(6),
                              child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                                Text(_short[m] ?? '–', style: Theme.of(context).textTheme.headlineSmall),
                                Text('${r['name']}', maxLines: 2, textAlign: TextAlign.center, overflow: TextOverflow.ellipsis),
                                Text('${r['roll_number'] ?? r['registration_number'] ?? ''}',
                                    style: Theme.of(context).textTheme.bodySmall),
                              ]),
                            ),
                          ),
                        );
                      }),
                  ],
                ),
      bottomNavigationBar: s == null || locked
          ? null
          : SafeArea(
              child: Row(children: [
                Expanded(
                    child: TextButton.icon(
                        onPressed: () => setState(() {
                              for (final r in (s['roster'] as List).cast<Map<String, dynamic>>()) {
                                _marks['${r['student_program_enrollment_id']}'] = '${r['prefill'] ?? 'present'}';
                              }
                            }),
                        icon: const Icon(Icons.done_all),
                        label: const Text('All present'))),
                Expanded(
                    child: FilledButton.icon(
                        onPressed: _busy ? null : _save, icon: const Icon(Icons.save), label: const Text('Save'))),
              ]),
            ),
    );
  }
}

class QrProjectorScreen extends ConsumerStatefulWidget {
  const QrProjectorScreen({super.key, required this.sessionId});
  final String sessionId;

  @override
  ConsumerState<QrProjectorScreen> createState() => _QrProjectorState();
}

class _QrProjectorState extends ConsumerState<QrProjectorScreen> {
  Map<String, dynamic>? _qr;
  Object? _err;
  bool _alive = true;

  @override
  void initState() {
    super.initState();
    _issue();
  }

  @override
  void dispose() {
    _alive = false;
    super.dispose();
  }

  Future<void> _issue() async {
    while (_alive) {
      try {
        final q = await ref.read(attendanceRepositoryProvider).issueQr(widget.sessionId);
        if (!_alive) return;
        setState(() => _qr = q);
        await Future<void>.delayed(Duration(seconds: ((q['ttl_seconds'] as int?) ?? 120) - 10));
      } catch (e) {
        if (mounted) setState(() => _err = e);
        return;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final q = _qr;
    return Scaffold(
      appBar: AppBar(title: const Text('Scan to check in')),
      body: Center(
        child: _err != null
            ? Text(_error(_err!))
            : q == null
                ? const CircularProgressIndicator()
                : Column(mainAxisSize: MainAxisSize.min, children: [
                    if (q['png_base64'] != null)
                      Image.memory(base64Decode('${q['png_base64']}'), width: 280, height: 280)
                    else
                      SelectableText('${q['token']}', style: Theme.of(context).textTheme.headlineSmall),
                    const SizedBox(height: 12),
                    Text('${q['checked_in']} checked in', style: Theme.of(context).textTheme.headlineMedium),
                  ]),
      ),
    );
  }
}

// ---- student / parent ------------------------------------------------------------------------------------------------------
class StudentAttendanceScreen extends ConsumerStatefulWidget {
  const StudentAttendanceScreen({super.key, this.wardId});
  final String? wardId;

  @override
  ConsumerState<StudentAttendanceScreen> createState() => _StudentAttendanceState();
}

class _StudentAttendanceState extends ConsumerState<StudentAttendanceScreen> {
  late Future<Map<String, dynamic>> _future;

  @override
  void initState() {
    super.initState();
    _future = ref.read(attendanceRepositoryProvider).mySummary(widget.wardId);
  }

  Future<void> _checkin() async {
    final ctrl = TextEditingController();
    final token = await showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('QR check-in'),
        content: TextField(controller: ctrl, decoration: const InputDecoration(labelText: 'Code under the QR')),
        actions: [FilledButton(onPressed: () => Navigator.pop(context, ctrl.text.trim()), child: const Text('Check in'))],
      ),
    );
    if (token == null || token.isEmpty || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      final r = await ref.read(attendanceRepositoryProvider).qrCheckin(token);
      messenger.showSnackBar(SnackBar(content: Text(r['duplicate'] == true ? 'Already checked in' : 'Marked ${r['status']}')));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  Future<void> _od() async {
    final range = await showDateRangePicker(
        context: context, firstDate: DateTime.now().subtract(const Duration(days: 30)), lastDate: DateTime.now().add(const Duration(days: 60)));
    if (range == null || !mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(attendanceRepositoryProvider).applyOd({
        'from_date': range.start.toIso8601String().substring(0, 10),
        'to_date': range.end.toIso8601String().substring(0, 10),
        'reason_type': 'other',
      });
      messenger.showSnackBar(const SnackBar(content: Text('On-duty request submitted')));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final self = widget.wardId == null;
    return Scaffold(
      appBar: AppBar(title: Text(self ? 'My attendance' : 'Ward attendance'), actions: [
        if (self) IconButton(tooltip: 'QR check-in', icon: const Icon(Icons.qr_code_scanner), onPressed: _checkin),
        if (self) IconButton(tooltip: 'Apply for OD', icon: const Icon(Icons.event_available), onPressed: _od),
      ]),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _future,
        builder: (context, snap) {
          if (snap.hasError) return ListTile(title: Text(_error(snap.error!)));
          if (!snap.hasData) return const LinearProgressIndicator();
          final d = snap.data!;
          final rows = ((d['per_offering'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return ListView(padding: const EdgeInsets.all(8), children: [
            ListTile(
              title: const Text('Overall (credit-weighted)'),
              trailing: Text('${(d['overall_pct'] as num).toStringAsFixed(1)}%',
                  style: Theme.of(context).textTheme.titleLarge),
            ),
            for (final r in rows) _CourseRing(r: r),
          ]);
        },
      ),
    );
  }
}

class _CourseRing extends StatelessWidget {
  const _CourseRing({required this.r});
  final Map<String, dynamic> r;

  @override
  Widget build(BuildContext context) {
    final pct = (r['pct'] as num).toDouble();
    final band = '${r['eligibility']}';
    final need = r['sessions_needed_for_threshold'] as int? ?? 0;
    return Card(
      child: ListTile(
        leading: SizedBox(
          width: 48,
          height: 48,
          child: Stack(alignment: Alignment.center, children: [
            CircularProgressIndicator(value: pct / 100, color: _bandColor(band), strokeWidth: 5),
            Text(pct.toStringAsFixed(0), style: Theme.of(context).textTheme.labelSmall),
          ]),
        ),
        title: Text('${r['course_code']} ${r['course_title'] ?? ''}'),
        subtitle: Text(need > 0
            ? 'Attend the next $need session(s) to reach ${r['min_pct']}%'
            : 'You can miss ${r['sessions_can_miss']} session(s)'),
        trailing: Chip(label: Text(band.replaceAll('_', ' '))),
      ),
    );
  }
}

// ---- HOD ------------------------------------------------------------------------------------------------------------------------
class CondonationRecommendScreen extends ConsumerStatefulWidget {
  const CondonationRecommendScreen({super.key});

  @override
  ConsumerState<CondonationRecommendScreen> createState() => _CondonationRecommendState();
}

class _CondonationRecommendState extends ConsumerState<CondonationRecommendScreen> {
  late Future<List<Map<String, dynamic>>> _future;

  @override
  void initState() {
    super.initState();
    _future = ref.read(attendanceRepositoryProvider).condonations();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Condonations')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _future,
        builder: (context, snap) {
          if (snap.hasError) return ListTile(title: Text(_error(snap.error!)));
          if (!snap.hasData) return const LinearProgressIndicator();
          if (snap.data!.isEmpty) return const ListTile(title: Text('Nothing to recommend.'));
          return ListView(children: [
            for (final c in snap.data!)
              ListTile(
                title: Text('${c['student_name']} · ${c['course_code'] ?? 'aggregate'}'),
                subtitle: Text('${c['actual_pct']}% · ${c['reason_type']}'),
                trailing: c['can_act'] == true
                    ? FilledButton(
                        onPressed: () async {
                          final messenger = ScaffoldMessenger.of(context);
                          try {
                            await ref.read(attendanceRepositoryProvider).recommend('${c['id']}');
                            setState(() => _future = ref.read(attendanceRepositoryProvider).condonations());
                          } catch (e) {
                            messenger.showSnackBar(SnackBar(content: Text(_error(e))));
                          }
                        },
                        child: const Text('Recommend'))
                    : null,
              ),
          ]);
        },
      ),
    );
  }
}
