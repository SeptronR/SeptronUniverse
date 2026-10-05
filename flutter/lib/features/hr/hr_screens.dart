import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/providers.dart';

/// Phase 06 mobile (Prompts/06 §06.10): Leaves (apply, balances, history), My attendance (self check-in / check-out
/// with geo when `attendance.geo_app` is on, month view), Payslips (list, PDF share) and the HR tab (staff, leaves,
/// staff attendance with All | Mine segments for accountant / HR / HOD — the API narrows `scope` to what the role may
/// see). Leave approvals arrive in the Approvals tab (workflow inbox).
double _num(Object? v) =>
    v == null ? 0 : (v is num ? v.toDouble() : double.tryParse('$v') ?? 0);
String _fmt(Object? v) {
  final d = _num(v);
  return d == d.roundToDouble() ? d.toInt().toString() : d.toString();
}

String _inr(Object? paise) => '₹${(_num(paise) / 100).toStringAsFixed(2)}';

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

const _months = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec'
];

class HrRepository {
  HrRepository(this._dio);

  final Dio _dio;

  Future<List<Map<String, dynamic>>> _list(String path,
      [Map<String, dynamic>? q]) async {
    final res = await _dio.get<Map<String, dynamic>>(path, queryParameters: q);
    return ((res.data?['data'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> balances() => _list('/leaves/me/balance');
  Future<List<Map<String, dynamic>>> leaveTypes() => _list('/leave-types');
  Future<List<Map<String, dynamic>>> leaves(String scope) =>
      _list('/leaves', {'scope': scope, 'page_size': 50});
  Future<void> apply(Map<String, dynamic> body) => _dio.post('/leaves',
      data: body,
      options: Options(headers: {
        'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()
      }));
  Future<void> cancel(String id) => _dio.post('/leaves/$id/cancel');
  Future<List<Map<String, dynamic>>> attendance(String scope, String month) =>
      _list('/staff-attendance',
          {'scope': scope, 'month': month, 'page_size': 200});
  Future<void> checkIn(Map<String, dynamic>? geo) =>
      _dio.post('/staff-attendance/self-checkin',
          data: {if (geo != null) 'geo': geo});
  Future<void> checkOut() =>
      _dio.post('/staff-attendance/self-checkout', data: <String, dynamic>{});
  Future<List<Map<String, dynamic>>> payslips() => _list('/payroll/me');
  Future<List<Map<String, dynamic>>> staff(String scope) =>
      _list('/staff', {'scope': scope, 'page_size': 100});

  Future<File> payslipPdf(String id, String name) async {
    final dir = await getTemporaryDirectory();
    final file = File('${dir.path}/$name');
    await _dio.download('/payroll/$id/payslip.pdf', file.path);
    return file;
  }
}

final hrRepositoryProvider =
    Provider<HrRepository>((ref) => HrRepository(ref.watch(dioProvider)));

Widget _errorView(Object e, VoidCallback retry) => Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(_error(e), textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton(onPressed: retry, child: const Text('Retry')),
        ]),
      ),
    );

/// More › Leaves — balances, history, apply, cancel.
class LeavesScreen extends ConsumerStatefulWidget {
  const LeavesScreen({super.key});

  @override
  ConsumerState<LeavesScreen> createState() => _LeavesState();
}

class _LeavesState extends ConsumerState<LeavesScreen> {
  List<Map<String, dynamic>>? _balances;
  List<Map<String, dynamic>>? _leaves;
  Object? _err;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final repo = ref.read(hrRepositoryProvider);
    try {
      final b = await repo.balances();
      final l = await repo.leaves('self');
      if (mounted) {
        setState(() {
          _balances = b;
          _leaves = l;
          _err = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  Future<void> _apply() async {
    final ok = await showModalBottomSheet<bool>(
        context: context,
        isScrollControlled: true,
        builder: (_) => const _ApplySheet());
    if (ok == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now().toIso8601String().substring(0, 10);
    return Scaffold(
      appBar: AppBar(title: const Text('Leaves')),
      floatingActionButton: FloatingActionButton.extended(
          onPressed: _apply,
          icon: const Icon(Icons.add),
          label: const Text('Apply')),
      body: _err != null
          ? _errorView(_err!, _load)
          : _leaves == null
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(padding: const EdgeInsets.all(12), children: [
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final b in _balances ?? const [])
                          if (b['available'] != null)
                            Chip(
                                label: Text(
                                    '${b['code']}  ${_fmt(b['available'])} left'
                                    '${_num(b['pending']) > 0 ? ' · ${_fmt(b['pending'])} pending' : ''}')),
                      ],
                    ),
                    const SizedBox(height: 12),
                    for (final l in _leaves!)
                      Card(
                        child: ListTile(
                          title: Text(
                              '${l['leave_type_code']} · ${_fmt(l['days_count'])} day(s)'),
                          subtitle: Text(
                              '${l['from_date']} → ${l['to_date']} · ${l['status']}'),
                          trailing: (l['status'] == 'pending' ||
                                  (l['status'] == 'approved' &&
                                      '${l['from_date']}'.compareTo(today) > 0))
                              ? TextButton(
                                  onPressed: () async {
                                    try {
                                      await ref
                                          .read(hrRepositoryProvider)
                                          .cancel('${l['id']}');
                                      _load();
                                    } catch (e) {
                                      if (context.mounted) {
                                        ScaffoldMessenger.of(context)
                                            .showSnackBar(SnackBar(
                                                content: Text(_error(e))));
                                      }
                                    }
                                  },
                                  child: const Text('Cancel'))
                              : null,
                        ),
                      ),
                    if (_leaves!.isEmpty)
                      const Padding(
                          padding: EdgeInsets.all(24),
                          child: Text('No leave applications yet.')),
                  ]),
                ),
    );
  }
}

class _ApplySheet extends ConsumerStatefulWidget {
  const _ApplySheet();

