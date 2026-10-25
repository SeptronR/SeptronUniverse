import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// Phase 25 mobile (Prompts/25 §25.10): **SOS** (long-press, confirm, status), **Events** (browse, register, QR
/// ticket), **Service requests** (raise, track, rate), **Wellness** (book counselling, my visits), **Wallet** (balance,
/// top-up, pay QR), security officer **Responder** board (acknowledge / resolve) and **Gate scan** (visitor pass in / out),
/// estate officer service-desk actions live on the same Service requests screen (assign / resolve via the web).
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _rupees(dynamic p) => '₹${(((p ?? 0) as num) / 100).toStringAsFixed(0)}';
String _when(dynamic iso) {
  final d = DateTime.tryParse('${iso ?? ''}')?.toLocal();
  if (d == null) return '';
  return '${d.day}/${d.month} ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

class FacilitiesRepository {
  FacilitiesRepository(this._dio);

  final Dio _dio;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async => (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path, data: body ?? {})).data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<Map<String, dynamic>> sos(String type, String where) async => ((await _post('/emergency/sos', {'alert_type': type, 'location': {'text': where}})) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> myAlerts() async => _list(await _get('/emergency/me'));
  Future<List<Map<String, dynamic>>> alerts() async => _list(await _get('/emergency/alerts'));
  Future<void> alertAct(String id, String act) => _post('/emergency/alerts/$id/$act', {'notes': null});
  Future<List<Map<String, dynamic>>> events() async => _list(await _get('/events', {'status': 'scheduled'}));
  Future<List<Map<String, dynamic>>> myEvents() async => _list(await _get('/events/me'));
  Future<void> register(String id) => _post('/events/$id/register', {'person_type': 'student'});
  Future<List<Map<String, dynamic>>> tickets() async => _list(await _get('/facilities/service-requests/me'));
  Future<void> raise(String category, String description) => _post('/facilities/service-requests', {'category': category, 'description': description});
  Future<void> rate(String id, int rating) => _post('/facilities/service-requests/$id/rate', {'rating': rating});
  Future<List<Map<String, dynamic>>> slots() async => _list(await _get('/counselling/slots/available'));
  Future<void> book(String id) => _post('/counselling/slots/$id/book', {});
  Future<List<Map<String, dynamic>>> visits() async => _list(await _get('/health/visits/me'));
  Future<Map<String, dynamic>> wallet() async => ((await _get('/wallet/me')) as Map).cast<String, dynamic>();
  Future<void> topup(int paise) => _post('/wallet/topup', {'amount_paise': paise});
  Future<Map<String, dynamic>> scan(String code, String direction) async =>
      ((await _post('/facilities/visitor-passes/scan', {'pass_code': code, 'direction': direction})) as Map).cast<String, dynamic>();
}

final facilitiesRepositoryProvider = Provider<FacilitiesRepository>((ref) => FacilitiesRepository(ref.watch(dioProvider)));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

Widget _futureList(Future<List<Map<String, dynamic>>> f, Widget Function(Map<String, dynamic>) row, {String empty = 'Nothing yet'}) => FutureBuilder<List<Map<String, dynamic>>>(
      future: f,
      builder: (context, snap) {
        if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
        if (!snap.hasData) return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
        if (snap.data!.isEmpty) return Padding(padding: const EdgeInsets.all(16), child: Text(empty));
        return Column(children: [for (final r in snap.data!) row(r)]);
      },
    );

// ---- SOS -------------------------------------------------------------------------------------------------------------
class SosScreen extends ConsumerStatefulWidget {
  const SosScreen({super.key});

  @override
  ConsumerState<SosScreen> createState() => _SosScreenState();
}

class _SosScreenState extends ConsumerState<SosScreen> {
  String _type = 'sos';
  final _where = TextEditingController();
  late Future<List<Map<String, dynamic>>> _mine = ref.read(facilitiesRepositoryProvider).myAlerts();

  Future<void> _raise() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Send SOS?'),
        content: const Text('Security responders will be alerted with your location.'),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Send'))],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(facilitiesRepositoryProvider).sos(_type, _where.text.trim().isEmpty ? 'Campus' : _where.text.trim());
      if (mounted) _snack(context, 'Help is being alerted');
      setState(() => _mine = ref.read(facilitiesRepositoryProvider).myAlerts());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Emergency SOS')),
        body: ListView(padding: const EdgeInsets.all(16), children: [
          Wrap(spacing: 8, children: [
            for (final t in ['sos', 'medical', 'fire', 'security']) ChoiceChip(label: Text(t), selected: _type == t, onSelected: (_) => setState(() => _type = t)),
          ]),
          TextField(controller: _where, decoration: const InputDecoration(labelText: 'Where are you?')),
          const SizedBox(height: 24),
          Center(
            child: GestureDetector(
              onLongPress: _raise,
              child: Container(
                width: 180,
                height: 180,
                decoration: const BoxDecoration(color: Colors.red, shape: BoxShape.circle),
                alignment: Alignment.center,
                child: const Text('HOLD\nfor SOS', textAlign: TextAlign.center, style: TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.bold)),
              ),
            ),
          ),
          const SizedBox(height: 24),
          Text('My alerts', style: Theme.of(context).textTheme.titleMedium),
          _futureList(_mine, (a) => ListTile(leading: const Icon(Icons.warning_amber, color: Colors.red), title: Text('${a['alert_type']} · ${a['status']}'), subtitle: Text(_when(a['created_at'])))),
        ]),
      );
}

