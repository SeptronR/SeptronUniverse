import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../core/offline/cache_repository.dart';
import '../../core/providers.dart';

/// Phase 20 mobile (Prompts/20 §20.10): student **Hostel** (room card, leave request → consent status → QR pass, mess
/// card QR, bills), parent **Ward hostel** (consent approve, out / return timeline), warden **Out-passes** (approve /
/// reject), **Gate scan** (QR mark-out / return with an offline queue sent as one batch with device times) and the
/// **Roll-call** grid. Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _dt(dynamic v) => v == null ? '—' : DateTime.parse('$v').toLocal().toString().substring(0, 16);

class HostelRepository {
  HostelRepository(this._dio, this._cache);

  final Dio _dio;
  final CacheRepository _cache;
  static const _queueKey = 'hostel.gate_queue';

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path,
          data: body ?? {}, options: Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()})))
      .data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<List<Map<String, dynamic>>> myAllocations() async => _list(await _get('/hostel-allocations/me'));
  Future<List<Map<String, dynamic>>> myLeaves() async => _list(await _get('/hostel-leaves/me'));
  Future<List<Map<String, dynamic>>> wardLeaves() async => _list(await _get('/hostel-leaves/wards'));
  Future<List<Map<String, dynamic>>> wardAllocations() async => _list(await _get('/hostel-allocations/wards'));
  Future<List<Map<String, dynamic>>> mySubscriptions() async {
    try {
      return _list(await _get('/mess-subscriptions', {'mine': true}));
    } catch (_) {
      return const [];
    }
  }

  Future<void> requestLeave(Map<String, dynamic> body) => _post('/hostel-leaves', body);
  Future<void> sendOtp(String id) => _post('/hostel-leaves/$id/consent/send-otp');
  Future<void> verifyOtp(String id, String otp) => _post('/hostel-leaves/$id/consent/verify', {'otp': otp});
  Future<void> parentApprove(String id) => _post('/hostel-leaves/$id/consent/parent-approve');
  Future<List<Map<String, dynamic>>> queue() async => _list(await _get('/hostel-leaves', {'status': 'requested'}));
  Future<void> decide(String id, String action) => _post('/hostel-leaves/$id/decide', {'action': action});
  Future<Map<String, dynamic>> scan(String token, String direction, {DateTime? at}) async =>
      ((await _post('/hostel-gate/scan', {'qr_token': token, 'direction': direction, if (at != null) 'scanned_at': at.toUtc().toIso8601String()})) as Map)
          .cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> hostels() async => _list(await _get('/hostels'));
  Future<List<Map<String, dynamic>>> rollCalls(String hostelId, String onDate) async => _list(await _get('/hostel-roll-calls', {'hostel_id': hostelId, 'on_date': onDate}));
  Future<void> startRollCall(String hostelId) => _post('/hostel-roll-calls', {'hostel_id': hostelId});
  Future<void> markRollCall(String id, List<Map<String, dynamic>> entries) => _dio.put('/hostel-roll-calls/$id/entries', data: {'entries': entries});

  // ---- offline gate queue -------------------------------------------------------------------------------------------
  Future<List<Map<String, dynamic>>> queued() async {
    final hit = await _cache.read(_queueKey);
    return hit == null ? [] : (jsonDecode(hit.json) as List).cast<Map<String, dynamic>>();
  }

  Future<void> enqueue(String token, String direction) async {
    final q = await queued()..add({'qr_token': token, 'direction': direction, 'scanned_at': DateTime.now().toUtc().toIso8601String()});
    await _cache.write(_queueKey, jsonEncode(q), ttl: const Duration(days: 3));
  }

  Future<int> flush() async {
    final q = await queued();
    if (q.isEmpty) return 0;
    await _post('/hostel-gate/scan-batch', {'scans': q});
    await _cache.write(_queueKey, jsonEncode([]), ttl: const Duration(days: 3));
    return q.length;
  }
}

