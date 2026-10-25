import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 28 mobile (Prompts/28 §28.10): student **Placement** (profile completeness, resume PDF link, open drives with
/// eligibility reasons, apply, rounds schedule, offers accept / decline, internships / NOC request, training sessions);
/// parent **Ward placement** (read); placement officer **Drives** (drives today, pending offers, funnel by round, bulk
/// round results by registration numbers — typed or scanned) and **Blacklist**; faculty **Internship evaluation**.
/// The recruiter portal is web only.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) {
      final err = data['error'] as Map;
      final reasons = (err['details'] is Map) ? (err['details'] as Map)['messages'] : null;
      return reasons is List ? '${err['message']}: ${reasons.join(', ')}' : '${err['message']}';
    }
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _day(dynamic iso) {
  final d = DateTime.tryParse('${iso ?? ''}')?.toLocal();
  return d == null ? '' : '${d.day}/${d.month}/${d.year}';
}

String _when(dynamic iso) {
  final d = DateTime.tryParse('${iso ?? ''}')?.toLocal();
  return d == null ? '' : '${d.day}/${d.month} ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

String _lpa(dynamic paise) {
  final p = paise is num ? paise : num.tryParse('${paise ?? ''}');
  return p == null || p == 0 ? '—' : '₹${(p / 10000000).toStringAsFixed(2)} LPA';
}

const _reasons = {
  'CGPA': 'CGPA below minimum',
  'ACTIVE_BACKLOGS': 'Active backlogs',
  'HISTORY_BACKLOGS': 'Backlog history',
  'PCT_10': '10th %',
  'PCT_12': '12th %',
  'GAP_YEARS': 'Gap years',
  'PROGRAM': 'Programme not in drive',
  'BATCH': 'Batch not in drive',
  'ATTENDANCE': 'Attendance',
  'SKILLS': 'Skills',
  'ALREADY_PLACED': 'Already placed (dream only)',
  'OPTED_OUT': 'Opted out',
  'BLACKLISTED': 'Blacklisted',
  'DEBARRED': 'Debarred',
  'HOLD': 'Active hold',
  'INACTIVE': 'Enrolment not active',
};

class PlacementRepository {
  PlacementRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body, Options? options]) async =>
      (await _dio.post<Map<String, dynamic>>(path, data: body ?? {}, options: options)).data?['data'];
  Future<dynamic> _put(String path, [Object? body]) async => (await _dio.put<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();
  Map<String, dynamic> _map(dynamic v) => ((v as Map?) ?? const {}).cast<String, dynamic>();

  // student
  Future<Map<String, dynamic>> profile() async => _map(await _get('/placement/profile/me'));
  Future<void> updateProfile(Map<String, dynamic> body) => _put('/placement/profile/me', body);
  Future<Map<String, dynamic>> renderResume(String key) async => _map(await _post('/placement/profile/me/resume/render', {'template_key': key}));
  Future<List<Map<String, dynamic>>> openDrives() async => _list(await _get('/placement/drives/open'));
  Future<void> apply(String driveId) => _post('/placement/drives/$driveId/apply', {}, Options(headers: {'Idempotency-Key': '$driveId-${DateTime.now().millisecondsSinceEpoch ~/ 60000}'}));
  Future<void> withdraw(String id) => _post('/placement/applications/$id/withdraw');
  Future<List<Map<String, dynamic>>> myApplications() async => _list(await _get('/placement/applications/me'));
  Future<List<Map<String, dynamic>>> myOffers() async => _list(await _get('/placement/offers/me'));
  Future<void> decide(String id, String action, [String? reason]) => _post('/placement/offers/$id/decision', {'action': action, 'reason': reason});
  Future<List<Map<String, dynamic>>> myInternships() async => _list(await _get('/internships/me'));
  Future<void> requestNoc(String id) => _post('/internships/$id/noc', {'purpose': 'Internship'});
  Future<List<Map<String, dynamic>>> myTraining() async => _list(await _get('/training/me'));
  // parent
  Future<List<Map<String, dynamic>>> wardOffers() async => _list(await _get('/placement/offers/wards'));
  Future<List<Map<String, dynamic>>> wardApplications() async => _list(await _get('/placement/applications/wards'));
  // officer
  Future<List<Map<String, dynamic>>> drives([String? status]) async => _list(await _get('/placement/drives', {if (status != null) 'status': status}));
  Future<Map<String, dynamic>> funnel(String id) async => _map(await _get('/placement/drives/$id/funnel'));
  Future<List<Map<String, dynamic>>> rounds(String id) async => _list(await _get('/placement/drives/$id/rounds'));
  Future<Map<String, dynamic>> roundResults(String roundId, List<String> regs, String status) async =>
      _map(await _post('/placement/rounds/$roundId/results', {
        'rows': [for (final r in regs) {'registration_number': r, 'status': status}],
      }));
  Future<List<Map<String, dynamic>>> offers(String status) async => _list(await _get('/placement/offers', {'status': status}));
  Future<List<Map<String, dynamic>>> blacklist() async => _list(await _get('/placement/blacklist'));
  // faculty
  Future<List<Map<String, dynamic>>> assignedInternships() async => _list(await _get('/internships', {'scope': 'own'}));
  Future<void> evaluate(String id, num marks, String remarks) => _post('/internships/$id/evaluate', {'rubric_scores': {}, 'marks': marks, 'max_marks': 100, 'remarks': remarks});
}