// ---- responder (security officer) ---------------------------------------------------------------------------------
class SosResponderScreen extends ConsumerStatefulWidget {
  const SosResponderScreen({super.key});

  @override
  ConsumerState<SosResponderScreen> createState() => _SosResponderScreenState();
}

class _SosResponderScreenState extends ConsumerState<SosResponderScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(facilitiesRepositoryProvider).alerts();

  Future<void> _act(String id, String act) async {
    try {
      await ref.read(facilitiesRepositoryProvider).alertAct(id, act);
      setState(() => _f = ref.read(facilitiesRepositoryProvider).alerts());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('SOS responder')),
        body: RefreshIndicator(
          onRefresh: () async => setState(() => _f = ref.read(facilitiesRepositoryProvider).alerts()),
          child: ListView(children: [
            _futureList(_f, (a) => Card(
                  child: ListTile(
                    title: Text('${a['drill'] == true ? '[DRILL] ' : ''}${a['alert_type']} — ${a['raised_by_name'] ?? ''}'),
                    subtitle: Text('${(a['location'] as Map?)?['text'] ?? a['map_url'] ?? ''} · ${_when(a['created_at'])} · ${a['status']}'),
                    trailing: Wrap(spacing: 4, children: [
                      if (a['status'] == 'raised') IconButton(icon: const Icon(Icons.check), tooltip: 'Acknowledge', onPressed: () => _act('${a['id']}', 'acknowledge')),
                      if (a['status'] != 'resolved') IconButton(icon: const Icon(Icons.done_all), tooltip: 'Resolve', onPressed: () => _act('${a['id']}', 'resolve')),
                    ]),
                  ),
                ), empty: 'No alerts'),
          ]),
        ),
      );
}

// ---- events ---------------------------------------------------------------------------------------------------------
class CampusEventsScreen extends ConsumerStatefulWidget {
  const CampusEventsScreen({super.key});

  @override
  ConsumerState<CampusEventsScreen> createState() => _CampusEventsScreenState();
}

class _CampusEventsScreenState extends ConsumerState<CampusEventsScreen> {
  late Future<List<Map<String, dynamic>>> _all = ref.read(facilitiesRepositoryProvider).events();
  late Future<List<Map<String, dynamic>>> _mine = ref.read(facilitiesRepositoryProvider).myEvents();

