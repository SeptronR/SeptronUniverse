import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 33 mobile (Prompts/33 §33.10). Staff: **Governance** with Meetings (agenda docs, mark my attendance at the
/// meeting — the QR at the venue opens this screen), ATRs (resolutions I own: submit the action-taken report),
/// e-File (inbox with notings; forward / return / approve), Policies (pending acknowledgement). Committee secretary:
/// **Committee desk** (schedule, notice, attendance roll, quick resolution capture into the minutes draft); registrar /
/// principal: approvals (minutes, policies) and e-file pendency; PIO: RTI due list; legal officer: hearing calendar.
/// The API narrows every list (member / secretary / chair / owner / holder / PIO / legal).
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

class GovernanceRepository {
  GovernanceRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();
  Map<String, dynamic> _map(dynamic v) => ((v as Map?) ?? const {}).cast<String, dynamic>();

  Future<Map<String, dynamic>> me() async => _map(await _get('/governance/me'));
  Future<List<Map<String, dynamic>>> myMeetings() async => _list(await _get('/governance/meetings/me'));
  Future<Map<String, dynamic>> meeting(String id) async => _map(await _get('/governance/meetings/$id'));
  Future<void> checkIn(String id) => _post('/governance/meetings/$id/attendance', {'self_check_in': true});
  Future<List<Map<String, dynamic>>> myResolutions() async => _list(await _get('/governance/resolutions', {'scope': 'mine'}));
  Future<void> submitAtr(String id, String text) => _post('/governance/resolutions/$id/atr', {'report_text': text});
  Future<List<Map<String, dynamic>>> inbox() async => _list(await _get('/efiles/inbox'));
  Future<Map<String, dynamic>> efile(String id) async => _map(await _get('/efiles/$id'));
  Future<void> move(String id, Map<String, dynamic> body) => _post('/efiles/$id/move', body);
  Future<List<Map<String, dynamic>>> pendingAcks() async => _list(await _get('/policies/me/pending-ack'));
  Future<void> acknowledge(String id) => _post('/policies/$id/acknowledge');
  // secretary
  Future<List<Map<String, dynamic>>> myCommittees() async => _list(await _get('/governance/committees/me'));
  Future<Map<String, dynamic>> committee(String id) async => _map(await _get('/governance/committees/$id'));
  Future<void> schedule(Map<String, dynamic> body) => _post('/governance/meetings', body);
  Future<void> notice(String id) => _post('/governance/meetings/$id/notice', {'channels': ['in_app', 'email']});
  Future<Map<String, dynamic>> attendance(String id, List<String> present) async =>
      _map(await _post('/governance/meetings/$id/attendance', {'present_member_ids': present}));
  Future<void> draftMinutes(String id, String text, List<Map<String, dynamic>> resolutions) =>
      _post('/governance/meetings/$id/minutes', {'minutes_text': text, 'resolutions': resolutions});
  // approvals / officers
  Future<List<Map<String, dynamic>>> draftMeetings() async => _list(await _get('/governance/meetings', {'status': 'minutes_draft'}));
  Future<void> approveMinutes(String id) => _post('/governance/meetings/$id/minutes/approve', {'approve': true});
  Future<List<Map<String, dynamic>>> submittedPolicies() async =>
      _list(await _get('/policies', {'status': 'draft'})).where((p) => p['stage'] == 'submitted').toList();
  Future<void> approvePolicy(String id, String? resolutionId) =>
      _post('/policies/$id/approve', {'approve': true, if (resolutionId != null && resolutionId.isNotEmpty) 'resolution_id': resolutionId});
  Future<List<Map<String, dynamic>>> pendency() async => _list(await _get('/efiles/pendency'));
  Future<List<Map<String, dynamic>>> rtiDue() async => _list(await _get('/rti/requests', {'overdue': false}))
      .where((r) => r['status'] == 'received' || r['status'] == 'assigned')
      .toList();
  Future<List<Map<String, dynamic>>> hearings() async => _list(await _get('/legal/calendar', {'days': 60}));
}

final governanceRepositoryProvider = Provider<GovernanceRepository>((ref) => GovernanceRepository(ref.watch(dioProvider)));

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

// ---- staff: governance hub -------------------------------------------------------------------------------------------------
class GovernanceHubScreen extends ConsumerStatefulWidget {
  const GovernanceHubScreen({super.key});

  @override
  ConsumerState<GovernanceHubScreen> createState() => _GovernanceHubScreenState();
}

class _GovernanceHubScreenState extends ConsumerState<GovernanceHubScreen> {
  late final GovernanceRepository _repo = ref.read(governanceRepositoryProvider);
  int _tick = 0;

  void _refresh() => setState(() => _tick++);

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 4,
      child: Column(children: [
        const TabBar(isScrollable: true, tabs: [Tab(text: 'Meetings'), Tab(text: 'ATRs'), Tab(text: 'e-File'), Tab(text: 'Policies')]),
        Expanded(
          child: TabBarView(key: ValueKey(_tick), children: [
            _futureList(
              _repo.myMeetings(),
              (m) => ListTile(
                title: Text('${m['committee_name']} · ${m['meeting_no'] ?? ''}'),
                subtitle: Text('${_day(m['held_on'])} · ${m['venue_or_link'] ?? ''} · ${m['status']}'),
                trailing: m['status'] == 'scheduled'
                    ? TextButton(onPressed: () => _act(context, () => _repo.checkIn('${m['id']}'), 'Marked present', _refresh), child: const Text('Check in'))
                    : null,
                onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => _MeetingDetail(repo: _repo, id: '${m['id']}'))),
              ),
              empty: 'No meetings',
            ),
            _futureList(
              _repo.myResolutions(),
              (r) => ListTile(
                title: Text('${r['number']} · ${r['subject']}'),
                subtitle: Text('Due ${_day(r['due_on'])} · ${r['status']}${r['atr'] != null ? ' · ATR ${r['atr']['status']}' : ''}'),
                trailing: r['status'] == 'passed' && (r['atr'] == null || r['atr']['status'] == 'returned')
                    ? TextButton(
                        onPressed: () async {
                          final t = await _ask(context, 'Action taken', hint: 'What was done');
                          if (t != null && t.isNotEmpty && context.mounted) await _act(context, () => _repo.submitAtr('${r['id']}', t), 'ATR submitted', _refresh);
                        },
                        child: const Text('ATR'))
                    : null,
              ),
              empty: 'No resolutions assigned to you',
            ),
            _futureList(
              _repo.inbox(),
              (f) => ListTile(
                title: Text('${f['file_no']} · ${f['subject']}'),
                subtitle: Text('${f['priority']} · with you ${f['pendency_days']} day(s)${f['over_sla'] == true ? ' · over SLA' : ''}'),
                onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => _EfileDetail(repo: _repo, id: '${f['id']}'))).then((_) => _refresh()),
              ),
              empty: 'No files with you',
            ),
            _futureList(
              _repo.pendingAcks(),
              (p) => ListTile(
                title: Text('${p['title']} v${p['version']}'),
                subtitle: Text('${p['category'] ?? ''} · effective ${_day(p['effective_from'])}'),
                trailing: FilledButton(onPressed: () => _act(context, () => _repo.acknowledge('${p['id']}'), 'Acknowledged', _refresh), child: const Text('Acknowledge')),
              ),
              empty: 'No policies awaiting acknowledgement',
            ),
          ]),
        ),
      ]),
    );
  }
}

