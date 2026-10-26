import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 32 mobile (Prompts/32 §32.10). IQAC coordinator: **IQAC** with Home (criteria completion, submissions due,
/// alerts) · Metrics (grid read, verify, override read) · Evidence (upload a document / photo link with tags,
/// suggestions accept) · Cycles (progress, response status, review approve / return) · More (audit findings, consistency
/// alerts); HOD: **Department quality** (department metrics, assigned responses, evidence upload, findings owned);
/// faculty: assigned responses and evidence upload in the same screen (the API narrows every list).
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String currentAcademicYear() {
  final now = DateTime.now();
  final y = now.month >= 6 ? now.year : now.year - 1;
  return '$y-${'${y + 1}'.substring(2)}';
}

String _num(dynamic v) {
  if (v == null) return '—';
  final n = v is num ? v : num.tryParse('$v');
  return n == null ? '$v' : (n == n.roundToDouble() ? n.toStringAsFixed(0) : n.toStringAsFixed(2));
}

class IqacRepository {
  IqacRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();
  Map<String, dynamic> _map(dynamic v) => ((v as Map?) ?? const {}).cast<String, dynamic>();

  Future<Map<String, dynamic>> dashboard(String period) async => _map(await _get('/accreditation/dashboard', {'period': period}));
  Future<List<Map<String, dynamic>>> metrics(String period, {String? scope}) async =>
      _list(await _get('/accreditation/metrics', {'period': period, 'per_page': 300, if (scope != null) 'scope': scope}));
  Future<void> verify(Map<String, dynamic> m) => _post('/accreditation/metrics/${Uri.encodeComponent('${m['key']}')}/verify', {
        'period_label': m['period'],
        if (m['college_id'] != null) 'college_id': m['college_id'],
        if (m['program_id'] != null) 'program_id': m['program_id'],
        'action': 'verify',
      });
  Future<List<Map<String, dynamic>>> evidence() async => _list(await _get('/accreditation/evidence', {'per_page': 50}));
  Future<void> upload(Map<String, dynamic> body) => _post('/accreditation/evidence', body);
  Future<List<Map<String, dynamic>>> suggestions() async => _list(await _get('/accreditation/evidence/suggestions'));
  Future<void> acceptSuggestion(String id) => _post('/accreditation/evidence/suggestions/${Uri.encodeComponent(id)}/accept');
  Future<List<Map<String, dynamic>>> cycles() async => _list(await _get('/accreditation/cycles'));
  Future<List<Map<String, dynamic>>> criteria(String cid) async => _list(await _get('/accreditation/cycles/$cid/criteria'));
  Future<void> review(String cid, String code, String action) =>
      _post('/accreditation/cycles/$cid/criteria/${Uri.encodeComponent(code)}/review', {'action': action});
  Future<List<Map<String, dynamic>>> audits() async => _list(await _get('/accreditation/audits'));
  Future<void> closeFinding(String aid, int no) =>
      _dio.put<Map<String, dynamic>>('/accreditation/audits/$aid/findings/$no', data: {'status': 'closed', 'action_taken': 'Closed from mobile'});
  Future<Map<String, dynamic>> consistency(String period) async => _map(await _get('/accreditation/consistency', {'period': period}));
}

final iqacRepositoryProvider = Provider<IqacRepository>((ref) => IqacRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

Future<void> _act(BuildContext context, Future<void> Function() fn, String done, VoidCallback refresh) async {
  try {
    await fn();
    if (context.mounted) _snack(context, done);
    refresh();
  } catch (e) {
    if (context.mounted) _snack(context, _error(e));
  }
}

Future<String?> _ask(BuildContext context, String title, {String hint = ''}) async {
  final c = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(controller: c, decoration: InputDecoration(hintText: hint)),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('OK'))],
    ),
  );
}