  void _reload() => setState(() {
        _all = ref.read(facilitiesRepositoryProvider).events();
        _mine = ref.read(facilitiesRepositoryProvider).myEvents();
      });

  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 2,
        child: Scaffold(
          appBar: AppBar(title: const Text('Events'), bottom: const TabBar(tabs: [Tab(text: 'Upcoming'), Tab(text: 'My tickets')])),
          body: TabBarView(children: [
            ListView(children: [
              _futureList(_all, (e) => ListTile(
                    title: Text('${e['title']}'),
                    subtitle: Text('${e['event_type']} · ${e['from_on']} · ${e['venue_label'] ?? ''}'),
                    trailing: e['my_registration'] == null && (e['registration'] as Map?)?['open'] == true
                        ? FilledButton(
                            onPressed: () async {
                              try {
                                await ref.read(facilitiesRepositoryProvider).register('${e['id']}');
                                if (context.mounted) _snack(context, 'Registered');
                                _reload();
                              } catch (err) {
                                if (context.mounted) _snack(context, _error(err));
                              }
                            },
                            child: const Text('Register'))
                        : const Icon(Icons.check_circle_outline),
                  )),
            ]),
            ListView(children: [
              _futureList(_mine, (m) {
                final ev = (m['event'] as Map).cast<String, dynamic>();
                final reg = (m['registration'] as Map).cast<String, dynamic>();
                return ListTile(
                  leading: const Icon(Icons.qr_code_2),
                  title: Text('${ev['title']}'),
                  subtitle: Text('${ev['from_on']} · ${reg['waitlisted'] == true ? 'waitlisted' : 'ticket ${reg['qr_token'] ?? ''}'}${reg['certificate_url'] != null ? ' · certificate ready' : ''}'),
                );
              }, empty: 'No registrations'),
            ]),
          ]),
        ),
      );
}

// ---- service requests -------------------------------------------------------------------------------------------------
class ServiceRequestsScreen extends ConsumerStatefulWidget {
  const ServiceRequestsScreen({super.key});

  @override
  ConsumerState<ServiceRequestsScreen> createState() => _ServiceRequestsScreenState();
}

class _ServiceRequestsScreenState extends ConsumerState<ServiceRequestsScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(facilitiesRepositoryProvider).tickets();

  Future<void> _new() async {
    String cat = 'it';
    final desc = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('Raise a ticket'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButton<String>(
              isExpanded: true,
              value: cat,
              items: [for (final c in ['electrical', 'plumbing', 'it', 'network', 'furniture', 'cleaning', 'civil', 'security', 'other']) DropdownMenuItem(value: c, child: Text(c))],
              onChanged: (v) => set(() => cat = v ?? 'it'),
            ),
            TextField(controller: desc, maxLines: 3, decoration: const InputDecoration(labelText: 'What is the problem?')),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Raise'))],
        ),
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(facilitiesRepositoryProvider).raise(cat, desc.text);
      setState(() => _f = ref.read(facilitiesRepositoryProvider).tickets());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Service requests')),
        floatingActionButton: FloatingActionButton(onPressed: _new, child: const Icon(Icons.add)),
        body: RefreshIndicator(
          onRefresh: () async => setState(() => _f = ref.read(facilitiesRepositoryProvider).tickets()),
          child: ListView(children: [
            _futureList(_f, (t) => ListTile(
                  title: Text('${t['ticket_number']} · ${t['category']}'),
                  subtitle: Text('${t['description']}\n${t['status']}${t['sla_breached'] == true ? ' · SLA breached' : ''}'),
                  isThreeLine: true,
                  trailing: t['status'] == 'resolved'
                      ? TextButton(
                          onPressed: () async {
                            try {
                              await ref.read(facilitiesRepositoryProvider).rate('${t['id']}', 5);
                              setState(() => _f = ref.read(facilitiesRepositoryProvider).tickets());
                            } catch (e) {
                              if (context.mounted) _snack(context, _error(e));
                            }
                          },
                          child: const Text('Rate ★5'))
                      : null,
                ), empty: 'No tickets'),
          ]),
        ),
      );
}

// ---- wellness ---------------------------------------------------------------------------------------------------------
class WellnessScreen extends ConsumerStatefulWidget {
  const WellnessScreen({super.key});

  @override
  ConsumerState<WellnessScreen> createState() => _WellnessScreenState();
}

