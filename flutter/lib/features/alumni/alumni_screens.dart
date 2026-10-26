import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 29 mobile (Prompts/29 §29.10): the alumni shell — **Home** (engagement, upcoming events, campaign spotlight),
/// **Directory** (consented fields, contact request), **Events** (register / pay via Phase 25; the QR ticket lives in
/// the Events screens), **Give** (campaigns, donate through the gateway checkout, my receipts) and **Profile**
/// (employment, consents, membership card link). Coordinator: **verification queue** and **offline donation record**;
/// event check-in uses the Phase 25 scanner.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _day(dynamic iso) {
  final d = DateTime.tryParse('${iso ?? ''}')?.toLocal();
  return d == null ? '' : '${d.day}/${d.month}/${d.year}';
}

String _inr(dynamic paise) {
  final p = paise is num ? paise : num.tryParse('${paise ?? ''}') ?? 0;
  return '₹${(p / 100).toStringAsFixed(0)}';
}

class AlumniRepository {
  AlumniRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body, Options? options]) async =>
      (await _dio.post<Map<String, dynamic>>(path, data: body ?? {}, options: options)).data?['data'];
  Future<dynamic> _put(String path, [Object? body]) async => (await _dio.put<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();
  Map<String, dynamic> _map(dynamic v) => ((v as Map?) ?? const {}).cast<String, dynamic>();

  Future<Map<String, dynamic>> me() async => _map(await _get('/alumni/me'));
  Future<void> updateMe(Map<String, dynamic> body) => _put('/alumni/me', body);
  Future<void> addEmployment(Map<String, dynamic> body) => _post('/alumni/me/employment', body);
  Future<Map<String, dynamic>> engagement() async => _map(await _get('/alumni/me/engagement'));
  Future<Map<String, dynamic>> directory(Map<String, dynamic> q) async => _map(await _get('/alumni/directory', q));
  Future<void> contact(String id, String message) => _post('/alumni/directory/$id/contact-request', {'message': message});
  Future<List<Map<String, dynamic>>> events() async => _list(await _get('/alumni/events'));
  Future<void> register(String eventId) => _post('/events/$eventId/register', {});
  Future<List<Map<String, dynamic>>> campaigns() async => _list(await _get('/fundraising/campaigns', {'status': 'active'}));
  Future<Map<String, dynamic>> donate(Map<String, dynamic> body) async => _map(await _post(
      '/fundraising/donate', body, Options(headers: {'Idempotency-Key': 'don-${DateTime.now().millisecondsSinceEpoch}'})));
  Future<List<Map<String, dynamic>>> myDonations() async => _list(await _get('/fundraising/donations/me'));
  // coordinator
  Future<List<Map<String, dynamic>>> claimed() async => _list(await _get('/alumni/profiles', {'status': 'claimed'}));
  Future<void> verify(String id, bool approve) => _post('/alumni/profiles/$id/verify', {'approve': approve});
  Future<void> recordDonation(Map<String, dynamic> body) => _post('/fundraising/donations', body);
}

final alumniRepositoryProvider = Provider<AlumniRepository>((ref) => AlumniRepository(ref.watch(dioProvider)));

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

double _pct(Map<String, dynamic> c) => (((c['progress_pct'] as num?) ?? 0) / 100).clamp(0, 1).toDouble();

// ---- alumni shell -------------------------------------------------------------------------------------------------------------
class AlumniHubScreen extends ConsumerStatefulWidget {
  const AlumniHubScreen({super.key});

  @override
  ConsumerState<AlumniHubScreen> createState() => _AlumniHubScreenState();
}

class _AlumniHubScreenState extends ConsumerState<AlumniHubScreen> {
  late final AlumniRepository _repo = ref.read(alumniRepositoryProvider);
  late Future<Map<String, dynamic>> _me = _repo.me();
  late Future<List<Map<String, dynamic>>> _events = _repo.events();
  late Future<List<Map<String, dynamic>>> _campaigns = _repo.campaigns();
  late Future<List<Map<String, dynamic>>> _donations = _repo.myDonations();
  Future<List<Map<String, dynamic>>> _people = Future.value(const []);
  final _q = TextEditingController();

  void _refresh() => setState(() {
        _me = _repo.me();
        _events = _repo.events();
        _campaigns = _repo.campaigns();
        _donations = _repo.myDonations();
      });

  void _search() => setState(() {
        _people = _repo.directory({'q': _q.text.trim()}).then((p) => ((p['items'] as List?) ?? const []).cast<Map<String, dynamic>>());
      });

