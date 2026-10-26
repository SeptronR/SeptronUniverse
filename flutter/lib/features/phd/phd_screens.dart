import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 31 mobile (Prompts/31 §31.10). Scholar: **My PhD** with Home (status, deadlines, duration meter) · Progress
/// (report submit with the file link, DC meetings / recommendations) · Thesis (submission status, similarity, viva, ETD)
/// · Fellowship (disbursements, contingency claim with the bill photo link) · Requests; guide: **My scholars** (review
/// reports, recommend requests, DC minutes quick capture, panel read); research cell: **PhD approvals** (requests,
/// fellowship run approvals). External examiners use the web token pages only.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _inr(dynamic paise) {
  final p = paise is num ? paise : num.tryParse('${paise ?? ''}') ?? 0;
  return '₹${(p / 100).toStringAsFixed(0)}';
}

class PhdRepository {
  PhdRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  Future<dynamic> _put(String path, [Object? body]) async => (await _dio.put<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();
  Map<String, dynamic> _map(dynamic v) => ((v as Map?) ?? const {}).cast<String, dynamic>();

  Future<Map<String, dynamic>> dashboard() async => _map(await _get('/phd/me/dashboard'));
  Future<Map<String, dynamic>> me() async => _map(await _get('/phd/me'));
  Future<List<Map<String, dynamic>>> periods(String sid) async => _list(await _get('/phd/scholars/$sid/progress-periods'));
  Future<List<Map<String, dynamic>>> reports(String sid) async => _list(await _get('/phd/scholars/$sid/progress-reports'));
  Future<void> submitReport(String sid, Map<String, dynamic> body) => _post('/phd/scholars/$sid/progress-reports', body);
  Future<List<Map<String, dynamic>>> meetings(String sid) async => _list(await _get('/phd/scholars/$sid/dc-meetings'));
  Future<void> minutes(String mid, String text) => _put('/phd/dc-meetings/$mid/minutes', {'minutes': text, 'recommendations': []});
  Future<List<Map<String, dynamic>>> theses(String sid) async => _list(await _get('/phd/scholars/$sid/thesis'));
  Future<List<Map<String, dynamic>>> myDisbursements() async => _list(await _get('/phd/fellowships/me'));
  Future<void> contingency(String did, Map<String, dynamic> body) => _post('/phd/disbursements/$did/contingency', body);
  Future<List<Map<String, dynamic>>> scholarRequests(String sid) async => _list(await _get('/phd/scholars/$sid/requests'));
  Future<void> raise(String sid, Map<String, dynamic> body) => _post('/phd/scholars/$sid/requests', body);
  Future<List<Map<String, dynamic>>> myScholars() async => _list(await _get('/phd/scholars', {'scope': 'own', 'per_page': 200}));
  Future<void> guideReview(String rid, String remarks) => _post('/phd/progress-reports/$rid/guide-review', {'remarks': remarks});
  Future<List<Map<String, dynamic>>> requests(Map<String, dynamic> q) async => _list(await _get('/phd/requests', q));
  Future<void> decide(String rid, bool approve) => _post('/phd/requests/$rid/decide', {'approve': approve});
  Future<List<Map<String, dynamic>>> disbursements(Map<String, dynamic> q) async => _list(await _get('/phd/disbursements', q));
  Future<void> approveDisbursement(String did) => _post('/phd/disbursements/$did/approve');
}

final phdRepositoryProvider = Provider<PhdRepository>((ref) => PhdRepository(ref.watch(dioProvider)));

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

Future<String?> _ask(BuildContext context, String title, {String hint = '', TextInputType? type}) async {
  final c = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(controller: c, keyboardType: type, decoration: InputDecoration(hintText: hint)),
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
        return Column(children: [for (final r in snap.data!) row(r)]);
      },
    );

Widget _header(String text) => Padding(padding: const EdgeInsets.fromLTRB(16, 16, 16, 4), child: Text(text, style: const TextStyle(fontWeight: FontWeight.w600)));

Widget _stat(String label, String value) => Card(
      child: Padding(padding: const EdgeInsets.all(12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(label, style: const TextStyle(fontSize: 12)), Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600))])),
    );

// ---- scholar: My PhD ----------------------------------------------------------------------------------------------------------
class ScholarHubScreen extends ConsumerStatefulWidget {
  const ScholarHubScreen({super.key});

  @override
  ConsumerState<ScholarHubScreen> createState() => _ScholarHubScreenState();
}

class _ScholarHubScreenState extends ConsumerState<ScholarHubScreen> {
  late final PhdRepository _repo = ref.read(phdRepositoryProvider);
  late Future<Map<String, dynamic>> _dash = _repo.dashboard();