class _MeetingDetail extends StatelessWidget {
  const _MeetingDetail({required this.repo, required this.id});

  final GovernanceRepository repo;
  final String id;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Meeting')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: repo.meeting(id),
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final m = snap.data!;
          final agenda = ((m['agenda'] as List?) ?? const []).cast<Map<String, dynamic>>();
          final res = ((m['resolutions'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return ListView(padding: const EdgeInsets.all(12), children: [
            Text('${m['committee_name']} · ${m['meeting_no'] ?? ''}', style: Theme.of(context).textTheme.titleMedium),
            Text('${_day(m['held_on'])} · ${m['venue_or_link'] ?? ''} · ${m['status']}'),
            const Divider(),
            const Text('Agenda', style: TextStyle(fontWeight: FontWeight.w600)),
            for (var i = 0; i < agenda.length; i++) ListTile(dense: true, leading: Text('${i + 1}.'), title: Text('${agenda[i]['item']}'), subtitle: agenda[i]['doc_url'] != null ? Text('${agenda[i]['doc_url']}') : null),
            if (m['minutes_text'] != null) ...[const Divider(), const Text('Minutes', style: TextStyle(fontWeight: FontWeight.w600)), Text('${m['minutes_text']}')],
            if (res.isNotEmpty) ...[const Divider(), for (final r in res) ListTile(dense: true, title: Text('${r['number']} · ${r['subject']}'), subtitle: Text('${r['status']}'))],
          ]);
        },
      ),
    );
  }
}