Widget _futureList(Future<List<Map<String, dynamic>>> f, Widget Function(Map<String, dynamic>) row, {String empty = 'Nothing yet'}) => FutureBuilder<List<Map<String, dynamic>>>(
      future: f,
      builder: (context, snap) {
        if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
        if (!snap.hasData) return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
        if (snap.data!.isEmpty) return Padding(padding: const EdgeInsets.all(16), child: Text(empty));
        return ListView(children: [for (final r in snap.data!) row(r)]);
      },
    );

Widget _stat(String label, String value) => Card(
      child: Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: const TextStyle(fontSize: 12)), Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600))])),
    );

// ---- IQAC coordinator / HOD / faculty ------------------------------------------------------------------------------------------
class IqacHubScreen extends ConsumerStatefulWidget {
  const IqacHubScreen({super.key, this.department = false});

  /// HOD / faculty view: department-scoped metrics, no dashboard tab.
  final bool department;

  @override
  ConsumerState<IqacHubScreen> createState() => _IqacHubScreenState();
}

class _IqacHubScreenState extends ConsumerState<IqacHubScreen> {
  late final IqacRepository _repo = ref.read(iqacRepositoryProvider);
  final String _period = currentAcademicYear();

  @override
  Widget build(BuildContext context) {
    final tabs = [if (!widget.department) const Tab(text: 'Home'), const Tab(text: 'Metrics'), const Tab(text: 'Evidence'), const Tab(text: 'Cycles'), const Tab(text: 'More')];
    return DefaultTabController(
      length: tabs.length,
      child: Column(children: [
        TabBar(isScrollable: true, tabs: tabs),
        Expanded(
          child: TabBarView(children: [
            if (!widget.department) _HomeTab(repo: _repo, period: _period),
            _MetricsTab(repo: _repo, period: _period, scope: widget.department ? 'department' : null),
            _EvidenceTab(repo: _repo),
            _CyclesTab(repo: _repo),
            _MoreTab(repo: _repo, period: _period),
          ]),
        ),
      ]),
    );
  }
}

class _HomeTab extends StatelessWidget {
  const _HomeTab({required this.repo, required this.period});

  final IqacRepository repo;
  final String period;

  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
        future: repo.dashboard(period),
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          final d = snap.data;
          if (d == null) return const Center(child: CircularProgressIndicator());
          final sim = ((d['score_simulation'] as Map?) ?? const {}).cast<String, dynamic>();
          final cycles = ((d['cycles'] as List?) ?? const []).cast<Map<String, dynamic>>();
          final due = ((d['submissions_due'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return ListView(children: [
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              childAspectRatio: 2.4,
              padding: const EdgeInsets.all(8),
              children: [
                _stat('Verified metrics', '${d['metrics_verified_pct'] ?? 0} %'),
                _stat('Overrides pending', '${d['overrides_pending'] ?? 0}'),
                _stat('Consistency alerts', '${d['consistency_alerts'] ?? 0}'),
                _stat('NAAC estimate', '${sim['grade_estimate'] ?? '—'}'),
              ],
            ),
            for (final c in cycles)
              ListTile(
                title: Text('${c['name']}'),
                subtitle: LinearProgressIndicator(value: ((c['completion_pct'] as num?) ?? 0) / 100),
                trailing: Text('${c['completion_pct']} %'),
              ),
            const Padding(padding: EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text('Submissions due', style: TextStyle(fontWeight: FontWeight.w600))),
            for (final s in due) ListTile(dense: true, title: Text('${s['type']} · ${s['period']}'), trailing: Text('${s['status']}')),
          ]);
        },
      );
}

class _MetricsTab extends StatefulWidget {
  const _MetricsTab({required this.repo, required this.period, this.scope});

  final IqacRepository repo;
  final String period;
  final String? scope;

  @override
  State<_MetricsTab> createState() => _MetricsTabState();
}

class _MetricsTabState extends State<_MetricsTab> {
  late Future<List<Map<String, dynamic>>> _f = widget.repo.metrics(widget.period, scope: widget.scope);

  void _refresh() => setState(() => _f = widget.repo.metrics(widget.period, scope: widget.scope));

