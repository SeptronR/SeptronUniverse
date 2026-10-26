import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 34 mobile (Prompts/34 §34.10). College admin / principal: **Affiliation** (dashboard, applications with
/// deficiency responses and evidence links, dues, submission windows, results release). College exam coordinator:
/// **Exam centre** (registrations routed, seating, bundles). University office: **Affiliation office** (portfolio
/// cards, scrutiny / decision inbox, inspection schedule; COE: gating per college with accept / lock). Inspection
/// committee member: **Inspections** (assigned inspections, findings capture, report upload). The API narrows every
/// list (college scope, inspector ownership, office all).
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _day(dynamic s) {
  final d = s == null ? null : DateTime.tryParse('$s');
  return d == null ? '—' : '${d.day.toString().padLeft(2, '0')}-${d.month.toString().padLeft(2, '0')}-${d.year}';
}

String _rupees(dynamic p) => p == null ? '—' : '₹${((p as num) / 100).toStringAsFixed(0)}';

class AffiliationRepository {
  AffiliationRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();
  Map<String, dynamic> _map(dynamic v) => ((v as Map?) ?? const {}).cast<String, dynamic>();

  // college
  Future<Map<String, dynamic>> myDashboard() async => _map(await _get('/affiliation/colleges/me/dashboard'));
  Future<Map<String, dynamic>> application(String id) async => _map(await _get('/affiliation/applications/$id'));
  Future<void> respond(String id, String did, String text, String? evidence) => _post(
      '/affiliation/applications/$id/deficiencies/$did/respond', {'response_text': text, if (evidence != null && evidence.isNotEmpty) 'evidence_url': evidence});
  Future<List<Map<String, dynamic>>> windows(String termId, String collegeId) async =>
      _list(await _get('/affiliation/submissions/windows', {'term_id': termId, 'college_id': collegeId}));
  // coordinator
  Future<List<Map<String, dynamic>>> myCentres() async => _list(await _get('/affiliation/exam-centres/me'));
  // office
  Future<Map<String, dynamic>> portfolio() async => _map(await _get('/affiliation/portfolio'));
  Future<List<Map<String, dynamic>>> queue(String status) async => _list(await _get('/affiliation/applications', {'status': status}));
  Future<void> scrutiny(String id, String action, String? remarks) => _post('/affiliation/applications/$id/scrutiny', {'action': action, 'remarks': remarks});
  Future<void> decide(String id, Map<String, dynamic> body) => _post('/affiliation/applications/$id/decide', body);
  Future<List<Map<String, dynamic>>> inspections() async => _list(await _get('/affiliation/inspections'));
  Future<List<Map<String, dynamic>>> gating(String sessionId) async => _list(await _get('/affiliation/exam-sessions/$sessionId/college-status'));
  Future<List<Map<String, dynamic>>> submissions(String status) async => _list(await _get('/affiliation/submissions', {'status': status}));
  Future<void> submissionAction(String id, String action, [String? remarks]) =>
      _post('/affiliation/submissions/$id/action', {'action': action, if (remarks != null) 'remarks': remarks});
  // inspector
  Future<List<Map<String, dynamic>>> myInspections() async => _list(await _get('/affiliation/inspections/me'));
  Future<void> report(String id, String url, List<Map<String, dynamic>> findings, String recommendation) =>
      _post('/affiliation/applications/$id/inspection/report', {'report_url': url, 'findings': findings, 'recommendation': recommendation});
}

final affiliationRepositoryProvider = Provider<AffiliationRepository>((ref) => AffiliationRepository(ref.watch(dioProvider)));

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
      content: TextField(controller: c, maxLines: 3, decoration: InputDecoration(hintText: hint)),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('OK'))],
    ),
  );
}

Widget _futureList(Future<List<Map<String, dynamic>>> f, Widget Function(Map<String, dynamic>) row, {String empty = 'Nothing pending'}) => FutureBuilder<List<Map<String, dynamic>>>(
      future: f,
      builder: (context, snap) {
        if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
        if (!snap.hasData) return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
        if (snap.data!.isEmpty) return Padding(padding: const EdgeInsets.all(16), child: Text(empty));
        return ListView(children: [for (final r in snap.data!) row(r)]);
      },
    );

Widget _card(String label, String value) => Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: const TextStyle(fontSize: 12)), Text(value, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600))]),
      ),
    );

// ---- college admin / principal ---------------------------------------------------------------------------------------------
class CollegeAffiliationScreen extends ConsumerStatefulWidget {
  const CollegeAffiliationScreen({super.key});

  @override
  ConsumerState<CollegeAffiliationScreen> createState() => _CollegeAffiliationScreenState();
}

class _CollegeAffiliationScreenState extends ConsumerState<CollegeAffiliationScreen> {
  late final AffiliationRepository _repo = ref.read(affiliationRepositoryProvider);
  int _tick = 0;