  Widget _home() => RefreshIndicator(
        onRefresh: () async => _refresh(),
        child: ListView(children: [
          FutureBuilder<Map<String, dynamic>>(
            future: _me,
            builder: (context, snap) {
              if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
              final p = snap.data ?? const {};
              return Card(
                margin: const EdgeInsets.all(12),
                child: ListTile(
                  title: Text('${p['name'] ?? ''}'),
                  subtitle: Text('${p['program'] ?? ''} · ${p['graduation_year'] ?? ''}\nEngagement ${p['engagement_score'] ?? 0} · profile ${p['completeness'] ?? 0}%'),
                  isThreeLine: true,
                  trailing: Chip(label: Text('${p['claim_status'] ?? ''}')),
                ),
              );
            },
          ),
          _header('Upcoming events'),
          _futureList(_events, (e) => ListTile(title: Text('${e['title']}'), subtitle: Text('${_day(e['held_on'])} · ${e['venue'] ?? 'Online'}'))),
          _header('Campaign spotlight'),
          _futureList(_campaigns, (c) => ListTile(title: Text('${c['title']}'), subtitle: LinearProgressIndicator(value: _pct(c)))),
        ]),
      );

  Widget _directory() => ListView(children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: TextField(
            controller: _q,
            decoration: InputDecoration(hintText: 'Name, city, company', suffixIcon: IconButton(icon: const Icon(Icons.search), onPressed: _search)),
            onSubmitted: (_) => _search(),
          ),
        ),
        _futureList(_people, (e) {
          final f = ((e['fields'] as Map?) ?? const {}).cast<String, dynamic>();
          return ListTile(
            title: Text('${f['name'] ?? '—'}'),
            subtitle: Text([f['batch'], f['city'], f['company']].where((x) => x != null).join(' · ')),
            trailing: e['contactable'] == true
                ? IconButton(
                    icon: const Icon(Icons.mail_outline),
                    onPressed: () async {
                      final m = await _ask(context, 'Message', hint: 'Introduce yourself');
                      if (m == null || m.length < 5 || !mounted) return;
                      await _act(context, () => _repo.contact('${e['id']}', m), 'Request relayed', () {});
                    },
                  )
                : null,
          );
        }, empty: 'Search the directory'),
      ]);

  Widget _eventsTab() => RefreshIndicator(
        onRefresh: () async => _refresh(),
        child: ListView(children: [
          _futureList(_events, (e) {
            final fee = (e['registration_fee_paise'] as num?) ?? 0;
            return ListTile(
              title: Text('${e['title']}'),
              subtitle: Text('${_day(e['held_on'])} · ${fee > 0 ? _inr(fee) : 'free'}'),
              trailing: e['my_registration_id'] != null
                  ? const Chip(label: Text('registered'))
                  : (e['event_status'] == 'scheduled'
                      ? FilledButton(onPressed: () => _act(context, () => _repo.register('${e['event_id']}'), fee > 0 ? 'Registered — pay under Fees' : 'Registered', _refresh), child: const Text('Register'))
                      : null),
            );
          }),
        ]),
      );

  Widget _give() => RefreshIndicator(
        onRefresh: () async => _refresh(),
        child: ListView(children: [
          _futureList(_campaigns, (c) => ListTile(
                title: Text('${c['title']}'),
                subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [LinearProgressIndicator(value: _pct(c)), Text('${_inr(c['raised_paise'])} of ${_inr(c['goal_paise'])}')]),
                trailing: FilledButton(
                  onPressed: () async {
                    final amt = await _ask(context, 'Amount (₹)', type: TextInputType.number);
                    final v = num.tryParse(amt ?? '');
                    if (v == null || !mounted) return;
                    try {
                      final r = await _repo.donate({'campaign_id': c['id'], 'amount_paise': (v * 100).round(), 'wants_80g': false});
                      if (mounted) _snack(context, 'Order ${(r['order'] as Map?)?['order_id'] ?? ''} created — complete the UPI / gateway payment');
                    } catch (e) {
                      if (mounted) _snack(context, _error(e));
                    }
                  },
                  child: const Text('Give'),
                ),
              )),
          _header('My donations & receipts'),
          _futureList(_donations, (d) => ListTile(title: Text('${_inr(d['amount_paise'])} · ${d['campaign'] ?? ''}'), subtitle: Text('${_day(d['on_date'])} · ${d['receipt_no'] ?? 'no receipt'}'))),
        ]),
      );

  Widget _profile() => FutureBuilder<Map<String, dynamic>>(
        future: _me,
        builder: (context, snap) {
          final p = snap.data ?? const {};
          final jobs = ((p['employment'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return ListView(children: [
            SwitchListTile(
              title: const Text('Others may contact me'),
              value: p['consent_contact'] == true,
              onChanged: (v) => _act(context, () => _repo.updateMe({'consent_contact': v}), 'Saved', _refresh),
            ),
            SwitchListTile(
              title: const Text('Willing to mentor'),
              value: p['willing_to_mentor'] == true,
              onChanged: (v) => _act(context, () => _repo.updateMe({'willing_to_mentor': v}), 'Saved', _refresh),
            ),
            _header('Employment'),
            for (final j in jobs) ListTile(title: Text('${j['company']}'), subtitle: Text('${j['designation'] ?? ''}${j['is_current'] == true ? ' · current' : ''}')),
            TextButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Add current job'),
              onPressed: () async {
                final c = await _ask(context, 'Company');
                if (c == null || c.isEmpty || !context.mounted) return;
                await _act(context, () => _repo.addEmployment({'company': c, 'is_current': true}), 'Added', _refresh);
              },
            ),
            const ListTile(leading: Icon(Icons.badge_outlined), title: Text('Membership card'), subtitle: Text('Download from the web portal (verified alumni)')),
          ]);
        },
      );

  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 5,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Alumni'),
            bottom: const TabBar(isScrollable: true, tabs: [Tab(text: 'Home'), Tab(text: 'Directory'), Tab(text: 'Events'), Tab(text: 'Give'), Tab(text: 'Profile')]),
          ),
          body: TabBarView(children: [_home(), _directory(), _eventsTab(), _give(), _profile()]),
        ),
      );
}

