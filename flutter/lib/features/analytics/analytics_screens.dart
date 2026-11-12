import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/offline/cache_repository.dart';
import '../../core/providers.dart';

/// Phase 35 mobile (Prompts/35 §35.10). Every role's **Home** renders the `GET /dashboard` widgets natively — stat
/// cards (target chip, delta, class average for students / parents), simple charts (`fl_chart`) with a table sheet,
/// list widgets and quick actions — with a segmented scope control from `meta.visibility`. Offline: the last
/// dashboard is cached for 1 h and shown with a stale badge. HOD / registrar / mentor: **Early warning** (cohort heat
/// map, at-risk students, log intervention). The API decides composition, permissions and visibility.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _num(dynamic v, [String? fmt]) {
  if (v == null) return '—';
  final n = v is num ? v : num.tryParse('$v');
  if (n == null) return '$v';
  final s = n == n.roundToDouble() ? n.toInt().toString() : n.toStringAsFixed(2);
  if (fmt == 'pct') return '$s%';
  if (fmt == 'inr') return '₹$s';
  return s;
}

const _levelColors = {'low': Colors.green, 'medium': Colors.orange, 'high': Colors.red};

class AnalyticsRepository {
  AnalyticsRepository(this._dio, this._cache);

  final Dio _dio;
  final CacheRepository _cache;

  Future<({Map<String, dynamic> data, Map<String, dynamic> visibility, bool cached})> dashboard({String? scope, String? role}) async {
    final key = 'dashboard:${role ?? ''}:${scope ?? ''}';
    try {
      final r = await _dio.get<Map<String, dynamic>>('/dashboard', queryParameters: {if (scope != null) 'scope': scope, if (role != null) 'role': role});
      final body = r.data ?? const {};
      await _cache.write(key, jsonEncode(body), ttl: const Duration(hours: 1));
      return (
        data: ((body['data'] as Map?) ?? const {}).cast<String, dynamic>(),
        visibility: (((body['meta'] as Map?)?['visibility'] as Map?) ?? const {}).cast<String, dynamic>(),
        cached: false,
      );
    } on DioException {
      final row = await _cache.read(key);
      if (row == null) rethrow;
      final body = (jsonDecode(row.json) as Map).cast<String, dynamic>();
      return (
        data: ((body['data'] as Map?) ?? const {}).cast<String, dynamic>(),
        visibility: (((body['meta'] as Map?)?['visibility'] as Map?) ?? const {}).cast<String, dynamic>(),
        cached: true,
      );
    }
  }

  Future<Map<String, dynamic>> cohort({String groupBy = 'department', String? scope}) async =>
      (((await _dio.get<Map<String, dynamic>>('/risk/cohort', queryParameters: {'group_by': groupBy, if (scope != null) 'scope': scope})).data?['data'] as Map?) ?? const {})
          .cast<String, dynamic>();

  Future<List<Map<String, dynamic>>> students({String level = 'high', String? scope}) async =>
      (((await _dio.get<Map<String, dynamic>>('/risk/students', queryParameters: {'level': level, if (scope != null) 'scope': scope})).data?['data'] as List?) ?? const [])
          .cast<Map<String, dynamic>>();

  Future<void> logIntervention(String enrollmentId, String type, String? notes) =>
      _dio.post<Map<String, dynamic>>('/risk/students/$enrollmentId/interventions', data: {'intervention_type': type, if (notes != null && notes.isNotEmpty) 'notes': notes});
}

final analyticsRepositoryProvider = Provider<AnalyticsRepository>((ref) => AnalyticsRepository(ref.watch(dioProvider), ref.watch(cacheRepositoryProvider)));

/// Home tab for every role shell: the role dashboard from `GET /dashboard`.
class DashboardHomeScreen extends ConsumerStatefulWidget {
  const DashboardHomeScreen({super.key});

  @override
  ConsumerState<DashboardHomeScreen> createState() => _DashboardHomeScreenState();
}

class _DashboardHomeScreenState extends ConsumerState<DashboardHomeScreen> {
  String? _scope;
  late Future<({Map<String, dynamic> data, Map<String, dynamic> visibility, bool cached})> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() => _future = ref.read(analyticsRepositoryProvider).dashboard(scope: _scope);