final hostelRepositoryProvider = Provider<HostelRepository>((ref) => HostelRepository(ref.watch(dioProvider), CacheRepository()));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

// ---- student --------------------------------------------------------------------------------------------------------------------
class StudentHostelScreen extends ConsumerStatefulWidget {
  const StudentHostelScreen({super.key});

  @override
  ConsumerState<StudentHostelScreen> createState() => _StudentHostelScreenState();
}

class _StudentHostelScreenState extends ConsumerState<StudentHostelScreen> {
  late Future<List<List<Map<String, dynamic>>>> _f = _load();

  Future<List<List<Map<String, dynamic>>>> _load() {
    final r = ref.read(hostelRepositoryProvider);
    return Future.wait([r.myAllocations(), r.myLeaves(), r.mySubscriptions()]);
  }

  Future<void> _newLeave() async {
    var type = 'out_pass';
    var from = DateTime.now().add(const Duration(hours: 1));
    var hours = 4;
    final dest = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('Leave / out-pass'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButton<String>(
              value: type,
              items: const [
                DropdownMenuItem(value: 'out_pass', child: Text('Out-pass')),
                DropdownMenuItem(value: 'day_leave', child: Text('Day leave')),
                DropdownMenuItem(value: 'home_leave', child: Text('Home leave')),
                DropdownMenuItem(value: 'medical', child: Text('Medical')),
              ],
              onChanged: (v) => set(() {
                type = v ?? 'out_pass';
                hours = type == 'home_leave' ? 72 : (type == 'medical' ? 48 : 4);
              }),
            ),
            ListTile(title: Text('From ${from.toString().substring(0, 16)}'), trailing: const Icon(Icons.schedule), onTap: () async {
              final t = await showTimePicker(context: ctx, initialTime: TimeOfDay.fromDateTime(from));
              if (t != null) set(() => from = DateTime(from.year, from.month, from.day, t.hour, t.minute));
            }),
            Row(children: [const Text('Hours'), Expanded(child: Slider(value: hours.toDouble(), min: 1, max: 240, divisions: 239, label: '$hours', onChanged: (v) => set(() => hours = v.round())))]),
            TextField(controller: dest, decoration: const InputDecoration(labelText: 'Destination')),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Request'))],
        ),
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(hostelRepositoryProvider).requestLeave({
        'leave_type': type,
        'from_at': from.toUtc().toIso8601String(),
        'to_at': from.add(Duration(hours: hours)).toUtc().toIso8601String(),
        'destination': dest.text,
      });
      if (mounted) _snack(context, 'Requested');
      setState(() => _f = _load());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(hostelRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Hostel')),
      floatingActionButton: FloatingActionButton.extended(onPressed: _newLeave, icon: const Icon(Icons.exit_to_app), label: const Text('Leave')),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = _load()),
        child: FutureBuilder<List<List<Map<String, dynamic>>>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final allocs = snap.data![0];
            final leaves = snap.data![1];
            final subs = snap.data![2].where((s) => s['qr_token'] != null).toList();
            final active = allocs.where((a) => a['status'] == 'allotted' || a['status'] == 'checked_in').toList();
            return ListView(padding: const EdgeInsets.all(8), children: [
              Card(
                child: ListTile(
                  leading: const Icon(Icons.bed_outlined),
                  title: Text(active.isEmpty ? 'No hostel allocation' : '${active.first['hostel']} · ${active.first['room_number']} ${active.first['bed_label']}'),
                  subtitle: Text(active.isEmpty ? 'Apply from the web portal' : 'Status ${active.first['status']} · fee ${active.first['fee_status'] ?? '—'}'),
                ),
              ),
              for (final s in subs)
                Card(child: Column(children: [ListTile(title: Text('Mess card · ${s['plan']}')), QrImageView(data: '${s['qr_token']}', size: 160)])),
              const Padding(padding: EdgeInsets.all(8), child: Text('Leaves', style: TextStyle(fontWeight: FontWeight.w600))),
              if (leaves.isEmpty) const ListTile(title: Text('No leaves yet.')),
              for (final l in leaves)
                Card(
                  child: Column(children: [
                    ListTile(
                      title: Text('${l['leave_type']} · ${l['status']}'),
                      subtitle: Text('${_dt(l['from_at'])} → ${_dt(l['to_at'])}\nConsent: ${l['guardian_consent']}${l['late_minutes'] != null && l['late_minutes'] != 0 ? ' · late ${l['late_minutes']} min' : ''}'),
                      isThreeLine: true,
                    ),
                    if (l['guardian_consent'] == 'pending')
                      Padding(
                        padding: const EdgeInsets.all(8),
                        child: Row(children: [
                          TextButton(
                            onPressed: () async {
                              try {
                                await repo.sendOtp('${l['id']}');
                                if (context.mounted) _snack(context, 'OTP sent to your guardian');
                              } catch (e) {
                                if (context.mounted) _snack(context, _error(e));
                              }
                            },
                            child: const Text('Send OTP'),
                          ),
                          const Spacer(),
                          TextButton(
                            onPressed: () async {
                              final c = TextEditingController();
                              final code = await showDialog<String>(
                                context: context,
                                builder: (ctx) => AlertDialog(
                                  title: const Text('Guardian OTP'),
                                  content: TextField(controller: c, keyboardType: TextInputType.number),
                                  actions: [FilledButton(onPressed: () => Navigator.pop(ctx, c.text), child: const Text('Verify'))],
                                ),
                              );
                              if (code == null) return;
                              try {
                                await repo.verifyOtp('${l['id']}', code);
                                setState(() => _f = _load());
                              } catch (e) {
                                if (context.mounted) _snack(context, _error(e));
                              }
                            },
                            child: const Text('Enter OTP'),
                          ),
                        ]),
                      ),
                    if (l['qr_token'] != null) Padding(padding: const EdgeInsets.all(8), child: QrImageView(data: '${l['qr_token']}', size: 200)),
                  ]),
                ),
            ]);
          },
        ),
      ),
    );
  }
}