final placementRepositoryProvider = Provider<PlacementRepository>((ref) => PlacementRepository(ref.watch(dioProvider)));

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

Future<String?> _ask(BuildContext context, String title, {String hint = '', int lines = 1}) async {
  final c = TextEditingController();
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(controller: c, maxLines: lines, decoration: InputDecoration(hintText: hint)),
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

Widget _status(dynamic s) => Chip(label: Text('${s ?? ''}'), visualDensity: VisualDensity.compact);

// ---- student ----------------------------------------------------------------------------------------------------------------
class StudentPlacementScreen extends ConsumerStatefulWidget {
  const StudentPlacementScreen({super.key});

  @override
  ConsumerState<StudentPlacementScreen> createState() => _StudentPlacementScreenState();
}

class _StudentPlacementScreenState extends ConsumerState<StudentPlacementScreen> {
  late final PlacementRepository _repo = ref.read(placementRepositoryProvider);
  late Future<Map<String, dynamic>> _profile = _repo.profile();
  late Future<List<Map<String, dynamic>>> _drives = _repo.openDrives();
  late Future<List<Map<String, dynamic>>> _apps = _repo.myApplications();
  late Future<List<Map<String, dynamic>>> _offers = _repo.myOffers();
  late Future<List<Map<String, dynamic>>> _interns = _repo.myInternships();
  late Future<List<Map<String, dynamic>>> _training = _repo.myTraining();

  void _refresh() => setState(() {
        _profile = _repo.profile();
        _drives = _repo.openDrives();
        _apps = _repo.myApplications();
        _offers = _repo.myOffers();
        _interns = _repo.myInternships();
        _training = _repo.myTraining();
      });

  Widget _profileCard() => FutureBuilder<Map<String, dynamic>>(
        future: _profile,
        builder: (context, snap) {
          final p = snap.data ?? const {};
          final a = (p['academics'] as Map?) ?? const {};
          final pct = (p['completeness'] as num?)?.toDouble() ?? 0;
          return Card(
            margin: const EdgeInsets.all(12),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Status: ${p['placement_status'] ?? '—'}${p['is_blacklisted'] == true ? ' · blacklisted' : ''}', style: const TextStyle(fontWeight: FontWeight.w600)),
                const SizedBox(height: 8),
                LinearProgressIndicator(value: pct / 100),
                Text('Profile ${pct.round()}% complete · CGPA ${a['cgpa'] ?? '—'} · backlogs ${a['active_backlogs'] ?? 0}'),
                Wrap(spacing: 8, children: [
                  TextButton.icon(
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('Skills'),
                    onPressed: () async {
                      final s = await _ask(context, 'Skills', hint: 'Comma separated');
                      if (s == null || !context.mounted) return;
                      await _act(context, () => _repo.updateProfile({'skills': s.split(',').map((x) => x.trim()).where((x) => x.isNotEmpty).toList()}), 'Saved', _refresh);
                    },
                  ),
                  TextButton.icon(
                    icon: const Icon(Icons.picture_as_pdf_outlined),
                    label: const Text('Resume PDF'),
                    onPressed: () async {
                      try {
                        final r = await _repo.renderResume('resume_classic');
                        final url = '${r['pdf_url'] ?? ''}';
                        if (url.isNotEmpty) await Clipboard.setData(ClipboardData(text: url));
                        if (context.mounted) _snack(context, url.isEmpty ? 'Resume rendered' : 'Resume link copied — share it');
                      } catch (e) {
                        if (context.mounted) _snack(context, _error(e));
                      }
                    },
                  ),
                ]),
              ]),
            ),
          );
        },
      );

  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 5,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Placement'),
            bottom: const TabBar(isScrollable: true, tabs: [Tab(text: 'Drives'), Tab(text: 'Applications'), Tab(text: 'Offers'), Tab(text: 'Internships'), Tab(text: 'Training')]),
          ),
          body: TabBarView(children: [
            RefreshIndicator(
              onRefresh: () async => _refresh(),
              child: ListView(children: [
                _profileCard(),
                _header('Open drives'),
                _futureList(_drives, (d) {
                  final e = (d['my_eligibility'] as Map?) ?? const {};
                  final ok = e['is_eligible'] == true;
                  final reasons = ((e['reasons'] as List?) ?? const []).map((r) => _reasons[r] ?? '$r').join(' · ');
                  return ListTile(
                    title: Text('${d['company_name']} — ${d['title']}'),
                    subtitle: Text('${_lpa(d['ctc_min_paise'])} · apply by ${_when(d['registration_deadline'])}\n${ok ? 'Eligible' : reasons}'),
                    isThreeLine: true,
                    trailing: d['my_application_id'] != null
                        ? _status(d['my_application_status'])
                        : FilledButton(onPressed: ok ? () => _act(context, () => _repo.apply('${d['id']}'), 'Applied', _refresh) : null, child: const Text('Apply')),
                  );
                }, empty: 'No open drives'),
              ]),
            ),
            ListView(children: [
              _futureList(_apps, (a) {
                final rounds = (a['rounds'] as List?) ?? const [];
                return ExpansionTile(
                  title: Text('${a['company_name']} — ${a['drive_title']}'),
                  subtitle: Text('${a['status']} · applied ${_day(a['applied_at'])}'),
                  children: [
                    for (final r in rounds) ListTile(dense: true, title: Text('${r['name']} · ${r['status']}'), subtitle: Text('${_when(r['scheduled_at'])} ${r['venue'] ?? ''}')),
                    if (a['status'] == 'applied') TextButton(onPressed: () => _act(context, () => _repo.withdraw('${a['id']}'), 'Withdrawn', _refresh), child: const Text('Withdraw')),
                  ],
                );
              }, empty: 'No applications'),
            ]),
            ListView(children: [
              _futureList(_offers, (o) => Card(
                    margin: const EdgeInsets.all(8),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${o['company_name']} — ${o['role'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w600)),
                        Text('${_lpa(o['ctc_paise'])} · joining ${_day(o['joining_on'])}${o['is_ppo'] == true ? ' · PPO' : ''} · ${o['status']}'),
                        if (o['policy_warning'] != null) Text('${o['policy_warning']}', style: const TextStyle(color: Colors.orange)),
                        if (o['status'] == 'offered')
                          Row(children: [
                            FilledButton(onPressed: () => _act(context, () => _repo.decide('${o['id']}', 'accept'), 'Accepted', _refresh), child: const Text('Accept')),
                            const SizedBox(width: 8),
                            OutlinedButton(
                              onPressed: () async {
                                final reason = await _ask(context, 'Reason for declining');
                                if (reason == null || !context.mounted) return;
                                await _act(context, () => _repo.decide('${o['id']}', 'decline', reason), 'Declined', _refresh);
                              },
                              child: const Text('Decline'),
                            ),
                          ]),
                      ]),
                    ),
                  ), empty: 'No offers yet'),
            ]),
            ListView(children: [
              _futureList(_interns, (i) => ListTile(
                    title: Text('${i['company_name']} — ${i['role'] ?? ''}'),
                    subtitle: Text('${_day(i['from_on'])} – ${_day(i['to_on'])} · ${i['status']}'),
                    trailing: i['noc_document_id'] != null
                        ? const Chip(label: Text('NOC ready'))
                        : TextButton(onPressed: () => _act(context, () => _repo.requestNoc('${i['id']}'), 'NOC requested', _refresh), child: const Text('Request NOC')),
                  ), empty: 'No internships'),
            ]),
            ListView(children: [
              _futureList(_training, (t) {
                final sessions = (t['sessions'] as List?) ?? const [];
                final next = sessions.map((s) => DateTime.tryParse('${(s as Map)['at']}')).whereType<DateTime>().where((d) => d.isAfter(DateTime.now())).toList()..sort();
                return ListTile(
                  title: Text('${t['title']}'),
                  subtitle: Text('${t['training_type']} · attended ${t['sessions_attended']}/${sessions.length}${next.isNotEmpty ? ' · next ${_when(next.first.toIso8601String())}' : ''}'),
                  trailing: Text('${t['score'] ?? ''}'),
                );
              }, empty: 'No training programmes'),
            ]),
          ]),
        ),
      );
}