  void _refresh() => setState(() => _tick++);

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Map<String, dynamic>>(
      key: ValueKey(_tick),
      future: _repo.myDashboard(),
      builder: (context, snap) {
        if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
        if (!snap.hasData) return const Center(child: CircularProgressIndicator());
        final d = snap.data!;
        final p = (d['profile'] as Map).cast<String, dynamic>();
        final apps = ((d['applications'] as List?) ?? const []).cast<Map<String, dynamic>>();
        final approvals = ((d['approvals'] as List?) ?? const []).cast<Map<String, dynamic>>();
        final results = ((d['results_release'] as List?) ?? const []).cast<Map<String, dynamic>>();
        return RefreshIndicator(
          onRefresh: () async => _refresh(),
          child: ListView(padding: const EdgeInsets.all(12), children: [
            Text('${p['code']} · ${p['name']}', style: Theme.of(context).textTheme.titleMedium),
            Text('${p['college_type']} · ${p['affiliation_number'] ?? '—'}'),
            Wrap(children: [
              _card('Compliance', '${d['compliance_score']}'),
              _card('Programmes', '${(p['approvals'] as Map)['programmes']}'),
              _card('Dues', _rupees((d['dues'] as Map?)?['outstanding_paise'] ?? 0)),
            ]),
            const Divider(),
            const Text('Applications', style: TextStyle(fontWeight: FontWeight.w600)),
            for (final a in apps)
              ListTile(
                title: Text('${a['number'] ?? ''} · ${a['application_type']}'),
                subtitle: Text('${a['status']} · deficiencies open ${((a['deficiencies'] as List?) ?? const []).where((x) => (x as Map)['status'] != 'closed').length}'),
                onTap: () => Navigator.of(context)
                    .push(MaterialPageRoute<void>(builder: (_) => _ApplicationDetail(repo: _repo, id: '${a['id']}')))
                    .then((_) => _refresh()),
              ),
            const Divider(),
            const Text('Programme approvals', style: TextStyle(fontWeight: FontWeight.w600)),
            for (final a in approvals)
              ListTile(dense: true, title: Text('${a['program_code']} · intake ${a['sanctioned_intake']} + ${a['lateral_intake']}'), subtitle: Text('${a['approval_status']} · valid to ${_day(a['valid_to'])} · ${a['validity']}')),
            const Divider(),
            const Text('Results release', style: TextStyle(fontWeight: FontWeight.w600)),
            for (final r in results)
              ListTile(dense: true, title: Text('${r['session']}'), subtitle: Text('published ${r['published']} · ${r['gating'] ?? ''} ${((r['missing'] as List?) ?? const []).join(', ')}')),
          ]),
        );
      },
    );
  }
}

class _ApplicationDetail extends StatefulWidget {
  const _ApplicationDetail({required this.repo, required this.id});

  final AffiliationRepository repo;
  final String id;

  @override
  State<_ApplicationDetail> createState() => _ApplicationDetailState();
}

class _ApplicationDetailState extends State<_ApplicationDetail> {
  int _tick = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Application')),
      body: FutureBuilder<Map<String, dynamic>>(
        key: ValueKey(_tick),
        future: widget.repo.application(widget.id),
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final a = snap.data!;
          final defs = ((a['deficiencies'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return ListView(padding: const EdgeInsets.all(12), children: [
            Text('${a['number']} · ${a['application_type']} · ${a['status']}', style: Theme.of(context).textTheme.titleMedium),
            Text('Fee ${a['fee_status'] ?? '—'} ${_rupees(a['fee_total_paise'])}'),
            if ((a['missing_documents'] as List?)?.isNotEmpty ?? false) Text('Missing: ${(a['missing_documents'] as List).join(', ')}'),
            const Divider(),
            for (final d in defs)
              ListTile(
                title: Text('${d['area']} (${d['severity']})'),
                subtitle: Text('${d['observation']}\nDue ${_day(d['due_on'])} · ${d['status']}${d['response_text'] != null ? '\n${d['response_text']}' : ''}'),
                isThreeLine: true,
                trailing: d['status'] == 'open'
                    ? TextButton(
                        onPressed: () async {
                          final t = await _ask(context, 'Response', hint: 'What was done');
                          if (t == null || t.isEmpty || !context.mounted) return;
                          final ev = await _ask(context, 'Evidence link', hint: 'Photo / document URL (optional)');
                          if (!context.mounted) return;
                          await _act(context, () => widget.repo.respond(widget.id, '${d['id']}', t, ev), 'Response sent', () => setState(() => _tick++));
                        },
                        child: const Text('Respond'))
                    : null,
              ),
            if (a['decision'] != null) ListTile(title: Text('Decision: ${(a['decision'] as Map)['decision']}'), subtitle: Text('Order ${(a['decision'] as Map)['order_no']}')),
          ]);
        },
      ),
    );
  }
}