  @override
  Widget build(BuildContext context) {
    return FutureBuilder(
      future: _future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
        if (snap.hasError) return Center(child: Padding(padding: const EdgeInsets.all(24), child: Text(_error(snap.error!))));
        final d = snap.data!.data;
        final vis = snap.data!.visibility;
        final scopes = ((vis['scopes'] as List?) ?? const []).cast<String>();
        final widgets = ((d['widgets'] as List?) ?? const []).cast<Map<String, dynamic>>();
        final alerts = ((d['alerts'] as List?) ?? const []).cast<Map<String, dynamic>>();
        return RefreshIndicator(
          onRefresh: () async => setState(_load),
          child: ListView(
            padding: const EdgeInsets.all(12),
            children: [
              if (snap.data!.cached || widgets.any((w) => w['stale'] == true))
                const Padding(padding: EdgeInsets.only(bottom: 8), child: Chip(avatar: Icon(Icons.cloud_off, size: 16), label: Text('stale — last saved dashboard'))),
              if (scopes.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: SegmentedButton<String>(
                    segments: [for (final s in scopes) ButtonSegment(value: s, label: Text(s))],
                    selected: {_scope ?? (vis['default'] as String? ?? scopes.last)},
                    onSelectionChanged: (v) => setState(() {
                      _scope = v.first;
                      _load();
                    }),
                  ),
                ),
              for (final a in alerts)
                Card(
                  color: Theme.of(context).colorScheme.tertiaryContainer,
                  child: ListTile(
                    dense: true,
                    leading: const Icon(Icons.warning_amber),
                    title: Text(a['kind'] == 'kpi' ? '${a['key']}: ${_num(a['value'])} vs target ${_num(a['target'])}' : a['kind'] == 'approvals' ? '${a['count']} approval(s) waiting' : '${a['message'] ?? ''}'),
                  ),
                ),
              if (d['risk'] is Map) Card(child: ListTile(leading: const Icon(Icons.favorite_outline), title: Text('Early-warning level: ${(d['risk'] as Map)['level']}'))),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [for (final w in widgets.where((w) => w['kind'] == 'stat' && w['unavailable'] != true)) _StatTile(w)],
              ),
              const SizedBox(height: 8),
              for (final w in widgets.where((w) => w['kind'] == 'chart' && w['unavailable'] != true)) _ChartTile(w),
              for (final w in widgets.where((w) => w['kind'] == 'list' && w['unavailable'] != true)) _ListTile(w),
              Wrap(
                spacing: 8,
                children: [
                  for (final w in widgets.where((w) => w['kind'] == 'action'))
                    ActionChip(label: Text('${w['title'] ?? w['key']}'), onPressed: () => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Open ${w['route']} on the web')))),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

class _StatTile extends StatelessWidget {
  const _StatTile(this.w);

  final Map<String, dynamic> w;

  @override
  Widget build(BuildContext context) {
    final s = ((w['stat'] as Map?) ?? const {}).cast<String, dynamic>();
    final fmt = s['format'] as String?;
    final target = s['target'];
    final onTarget = s['on_target'];
    return SizedBox(
      width: (MediaQuery.of(context).size.width - 32) / 2,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${w['title'] ?? w['key']}', style: Theme.of(context).textTheme.labelSmall, maxLines: 1, overflow: TextOverflow.ellipsis),
              Text(_num(s['value'], fmt), style: Theme.of(context).textTheme.headlineSmall),
              if (target != null)
                Text('target ${_num(target, fmt)}', style: TextStyle(fontSize: 11, color: onTarget == false ? Colors.red : Colors.green)),
              if (s['class_average'] != null) Text('class average ${_num(s['class_average'], fmt)}', style: const TextStyle(fontSize: 11)),
              if (s['delta'] != null && s['delta'] != 0) Text('${(s['delta'] as num) > 0 ? '▲' : '▼'} ${_num((s['delta'] as num).abs())}', style: const TextStyle(fontSize: 11)),
            ],
          ),
        ),
      ),
    );
  }
}

class _ChartTile extends StatelessWidget {
  const _ChartTile(this.w);

  final Map<String, dynamic> w;

  @override
  Widget build(BuildContext context) {
    final data = ((w['data'] as Map?) ?? const {}).cast<String, dynamic>();
    final series = ((data['series'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final keys = (((data['dims'] as Map?)?['series'] as List?) ?? const ['value']).cast<String>();
    final table = ((data['table'] as Map?) ?? const {}).cast<String, dynamic>();
    final kind = '${data['kind'] ?? 'bar'}';
    Widget chart;
    if (kind == 'number' || kind == 'gauge') {
      chart = Center(child: Text(_num(series.isEmpty ? 0 : series.first['value'], kind == 'gauge' ? 'pct' : null), style: Theme.of(context).textTheme.displaySmall));
    } else if (kind == 'line' || kind == 'sparkline') {
      chart = LineChart(LineChartData(
        titlesData: const FlTitlesData(show: false),
        borderData: FlBorderData(show: false),
        lineBarsData: [
          for (var k = 0; k < keys.length; k++)
            LineChartBarData(
              spots: [for (var i = 0; i < series.length; i++) FlSpot(i.toDouble(), ((series[i][keys[k]] as num?) ?? 0).toDouble())],
              color: _levelColors[keys[k]] ?? Colors.primaries[k % Colors.primaries.length],
              dotData: const FlDotData(show: false),
            ),
        ],
      ));
    } else {
      chart = BarChart(BarChartData(
        titlesData: const FlTitlesData(show: false),
        borderData: FlBorderData(show: false),
        barGroups: [
          for (var i = 0; i < series.length && i < 20; i++)
            BarChartGroupData(x: i, barRods: [
              BarChartRodData(
                toY: keys.fold<double>(0, (sum, k) => sum + ((series[i][k] as num?) ?? 0).toDouble()),
                color: Theme.of(context).colorScheme.primary,
              ),
            ]),
        ],
      ));
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(child: Text('${w['title'] ?? data['title']}', style: Theme.of(context).textTheme.titleSmall)),
              IconButton(
                tooltip: 'Table',
                icon: const Icon(Icons.table_rows_outlined),
                onPressed: () => showModalBottomSheet<void>(context: context, isScrollControlled: true, builder: (_) => _TableSheet(table)),
              ),
            ]),
            SizedBox(height: 160, child: chart),
          ],
        ),
      ),
    );
  }
}

class _TableSheet extends StatelessWidget {
  const _TableSheet(this.table);

  final Map<String, dynamic> table;

  @override
  Widget build(BuildContext context) {
    final cols = ((table['columns'] as List?) ?? const []).map((c) => '$c').toList();
    final rows = ((table['rows'] as List?) ?? const []).cast<List<dynamic>>();
    return SafeArea(
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: SingleChildScrollView(
          child: DataTable(
            columns: [for (final c in cols) DataColumn(label: Text(c))],
            rows: [for (final r in rows) DataRow(cells: [for (final c in r) DataCell(Text(_num(c)))])],
          ),
        ),
      ),
    );
  }
}

class _ListTile extends StatelessWidget {
  const _ListTile(this.w);