// ---- parent -----------------------------------------------------------------------------------------------------------------
class ParentPlacementScreen extends ConsumerStatefulWidget {
  const ParentPlacementScreen({super.key});

  @override
  ConsumerState<ParentPlacementScreen> createState() => _ParentPlacementScreenState();
}

class _ParentPlacementScreenState extends ConsumerState<ParentPlacementScreen> {
  late final PlacementRepository _repo = ref.read(placementRepositoryProvider);
  late final Future<List<Map<String, dynamic>>> _offers = _repo.wardOffers();
  late final Future<List<Map<String, dynamic>>> _apps = _repo.wardApplications();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Ward placement')),
        body: ListView(children: [
          _header('Offers'),
          _futureList(_offers, (o) => ListTile(title: Text('${o['student_name'] ?? ''} · ${o['company_name']}'), subtitle: Text('${_lpa(o['ctc_paise'])} · ${o['status']}')), empty: 'No offers'),
          _header('Applications'),
          _futureList(_apps, (a) => ListTile(title: Text('${a['company_name']} — ${a['drive_title']}'), subtitle: Text('${a['status']} · ${_day(a['applied_at'])}')), empty: 'No applications'),
        ]),
      );
}

// ---- placement officer --------------------------------------------------------------------------------------------------------
class PlacementOfficerScreen extends ConsumerStatefulWidget {
  const PlacementOfficerScreen({super.key});