// ---- parent ----------------------------------------------------------------------------------------------------------------------
class WardHostelScreen extends ConsumerStatefulWidget {
  const WardHostelScreen({super.key});

  @override
  ConsumerState<WardHostelScreen> createState() => _WardHostelScreenState();
}

class _WardHostelScreenState extends ConsumerState<WardHostelScreen> {
  late Future<List<List<Map<String, dynamic>>>> _f = _load();

  Future<List<List<Map<String, dynamic>>>> _load() {
    final r = ref.read(hostelRepositoryProvider);
    return Future.wait([r.wardAllocations(), r.wardLeaves()]);
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(hostelRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text("Ward's hostel")),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = _load()),
        child: FutureBuilder<List<List<Map<String, dynamic>>>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            return ListView(padding: const EdgeInsets.all(8), children: [
              for (final a in snap.data![0]) ListTile(leading: const Icon(Icons.bed_outlined), title: Text('${a['student']?['name']} · ${a['hostel']}'), subtitle: Text('Room ${a['room_number']} · ${a['status']}')),
              const Divider(),
              for (final l in snap.data![1])
                ListTile(
                  title: Text('${l['student']?['name']} · ${l['leave_type']} · ${l['status']}'),
                  subtitle: Text('${_dt(l['from_at'])} → ${_dt(l['to_at'])}\nOut ${_dt(l['actual_out_at'])} · back ${_dt(l['actual_return_at'])}'),
                  isThreeLine: true,
                  trailing: l['guardian_consent'] == 'pending'
                      ? FilledButton(
                          onPressed: () async {
                            try {
                              await repo.parentApprove('${l['id']}');
                              setState(() => _f = _load());
                            } catch (e) {
                              if (context.mounted) _snack(context, _error(e));
                            }
                          },
                          child: const Text('Approve'),
                        )
                      : null,
                ),
            ]);
          },
        ),
      ),
    );
  }
}