  @override
  ConsumerState<_ApplySheet> createState() => _ApplySheetState();
}

class _ApplySheetState extends ConsumerState<_ApplySheet> {
  List<Map<String, dynamic>> _types = const [];
  String? _type;
  DateTimeRange? _range;
  final _reason = TextEditingController();
  String? _err;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    ref.read(hrRepositoryProvider).leaveTypes().then((t) {
      if (mounted) setState(() => _types = t);
    });
  }

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  String _d(DateTime d) => d.toIso8601String().substring(0, 10);

  Future<void> _submit() async {
    if (_type == null || _range == null || _reason.text.trim().length < 3) {
      setState(() => _err = 'Choose a type, the dates and give a reason');
      return;
    }
    setState(() => _busy = true);
    try {
      await ref.read(hrRepositoryProvider).apply({
        'leave_type_id': _type,
        'from_date': _d(_range!.start),
        'to_date': _d(_range!.end),
        'reason': _reason.text.trim(),
      });
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      setState(() {
        _err = _error(e);
        _busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 16,
          bottom: MediaQuery.of(context).viewInsets.bottom + 16),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Text('Apply for leave', style: Theme.of(context).textTheme.titleMedium),
        InputDecorator(
          decoration: const InputDecoration(labelText: 'Leave type'),
          child: DropdownButton<String>(
            value: _type,
            isExpanded: true,
            underline: const SizedBox.shrink(),
            items: [
              for (final t in _types)
                DropdownMenuItem(
                    value: '${t['id']}',
                    child: Text('${t['code']} · ${t['name']}')),
            ],
            onChanged: (v) => setState(() => _type = v),
          ),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(_range == null
              ? 'Choose dates'
              : '${_d(_range!.start)} → ${_d(_range!.end)}'),
          trailing: const Icon(Icons.date_range),
          onTap: () async {
            final now = DateTime.now();
            final r = await showDateRangePicker(
                context: context,
                firstDate: now.subtract(const Duration(days: 30)),
                lastDate: now.add(const Duration(days: 365)));
            if (r != null) setState(() => _range = r);
          },
        ),
        TextField(
            controller: _reason,
            decoration: const InputDecoration(labelText: 'Reason')),
        if (_err != null)
          Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_err!,
                  style:
                      TextStyle(color: Theme.of(context).colorScheme.error))),
        const SizedBox(height: 12),
        FilledButton(
            onPressed: _busy ? null : _submit, child: const Text('Apply')),
      ]),
    );
  }
}

/// More › My attendance — check in / out (location when the geo-fence is on) and the month view.
class MyAttendanceScreen extends ConsumerStatefulWidget {
  const MyAttendanceScreen({super.key});

  @override
  ConsumerState<MyAttendanceScreen> createState() => _MyAttendanceState();
}

class _MyAttendanceState extends ConsumerState<MyAttendanceScreen> {
  List<Map<String, dynamic>>? _rows;
  Object? _err;
  bool _busy = false;
  final String _month = DateTime.now().toIso8601String().substring(0, 7);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final rows =
          await ref.read(hrRepositoryProvider).attendance('self', _month);
      if (mounted) {
        setState(() {
          _rows = rows;
          _err = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  Future<Map<String, dynamic>?> _position() async {
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) {
        perm = await Geolocator.requestPermission();
      }
      if (perm == LocationPermission.denied ||
          perm == LocationPermission.deniedForever) {
        return null;
      }
      final p = await Geolocator.getCurrentPosition();
      return {'lat': p.latitude, 'lng': p.longitude, 'accuracy_m': p.accuracy};
    } catch (_) {
      return null;
    }
  }

  Future<void> _act(bool checkIn) async {
    setState(() => _busy = true);
    final repo = ref.read(hrRepositoryProvider);
    try {
      if (checkIn) {
        await repo.checkIn(await _position());
      } else {
        await repo.checkOut();
      }
      await _load();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(_error(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now().toIso8601String().substring(0, 10);
    final row = (_rows ?? const <Map<String, dynamic>>[])
        .where((r) => r['attendance_date'] == today)
        .firstOrNull;
    return Scaffold(
      appBar: AppBar(title: const Text('My attendance')),
      body: _err != null
          ? _errorView(_err!, _load)
          : ListView(padding: const EdgeInsets.all(12), children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(children: [
                    Text(row == null
                        ? 'Not checked in today'
                        : 'Today: ${row['status']}'),
                    const SizedBox(height: 12),
                    Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                      FilledButton.icon(
                          onPressed: _busy || row?['check_in_time'] != null
                              ? null
                              : () => _act(true),
                          icon: const Icon(Icons.login),
                          label: const Text('Check in')),
                      const SizedBox(width: 12),
                      OutlinedButton.icon(
                          onPressed: _busy ||
                                  row?['check_in_time'] == null ||
                                  row?['check_out_time'] != null
                              ? null
                              : () => _act(false),
                          icon: const Icon(Icons.logout),
                          label: const Text('Check out')),
                    ]),
                  ]),
                ),
              ),
              for (final r in _rows ?? const <Map<String, dynamic>>[])
                ListTile(
                  dense: true,
                  title: Text('${r['attendance_date']} · ${r['status']}'),
                  subtitle: Text('${r['source']}'),
                ),
            ]),
    );
  }
}