  @override
  ConsumerState<PlacementOfficerScreen> createState() => _PlacementOfficerScreenState();
}

class _PlacementOfficerScreenState extends ConsumerState<PlacementOfficerScreen> {
  late final PlacementRepository _repo = ref.read(placementRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _drives = _repo.drives();
  late Future<List<Map<String, dynamic>>> _pending = _repo.offers('offered');

  void _refresh() => setState(() {
        _drives = _repo.drives();
        _pending = _repo.offers('offered');
      });

  bool _today(dynamic iso) {
    final d = DateTime.tryParse('${iso ?? ''}');
    final n = DateTime.now();
    return d != null && d.year == n.year && d.month == n.month && d.day == n.day;
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Placement drives'), actions: [
          IconButton(icon: const Icon(Icons.block_outlined), tooltip: 'Blacklist', onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const PlacementBlacklistScreen()))),
        ]),
        body: RefreshIndicator(
          onRefresh: () async => _refresh(),
          child: ListView(children: [
            _header('Drives'),
            _futureList(_drives, (d) => ListTile(
                  leading: _today(d['drive_on']) ? const Icon(Icons.today, color: Colors.green) : null,
                  title: Text('${d['company_name']} — ${d['title']}'),
                  subtitle: Text('${d['status']} · ${_day(d['drive_on'])} · ${d['applications']} applications'),
                  onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => DriveFunnelScreen(driveId: '${d['id']}', title: '${d['title']}'))),
                ), empty: 'No drives'),
            _header('Offers awaiting the student'),
            _futureList(_pending, (o) => ListTile(title: Text('${o['student_name']} · ${o['company_name']}'), subtitle: Text('${_lpa(o['ctc_paise'])} · offered ${_day(o['offered_on'])}')), empty: 'None pending'),
          ]),
        ),
      );
}

class DriveFunnelScreen extends ConsumerStatefulWidget {
  const DriveFunnelScreen({super.key, required this.driveId, required this.title});

  final String driveId;
  final String title;

  @override
  ConsumerState<DriveFunnelScreen> createState() => _DriveFunnelScreenState();
}

class _DriveFunnelScreenState extends ConsumerState<DriveFunnelScreen> {
  late final PlacementRepository _repo = ref.read(placementRepositoryProvider);
  late Future<Map<String, dynamic>> _funnel = _repo.funnel(widget.driveId);
  late Future<List<Map<String, dynamic>>> _rounds = _repo.rounds(widget.driveId);

  void _refresh() => setState(() {
        _funnel = _repo.funnel(widget.driveId);
        _rounds = _repo.rounds(widget.driveId);
      });

