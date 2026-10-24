import 'package:dio/dio.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/providers.dart';

/// Phase 17 mobile (Prompts/17 §17.10): faculty **Attainment** (own offerings → read-only CO table + level heatmap),
/// HOD / IQAC **Attainment dashboard** (programme + batch → PO / PSO radar, gap list), **CQI actions** (status moves,
/// photo evidence upload, verify for the OBE office) and the setting-gated student **Course outcomes** list. Rules and
/// visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class ObeRepository {
  ObeRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path,
          data: body ?? {}, options: Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()})))
      .data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) {
    if (v is Map && v['items'] is List) return (v['items'] as List).cast<Map<String, dynamic>>();
    return ((v as List?) ?? const []).cast<Map<String, dynamic>>();
  }

  Future<List<Map<String, dynamic>>> myOfferings() async => _list(await _get('/course-offerings', {'scope': 'mine'}));
  Future<Map<String, dynamic>> co(String offeringId) async =>
      ((await _get('/course-offerings/$offeringId/attainment')) as Map).cast<String, dynamic>();
  Future<Map<String, dynamic>> coHeatmap(String offeringId) async =>
      ((await _get('/course-offerings/$offeringId/attainment/heatmap')) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> programs() async => _list(await _get('/programs', {'page_size': 200}));
  Future<List<Map<String, dynamic>>> batches(String programId) async =>
      _list(await _get('/batches', {'program_id': programId, 'page_size': 200}));
  Future<Map<String, dynamic>> dashboard(String programId, String batchId) async =>
      ((await _get('/obe/dashboard', {'program_id': programId, 'batch_id': batchId})) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> cqi({bool mine = false}) async => _list(await _get('/cqi-actions', {'mine': mine}));
  Future<void> status(String id, String status, [String? evidence]) =>
      _post('/cqi-actions/$id/status', {'status': status, if (evidence != null) 'evidence_url': evidence});
  Future<void> verify(String id, bool approve) => _post('/cqi-actions/$id/verify', {'approve': approve});
  Future<void> evidence(String id, XFile file) async {
    final form = FormData.fromMap({'file': await MultipartFile.fromFile(file.path, filename: file.name)});
    await _dio.post('/cqi-actions/$id/evidence', data: form);
  }

  Future<Map<String, dynamic>> me(String offeringId) async =>
      ((await _get('/attainment/me', {'offering_id': offeringId})) as Map).cast<String, dynamic>();
}

final obeRepositoryProvider = Provider<ObeRepository>((ref) => ObeRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, Object e) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
String _lv(dynamic v) => v == null ? '—' : (v as num).toStringAsFixed(2);

Color _heat(num? v) {
  if (v == null) return Colors.grey.shade200;
  if (v >= 2.5) return Colors.green.shade300;
  if (v >= 2) return Colors.green.shade100;
  if (v >= 1) return Colors.amber.shade100;
  return Colors.red.shade100;
}

Widget _gap(dynamic g) {
  if (g == null) return const Text('—');
  final v = (g as num).toDouble();
  final c = v <= 0 ? Colors.green : (v <= 0.5 ? Colors.orange : Colors.red);
  return Chip(label: Text(v <= 0 ? 'met' : '−${v.toStringAsFixed(2)}'), backgroundColor: c.withValues(alpha: 0.15), visualDensity: VisualDensity.compact);
}

// ---- faculty: my offerings → CO attainment ----------------------------------------------------------------------------------------
class AttainmentOfferingsScreen extends ConsumerStatefulWidget {
  const AttainmentOfferingsScreen({super.key});

  @override
  ConsumerState<AttainmentOfferingsScreen> createState() => _AttainmentOfferingsScreenState();
}

class _AttainmentOfferingsScreenState extends ConsumerState<AttainmentOfferingsScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(obeRepositoryProvider).myOfferings();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Attainment')),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = ref.read(obeRepositoryProvider).myOfferings()),
        child: FutureBuilder<List<Map<String, dynamic>>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final rows = snap.data!;
            if (rows.isEmpty) return ListView(children: const [ListTile(title: Text('No offerings.'))]);
            return ListView(children: [
              for (final o in rows)
                ListTile(
                  title: Text('${o['course_code'] ?? o['course']?['code'] ?? ''} ${o['section_code'] ?? ''}'),
                  subtitle: Text('${o['course_title'] ?? o['course']?['title'] ?? ''}'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => CoAttainmentScreen(offeringId: '${o['id']}'))),
                ),
            ]);
          },
        ),
      ),
    );
  }
}

class CoAttainmentScreen extends ConsumerWidget {
  const CoAttainmentScreen({super.key, required this.offeringId});