  void _refresh() => setState(() => _dash = _repo.dashboard());

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 5,
      child: Column(children: [
        const TabBar(isScrollable: true, tabs: [Tab(text: 'Home'), Tab(text: 'Progress'), Tab(text: 'Thesis'), Tab(text: 'Fellowship'), Tab(text: 'Requests')]),
        Expanded(
          child: FutureBuilder<Map<String, dynamic>>(
            future: _dash,
            builder: (context, snap) {
              if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
              final d = snap.data;
              if (d == null) return const Center(child: CircularProgressIndicator());
              final s = ((d['scholar'] as Map?) ?? const {}).cast<String, dynamic>();
              final sid = '${s['id']}';
              return TabBarView(children: [
                _home(d, s),
                _ScholarProgressTab(repo: _repo, sid: sid),
                _ScholarThesisTab(repo: _repo, sid: sid),
                _ScholarFellowshipTab(repo: _repo),
                _ScholarRequestsTab(repo: _repo, sid: sid, onChange: _refresh),
              ]);
            },
          ),
        ),
      ]),
    );
  }

  Widget _home(Map<String, dynamic> d, Map<String, dynamic> s) {
    final pct = (d['duration_pct'] as num?)?.toDouble();
    final cw = ((d['coursework'] as Map?) ?? const {}).cast<String, dynamic>();
    final deadlines = ((d['deadlines'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final recs = ((d['open_recommendations'] as List?) ?? const []).cast<Map<String, dynamic>>();
    return RefreshIndicator(
      onRefresh: () async => _refresh(),
      child: ListView(children: [
        ListTile(title: Text('${s['research_area'] ?? 'My PhD'}'), subtitle: Text('Guide ${s['guide_name'] ?? '—'} · ${s['status']}')),
        if (pct != null) Padding(padding: const EdgeInsets.symmetric(horizontal: 16), child: LinearProgressIndicator(value: pct / 100)),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          childAspectRatio: 2.4,
          padding: const EdgeInsets.all(8),
          children: [
            _stat('Duration used', pct == null ? '—' : '${pct.toStringAsFixed(0)} %'),
            _stat('Coursework', cw.isEmpty ? '—' : '${cw['credits_earned']}/${cw['credits_required']}'),
            _stat('Open requests', '${d['open_requests'] ?? 0}'),
            _stat('Max duration', '${s['max_duration_end'] ?? '—'}'),
          ],
        ),
        _header('Deadlines'),
        for (final x in deadlines) ListTile(dense: true, leading: const Icon(Icons.event_outlined), title: Text('${x['label']}'), trailing: Text('${x['due_on']}')),
        _header('DC recommendations'),
        for (final r in recs) ListTile(dense: true, title: Text('${r['text']}'), subtitle: Text('Meeting ${r['meeting_no']} · due ${r['due_on'] ?? '—'}')),
      ]),
    );
  }
}

class _ScholarProgressTab extends StatefulWidget {
  const _ScholarProgressTab({required this.repo, required this.sid});

  final PhdRepository repo;
  final String sid;

  @override
  State<_ScholarProgressTab> createState() => _ScholarProgressTabState();
}

class _ScholarProgressTabState extends State<_ScholarProgressTab> {
  late Future<List<Map<String, dynamic>>> _periods = widget.repo.periods(widget.sid);
  late Future<List<Map<String, dynamic>>> _meetings = widget.repo.meetings(widget.sid);

  void _refresh() => setState(() {
        _periods = widget.repo.periods(widget.sid);
        _meetings = widget.repo.meetings(widget.sid);
      });

  Future<void> _submit(String period) async {
    final url = await _ask(context, 'Report file ($period)', hint: 'https://… (uploaded to Files)');
    if (url == null || url.isEmpty || !mounted) return;
    final summary = await _ask(context, 'Summary');
    if (summary == null || summary.isEmpty || !mounted) return;
    await _act(context, () => widget.repo.submitReport(widget.sid, {'period_label': period, 'report_url': url, 'summary': summary}), 'Submitted', _refresh);
  }

  @override
  Widget build(BuildContext context) => ListView(children: [
        _header('Half-yearly reports'),
        _futureList(
            _periods,
            (p) => ListTile(
                  title: Text('${p['period_label']}'),
                  subtitle: Text('Due ${p['due_on']} · ${p['status']}'),
                  trailing: p['report_id'] == null ? TextButton(onPressed: () => _submit('${p['period_label']}'), child: const Text('Submit')) : const Icon(Icons.check),
                )),
        _header('DC meetings'),
        _futureList(
            _meetings,
            (m) => ExpansionTile(
                  title: Text('Meeting ${m['meeting_no']} · ${m['status']}'),
                  subtitle: Text('${m['held_on'] ?? ''}'),
                  children: [for (final r in (m['recommendations'] as List? ?? const [])) ListTile(dense: true, title: Text('${(r as Map)['text']}'), subtitle: Text('due ${r['due_on'] ?? '—'}'))],
                )),
      ]);
}

class _ScholarThesisTab extends StatelessWidget {
  const _ScholarThesisTab({required this.repo, required this.sid});

  final PhdRepository repo;
  final String sid;

  @override
  Widget build(BuildContext context) => ListView(children: [
        _header('Submissions'),
        _futureList(
            repo.theses(sid),
            (t) => ListTile(
                  title: Text('${t['stage']} · ${t['title'] ?? ''}'),
                  subtitle: Text('${t['status']} · similarity ${t['similarity_pct'] ?? '—'} % (limit ${t['similarity_limit_pct'] ?? '—'} %)'),
                  trailing: ((t['flags'] as List?) ?? const []).isEmpty ? null : const Icon(Icons.warning_amber, color: Colors.orange),
                ),
            empty: 'No submissions yet — submit from the web portal'),
      ]);
}

class _ScholarFellowshipTab extends StatefulWidget {
  const _ScholarFellowshipTab({required this.repo});

  final PhdRepository repo;

  @override
  State<_ScholarFellowshipTab> createState() => _ScholarFellowshipTabState();
}

class _ScholarFellowshipTabState extends State<_ScholarFellowshipTab> {
  late Future<List<Map<String, dynamic>>> _rows = widget.repo.myDisbursements();

  void _refresh() => setState(() => _rows = widget.repo.myDisbursements());

  Future<void> _claim(String did) async {
    final amount = await _ask(context, 'Contingency amount (₹)', type: TextInputType.number);
    final rupees = num.tryParse(amount ?? '');
    if (rupees == null || !mounted) return;
    final desc = await _ask(context, 'Description');
    if (desc == null || desc.length < 3 || !mounted) return;
    final bill = await _ask(context, 'Bill photo link', hint: 'https://… (photo uploaded to Files)');
    if (!mounted) return;
    await _act(context, () => widget.repo.contingency(did, {'amount_paise': (rupees * 100).round(), 'description': desc, 'bills': [if ((bill ?? '').isNotEmpty) bill]}), 'Claimed', _refresh);
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<List<Map<String, dynamic>>>(
        future: _rows,
        builder: (context, snap) {
          final rows = snap.data ?? const [];
          return ListView(children: [
            if (rows.isNotEmpty)
              Padding(padding: const EdgeInsets.all(16), child: OutlinedButton.icon(onPressed: () => _claim('${rows.first['id']}'), icon: const Icon(Icons.receipt_long_outlined), label: const Text('Contingency claim'))),
            for (final d in rows)
              ListTile(
                title: Text('${d['month']} · ${d['kind']}'),
                subtitle: Text('${d['status']}${d['hold_reason'] != null ? ' · ${d['hold_reason']}' : ''}'),
                trailing: Text(_inr(d['amount_paise'])),
              ),
            if (snap.hasData && rows.isEmpty) const Padding(padding: EdgeInsets.all(16), child: Text('No disbursements')),
          ]);
        },
      );
}

class _ScholarRequestsTab extends StatefulWidget {
  const _ScholarRequestsTab({required this.repo, required this.sid, required this.onChange});

  final PhdRepository repo;
  final String sid;
  final VoidCallback onChange;

  @override
  State<_ScholarRequestsTab> createState() => _ScholarRequestsTabState();
}

class _ScholarRequestsTabState extends State<_ScholarRequestsTab> {
  late Future<List<Map<String, dynamic>>> _rows = widget.repo.scholarRequests(widget.sid);

  void _refresh() {
    setState(() => _rows = widget.repo.scholarRequests(widget.sid));
    widget.onChange();
  }

  Future<void> _extension() async {
    final months = int.tryParse(await _ask(context, 'Extension (months)', type: TextInputType.number) ?? '');
    if (months == null || !mounted) return;
    final reason = await _ask(context, 'Justification');
    if (reason == null || reason.length < 3 || !mounted) return;
    await _act(context, () => widget.repo.raise(widget.sid, {'request_type': 'extension', 'details': {'months': months, 'reason': reason}}), 'Requested', _refresh);
  }

  @override
  Widget build(BuildContext context) => ListView(children: [
        Padding(padding: const EdgeInsets.all(16), child: FilledButton.icon(onPressed: _extension, icon: const Icon(Icons.more_time), label: const Text('Request an extension'))),
        _futureList(_rows, (r) => ListTile(title: Text('${r['request_type']}'), subtitle: Text('${r['status']}${r['workflow_status'] != null ? ' · ${r['workflow_status']}' : ''}'))),
      ]);
}

// ---- guide: my scholars ---------------------------------------------------------------------------------------------------------
class GuideScholarsScreen extends ConsumerStatefulWidget {
  const GuideScholarsScreen({super.key});

  @override
  ConsumerState<GuideScholarsScreen> createState() => _GuideScholarsScreenState();
}

class _GuideScholarsScreenState extends ConsumerState<GuideScholarsScreen> {
  late final PhdRepository _repo = ref.read(phdRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _rows = _repo.myScholars();

  void _refresh() => setState(() => _rows = _repo.myScholars());

  Future<void> _open(Map<String, dynamic> s) async {
    final sid = '${s['id']}';
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => DraggableScrollableSheet(
        expand: false,
        builder: (ctx, controller) => ListView(controller: controller, children: [
          ListTile(title: Text('${s['name']}'), subtitle: Text('${s['status']} · ${s['research_area'] ?? ''}')),
          _header('Progress reports to review'),
          _futureList(
              _repo.reports(sid),
              (r) => ListTile(
                    title: Text('${r['period_label']} · ${r['status']}'),
                    subtitle: Text('${r['summary'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis),
                    trailing: r['status'] == 'submitted'
                        ? TextButton(
                            onPressed: () async {
                              final remarks = await _ask(ctx, 'Guide remarks');
                              if (remarks == null || remarks.isEmpty || !ctx.mounted) return;
                              await _act(ctx, () => _repo.guideReview('${r['id']}', remarks), 'Reviewed', _refresh);
                            },
                            child: const Text('Review'))
                        : null,
                  )),
          _header('DC meetings — minutes quick capture'),
          _futureList(
              _repo.meetings(sid),
              (m) => ListTile(
                    title: Text('Meeting ${m['meeting_no']} · ${m['status']}'),
                    trailing: m['status'] == 'scheduled'
                        ? TextButton(
                            onPressed: () async {
                              final text = await _ask(ctx, 'Minutes');
                              if (text == null || text.isEmpty || !ctx.mounted) return;
                              await _act(ctx, () => _repo.minutes('${m['id']}', text), 'Minutes recorded', _refresh);
                            },
                            child: const Text('Minutes'))
                        : null,
                  )),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => RefreshIndicator(
        onRefresh: () async => _refresh(),
        child: ListView(children: [
          _futureList(
              _rows,
              (s) => ListTile(
                    title: Text('${s['name']}'),
                    subtitle: Text('${s['status']} · ${s['mode']} · ${s['fellowship_type']}'),
                    trailing: Text('${s['months_left'] ?? '—'} mo'),
                    onTap: () => _open(s),
                  ),
              empty: 'No scholars'),
        ]),
      );
}

// ---- research cell: approvals inbox ---------------------------------------------------------------------------------------------
class PhdApprovalsScreen extends ConsumerStatefulWidget {
  const PhdApprovalsScreen({super.key});

  @override
  ConsumerState<PhdApprovalsScreen> createState() => _PhdApprovalsScreenState();
}

class _PhdApprovalsScreenState extends ConsumerState<PhdApprovalsScreen> {
  late final PhdRepository _repo = ref.read(phdRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _requests = _repo.requests({'status': 'in_review'});
  late Future<List<Map<String, dynamic>>> _disb = _repo.disbursements({'status': 'pending'});

  void _refresh() => setState(() {
        _requests = _repo.requests({'status': 'in_review'});
        _disb = _repo.disbursements({'status': 'pending'});
      });

  @override
  Widget build(BuildContext context) => RefreshIndicator(
        onRefresh: () async => _refresh(),
        child: ListView(children: [
          _header('Scholar requests'),
          _futureList(
              _requests,
              (r) => ListTile(
                    title: Text('${r['scholar_name'] ?? ''} · ${r['request_type']}'),
                    subtitle: Text('${r['workflow_status'] ?? r['status']}'),
                    trailing: Wrap(children: [
                      IconButton(icon: const Icon(Icons.check_circle_outline), onPressed: () => _act(context, () => _repo.decide('${r['id']}', true), 'Approved', _refresh)),
                      IconButton(icon: const Icon(Icons.cancel_outlined), onPressed: () => _act(context, () => _repo.decide('${r['id']}', false), 'Rejected', _refresh)),
                    ]),
                  ),
              empty: 'No requests waiting'),
          _header('Fellowship disbursements (pending)'),
          _futureList(
              _disb,
              (d) => ListTile(
                    title: Text('${d['scholar_name'] ?? ''} · ${d['month']}'),
                    subtitle: Text('${d['fellowship_type']} · ${d['kind']}'),
                    trailing: TextButton(onPressed: () => _act(context, () => _repo.approveDisbursement('${d['id']}'), 'Approved', _refresh), child: Text(_inr(d['amount_paise']))),
                  ),
              empty: 'Nothing pending'),
        ]),
      );
}
