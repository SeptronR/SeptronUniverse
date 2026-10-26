import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 30 mobile (Prompts/30 §30.10). Faculty: **My research** (counts, add a publication by DOI paste with a
/// Crossref lookup, FDP record with the certificate link, incentive status, project ledger balance, MoU expiry alerts);
/// HOD: **verification queue** (approve / reject with remarks) and department stats; research cell: **approvals**
/// (incentives waiting on the caller, ethics applications to decide). Scholars reuse the publications list.
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

class ResearchRepository {
  ResearchRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();
  Map<String, dynamic> _map(dynamic v) => ((v as Map?) ?? const {}).cast<String, dynamic>();

  Future<Map<String, dynamic>> profile() async => _map(await _get('/research/profile/me'));
  Future<List<Map<String, dynamic>>> publications(Map<String, dynamic> q) async => _list(await _get('/research/publications', q));
  Future<Map<String, dynamic>> lookupDoi(String doi) async => _map(await _post('/research/publications/import/preview', {'source': 'crossref', 'identifier': doi}));
  Future<Map<String, dynamic>> applyImport(String token) async => _map(await _post('/research/publications/import/apply?inline=true', {'token': token}));
  Future<void> claim(String id) => _post('/research/publications/$id/claim-coauthor', {});
  Future<void> verify(List<String> ids, bool approve, String remarks) =>
      _post('/research/publications/verify', {'ids': ids, 'approve': approve, if (remarks.isNotEmpty) 'remarks': remarks});
  Future<void> addFdp(Map<String, dynamic> body) => _post('/research/fdp', body);
  Future<List<Map<String, dynamic>>> myIncentives() async => _list(await _get('/research/incentives/me'));
  Future<List<Map<String, dynamic>>> incentives() async => _list(await _get('/research/incentives', {'status': 'requested'}));
  Future<void> decideIncentive(String id, bool approve) => _post('/research/incentives/$id/decide', {'decision': approve ? 'approve' : 'reject'});
  Future<List<Map<String, dynamic>>> myProjects() async => _list(await _get('/research/projects/me'));
  Future<List<Map<String, dynamic>>> expiringMous() async => _list(await _get('/research/mous', {'expiring': true}));
  Future<List<Map<String, dynamic>>> pendingEthics() async => _list(await _get('/research/ethics/applications', {'status': 'pending'}));
  Future<void> decideEthics(String id, String decision) => _post('/research/ethics/applications/$id/decide', {'decision': decision});
  Future<Map<String, dynamic>> stats(Map<String, dynamic> q) async => _map(await _get('/research/stats', q));
}

final researchRepositoryProvider = Provider<ResearchRepository>((ref) => ResearchRepository(ref.watch(dioProvider)));

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

// ---- faculty: my research -------------------------------------------------------------------------------------------------------
class FacultyResearchScreen extends ConsumerStatefulWidget {
  const FacultyResearchScreen({super.key});

  @override
  ConsumerState<FacultyResearchScreen> createState() => _FacultyResearchScreenState();
}

class _FacultyResearchScreenState extends ConsumerState<FacultyResearchScreen> {
  late final ResearchRepository _repo = ref.read(researchRepositoryProvider);
  late Future<Map<String, dynamic>> _profile = _repo.profile();
  late Future<List<Map<String, dynamic>>> _incentives = _repo.myIncentives();
  late Future<List<Map<String, dynamic>>> _projects = _repo.myProjects();
  late Future<List<Map<String, dynamic>>> _mous = _repo.expiringMous();

  void _refresh() => setState(() {
        _profile = _repo.profile();
        _incentives = _repo.myIncentives();
        _projects = _repo.myProjects();
        _mous = _repo.expiringMous();
      });

  Future<void> _addByDoi() async {
    final doi = await _ask(context, 'Add publication by DOI', hint: '10.xxxx/…');
    if (doi == null || doi.isEmpty || !mounted) return;
    try {
      final prev = await _repo.lookupDoi(doi);
      final news = (prev['new'] as List?) ?? const [];
      final matches = (prev['matches'] as List?) ?? const [];
      if (news.isEmpty && matches.isEmpty) {
        if (mounted) _snack(context, 'Already in your publications');
        return;
      }
      final w = ((news.isNotEmpty ? news.first : matches.first) as Map).cast<String, dynamic>();
      if (!mounted) return;
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(news.isNotEmpty ? 'Add this publication?' : 'Claim co-authorship?'),
          content: Text('${w['title']}\n${w['venue'] ?? ''} ${w['year'] ?? ''}\n${(w['indexing'] ?? '').toString().toUpperCase()}'),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Confirm'))],
        ),
      );
      if (ok != true || !mounted) return;
      await _act(context, () async => _repo.applyImport('${prev['token']}'), news.isNotEmpty ? 'Added (unverified)' : 'Claimed', _refresh);
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  Future<void> _addFdp() async {
    final title = await _ask(context, 'FDP / workshop title');
    if (title == null || title.length < 3 || !mounted) return;
    final hours = await _ask(context, 'Hours', type: TextInputType.number);
    if (!mounted) return;
    final cert = await _ask(context, 'Certificate link (photo uploaded to Files)', hint: 'https://…');
    if (!mounted) return;
    await _act(
        context,
        () => _repo.addFdp({'title': title, 'event_type': 'fdp', 'hours': num.tryParse(hours ?? ''), if ((cert ?? '').isNotEmpty) 'certificate_url': cert}),
        'FDP recorded',
        _refresh);
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _refresh(),
      child: ListView(
        children: [
          FutureBuilder<Map<String, dynamic>>(
            future: _profile,
            builder: (context, snap) {
              final p = snap.data;
              if (p == null) return const Padding(padding: EdgeInsets.all(16), child: LinearProgressIndicator());
              return GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                childAspectRatio: 2.4,
                padding: const EdgeInsets.all(8),
                children: [
                  _stat('Publications', '${p['verified_publications']}/${p['publications']}'),
                  _stat('Citations · h', '${p['citations']} · ${p['h_index']}'),
                  _stat('Projects', '${p['projects']} (${p['ongoing_projects']} live)'),
                  _stat('FDP hours', '${p['fdp_hours']}'),
                  _stat('Patents', '${p['patents']}'),
                  _stat('API score', '${p['api_score'] ?? '—'}'),
                ],
              );
            },
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Wrap(spacing: 8, children: [
              FilledButton.icon(onPressed: _addByDoi, icon: const Icon(Icons.qr_code_scanner), label: const Text('Add by DOI')),
              OutlinedButton.icon(onPressed: _addFdp, icon: const Icon(Icons.workspace_premium_outlined), label: const Text('FDP record')),
            ]),
          ),
          _header('Projects — ledger balance'),
          _futureList(
              _projects,
              (p) => ListTile(
                    title: Text('${p['title']}'),
                    subtitle: Text('${p['funding_agency'] ?? ''} · ${p['status']} · ${p['utilisation_pct']}% used'),
                    trailing: Text(_inr(((p['received_paise'] as num?) ?? 0) - ((p['utilised_paise'] as num?) ?? 0))),
                  ),
              empty: 'No projects'),
          _header('Incentive requests'),
          _futureList(
              _incentives,
              (r) => ListTile(
                    title: Text('${r['incentive_type']}'.replaceAll('_', ' ')),
                    subtitle: Text('Step ${r['current_step'] ?? '—'} · ${r['workflow_status'] ?? ''}'),
                    trailing: Chip(label: Text('${r['status']} · ${_inr(r['amount_paise'])}')),
                  ),
              empty: 'No requests'),
          _header('MoUs expiring'),
          _futureList(
              _mous,
              (m) => ListTile(
                    leading: const Icon(Icons.handshake_outlined),
                    title: Text('${m['partner']}'),
                    subtitle: Text('Valid to ${m['valid_to'] ?? '—'} · ${m['days_to_expiry'] ?? ''} days'),
                  ),
              empty: 'None in the alert window'),
        ],
      ),
    );
  }
}