  final String offeringId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(obeRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('CO attainment')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: Future.wait([repo.co(offeringId), repo.coHeatmap(offeringId)]),
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final d = snap.data![0];
          final heat = snap.data![1];
          final cos = ((d['cos'] as List?) ?? const []).cast<Map<String, dynamic>>();
          final columns = ((heat['columns'] as List?) ?? const []).cast<String>();
          final cells = ((heat['cells'] as List?) ?? const []).cast<List<dynamic>>();
          final rows = ((heat['rows'] as List?) ?? const []).cast<String>();
          return ListView(padding: const EdgeInsets.all(12), children: [
            if (cos.isEmpty) const ListTile(title: Text('No computed run yet — compute from the web workspace.')),
            for (final c in cos)
              Card(
                child: ListTile(
                  title: Text('${c['co']} · final ${_lv(c['final_level'])} / target ${_lv(c['target'])}'),
                  subtitle: Text('CIA ${_lv(c['cia_level'])} · ESE ${_lv(c['ese_level'])} · direct ${_lv(c['direct_level'])} · indirect ${_lv(c['indirect_level'])}\n'
                      '${c['students_above_target']}/${c['students_assessed']} above target'),
                  isThreeLine: true,
                  trailing: _gap(c['gap']),
                ),
              ),
            if (rows.isNotEmpty) ...[
              const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: Text('Heatmap', style: TextStyle(fontWeight: FontWeight.w600))),
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Table(
                  defaultColumnWidth: const FixedColumnWidth(64),
                  border: TableBorder.all(color: Colors.grey.shade300),
                  children: [
                    TableRow(children: [const SizedBox(), for (final c in columns) Padding(padding: const EdgeInsets.all(4), child: Text(c, style: const TextStyle(fontSize: 10)))]),
                    for (var i = 0; i < rows.length; i++)
                      TableRow(children: [
                        Padding(padding: const EdgeInsets.all(4), child: Text(rows[i], style: const TextStyle(fontSize: 11))),
                        for (final v in cells[i])
                          Container(color: _heat(v as num?), padding: const EdgeInsets.all(4), child: Text(_lv(v), style: const TextStyle(fontSize: 11))),
                      ]),
                  ],
                ),
              ),
            ],
          ]);
        },
      ),
    );
  }
}

// ---- HOD / IQAC: attainment dashboard ----------------------------------------------------------------------------------------------
class AttainmentDashboardScreen extends ConsumerStatefulWidget {
  const AttainmentDashboardScreen({super.key});

  @override
  ConsumerState<AttainmentDashboardScreen> createState() => _AttainmentDashboardScreenState();
}

class _AttainmentDashboardScreenState extends ConsumerState<AttainmentDashboardScreen> {
  String? _program;
  String? _batch;
  late final Future<List<Map<String, dynamic>>> _programs = ref.read(obeRepositoryProvider).programs();
  Future<List<Map<String, dynamic>>>? _batches;
  Future<Map<String, dynamic>>? _dash;

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(obeRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Attainment dashboard')),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        FutureBuilder<List<Map<String, dynamic>>>(
          future: _programs,
          builder: (context, snap) => DropdownButtonFormField<String>(
            value: _program,
            decoration: const InputDecoration(labelText: 'Programme'),
            items: [for (final p in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${p['id']}', child: Text('${p['code']}'))],
            onChanged: (v) => setState(() {
              _program = v;
              _batch = null;
              _dash = null;
              _batches = v == null ? null : repo.batches(v);
            }),
          ),
        ),
        if (_batches != null)
          FutureBuilder<List<Map<String, dynamic>>>(
            future: _batches,
            builder: (context, snap) => DropdownButtonFormField<String>(
              value: _batch,
              decoration: const InputDecoration(labelText: 'Batch'),
              items: [for (final b in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${b['id']}', child: Text('${b['code'] ?? b['admission_year']}'))],
              onChanged: (v) => setState(() {
                _batch = v;
                _dash = v == null ? null : repo.dashboard(_program!, v);
              }),
            ),
          ),
        if (_dash != null)
          FutureBuilder<Map<String, dynamic>>(
            future: _dash,
            builder: (context, snap) {
              if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
              if (!snap.hasData) return const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()));
              final d = snap.data!;
              final radar = ((d['radar'] as List?) ?? const []).cast<Map<String, dynamic>>();
              final gaps = ((d['gaps'] as List?) ?? const []).cast<Map<String, dynamic>>();
              return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const SizedBox(height: 12),
                Text('Coverage ${d['coverage_pct'] ?? 0}%'),
                if (radar.length >= 3)
                  SizedBox(
                    height: 280,
                    child: RadarChart(RadarChartData(
                      radarShape: RadarShape.polygon,
                      tickCount: 3,
                      getTitle: (i, _) => RadarChartTitle(text: '${radar[i]['outcome']}'),
                      dataSets: [
                        RadarDataSet(
                          fillColor: Colors.indigo.withValues(alpha: 0.3),
                          borderColor: Colors.indigo,
                          dataEntries: [for (final r in radar) RadarEntry(value: ((r['final'] as num?) ?? 0).toDouble())],
                        ),
                        RadarDataSet(
                          fillColor: Colors.transparent,
                          borderColor: Colors.orange,
                          dataEntries: [for (final r in radar) RadarEntry(value: ((r['target'] as num?) ?? 0).toDouble())],
                        ),
                      ],
                    )),
                  ),
                const Padding(padding: EdgeInsets.symmetric(vertical: 8), child: Text('Gap list', style: TextStyle(fontWeight: FontWeight.w600))),
                if (gaps.isEmpty) const ListTile(title: Text('No gaps.')),
                for (final g in gaps)
                  ListTile(title: Text('${g['label']} · ${g['outcome']}'), subtitle: Text('${g['suggested_action']}'), trailing: _gap(g['gap'])),
              ]);
            },
          ),
      ]),
    );
  }
}