class _WellnessScreenState extends ConsumerState<WellnessScreen> {
  late Future<List<Map<String, dynamic>>> _slots = ref.read(facilitiesRepositoryProvider).slots();
  late final Future<List<Map<String, dynamic>>> _visits = ref.read(facilitiesRepositoryProvider).visits();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Wellness')),
        body: ListView(padding: const EdgeInsets.all(8), children: [
          Text('Book counselling (confidential)', style: Theme.of(context).textTheme.titleMedium),
          _futureList(_slots, (s) => ListTile(
                title: Text(_when(s['slot_at'])),
                subtitle: Text('${s['counsellor_name'] ?? ''} · ${s['duration_minutes']} min'),
                trailing: FilledButton(
                  onPressed: () async {
                    try {
                      await ref.read(facilitiesRepositoryProvider).book('${s['id']}');
                      if (context.mounted) _snack(context, 'Booked');
                      setState(() => _slots = ref.read(facilitiesRepositoryProvider).slots());
                    } catch (e) {
                      if (context.mounted) _snack(context, _error(e));
                    }
                  },
                  child: const Text('Book'),
                ),
              ), empty: 'No open slots'),
          const Divider(),
          Text('My health visits', style: Theme.of(context).textTheme.titleMedium),
          _futureList(_visits, (v) => ListTile(title: Text('${v['complaint'] ?? 'Visit'}'), subtitle: Text('${_when(v['visited_at'])} · ${v['diagnosis'] ?? ''}')), empty: 'No visits'),
        ]),
      );
}

// ---- wallet ---------------------------------------------------------------------------------------------------------
class WalletScreen extends ConsumerStatefulWidget {
  const WalletScreen({super.key});

  @override
  ConsumerState<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends ConsumerState<WalletScreen> {
  late Future<Map<String, dynamic>> _f = ref.read(facilitiesRepositoryProvider).wallet();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Wallet')),
        body: FutureBuilder<Map<String, dynamic>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final w = snap.data!;
            final recent = ((w['recent'] as List?) ?? const []).cast<Map<String, dynamic>>();
            return ListView(padding: const EdgeInsets.all(16), children: [
              Text(_rupees(w['balance_paise']), style: Theme.of(context).textTheme.displaySmall),
              Text('Pay code: ${w['pay_qr'] ?? 'top up to create your wallet'}'),
              const SizedBox(height: 12),
              Wrap(spacing: 8, children: [
                for (final amt in [100, 200, 500])
                  OutlinedButton(
                    onPressed: () async {
                      try {
                        await ref.read(facilitiesRepositoryProvider).topup(amt * 100);
                        setState(() => _f = ref.read(facilitiesRepositoryProvider).wallet());
                      } catch (e) {
                        if (context.mounted) _snack(context, _error(e));
                      }
                    },
                    child: Text('+₹$amt'),
                  ),
              ]),
              const Divider(),
              for (final t in recent) ListTile(dense: true, title: Text('${t['txn_type']} ${_rupees(t['amount_paise'])}'), subtitle: Text('${t['merchant'] ?? ''} · ${_when(t['created_at'])}')),
            ]);
          },
        ),
      );
}

// ---- gate scan (security) ---------------------------------------------------------------------------------------------
class VisitorGateScanScreen extends ConsumerStatefulWidget {
  const VisitorGateScanScreen({super.key});

  @override
  ConsumerState<VisitorGateScanScreen> createState() => _VisitorGateScanScreenState();
}

class _VisitorGateScanScreenState extends ConsumerState<VisitorGateScanScreen> {
  final _code = TextEditingController();
  String? _last;

  Future<void> _scan(String dir) async {
    try {
      final p = await ref.read(facilitiesRepositoryProvider).scan(_code.text.trim(), dir);
      setState(() => _last = '${(p['visitor'] as Map?)?['name']} · ${p['status']}');
      _code.clear();
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Gate scan')),
        body: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(children: [
            TextField(controller: _code, decoration: const InputDecoration(labelText: 'Visitor pass code / QR')),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: FilledButton.icon(icon: const Icon(Icons.login), label: const Text('In'), onPressed: () => _scan('in'))),
              const SizedBox(width: 8),
              Expanded(child: OutlinedButton.icon(icon: const Icon(Icons.logout), label: const Text('Out'), onPressed: () => _scan('out'))),
            ]),
            if (_last != null) Padding(padding: const EdgeInsets.all(16), child: Text(_last!, style: Theme.of(context).textTheme.titleMedium)),
          ]),
        ),
      );
}
