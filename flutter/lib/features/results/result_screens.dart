import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/providers.dart';

/// Phase 15 mobile (Prompts/15 §15.10): student **Results** (published terms, SGPA / CGPA, grade-card download),
/// faculty **Evaluation** (assigned bundles → dummy-number entry with a numeric pad, question-wise when the paper has a
/// pattern, bundle submit), COE **Result runs** (anomaly count, verify / approve / publish with confirmation). Decode is
/// web-only (IP allow-list). Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class ResultRepository {
  ResultRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path,
          data: body ?? {}, options: Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()})))
      .data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<Map<String, dynamic>> myResults() async => ((await _get('/results/me')) as Map).cast<String, dynamic>();
  String gradeCardUrl(String id) => '${_dio.options.baseUrl}/grade-cards/$id.pdf';
  Future<List<Map<String, dynamic>>> myBundles() async => _list(await _get('/valuation/me/bundles'));
  Future<List<Map<String, dynamic>>> scripts(String bundleId) async => _list(await _get('/valuation/bundles/$bundleId/scripts'));
  Future<void> mark(String scriptId, int round, num marks, Map<String, num>? qw) =>
      _post('/answer-scripts/$scriptId/valuations/$round', {'marks': marks, if (qw != null && qw.isNotEmpty) 'question_wise': qw});
  Future<void> submitBundle(String bundleId) => _post('/valuation/bundles/$bundleId/submit');
  Future<List<Map<String, dynamic>>> runs() async => _list(await _get('/result-runs'));
  Future<void> runAction(String id, String action, [Map<String, dynamic>? body]) => _post('/result-runs/$id/$action', body ?? {});
}

final resultRepositoryProvider = Provider<ResultRepository>((ref) => ResultRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, Object e) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));

class StudentResultsScreen extends ConsumerStatefulWidget {
  const StudentResultsScreen({super.key});

  @override
  ConsumerState<StudentResultsScreen> createState() => _StudentResultsScreenState();
}

class _StudentResultsScreenState extends ConsumerState<StudentResultsScreen> {
  late Future<Map<String, dynamic>> _r = ref.read(resultRepositoryProvider).myResults();

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(resultRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Results')),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _r = repo.myResults()),
        child: FutureBuilder<Map<String, dynamic>>(
          future: _r,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final d = snap.data!;
            final terms = ((d['terms'] as List?) ?? const []).cast<Map<String, dynamic>>();
            return ListView(padding: const EdgeInsets.all(12), children: [
              ListTile(title: Text('CGPA ${d['cgpa'] ?? '—'}'), subtitle: Text('Credits ${d['credits_earned'] ?? '—'} · standing ${d['standing'] ?? '—'}')),
              if (terms.isEmpty) const ListTile(title: Text('No published results yet.')),
              for (final t in terms) _TermCard(term: (t['term'] as Map).cast<String, dynamic>(), courses: ((t['courses'] as List?) ?? const []).cast<Map<String, dynamic>>(), repo: repo),
            ]);
          },
        ),
      ),
    );
  }
}

class _TermCard extends StatelessWidget {
  const _TermCard({required this.term, required this.courses, required this.repo});

  final Map<String, dynamic> term;
  final List<Map<String, dynamic>> courses;
  final ResultRepository repo;

  @override
  Widget build(BuildContext context) => Card(
        child: ExpansionTile(
          title: Text('Term ${term['term_number']} · SGPA ${term['sgpa'] ?? '—'}'),
          subtitle: Text('CGPA ${term['cgpa'] ?? '—'}${(term['version'] as num? ?? 1) > 1 ? ' · revised' : ''}'),
          trailing: term['grade_card_id'] == null
              ? null
              : IconButton(
                  icon: const Icon(Icons.share),
                  onPressed: () => launchUrl(Uri.parse(repo.gradeCardUrl('${term['grade_card_id']}')), mode: LaunchMode.externalApplication),
                ),
          children: [
            for (final c in courses)
              ListTile(
                dense: true,
                title: Text('${c['course_code']} ${c['course_title'] ?? ''}'),
                subtitle: Text('${c['credits']} credits · ${c['result_status']}'),
                trailing: Chip(label: Text('${c['letter_grade'] ?? '—'}')),
              ),
          ],
        ),
      );
}

class EvaluationScreen extends ConsumerStatefulWidget {
  const EvaluationScreen({super.key});

  @override
  ConsumerState<EvaluationScreen> createState() => _EvaluationScreenState();
}

class _EvaluationScreenState extends ConsumerState<EvaluationScreen> {
  late Future<List<Map<String, dynamic>>> _b = ref.read(resultRepositoryProvider).myBundles();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Evaluation')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: _b,
          builder: (context, snap) => !snap.hasData
              ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
              : ListView(children: [
                  for (final b in snap.data!)
                    ListTile(
                      title: Text('${b['bundle_number']} · ${b['paper_code'] ?? ''}'),
                      subtitle: Text('Round ${b['valuation_round']} · ${b['valued']}/${b['scripts']} · ${b['status']}'),
                      onTap: () async {
                        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => _BundleEntryScreen(bundle: b)));
                        setState(() => _b = ref.read(resultRepositoryProvider).myBundles());
                      },
                    ),
                  if (snap.data!.isEmpty) const ListTile(title: Text('No bundles assigned.')),
                ]),
        ),
      );
}