// ---- CQI actions ------------------------------------------------------------------------------------------------------------------
class CqiActionsScreen extends ConsumerStatefulWidget {
  const CqiActionsScreen({super.key});

  @override
  ConsumerState<CqiActionsScreen> createState() => _CqiActionsScreenState();
}

class _CqiActionsScreenState extends ConsumerState<CqiActionsScreen> {
  bool _mine = true;
  late Future<List<Map<String, dynamic>>> _f = ref.read(obeRepositoryProvider).cqi(mine: _mine);

  void _reload() => setState(() => _f = ref.read(obeRepositoryProvider).cqi(mine: _mine));

  Future<void> _act(Future<void> Function() fn, String done) async {
    try {
      await fn();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
      _reload();
    } catch (e) {
      if (mounted) _snack(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(obeRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('CQI actions'), actions: [
        Row(children: [const Text('Mine'), Switch(value: _mine, onChanged: (v) => setState(() { _mine = v; _f = repo.cqi(mine: v); }))]),
      ]),
      body: RefreshIndicator(
        onRefresh: () async => _reload(),
        child: FutureBuilder<List<Map<String, dynamic>>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final rows = snap.data!;
            if (rows.isEmpty) return ListView(children: const [ListTile(title: Text('No actions.'))]);
            return ListView(padding: const EdgeInsets.all(8), children: [
              for (final a in rows)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${a['scope_label'] ?? a['scope_type']}${a['outcome'] != null ? ' · ${a['outcome']}' : ''}', style: const TextStyle(fontWeight: FontWeight.w600)),
                      const SizedBox(height: 4),
                      Text('${a['action_text']}'),
                      const SizedBox(height: 4),
                      Text('${a['status']} · ${a['owner_name'] ?? 'unassigned'} · due ${a['due_on'] ?? '—'}${a['overdue'] == true ? ' · OVERDUE' : ''}',
                          style: TextStyle(color: a['overdue'] == true ? Colors.red : Colors.grey.shade700, fontSize: 12)),
                      if (a['evidence_url'] != null) Text('Evidence attached', style: TextStyle(color: Colors.green.shade700, fontSize: 12)),
                      Wrap(spacing: 8, children: [
                        if (a['status'] == 'planned') TextButton(onPressed: () => _act(() => repo.status('${a['id']}', 'in_progress'), 'Started'), child: const Text('Start')),
                        if (a['status'] == 'planned' || a['status'] == 'in_progress')
                          TextButton.icon(
                            icon: const Icon(Icons.photo_camera_outlined, size: 18),
                            label: const Text('Evidence'),
                            onPressed: () async {
                              final file = await ImagePicker().pickImage(source: ImageSource.camera, imageQuality: 70);
                              if (file != null) await _act(() => repo.evidence('${a['id']}', file), 'Evidence uploaded');
                            },
                          ),
                        if ((a['status'] == 'planned' || a['status'] == 'in_progress') && a['evidence_url'] != null)
                          TextButton(onPressed: () => _act(() => repo.status('${a['id']}', 'done'), 'Marked done'), child: const Text('Done')),
                        if (a['status'] == 'done') ...[
                          TextButton(onPressed: () => _act(() => repo.verify('${a['id']}', true), 'Verified'), child: const Text('Verify')),
                          TextButton(onPressed: () => _act(() => repo.verify('${a['id']}', false), 'Returned'), child: const Text('Return')),
                        ],
                      ]),
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

// ---- student: course outcomes (setting obe.show_students) ----------------------------------------------------------------------------
class StudentOutcomesScreen extends ConsumerWidget {
  const StudentOutcomesScreen({super.key, required this.offeringId});

  final String offeringId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Course outcomes')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: ref.read(obeRepositoryProvider).me(offeringId),
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final cos = ((snap.data!['cos'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return ListView(children: [
            for (final c in cos)
              ListTile(
                title: Text('${c['co']} · ${c['marks_pct'] ?? '—'}%'),
                subtitle: Text('${c['statement'] ?? ''}'),
                trailing: Icon(c['above_target'] == true ? Icons.check_circle : Icons.info_outline, color: c['above_target'] == true ? Colors.green : Colors.orange),
              ),
          ]);
        },
      ),
    );
  }
}