// ---- HOD: verification queue ----------------------------------------------------------------------------------------------------
class ResearchVerificationScreen extends ConsumerStatefulWidget {
  const ResearchVerificationScreen({super.key});

  @override
  ConsumerState<ResearchVerificationScreen> createState() => _ResearchVerificationScreenState();
}

class _ResearchVerificationScreenState extends ConsumerState<ResearchVerificationScreen> {
  late final ResearchRepository _repo = ref.read(researchRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _queue = _repo.publications({'verified': false, 'scope': 'department', 'per_page': 100});
  late Future<Map<String, dynamic>> _stats = _repo.stats({'year': DateTime.now().year});

  void _refresh() => setState(() {
        _queue = _repo.publications({'verified': false, 'scope': 'department', 'per_page': 100});
        _stats = _repo.stats({'year': DateTime.now().year});
      });

  Future<void> _decide(Map<String, dynamic> p, bool approve) async {
    final remarks = approve ? '' : (await _ask(context, 'Reason for returning') ?? '');
    if (!mounted) return;
    await _act(context, () => _repo.verify(['${p['id']}'], approve, remarks), approve ? 'Verified' : 'Returned', _refresh);
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _refresh(),
      child: ListView(
        children: [
          FutureBuilder<Map<String, dynamic>>(
            future: _stats,
            builder: (context, snap) {
              final s = snap.data;
              if (s == null) return const SizedBox.shrink();
              return Padding(
                padding: const EdgeInsets.all(8),
                child: Row(children: [
                  Expanded(child: _stat('Publications ${DateTime.now().year}', '${s['publications']}')),
                  Expanded(child: _stat('Per teacher', '${s['per_teacher']}')),
                  Expanded(child: _stat('Grants', _inr(s['grants_amount_paise']))),
                ]),
              );
            },
          ),
          _header('Awaiting verification'),
          _futureList(
              _queue,
              (p) => Card(
                    margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                    child: ListTile(
                      title: Text('${p['title']}'),
                      subtitle: Text('${p['staff_name'] ?? ''} · ${p['venue'] ?? ''} ${p['year'] ?? ''} · ${(p['indexing'] ?? '').toString().toUpperCase()} · ${p['verification_level']}'),
                      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                        IconButton(icon: const Icon(Icons.check_circle_outline), onPressed: () => _decide(p, true)),
                        IconButton(icon: const Icon(Icons.undo), onPressed: () => _decide(p, false)),
                      ]),
                    ),
                  ),
              empty: 'Queue is empty'),
        ],
      ),
    );
  }
}