class _EfileDetail extends StatefulWidget {
  const _EfileDetail({required this.repo, required this.id});

  final GovernanceRepository repo;
  final String id;

  @override
  State<_EfileDetail> createState() => _EfileDetailState();
}

class _EfileDetailState extends State<_EfileDetail> {
  late Future<Map<String, dynamic>> _f = widget.repo.efile(widget.id);

  void _refresh() => setState(() => _f = widget.repo.efile(widget.id));

  Future<void> _move(String action) async {
    String? to;
    if (action == 'forward') {
      to = await _ask(context, 'Forward to role', hint: 'e.g. accountant, registrar, hod');
      if (to == null || to.isEmpty) return;
    }
    if (!mounted) return;
    final noting = await _ask(context, 'Noting', hint: 'Append to the notings sheet');
    if (noting == null || noting.isEmpty || !mounted) return;
    await _act(context, () => widget.repo.move(widget.id, {'action': action, 'noting': noting, if (to != null) 'to_role': to}), 'Done', _refresh);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('File')),
      body: FutureBuilder<Map<String, dynamic>>(
        future: _f,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final f = snap.data!;
          final moves = ((f['movements'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return ListView(padding: const EdgeInsets.all(12), children: [
            Text('${f['file_no']} · ${f['subject']}', style: Theme.of(context).textTheme.titleMedium),
            Text('${f['priority']} · ${f['status']} · with ${f['holder_name'] ?? '—'}'),
            const Divider(),
            for (final m in moves)
              ListTile(dense: true, title: Text('${m['noting'] ?? ''}'), subtitle: Text('${_day(m['moved_at'])} · ${m['action']} · ${m['from_name'] ?? '—'} → ${m['to_name'] ?? '—'}')),
            if (f['status'] != 'closed')
              Wrap(spacing: 8, children: [
                FilledButton(onPressed: () => _move('forward'), child: const Text('Forward')),
                OutlinedButton(onPressed: () => _move('return'), child: const Text('Return')),
                OutlinedButton(onPressed: () => _move('approve'), child: const Text('Approve')),
                OutlinedButton(onPressed: () => _move('reject'), child: const Text('Reject')),
              ]),
          ]);
        },
      ),
    );
  }
}

// ---- committee secretary desk -----------------------------------------------------------------------------------------------
class CommitteeDeskScreen extends ConsumerStatefulWidget {
  const CommitteeDeskScreen({super.key});

  @override
  ConsumerState<CommitteeDeskScreen> createState() => _CommitteeDeskScreenState();
}

class _CommitteeDeskScreenState extends ConsumerState<CommitteeDeskScreen> {
  late final GovernanceRepository _repo = ref.read(governanceRepositoryProvider);
  int _tick = 0;