  final Map<String, dynamic> w;

  @override
  Widget build(BuildContext context) {
    final items = ((w['items'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final risk = w['key'] == 'risk.high';
    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(title: Text('${w['title'] ?? w['key']}'), trailing: risk ? TextButton(onPressed: () => context.push('/app/risk'), child: const Text('Open')) : null),
          if (items.isEmpty) const Padding(padding: EdgeInsets.fromLTRB(16, 0, 16, 12), child: Text('Nothing here.')),
          for (final i in items.take(8)) ListTile(dense: true, title: Text('${i['title']}'), trailing: Text('${i['meta'] ?? ''}')),
        ],
      ),
    );
  }
}

/// Early warning (HOD / registrar / mentor): cohort heat map + at-risk students + log intervention.
class RiskCohortScreen extends ConsumerStatefulWidget {
  const RiskCohortScreen({super.key});

  @override
  ConsumerState<RiskCohortScreen> createState() => _RiskCohortScreenState();
}

class _RiskCohortScreenState extends ConsumerState<RiskCohortScreen> {
  static const _types = ['mentor_meeting', 'guardian_call', 'counselling', 'fee_plan', 'remedial_class', 'hostel_warden', 'other'];
  late Future<(Map<String, dynamic>, List<Map<String, dynamic>>)> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    final repo = ref.read(analyticsRepositoryProvider);
    _future = (() async => (await repo.cohort(), await repo.students()))();
  }

  Future<void> _log(Map<String, dynamic> s) async {
    var type = _types.first;
    final notes = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: Text('Log intervention — ${s['student_name'] ?? s['registration_number'] ?? ''}'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButton<String>(value: type, isExpanded: true, items: [for (final t in _types) DropdownMenuItem(value: t, child: Text(t.replaceAll('_', ' ')))], onChanged: (v) => setLocal(() => type = v ?? type)),
            TextField(controller: notes, decoration: const InputDecoration(labelText: 'Notes'), maxLines: 3),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save'))],
        ),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await ref.read(analyticsRepositoryProvider).logIntervention('${s['enrollment_id']}', type, notes.text);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Intervention logged')));
      setState(_load);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Early warning')),
      body: FutureBuilder(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          final (cohort, students) = snap.data!;
          final cells = ((cohort['cells'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return RefreshIndicator(
            onRefresh: () async => setState(_load),
            child: ListView(
              padding: const EdgeInsets.all(12),
              children: [
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(8),
                    child: Table(
                      columnWidths: const {0: FlexColumnWidth(2)},
                      children: [
                        const TableRow(children: [Text(''), Text('low'), Text('medium'), Text('high')]),
                        for (final c in cells)
                          TableRow(children: [
                            Padding(padding: const EdgeInsets.all(4), child: Text('${c['group']}')),
                            for (final lv in const ['low', 'medium', 'high'])
                              Container(
                                margin: const EdgeInsets.all(2),
                                padding: const EdgeInsets.all(6),
                                color: (_levelColors[lv] ?? Colors.grey).withValues(alpha: ((c[lv] as num? ?? 0) > 0) ? 0.35 : 0.08),
                                child: Text('${c[lv] ?? 0}', textAlign: TextAlign.center),
                              ),
                          ]),
                      ],
                    ),
                  ),
                ),
                const ListTile(title: Text('High-risk students')),
                for (final s in students)
                  Card(
                    child: ListTile(
                      title: Text('${s['student_name'] ?? s['registration_number'] ?? '—'}'),
                      subtitle: Text('score ${_num(s['score'])} · mentor ${s['mentor'] ?? '—'}'),
                      trailing: s['enrollment_id'] == null ? null : IconButton(icon: const Icon(Icons.volunteer_activism_outlined), tooltip: 'Log intervention', onPressed: () => _log(s)),
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }
}