class _BundleEntryScreen extends ConsumerStatefulWidget {
  const _BundleEntryScreen({required this.bundle});

  final Map<String, dynamic> bundle;

  @override
  ConsumerState<_BundleEntryScreen> createState() => _BundleEntryScreenState();
}

class _BundleEntryScreenState extends ConsumerState<_BundleEntryScreen> {
  late Future<List<Map<String, dynamic>>> _s = ref.read(resultRepositoryProvider).scripts('${widget.bundle['bundle_id']}');

  List<String> get _questions {
    final p = widget.bundle['qp_pattern'];
    if (p is Map && p['questions'] is List) return [for (final q in p['questions'] as List) '${(q as Map)['q'] ?? q['id']}'];
    if (p is Map) return [for (final k in p.keys) if (k != 'total') '$k'];
    return const [];
  }

  Future<void> _enter(Map<String, dynamic> s) async {
    final ctrls = {for (final q in (_questions.isEmpty ? ['total'] : _questions)) q: TextEditingController()};
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Script ${s['dummy_number']}'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            for (final e in ctrls.entries)
              TextField(
                controller: e.value,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]'))],
                decoration: InputDecoration(labelText: e.key == 'total' ? 'Marks (max ${widget.bundle['max_marks']})' : 'Q${e.key}'),
              ),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Save')),
        ],
      ),
    );
    if (ok != true) return;
    final qw = <String, num>{
      for (final e in ctrls.entries)
        if (e.key != 'total' && e.value.text.isNotEmpty) e.key: num.parse(e.value.text),
    };
    final total = qw.isNotEmpty ? qw.values.fold<num>(0, (a, b) => a + b) : num.tryParse(ctrls['total']!.text) ?? 0;
    try {
      await ref.read(resultRepositoryProvider).mark('${s['id']}', widget.bundle['valuation_round'] as int, total, qw);
      setState(() => _s = ref.read(resultRepositoryProvider).scripts('${widget.bundle['bundle_id']}'));
    } catch (e) {
      if (mounted) _snack(context, e);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text('${widget.bundle['bundle_number']}'), actions: [
          IconButton(
            icon: const Icon(Icons.lock),
            tooltip: 'Submit bundle',
            onPressed: () async {
              try {
                await ref.read(resultRepositoryProvider).submitBundle('${widget.bundle['bundle_id']}');
                if (context.mounted) Navigator.pop(context);
              } catch (e) {
                if (context.mounted) _snack(context, e);
              }
            },
          ),
        ]),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: _s,
          builder: (context, snap) => !snap.hasData
              ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
              : ListView(children: [
                  for (final s in snap.data!)
                    ListTile(
                      title: Text('${s['dummy_number']}', style: const TextStyle(fontFamily: 'monospace')),
                      trailing: Text('${s['marks'] ?? '—'}'),
                      enabled: s['is_locked'] != true,
                      onTap: s['is_locked'] == true ? null : () => _enter(s),
                    ),
                ]),
        ),
      );
}

class ResultRunsScreen extends ConsumerStatefulWidget {
  const ResultRunsScreen({super.key});

  @override
  ConsumerState<ResultRunsScreen> createState() => _ResultRunsScreenState();
}

class _ResultRunsScreenState extends ConsumerState<ResultRunsScreen> {
  late Future<List<Map<String, dynamic>>> _r = ref.read(resultRepositoryProvider).runs();

  Future<void> _act(Map<String, dynamic> r, String action, Map<String, dynamic> body) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('${action[0].toUpperCase()}${action.substring(1)} run?'),
        content: Text('${r['session_name'] ?? ''} · ${r['run_type']} · ${r['anomalies_count']} anomalies'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Confirm')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(resultRepositoryProvider).runAction('${r['id']}', action, body);
      setState(() => _r = ref.read(resultRepositoryProvider).runs());
    } catch (e) {
      if (mounted) _snack(context, e);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Result runs')),
        body: FutureBuilder<List<Map<String, dynamic>>>(
          future: _r,
          builder: (context, snap) => !snap.hasData
              ? Center(child: snap.hasError ? Text(_error(snap.error!)) : const CircularProgressIndicator())
              : ListView(children: [
                  for (final r in snap.data!)
                    ListTile(
                      title: Text('${r['session_name'] ?? ''} · ${r['run_type']}'),
                      subtitle: Text('${r['status']} · ${r['anomalies_count']} anomalies'),
                      trailing: switch ('${r['status']}') {
                        'computed' => TextButton(onPressed: () => _act(r, 'verify', {'acknowledge_anomalies': true}), child: const Text('Verify')),
                        'verified' => TextButton(onPressed: () => _act(r, 'approve', {}), child: const Text('Approve')),
                        'approved' => TextButton(onPressed: () => _act(r, 'publish', {'audience': 'student', 'notify': true}), child: const Text('Publish')),
                        _ => null,
                      },
                    ),
                  if (snap.data!.isEmpty) const ListTile(title: Text('No runs.')),
                ]),
        ),
      );
}