// ---- college exam coordinator ----------------------------------------------------------------------------------------------
class ExamCentreCoordinatorScreen extends ConsumerWidget {
  const ExamCentreCoordinatorScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(affiliationRepositoryProvider);
    return _futureList(
      repo.myCentres(),
      (d) {
        final c = (d['centre'] as Map).cast<String, dynamic>();
        final bundles = ((d['bundles'] as Map?) ?? const {}).entries.map((e) => '${e.key} ${e.value}').join(' · ');
        return Card(
          child: ListTile(
            title: Text('${c['centre_code']} · ${c['college_name']}'),
            subtitle: Text('Routed ${c['registrations_routed']} / capacity ${c['effective_capacity'] ?? '—'} · seated ${d['seating_allocated']}\nBundles: ${bundles.isEmpty ? '—' : bundles}'),
            isThreeLine: true,
          ),
        );
      },
      empty: 'No centre assigned',
    );
  }
}

// ---- university office (registrar / VC / COE) ------------------------------------------------------------------------------
class AffiliationOfficeScreen extends ConsumerStatefulWidget {
  const AffiliationOfficeScreen({super.key});

  @override
  ConsumerState<AffiliationOfficeScreen> createState() => _AffiliationOfficeScreenState();
}

class _AffiliationOfficeScreenState extends ConsumerState<AffiliationOfficeScreen> {
  late final AffiliationRepository _repo = ref.read(affiliationRepositoryProvider);
  int _tick = 0;

  void _refresh() => setState(() => _tick++);

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 4,
      child: Column(children: [
        const TabBar(isScrollable: true, tabs: [Tab(text: 'Portfolio'), Tab(text: 'Scrutiny / decisions'), Tab(text: 'Inspections'), Tab(text: 'Submissions')]),
        Expanded(
          child: TabBarView(key: ValueKey(_tick), children: [
            FutureBuilder<Map<String, dynamic>>(
              future: _repo.portfolio(),
              builder: (context, snap) {
                if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
                if (!snap.hasData) return const Center(child: CircularProgressIndicator());
                final p = snap.data!;
                final types = ((p['colleges_by_type'] as Map?) ?? const {});
                return ListView(padding: const EdgeInsets.all(12), children: [
                  Wrap(children: [
                    for (final e in types.entries) _card('${e.key}', '${e.value}'),
                    _card('Inspections due', '${p['inspections_due']}'),
                    _card('Deficiencies open', '${p['deficiencies_open']}'),
                    _card('Dues', _rupees(p['dues_outstanding_paise'])),
                    _card('Expiring', '${p['expiring_approvals']}'),
                  ]),
                ]);
              },
            ),
            _futureList(
              Future.wait([_repo.queue('fee_paid'), _repo.queue('compliance_pending')]).then((v) => [...v[0], ...v[1]]),
              (a) => ListTile(
                title: Text('${a['number']} · ${a['college_code']} · ${a['application_type']}'),
                subtitle: Text('${a['status']}'),
                trailing: a['status'] == 'fee_paid'
                    ? TextButton(onPressed: () => _act(context, () => _repo.scrutiny('${a['id']}', 'proceed', null), 'Scrutiny cleared', _refresh), child: const Text('Proceed'))
                    : TextButton(
                        onPressed: () async {
                          final res = await _ask(context, 'Decision', hint: 'Council resolution id (if required)');
                          if (res == null || !context.mounted) return;
                          final progs = ((a['programs'] as List?) ?? const [])
                              .cast<Map<String, dynamic>>()
                              .where((p) => p['program_id'] != null)
                              .map((p) => {'program_id': p['program_id'], 'sanctioned_intake': p['requested_intake'] ?? p['current_intake'] ?? 0, 'lateral_intake': p['lateral_intake'] ?? 0})
                              .toList();
                          await _act(
                              context,
                              () => _repo.decide('${a['id']}', {'decision': 'approved', 'programs': progs, if (res.isNotEmpty) 'resolution_id': res}),
                              'Approved — order issued',
                              _refresh);
                        },
                        child: const Text('Approve')),
              ),
              empty: 'No applications awaiting action',
            ),
            _futureList(
              _repo.inspections(),
              (r) => ListTile(title: Text('${r['college_name']} · ${r['application_type']}'), subtitle: Text('${_day(r['inspection_on'])} · ${r['mode'] ?? ''} · ${r['status']} · open ${r['open_deficiencies']}')),
              empty: 'No inspections',
            ),
            _futureList(
              Future.wait([_repo.submissions('submitted'), _repo.submissions('verified'), _repo.submissions('accepted')]).then((v) => [...v[0], ...v[1], ...v[2]]),
              (s) {
                final next = {'submitted': 'verify', 'verified': 'accept', 'accepted': 'lock'}['${s['status']}'];
                return ListTile(
                  title: Text('${s['college_code']} · ${s['submission_type']}'),
                  subtitle: Text('${s['status']} · ${s['record_count'] ?? 0} records${s['late'] == true ? ' · late' : ''}'),
                  trailing: next == null ? null : TextButton(onPressed: () => _act(context, () => _repo.submissionAction('${s['id']}', next), next, _refresh), child: Text(next)),
                );
              },
              empty: 'No submissions awaiting review',
            ),
          ]),
        ),
      ]),
    );
  }
}