  void _refresh() => setState(() => _tick++);

  Future<void> _schedule(Map<String, dynamic> c) async {
    final item = await _ask(context, 'Schedule in 7 days — first agenda item');
    if (item == null || !mounted) return;
    final heldOn = DateTime.now().add(const Duration(days: 7)).toUtc().toIso8601String();
    await _act(context, () => _repo.schedule({'committee_id': c['id'], 'held_on': heldOn, if (item.isNotEmpty) 'agenda': [{'item': item}]}), 'Scheduled', _refresh);
  }

  @override
  Widget build(BuildContext context) {
    return _futureListKeyed(
      ValueKey(_tick),
      _repo.myMeetings(),
      (m) => ExpansionTile(
        title: Text('${m['committee_name']} · ${m['meeting_no'] ?? ''}'),
        subtitle: Text('${_day(m['held_on'])} · ${m['status']}'),
        children: [
          Wrap(spacing: 8, children: [
            if (m['status'] == 'scheduled') OutlinedButton(onPressed: () => _act(context, () => _repo.notice('${m['id']}'), 'Notice sent', _refresh), child: const Text('Send notice')),
            if (m['status'] == 'scheduled' || m['status'] == 'held')
              OutlinedButton(
                  onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => _Roll(repo: _repo, meeting: m))).then((_) => _refresh()),
                  child: const Text('Attendance roll')),
            if (m['status'] == 'held' || m['status'] == 'minutes_draft')
              OutlinedButton(
                  onPressed: () async {
                    final subject = await _ask(context, 'Quick resolution — subject');
                    if (subject == null || subject.isEmpty || !context.mounted) return;
                    final text = await _ask(context, 'Resolution text');
                    if (text == null || text.isEmpty || !context.mounted) return;
                    await _act(
                        context,
                        () => _repo.draftMinutes('${m['id']}', '${m['minutes_text'] ?? 'Minutes recorded during the meeting.'}', [
                              {'subject': subject, 'text': text}
                            ]),
                        'Captured in the minutes draft',
                        _refresh);
                  },
                  child: const Text('Capture resolution')),
          ]),
        ],
      ),
      empty: 'No meetings — schedule one from a committee',
    ).withHeader(
      FutureBuilder<List<Map<String, dynamic>>>(
        future: _repo.myCommittees(),
        builder: (context, snap) => Wrap(spacing: 8, children: [
          for (final c in (snap.data ?? const <Map<String, dynamic>>[]).where((c) => c['my_role'] == 'secretary' || c['my_role'] == 'chair'))
            ActionChip(label: Text('Schedule · ${c['code']}'), onPressed: () => _schedule(c)),
        ]),
      ),
    );
  }
}

extension on Widget {
  Widget withHeader(Widget header) => Column(children: [Padding(padding: const EdgeInsets.all(8), child: header), Expanded(child: this)]);
}

Widget _futureListKeyed(Key key, Future<List<Map<String, dynamic>>> f, Widget Function(Map<String, dynamic>) row, {String empty = 'Nothing pending'}) =>
    KeyedSubtree(key: key, child: _futureList(f, row, empty: empty));

class _Roll extends StatefulWidget {
  const _Roll({required this.repo, required this.meeting});

  final GovernanceRepository repo;
  final Map<String, dynamic> meeting;

  @override
  State<_Roll> createState() => _RollState();
}