  @override
  Widget build(BuildContext context) => _futureList(
        _f,
        (m) => ListTile(
          title: Text('${m['name'] ?? m['key']}'),
          subtitle: Text('${m['period']} · ${m['source']}${m['verified'] == true ? ' · verified' : ''}${m['pending_override'] != null ? ' · override pending' : ''}'
              '${m['override_reason'] != null ? '\n${m['override_reason']}' : ''}'),
          isThreeLine: m['override_reason'] != null,
          trailing: Row(mainAxisSize: MainAxisSize.min, children: [
            Text(_num(m['value'])),
            if (m['verified'] != true) IconButton(icon: const Icon(Icons.verified_outlined), tooltip: 'Verify', onPressed: () => _act(context, () => widget.repo.verify(m), 'Verified', _refresh)),
          ]),
        ),
        empty: 'No metric values for ${widget.period}',
      );
}

class _EvidenceTab extends StatefulWidget {
  const _EvidenceTab({required this.repo});

  final IqacRepository repo;

  @override
  State<_EvidenceTab> createState() => _EvidenceTabState();
}

class _EvidenceTabState extends State<_EvidenceTab> {
  late Future<List<Map<String, dynamic>>> _ev = widget.repo.evidence();
  late Future<List<Map<String, dynamic>>> _sug = widget.repo.suggestions();

  void _refresh() => setState(() {
        _ev = widget.repo.evidence();
        _sug = widget.repo.suggestions();
      });

  Future<void> _upload() async {
    final url = await _ask(context, 'Document / photo link', hint: 'https://… (uploaded to Files)');
    if (url == null || url.isEmpty || !mounted) return;
    final title = await _ask(context, 'Title');
    if (title == null || title.isEmpty || !mounted) return;
    final code = await _ask(context, 'NAAC criterion (e.g. 7.1.3)', hint: 'optional');
    if (!mounted) return;
    final tags = await _ask(context, 'Tags (comma separated)', hint: 'optional');
    if (!mounted) return;
    await _act(
      context,
      () => widget.repo.upload({
        'title': title,
        'file_url': url,
        'doc_type': url.toLowerCase().endsWith('.jpg') || url.toLowerCase().endsWith('.png') ? 'photo' : 'report',
        'period_label': currentAcademicYear(),
        if (code != null && code.isNotEmpty) 'criterion_code': code,
        'tags': [for (final t in (tags ?? '').split(',')) if (t.trim().isNotEmpty) t.trim()],
      }),
      'Uploaded',
      _refresh,
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        floatingActionButton: FloatingActionButton.extended(onPressed: _upload, icon: const Icon(Icons.upload_file_outlined), label: const Text('Upload')),
        body: Column(children: [
          SizedBox(
            height: 160,
            child: _futureList(
              _sug,
              (s) => ListTile(
                dense: true,
                leading: const Icon(Icons.lightbulb_outline),
                title: Text('${s['title']}'),
                subtitle: Text('${s['module']} · ${s['criterion_code'] ?? '—'}'),
                trailing: TextButton(onPressed: () => _act(context, () => widget.repo.acceptSuggestion('${s['id']}'), 'Accepted', _refresh), child: const Text('Accept')),
              ),
              empty: 'No suggestions',
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: _futureList(
              _ev,
              (e) => ListTile(title: Text('${e['title']}'), subtitle: Text('${e['criterion_code'] ?? '—'} · ${e['period_label'] ?? '—'} · ${e['verified'] == true ? 'verified' : 'unverified'}')),
              empty: 'No evidence uploaded',
            ),
          ),
        ]),
      );
}

class _CyclesTab extends StatefulWidget {
  const _CyclesTab({required this.repo});

  final IqacRepository repo;

  @override
  State<_CyclesTab> createState() => _CyclesTabState();
}

class _CyclesTabState extends State<_CyclesTab> {
  late final Future<List<Map<String, dynamic>>> _f = widget.repo.cycles();

  @override
  Widget build(BuildContext context) => _futureList(
        _f,
        (c) => ListTile(
          title: Text('${c['name']}'),
          subtitle: Text('${c['framework_code']} · ${c['status']} · ${c['completion_pct']} %'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => _CycleCriteriaScreen(repo: widget.repo, cycle: c))),
        ),
        empty: 'No cycles',
      );
}

class _CycleCriteriaScreen extends StatefulWidget {
  const _CycleCriteriaScreen({required this.repo, required this.cycle});