/// More › Payslips — approved / paid payslips; the PDF is downloaded and shared.
class PayslipsScreen extends ConsumerWidget {
  const PayslipsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Payslips')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: ref.read(hrRepositoryProvider).payslips(),
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final rows = snap.data!;
          if (rows.isEmpty) {
            return const Center(child: Text('No payslips yet.'));
          }
          return ListView(children: [
            for (final p in rows)
              ListTile(
                title: Text(
                    '${_months[(p['month'] as num).toInt() - 1]} ${p['year']}'),
                subtitle: Text(
                    'Net ${_inr(p['net_paise'])} · gross ${_inr(p['gross_paise'])} · ${p['status']}'),
                trailing: IconButton(
                  icon: const Icon(Icons.share_outlined),
                  tooltip: 'Share PDF',
                  onPressed: () async {
                    try {
                      final f = await ref.read(hrRepositoryProvider).payslipPdf(
                          '${p['id']}',
                          'payslip-${p['year']}-${p['month']}.pdf');
                      await Share.shareXFiles([XFile(f.path)]);
                    } catch (e) {
                      if (context.mounted) {
                        ScaffoldMessenger.of(context)
                            .showSnackBar(SnackBar(content: Text(_error(e))));
                      }
                    }
                  },
                ),
              ),
          ]);
        },
      ),
    );
  }
}

/// HR tab (accountant / HR officer / HOD): staff, leaves and staff attendance with All | Mine segments.
class HrTabScreen extends ConsumerStatefulWidget {
  const HrTabScreen({super.key});

  @override
  ConsumerState<HrTabScreen> createState() => _HrTabState();
}

class _HrTabState extends ConsumerState<HrTabScreen> {
  String _scope = 'all';

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(hrRepositoryProvider);
    final month = DateTime.now().toIso8601String().substring(0, 7);
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('HR'),
          bottom: const TabBar(tabs: [
            Tab(text: 'Staff'),
            Tab(text: 'Leaves'),
            Tab(text: 'Attendance')
          ]),
        ),
        body: Column(children: [
          Padding(
            padding: const EdgeInsets.all(8),
            child: SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'all', label: Text('All')),
                ButtonSegment(value: 'self', label: Text('Mine')),
              ],
              selected: {_scope},
              onSelectionChanged: (s) => setState(() => _scope = s.first),
            ),
          ),
          Expanded(
            child: TabBarView(children: [
              _HrList(
                  key: ValueKey('staff$_scope'),
                  load: () => repo.staff(_scope),
                  title: (r) => '${r['employee_id']} · ${r['full_name']}',
                  subtitle: (r) =>
                      '${r['department_code'] ?? '—'} · ${r['designation_name'] ?? ''} · ${r['phone'] ?? ''}'),
              _HrList(
                  key: ValueKey('leaves$_scope'),
                  load: () => repo.leaves(_scope),
                  title: (r) =>
                      '${r['staff_name']} · ${r['leave_type_code']} ${_fmt(r['days_count'])}d',
                  subtitle: (r) =>
                      '${r['from_date']} → ${r['to_date']} · ${r['status']}'),
              _HrList(
                  key: ValueKey('att$_scope'),
                  load: () => repo.attendance(_scope, month),
                  title: (r) => '${r['staff_name']} · ${r['attendance_date']}',
                  subtitle: (r) => '${r['status']} · ${r['source']}'),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _HrList extends StatelessWidget {
  const _HrList(
      {super.key,
      required this.load,
      required this.title,
      required this.subtitle});

  final Future<List<Map<String, dynamic>>> Function() load;
  final String Function(Map<String, dynamic>) title;
  final String Function(Map<String, dynamic>) subtitle;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Map<String, dynamic>>>(
      future: load(),
      builder: (context, snap) {
        if (snap.hasError) return Center(child: Text(_error(snap.error!)));
        if (!snap.hasData) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.data!.isEmpty) {
          return const Center(child: Text('Nothing here.'));
        }
        return ListView(children: [
          for (final r in snap.data!)
            ListTile(
                dense: true,
                title: Text(title(r)),
                subtitle: Text(subtitle(r))),
        ]);
      },
    );
  }
}