  Future<void> _results(Map<String, dynamic> round) async {
    final text = await _ask(context, 'Registration numbers (${round['name']})', hint: 'One per line or comma separated — type or scan', lines: 6);
    if (text == null || text.isEmpty || !mounted) return;
    final status = await showDialog<String>(
      context: context,
      builder: (ctx) => SimpleDialog(title: const Text('Result'), children: [
        for (final s in const ['cleared', 'not_cleared', 'absent']) SimpleDialogOption(onPressed: () => Navigator.pop(ctx, s), child: Text(s)),
      ]),
    );
    if (status == null || !mounted) return;
    final regs = text.split(RegExp(r'[\s,]+')).where((x) => x.isNotEmpty).toList();
    try {
      final r = await _repo.roundResults('${round['id']}', regs, status);
      if (mounted) _snack(context, '${r['succeeded']} recorded, ${(r['failed'] as List?)?.length ?? 0} failed');
      _refresh();
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(widget.title)),
        body: ListView(children: [
          FutureBuilder<Map<String, dynamic>>(
            future: _funnel,
            builder: (context, snap) {
              final f = snap.data ?? const {};
              final rows = <MapEntry<String, num>>[
                MapEntry('Applied', (f['applied'] as num?) ?? 0),
                MapEntry('Shortlisted', (f['shortlisted'] as num?) ?? 0),
                for (final r in (f['rounds'] as List?) ?? const []) MapEntry('R${(r as Map)['round_no']} cleared', (r['cleared'] as num?) ?? 0),
                MapEntry('Selected', (f['selected'] as num?) ?? 0),
                MapEntry('Accepted', (f['accepted'] as num?) ?? 0),
              ];
              final max = rows.fold<num>(1, (m, e) => e.value > m ? e.value : m);
              return Padding(
                padding: const EdgeInsets.all(16),
                child: Column(children: [
                  for (final e in rows)
                    Row(children: [
                      SizedBox(width: 110, child: Text(e.key)),
                      Expanded(child: LinearProgressIndicator(value: e.value / max, minHeight: 10)),
                      SizedBox(width: 40, child: Text('  ${e.value}')),
                    ]),
                ]),
              );
            },
          ),
          _header('Rounds — tap to upload results'),
          _futureList(_rounds, (r) => ListTile(
                title: Text('R${r['round_no']} ${r['name']}'),
                subtitle: Text('${_when(r['scheduled_at'])} ${r['venue'] ?? ''} · ${(r['results'] as Map?)?.entries.map((e) => '${e.key} ${e.value}').join(' · ') ?? ''}'),
                trailing: const Icon(Icons.upload_outlined),
                onTap: () => _results(r),
              ), empty: 'No rounds'),
        ]),
      );
}

class PlacementBlacklistScreen extends ConsumerWidget {
  const PlacementBlacklistScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) => Scaffold(
        appBar: AppBar(title: const Text('Blacklist')),
        body: ListView(children: [
          _futureList(ref.read(placementRepositoryProvider).blacklist(),
              (b) => ListTile(title: Text('${b['student_name']} (${b['registration_number']})'), subtitle: Text('${b['reason'] ?? ''} · ${b['source'] ?? ''}${b['until'] != null ? ' · until ${b['until']}' : ''}')),
              empty: 'Nobody is blacklisted'),
        ]),
      );
}

// ---- faculty ------------------------------------------------------------------------------------------------------------------
class InternshipEvaluationScreen extends ConsumerStatefulWidget {
  const InternshipEvaluationScreen({super.key});

  @override
  ConsumerState<InternshipEvaluationScreen> createState() => _InternshipEvaluationScreenState();
}

class _InternshipEvaluationScreenState extends ConsumerState<InternshipEvaluationScreen> {
  late final PlacementRepository _repo = ref.read(placementRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _f = _repo.assignedInternships();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Internship evaluation')),
        body: RefreshIndicator(
          onRefresh: () async => setState(() => _f = _repo.assignedInternships()),
          child: ListView(children: [
            _futureList(_f, (i) => ListTile(
                  title: Text('${i['student_name']} · ${i['company_name']}'),
                  subtitle: Text('${i['weeks'] ?? '—'} weeks · ${i['status']} · marks ${(i['evaluation'] as Map?)?['marks'] ?? '—'}'),
                  trailing: const Icon(Icons.rate_review_outlined),
                  onTap: () async {
                    final marks = await _ask(context, 'Marks out of 100');
                    final m = num.tryParse(marks ?? '');
                    if (m == null || !context.mounted) return;
                    final remarks = await _ask(context, 'Remarks', lines: 3) ?? '';
                    if (!context.mounted) return;
                    await _act(context, () => _repo.evaluate('${i['id']}', m, remarks), 'Evaluated', () => setState(() => _f = _repo.assignedInternships()));
                  },
                ), empty: 'No internships assigned'),
          ]),
        ),
      );
}