// ---- coordinator ---------------------------------------------------------------------------------------------------------------
class AlumniCoordinatorScreen extends ConsumerStatefulWidget {
  const AlumniCoordinatorScreen({super.key});

  @override
  ConsumerState<AlumniCoordinatorScreen> createState() => _AlumniCoordinatorScreenState();
}

class _AlumniCoordinatorScreenState extends ConsumerState<AlumniCoordinatorScreen> {
  late final AlumniRepository _repo = ref.read(alumniRepositoryProvider);
  late Future<List<Map<String, dynamic>>> _queue = _repo.claimed();
  final _name = TextEditingController();
  final _amount = TextEditingController();
  final _ref = TextEditingController();
  String _mode = 'cheque';

  void _refresh() => setState(() => _queue = _repo.claimed());

  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 2,
        child: Scaffold(
          appBar: AppBar(title: const Text('Alumni office'), bottom: const TabBar(tabs: [Tab(text: 'Verification'), Tab(text: 'Offline donation')])),
          body: TabBarView(children: [
            RefreshIndicator(
              onRefresh: () async => _refresh(),
              child: ListView(children: [
                _futureList(_queue, (p) => ListTile(
                      title: Text('${p['name']}'),
                      subtitle: Text('${p['registration_number'] ?? ''} · ${p['graduation_year'] ?? ''}'),
                      trailing: Wrap(spacing: 4, children: [
                        IconButton(icon: const Icon(Icons.check_circle_outline), onPressed: () => _act(context, () => _repo.verify('${p['id']}', true), 'Verified', _refresh)),
                        IconButton(icon: const Icon(Icons.cancel_outlined), onPressed: () => _act(context, () => _repo.verify('${p['id']}', false), 'Rejected', _refresh)),
                      ]),
                    ), empty: 'No claims waiting'),
              ]),
            ),
            ListView(padding: const EdgeInsets.all(16), children: [
              TextField(controller: _name, decoration: const InputDecoration(labelText: 'Donor name')),
              TextField(controller: _amount, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Amount (₹)')),
              DropdownButtonFormField<String>(
                initialValue: _mode,
                items: const [
                  DropdownMenuItem(value: 'cheque', child: Text('Cheque')),
                  DropdownMenuItem(value: 'bank_transfer', child: Text('Bank transfer')),
                  DropdownMenuItem(value: 'upi', child: Text('UPI')),
                  DropdownMenuItem(value: 'cash', child: Text('Cash')),
                ],
                onChanged: (v) => setState(() => _mode = v ?? 'cheque'),
              ),
              TextField(controller: _ref, decoration: const InputDecoration(labelText: 'Reference (UTR / cheque no.)')),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: () => _act(
                  context,
                  () => _repo.recordDonation({
                    'donor_type': 'individual',
                    'donor_ref': {'name': _name.text.trim()},
                    'amount_paise': ((num.tryParse(_amount.text) ?? 0) * 100).round(),
                    'mode': _mode,
                    'on_date': DateTime.now().toIso8601String().substring(0, 10),
                    'reference': _ref.text.trim().isEmpty ? null : _ref.text.trim(),
                  }),
                  'Donation recorded',
                  () {
                    _name.clear();
                    _amount.clear();
                    _ref.clear();
                  },
                ),
                child: const Text('Record'),
              ),
            ]),
          ]),
        ),
      );
}