  final IqacRepository repo;
  final Map<String, dynamic> cycle;

  @override
  State<_CycleCriteriaScreen> createState() => _CycleCriteriaScreenState();
}

class _CycleCriteriaScreenState extends State<_CycleCriteriaScreen> {
  late Future<List<Map<String, dynamic>>> _f = widget.repo.criteria('${widget.cycle['id']}');

  void _refresh() => setState(() => _f = widget.repo.criteria('${widget.cycle['id']}'));

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text('${widget.cycle['name']}')),
        body: _futureList(
          _f,
          (r) => ListTile(
            title: Text('${r['code']} ${r['title']}'),
            subtitle: Text('${r['status']} · ${r['owner_name'] ?? 'unassigned'} · ${r['word_count']} words'),
            trailing: r['status'] == 'in_review'
                ? Row(mainAxisSize: MainAxisSize.min, children: [
                    IconButton(icon: const Icon(Icons.check_circle_outline), tooltip: 'Approve', onPressed: () => _act(context, () => widget.repo.review('${widget.cycle['id']}', '${r['code']}', 'approve'), 'Approved', _refresh)),
                    IconButton(icon: const Icon(Icons.undo), tooltip: 'Return', onPressed: () => _act(context, () => widget.repo.review('${widget.cycle['id']}', '${r['code']}', 'reject'), 'Returned', _refresh)),
                  ])
                : null,
          ),
          empty: 'No criteria visible to you',
        ),
      );
}

class _MoreTab extends StatefulWidget {
  const _MoreTab({required this.repo, required this.period});

  final IqacRepository repo;
  final String period;

  @override
  State<_MoreTab> createState() => _MoreTabState();
}

class _MoreTabState extends State<_MoreTab> {
  late Future<List<Map<String, dynamic>>> _audits = widget.repo.audits();
  late final Future<Map<String, dynamic>> _cons = widget.repo.consistency(widget.period);

  void _refresh() => setState(() => _audits = widget.repo.audits());

  @override
  Widget build(BuildContext context) => ListView(children: [
        const Padding(padding: EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text('Audit findings', style: TextStyle(fontWeight: FontWeight.w600))),
        FutureBuilder<List<Map<String, dynamic>>>(
          future: _audits,
          builder: (context, snap) {
            if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            return Column(children: [
              for (final a in snap.data!)
                for (final f in ((a['findings'] as List?) ?? const []).cast<Map<String, dynamic>>())
                  if (f['status'] != 'closed')
                    ListTile(
                      dense: true,
                      title: Text('${f['text']}'),
                      subtitle: Text('${a['audit_type']} · ${a['period_label']} · due ${f['due_on'] ?? '—'}'),
                      trailing: TextButton(onPressed: () => _act(context, () => widget.repo.closeFinding('${a['id']}', (f['no'] as num).toInt()), 'Closed', _refresh), child: const Text('Close')),
                    ),
            ]);
          },
        ),
        const Padding(padding: EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text('Consistency alerts', style: TextStyle(fontWeight: FontWeight.w600))),
        FutureBuilder<Map<String, dynamic>>(
          future: _cons,
          builder: (context, snap) {
            if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
            final checks = ((snap.data?['checks'] as List?) ?? const []).cast<Map<String, dynamic>>();
            return Column(children: [
              for (final c in checks)
                ListTile(dense: true, leading: Icon(c['status'] == 'fail' ? Icons.error_outline : Icons.check_circle_outline), title: Text('${c['name']}'), trailing: Text('${c['status']}')),
            ]);
          },
        ),
      ]);
}