// ---- inspection committee member -------------------------------------------------------------------------------------------
class InspectorScreen extends ConsumerStatefulWidget {
  const InspectorScreen({super.key});

  @override
  ConsumerState<InspectorScreen> createState() => _InspectorScreenState();
}

class _InspectorScreenState extends ConsumerState<InspectorScreen> {
  late final AffiliationRepository _repo = ref.read(affiliationRepositoryProvider);
  int _tick = 0;

  @override
  Widget build(BuildContext context) {
    return _futureList(
      _repo.myInspections(),
      (r) => ListTile(
        key: ValueKey('${r['application_id']}-$_tick'),
        title: Text('${r['college_name']} · ${r['application_type']}'),
        subtitle: Text('${_day(r['inspection_on'])} · ${r['mode'] ?? ''} · ${r['status']}'),
        trailing: r['status'] == 'inspection_scheduled'
            ? TextButton(
                onPressed: () => Navigator.of(context)
                    .push(MaterialPageRoute<void>(builder: (_) => _FindingsCapture(repo: _repo, applicationId: '${r['application_id']}')))
                    .then((_) => setState(() => _tick++)),
                child: const Text('Report'))
            : null,
      ),
      empty: 'No assigned inspections',
    );
  }
}

class _FindingsCapture extends StatefulWidget {
  const _FindingsCapture({required this.repo, required this.applicationId});

  final AffiliationRepository repo;
  final String applicationId;

  @override
  State<_FindingsCapture> createState() => _FindingsCaptureState();
}

class _FindingsCaptureState extends State<_FindingsCapture> {
  final _url = TextEditingController();
  final _area = TextEditingController();
  final _obs = TextEditingController();
  final _findings = <Map<String, dynamic>>[];
  String _severity = 'none';
  String _recommendation = 'approve';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Inspection findings')),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        TextField(controller: _area, decoration: const InputDecoration(labelText: 'Area (labs, library, faculty…)')),
        TextField(controller: _obs, maxLines: 3, decoration: const InputDecoration(labelText: 'Observation (attach photo links)')),
        DropdownButton<String>(
          value: _severity,
          items: const [
            DropdownMenuItem(value: 'none', child: Text('Not a deficiency')),
            DropdownMenuItem(value: 'minor', child: Text('Minor deficiency')),
            DropdownMenuItem(value: 'major', child: Text('Major deficiency')),
            DropdownMenuItem(value: 'critical', child: Text('Critical deficiency')),
          ],
          onChanged: (v) => setState(() => _severity = v ?? 'none'),
        ),
        OutlinedButton(
          onPressed: () => setState(() {
            if (_area.text.trim().length < 2) return;
            _findings.add({
              'area': _area.text.trim(),
              'observation': _obs.text.trim().isEmpty ? _area.text.trim() : _obs.text.trim(),
              'is_deficiency': _severity != 'none',
              'severity': _severity == 'none' ? 'minor' : _severity,
            });
            _area.clear();
            _obs.clear();
          }),
          child: const Text('Add finding'),
        ),
        for (final f in _findings) ListTile(dense: true, title: Text('${f['area']}'), subtitle: Text('${f['observation']}${f['is_deficiency'] == true ? ' · ${f['severity']}' : ''}')),
        const Divider(),
        TextField(controller: _url, decoration: const InputDecoration(labelText: 'Report file URL')),
        DropdownButton<String>(
          value: _recommendation,
          items: const [
            DropdownMenuItem(value: 'approve', child: Text('Recommend approval')),
            DropdownMenuItem(value: 'conditional', child: Text('Conditional')),
            DropdownMenuItem(value: 'reject', child: Text('Reject')),
            DropdownMenuItem(value: 'reinspect', child: Text('Re-inspect')),
          ],
          onChanged: (v) => setState(() => _recommendation = v ?? 'approve'),
        ),
        FilledButton(
          onPressed: () => _act(context, () => widget.repo.report(widget.applicationId, _url.text.trim(), _findings, _recommendation), 'Report uploaded', () {
            if (context.mounted) Navigator.of(context).pop();
          }),
          child: const Text('Upload report'),
        ),
      ]),
    );
  }
}