// ---- warden: out-pass approvals ------------------------------------------------------------------------------------------------
class OutPassApprovalsScreen extends ConsumerStatefulWidget {
  const OutPassApprovalsScreen({super.key});

  @override
  ConsumerState<OutPassApprovalsScreen> createState() => _OutPassApprovalsScreenState();
}

class _OutPassApprovalsScreenState extends ConsumerState<OutPassApprovalsScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(hostelRepositoryProvider).queue();

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(hostelRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Out-passes'), actions: [
        IconButton(icon: const Icon(Icons.qr_code_scanner), onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const GateScanScreen()))),
      ]),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = repo.queue()),
        child: FutureBuilder<List<Map<String, dynamic>>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            if (snap.data!.isEmpty) return ListView(children: const [ListTile(title: Text('Nothing pending.'))]);
            return ListView(children: [
              for (final l in snap.data!)
                Card(
                  child: ListTile(
                    title: Text('${l['student']?['name']} · ${l['leave_type']}'),
                    subtitle: Text('${_dt(l['from_at'])} → ${_dt(l['to_at'])} · consent ${l['guardian_consent']}'),
                    trailing: Wrap(children: [
                      IconButton(
                        icon: const Icon(Icons.check, color: Colors.green),
                        onPressed: l['guardian_consent'] == 'pending'
                            ? null
                            : () async {
                                try {
                                  await repo.decide('${l['id']}', 'approve');
                                  setState(() => _f = repo.queue());
                                } catch (e) {
                                  if (context.mounted) _snack(context, _error(e));
                                }
                              },
                      ),
                      IconButton(
                        icon: const Icon(Icons.close, color: Colors.red),
                        onPressed: () async {
                          try {
                            await repo.decide('${l['id']}', 'reject');
                            setState(() => _f = repo.queue());
                          } catch (e) {
                            if (context.mounted) _snack(context, _error(e));
                          }
                        },
                      ),
                    ]),
                  ),
                ),
            ]);
          },
        ),
      ),
    );
  }
}

// ---- gate scanner (offline queue) -------------------------------------------------------------------------------------------------
class GateScanScreen extends ConsumerStatefulWidget {
  const GateScanScreen({super.key});

  @override
  ConsumerState<GateScanScreen> createState() => _GateScanScreenState();
}

class _GateScanScreenState extends ConsumerState<GateScanScreen> {
  String _direction = 'out';
  String? _last;
  String _status = 'Scan a pass QR.';
  int _queued = 0;

  @override
  void initState() {
    super.initState();
    ref.read(hostelRepositoryProvider).queued().then((q) => mounted ? setState(() => _queued = q.length) : null);
  }

  Future<void> _onDetect(BarcodeCapture cap) async {
    final code = cap.barcodes.isNotEmpty ? cap.barcodes.first.rawValue : null;
    if (code == null || code == _last) return;
    _last = code;
    final repo = ref.read(hostelRepositoryProvider);
    try {
      final r = await repo.scan(code, _direction);
      setState(() => _status = '✓ ${r['student']?['name']} — ${r['result']}${r['late_minutes'] != null && r['late_minutes'] != 0 ? ' (${r['late_minutes']} min late)' : ''}');
    } on DioException catch (e) {
      if (e.response == null) {
        await repo.enqueue(code, _direction);
        final q = await repo.queued();
        setState(() {
          _queued = q.length;
          _status = 'Offline — scan queued';
        });
      } else {
        setState(() => _status = '✗ ${_error(e)}');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(hostelRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Gate scan'), actions: [
        if (_queued > 0)
          TextButton.icon(
            icon: const Icon(Icons.cloud_upload_outlined),
            label: Text('$_queued queued'),
            onPressed: () async {
              try {
                final n = await repo.flush();
                setState(() {
                  _queued = 0;
                  _status = 'Sent $n queued scan(s)';
                });
              } catch (e) {
                setState(() => _status = _error(e));
              }
            },
          ),
      ]),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.all(8),
          child: SegmentedButton<String>(
            segments: const [ButtonSegment(value: 'out', label: Text('Going out')), ButtonSegment(value: 'in', label: Text('Coming in'))],
            selected: {_direction},
            onSelectionChanged: (s) => setState(() => _direction = s.first),
          ),
        ),
        Expanded(child: MobileScanner(onDetect: _onDetect)),
        Padding(padding: const EdgeInsets.all(16), child: Text(_status, textAlign: TextAlign.center)),
      ]),
    );
  }
}