// ---- research cell: approvals inbox -------------------------------------------------------------------------------------------------
class ResearchApprovalsScreen extends ConsumerStatefulWidget {
  const ResearchApprovalsScreen({super.key});

  @override
  ConsumerState<ResearchApprovalsScreen> createState() => _ResearchApprovalsScreenState();
}

class _ResearchApprovalsScreenState extends ConsumerState<ResearchApprovalsScreen> {
  late final ResearchRepository _repo = ref.read(researchRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _incentives = _mine();
  late Future<List<Map<String, dynamic>>> _ethics = _repo.pendingEthics();

  Future<List<Map<String, dynamic>>> _mine() async => (await _repo.incentives()).where((r) => r['can_act'] == true).toList();

  void _refresh() => setState(() {
        _incentives = _mine();
        _ethics = _repo.pendingEthics();
      });

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _refresh(),
      child: ListView(
        children: [
          _header('Incentives waiting on you'),
          _futureList(
              _incentives,
              (r) => ListTile(
                    title: Text('${r['staff_name'] ?? ''} · ${'${r['incentive_type']}'.replaceAll('_', ' ')}'),
                    subtitle: Text('${_inr(r['amount_paise'])} · step ${r['current_step']}'),
                    trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                      IconButton(icon: const Icon(Icons.check), onPressed: () => _act(context, () => _repo.decideIncentive('${r['id']}', true), 'Approved', _refresh)),
                      IconButton(icon: const Icon(Icons.close), onPressed: () => _act(context, () => _repo.decideIncentive('${r['id']}', false), 'Rejected', _refresh)),
                    ]),
                  ),
              empty: 'Nothing waiting'),
          _header('Ethics applications'),
          _futureList(
              _ethics,
              (a) => ListTile(
                    title: Text('${a['project_title']}'),
                    subtitle: Text('${a['committee_type'] ?? ''} · ${a['category'] ?? ''} · ${(a['reviews'] as List?)?.length ?? 0} review(s)'),
                    trailing: PopupMenuButton<String>(
                      onSelected: (d) => _act(context, () => _repo.decideEthics('${a['id']}', d), 'Decided: $d', _refresh),
                      itemBuilder: (_) => const [
                        PopupMenuItem(value: 'approved', child: Text('Approve')),
                        PopupMenuItem(value: 'revise', child: Text('Revise')),
                        PopupMenuItem(value: 'rejected', child: Text('Reject')),
                      ],
                    ),
                  ),
              empty: 'No pending applications'),
          const Padding(padding: EdgeInsets.all(16), child: Text('Project sanctions and MoUs are acknowledged in the approvals inbox.')),
        ],
      ),
    );
  }
}