class _RollState extends State<_Roll> {
  final Set<String> _present = {};
  Map<String, dynamic>? _quorum;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Attendance roll'), actions: [
        TextButton(
          onPressed: () async {
            try {
              final q = await widget.repo.attendance('${widget.meeting['id']}', _present.toList());
              setState(() => _quorum = q);
            } catch (e) {
              if (context.mounted) _snack(context, _error(e));
            }
          },
          child: const Text('Save'),
        ),
      ]),
      body: FutureBuilder<Map<String, dynamic>>(
        future: widget.repo.committee('${widget.meeting['committee_id']}'),
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final members = ((snap.data!['member_list'] as List?) ?? const []).cast<Map<String, dynamic>>().where((m) => m['active'] == true).toList();
          return ListView(children: [
            if (_quorum != null) ListTile(title: Text(_quorum!['met'] == true ? 'Quorum met' : 'Quorum not met'), subtitle: Text('${_quorum!['present']} present · ${_quorum!['required']} required of ${_quorum!['total']}')),
            for (final m in members)
              CheckboxListTile(
                value: _present.contains('${m['id']}'),
                title: Text('${m['name'] ?? m['member_type']}'),
                subtitle: Text('${m['role']} · ${m['member_type']}'),
                onChanged: (v) => setState(() => v == true ? _present.add('${m['id']}') : _present.remove('${m['id']}')),
              ),
          ]);
        },
      ),
    );
  }
}

// ---- approvals / officers ------------------------------------------------------------------------------------------------------
class GovernanceApprovalsScreen extends ConsumerStatefulWidget {
  const GovernanceApprovalsScreen({super.key});

  @override
  ConsumerState<GovernanceApprovalsScreen> createState() => _GovernanceApprovalsScreenState();
}

class _GovernanceApprovalsScreenState extends ConsumerState<GovernanceApprovalsScreen> {
  late final GovernanceRepository _repo = ref.read(governanceRepositoryProvider);
  int _tick = 0;

  void _refresh() => setState(() => _tick++);

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 5,
      child: Column(children: [
        const TabBar(isScrollable: true, tabs: [Tab(text: 'Minutes'), Tab(text: 'Policies'), Tab(text: 'Pendency'), Tab(text: 'RTI due'), Tab(text: 'Hearings')]),
        Expanded(
          child: TabBarView(key: ValueKey(_tick), children: [
            _futureList(
              _repo.draftMeetings(),
              (m) => ListTile(
                title: Text('${m['committee_name']} · ${m['meeting_no'] ?? ''}'),
                subtitle: Text(_day(m['held_on'])),
                trailing: FilledButton(onPressed: () => _act(context, () => _repo.approveMinutes('${m['id']}'), 'Approved', _refresh), child: const Text('Approve')),
              ),
              empty: 'No minutes awaiting approval',
            ),
            _futureList(
              _repo.submittedPolicies(),
              (p) => ListTile(
                title: Text('${p['title']} v${p['version']}'),
                subtitle: Text('${p['category'] ?? ''}'),
                trailing: FilledButton(
                    onPressed: () async {
                      final res = await _ask(context, 'Council resolution id (if required)');
                      if (res == null || !context.mounted) return;
                      await _act(context, () => _repo.approvePolicy('${p['id']}', res), 'Approved', _refresh);
                    },
                    child: const Text('Approve')),
              ),
              empty: 'No policies awaiting approval',
            ),
            _futureList(
              _repo.pendency(),
              (r) => ListTile(title: Text('${r['holder_name'] ?? '—'}'), subtitle: Text('${r['files']} file(s) · ${r['over_sla']} over SLA · max ${r['max_days']} days')),
              empty: 'No pending files',
            ),
            _futureList(
              _repo.rtiDue(),
              (r) => ListTile(title: Text('${r['request_no']} · ${r['subject']}'), subtitle: Text('Due ${_day(r['due_on'])} (${r['days_left']} days)${r['late'] == true ? ' · late' : ''}')),
              empty: 'No RTI requests due',
            ),
            _futureList(
              _repo.hearings(),
              (h) => ListTile(title: Text('${h['case_no']} · ${h['court'] ?? ''}'), subtitle: Text('Hearing ${_day(h['date'])} · ${h['status']}')),
              empty: 'No hearings in 60 days',
            ),
          ]),
        ),
      ]),
    );
  }
}