// ---- warden: roll-call grid --------------------------------------------------------------------------------------------------------
class RollCallScreen extends ConsumerStatefulWidget {
  const RollCallScreen({super.key});

  @override
  ConsumerState<RollCallScreen> createState() => _RollCallScreenState();
}

class _RollCallScreenState extends ConsumerState<RollCallScreen> {
  String? _hostel;
  Future<List<Map<String, dynamic>>>? _rc;
  final Map<String, String> _marks = {};
  late final Future<List<Map<String, dynamic>>> _hostels = ref.read(hostelRepositoryProvider).hostels();
  final String _today = DateTime.now().toIso8601String().substring(0, 10);

  void _load() => setState(() => _rc = ref.read(hostelRepositoryProvider).rollCalls(_hostel!, _today));

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(hostelRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Roll-call')),
      body: Column(children: [
        FutureBuilder<List<Map<String, dynamic>>>(
          future: _hostels,
          builder: (context, snap) => Padding(
            padding: const EdgeInsets.all(8),
            child: DropdownButton<String>(
              isExpanded: true,
              hint: const Text('Hostel'),
              value: _hostel,
              items: [for (final h in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${h['id']}', child: Text('${h['name']}'))],
              onChanged: (v) {
                _hostel = v;
                _load();
              },
            ),
          ),
        ),
        if (_rc != null)
          Expanded(
            child: FutureBuilder<List<Map<String, dynamic>>>(
              future: _rc,
              builder: (context, snap) {
                if (snap.hasError) return Text(_error(snap.error!));
                if (!snap.hasData) return const Center(child: CircularProgressIndicator());
                if (snap.data!.isEmpty) {
                  return Center(
                    child: FilledButton(
                      onPressed: () async {
                        try {
                          await repo.startRollCall(_hostel!);
                          _load();
                        } catch (e) {
                          if (context.mounted) _snack(context, _error(e));
                        }
                      },
                      child: const Text("Start tonight's roll-call"),
                    ),
                  );
                }
                final rc = snap.data!.first;
                final entries = ((rc['entries'] as List?) ?? const []).cast<Map<String, dynamic>>();
                return Column(children: [
                  Expanded(
                    child: ListView(children: [
                      for (final e in entries)
                        ListTile(
                          title: Text('${e['room_number']} · ${e['student']?['name']}'),
                          trailing: SegmentedButton<String>(
                            segments: const [ButtonSegment(value: 'present', label: Text('P')), ButtonSegment(value: 'absent', label: Text('A')), ButtonSegment(value: 'on_leave', label: Text('L'))],
                            selected: {_marks['${e['allocation_id']}'] ?? '${e['status']}'},
                            onSelectionChanged: (s) => setState(() => _marks['${e['allocation_id']}'] = s.first),
                          ),
                        ),
                    ]),
                  ),
                  Padding(
                    padding: const EdgeInsets.all(8),
                    child: FilledButton(
                      onPressed: _marks.isEmpty
                          ? null
                          : () async {
                              try {
                                await repo.markRollCall('${rc['id']}', [for (final m in _marks.entries) {'allocation_id': m.key, 'status': m.value}]);
                                _marks.clear();
                                _load();
                              } catch (e) {
                                if (context.mounted) _snack(context, _error(e));
                              }
                            },
                      child: Text('Save ${_marks.length}'),
                    ),
                  ),
                ]);
              },
            ),
          ),
      ]),
    );
  }
}
