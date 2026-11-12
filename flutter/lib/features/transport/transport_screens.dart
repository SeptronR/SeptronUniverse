import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:geolocator/geolocator.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../core/offline/cache_repository.dart';
import '../../core/providers.dart';

/// Phase 21 mobile (Prompts/21 §21.10): driver **Trips** (today's trips → start / end with odometer, stop list with
/// arrive / depart, passenger QR scan, GPS auto-ping while the trip runs with an offline buffer flushed as one batch),
/// student / staff **My transport** (route, stop, times, fee, live bus + ETA during a trip, change request), parent
/// **Ward transport** (ward bus live, ETA; boarding / alighting arrive as push) and the transport manager **Fleet**
/// (stats, delays, compliance alerts, live vehicles, today's trips). Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _hm(dynamic v) => v == null ? '—' : '$v'.substring(0, 5);
String _rupees(dynamic p) => '₹${(((p ?? 0) as num) / 100).toStringAsFixed(0)}';

class TransportRepository {
  TransportRepository(this._dio, this._cache);

  final Dio _dio;
  final CacheRepository _cache;
  static const _bufferKey = 'transport.gps_buffer';

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body, bool idem = false]) async => (await _dio.post<Map<String, dynamic>>(path,
          data: body ?? {},
          options: idem ? Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()}) : null))
      .data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<Map<String, dynamic>> me() async => ((await _get('/transport/me')) as Map?)?.cast<String, dynamic>() ?? {};
  Future<List<Map<String, dynamic>>> wards() async => _list(await _get('/transport/wards'));
  Future<List<Map<String, dynamic>>> publicRoutes() async => _list(await _get('/transport/routes/public'));
  Future<void> request(String routeId, String stopId) => _post('/transport/me/request', {'route_id': routeId, 'stop_id': stopId});
  Future<List<Map<String, dynamic>>> live({String? routeId}) async {
    try {
      return _list(await _get('/transport/live', {if (routeId != null) 'route_id': routeId}));
    } catch (_) {
      return const [];
    }
  }

  // driver
  Future<List<Map<String, dynamic>>> driverTrips() async => _list(await _get('/transport/driver/trips'));
  Future<Map<String, dynamic>> manifest(String id) async => ((await _get('/transport/trips/$id/manifest')) as Map).cast<String, dynamic>();
  Future<void> start(String id, int? odometer) => _post('/transport/trips/$id/start', {'odometer': odometer});
  Future<Map<String, dynamic>> end(String id, int? odometer) async =>
      ((await _post('/transport/trips/$id/end', {'odometer': odometer})) as Map).cast<String, dynamic>();
  Future<void> stopEvent(String id, String stopId, String event) => _post('/transport/trips/$id/stop-event', {'stop_id': stopId, 'event': event});
  Future<Map<String, dynamic>> scan(String id, String qr, String event) async =>
      ((await _post('/transport/trips/$id/passenger-scan', {'qr': qr, 'event': event}, true)) as Map).cast<String, dynamic>();

  // manager
  Future<Map<String, dynamic>> stats() async => ((await _get('/transport/stats')) as Map).cast<String, dynamic>();
  Future<List<Map<String, dynamic>>> trips() async => _list(await _get('/transport/trips'));
  Future<List<Map<String, dynamic>>> compliance() async => _list(await _get('/transport/vehicles/compliance'));

  // ---- GPS buffer: pings are queued locally and sent as one batch (the server ignores duplicate timestamps) -----------
  Future<List<Map<String, dynamic>>> buffered() async {
    final hit = await _cache.read(_bufferKey);
    return hit == null ? [] : (jsonDecode(hit.json) as List).cast<Map<String, dynamic>>();
  }

  Future<void> buffer(Position p) async {
    final q = await buffered()
      ..add({
        'lat': p.latitude,
        'lng': p.longitude,
        'speed_kmh': p.speed >= 0 ? p.speed * 3.6 : null,
        'heading': p.heading >= 0 ? p.heading.round() % 361 : null,
        'recorded_at': p.timestamp.toUtc().toIso8601String(),
      });
    await _cache.write(_bufferKey, jsonEncode(q.length > 500 ? q.sublist(q.length - 500) : q), ttl: const Duration(days: 2));
  }

  Future<int> flush(String tripId) async {
    final q = await buffered();
    if (q.isEmpty) return 0;
    await _post('/transport/gps/ingest', {'trip_id': tripId, 'pings': q});
    await _cache.write(_bufferKey, jsonEncode([]), ttl: const Duration(days: 2));
    return q.length;
  }
}

final transportRepositoryProvider = Provider<TransportRepository>((ref) => TransportRepository(ref.watch(dioProvider), ref.watch(cacheRepositoryProvider)));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

Future<int?> _askOdometer(BuildContext context, String title) async {
  final c = TextEditingController();
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(controller: c, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Odometer (km, optional)')),
      actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('OK'))],
    ),
  );
  if (ok != true) return -1;
  return int.tryParse(c.text);
}

// ---- driver ------------------------------------------------------------------------------------------------------------------
class DriverTripsScreen extends ConsumerStatefulWidget {
  const DriverTripsScreen({super.key});

  @override
  ConsumerState<DriverTripsScreen> createState() => _DriverTripsScreenState();
}

class _DriverTripsScreenState extends ConsumerState<DriverTripsScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(transportRepositoryProvider).driverTrips();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("Today's trips")),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = ref.read(transportRepositoryProvider).driverTrips()),
        child: FutureBuilder<List<Map<String, dynamic>>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final trips = snap.data!;
            if (trips.isEmpty) return ListView(children: const [ListTile(title: Text('No trips today.'))]);
            return ListView(padding: const EdgeInsets.all(8), children: [
              for (final t in trips)
                Card(
                  child: ListTile(
                    leading: Icon(t['direction'] == 'pickup' ? Icons.wb_sunny_outlined : Icons.nightlight_outlined),
                    title: Text('${t['route_code']} · ${t['direction']} · ${t['status']}'),
                    subtitle: Text('${t['vehicle_registration']} · ${t['stops_done']}/${t['stops_total']} stops · boarded ${t['boarded']}/${t['manifest']}'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () async {
                      await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => DriverTripScreen(trip: t)));
                      setState(() => _f = ref.read(transportRepositoryProvider).driverTrips());
                    },
                  ),
                ),
            ]);
          },
        ),
      ),
    );
  }
}

class DriverTripScreen extends ConsumerStatefulWidget {
  const DriverTripScreen({super.key, required this.trip});

  final Map<String, dynamic> trip;

  @override
  ConsumerState<DriverTripScreen> createState() => _DriverTripScreenState();
}

class _DriverTripScreenState extends ConsumerState<DriverTripScreen> {
  late String _status = '${widget.trip['status']}';
  late Future<Map<String, dynamic>> _m = _repo.manifest(_id);
  StreamSubscription<Position>? _gps;
  Timer? _flushTimer;
  int _sent = 0;

  TransportRepository get _repo => ref.read(transportRepositoryProvider);
  String get _id => '${widget.trip['id']}';

  @override
  void initState() {
    super.initState();
    if (_status == 'in_progress') _startGps();
  }

  @override
  void dispose() {
    _gps?.cancel();
    _flushTimer?.cancel();
    super.dispose();
  }

  Future<void> _startGps() async {
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
    if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) {
      if (mounted) _snack(context, 'Location permission is needed for live tracking');
      return;
    }
    _gps = Geolocator.getPositionStream(locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, distanceFilter: 25))
        .listen((p) => _repo.buffer(p));
    _flushTimer = Timer.periodic(const Duration(seconds: 15), (_) async {
      try {
        final n = await _repo.flush(_id);
        if (mounted && n > 0) setState(() => _sent += n);
      } catch (_) {
        // offline: the buffer keeps the pings for the next flush
      }
    });
  }

  void _stopGps() {
    _gps?.cancel();
    _flushTimer?.cancel();
    _gps = null;
  }

  Future<void> _run(Future<void> Function() fn, String ok) async {
    try {
      await fn();
      if (mounted) _snack(context, ok);
      setState(() => _m = _repo.manifest(_id));
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  Future<void> _scan() async {
    final code = await Navigator.of(context).push<String>(MaterialPageRoute(
      builder: (ctx) => Scaffold(
        appBar: AppBar(title: const Text('Scan ID card')),
        body: MobileScanner(onDetect: (c) {
          final v = c.barcodes.isEmpty ? null : c.barcodes.first.rawValue;
          if (v != null) Navigator.of(ctx).pop(v);
        }),
      ),
    ));
    if (code == null) return;
    try {
      final r = await _repo.scan(_id, code, widget.trip['direction'] == 'pickup' ? 'board' : 'alight');
      if (mounted) _snack(context, '${r['person_name'] ?? 'Passenger'} ${r['event']}${r['warning'] != null ? ' — ${r['warning']}' : ''}');
      setState(() => _m = _repo.manifest(_id));
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = widget.trip;
    return Scaffold(
      appBar: AppBar(title: Text('${t['route_code']} ${t['direction']}'), actions: [
        if (_gps != null) Padding(padding: const EdgeInsets.all(12), child: Chip(label: Text('GPS · $_sent sent'))),
      ]),
      floatingActionButton: _status == 'in_progress'
          ? FloatingActionButton.extended(onPressed: _scan, icon: const Icon(Icons.qr_code_scanner), label: const Text('Scan'))
          : null,
      body: FutureBuilder<Map<String, dynamic>>(
        future: _m,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          final stops = ((snap.data!['stops'] as List?) ?? const []).cast<Map<String, dynamic>>();
          return ListView(padding: const EdgeInsets.all(8), children: [
            Row(children: [
              if (_status == 'scheduled')
                Expanded(
                  child: FilledButton.icon(
                    icon: const Icon(Icons.play_arrow),
                    label: const Text('Start trip'),
                    onPressed: () async {
                      final odo = await _askOdometer(context, 'Start trip');
                      if (odo == -1) return;
                      await _run(() => _repo.start(_id, odo), 'Trip started');
                      setState(() => _status = 'in_progress');
                      await _startGps();
                    },
                  ),
                ),
              if (_status == 'in_progress')
                Expanded(
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(backgroundColor: Colors.red),
                    icon: const Icon(Icons.stop),
                    label: const Text('End trip'),
                    onPressed: () async {
                      final odo = await _askOdometer(context, 'End trip');
                      if (odo == -1) return;
                      try {
                        await _repo.flush(_id);
                      } catch (_) {}
                      _stopGps();
                      Map<String, dynamic> r = const {};
                      await _run(() async => r = await _repo.end(_id, odo), 'Trip ended');
                      if (!context.mounted) return;
                      if (r['km'] != null) _snack(context, '${r['km']} km');
                      setState(() => _status = 'completed');
                    },
                  ),
                ),
            ]),
            Padding(padding: const EdgeInsets.all(8), child: Text('Boarded ${snap.data!['boarded']} of ${snap.data!['total']}')),
            for (final s in stops)
              Card(
                child: ExpansionTile(
                  title: Text('${s['sequence']}. ${s['stop']}'),
                  subtitle: Text(s['arrived_at'] == null ? 'not reached' : 'arrived ${DateTime.parse('${s['arrived_at']}').toLocal().toString().substring(11, 16)}'),
                  trailing: _status != 'in_progress'
                      ? null
                      : (s['arrived_at'] == null
                          ? TextButton(onPressed: () => _run(() => _repo.stopEvent(_id, '${s['stop_id']}', 'arrived'), 'Arrived'), child: const Text('Arrived'))
                          : (s['departed_at'] == null
                              ? TextButton(onPressed: () => _run(() => _repo.stopEvent(_id, '${s['stop_id']}', 'departed'), 'Departed'), child: const Text('Depart'))
                              : const Icon(Icons.check))),
                  children: [
                    for (final p in ((s['passengers'] as List?) ?? const []).cast<Map<String, dynamic>>())
                      ListTile(
                        dense: true,
                        leading: Icon(p['boarded'] == true ? Icons.check_circle : Icons.radio_button_unchecked, color: p['suspended'] == true ? Colors.red : null),
                        title: Text('${p['name']}'),
                        subtitle: Text('${p['phone'] ?? ''}${p['suspended'] == true ? ' · fee suspended' : ''}'),
                      ),
                  ],
                ),
              ),
          ]);
        },
      ),
    );
  }
}

// ---- passenger -----------------------------------------------------------------------------------------------------------------
class _PassengerCard extends ConsumerWidget {
  const _PassengerCard({required this.v, this.title});

  final Map<String, dynamic> v;
  final String? title;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final alloc = v['allocation'] as Map?;
    if (alloc == null) return const Card(child: ListTile(title: Text('No transport allocation')));
    final route = (v['route'] as Map).cast<String, dynamic>();
    final stop = (v['stop'] as Map?)?.cast<String, dynamic>();
    return Card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        ListTile(
          leading: const Icon(Icons.directions_bus_outlined),
          title: Text(title ?? '${route['code']} — ${route['name']}'),
          subtitle: Text('Stop ${stop?['name'] ?? '—'} · pickup ${_hm(v['pickup_time'])} · drop ${_hm(v['drop_time'])}\n'
              '${v['vehicle'] ?? ''} · driver ${v['driver_name'] ?? '—'} · fee ${_rupees(alloc['fee_paise'])} (${alloc['fee_status'] ?? 'no invoice'})'),
          isThreeLine: true,
        ),
        if (v['live_available'] == true)
          FutureBuilder<List<Map<String, dynamic>>>(
            future: ref.read(transportRepositoryProvider).live(routeId: '${route['id']}'),
            builder: (context, snap) {
              final live = snap.data ?? const [];
              if (live.isEmpty) return const ListTile(title: Text('Waiting for the bus position…'));
              final b = live.first;
              return ListTile(
                leading: const Icon(Icons.gps_fixed, color: Colors.green),
                title: Text('Bus live · ${b['speed'] ?? 0} km/h'),
                subtitle: Text(b['eta_min'] != null ? 'Next ${b['next_stop']} in ${b['eta_min']} min' : 'Updated ${b['at']}'),
              );
            },
          )
        else
          const Padding(padding: EdgeInsets.fromLTRB(16, 0, 16, 12), child: Text('Live tracking appears while your bus is on a trip.')),
      ]),
    );
  }
}

class MyTransportScreen extends ConsumerStatefulWidget {
  const MyTransportScreen({super.key});

  @override
  ConsumerState<MyTransportScreen> createState() => _MyTransportScreenState();
}

class _MyTransportScreenState extends ConsumerState<MyTransportScreen> {
  late Future<Map<String, dynamic>> _f = ref.read(transportRepositoryProvider).me();
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 20), (_) => setState(() => _f = ref.read(transportRepositoryProvider).me()));
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  Future<void> _request() async {
    final routes = await ref.read(transportRepositoryProvider).publicRoutes();
    if (!mounted) return;
    Map<String, dynamic>? route;
    String? stopId;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('Request a route'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButton<Map<String, dynamic>>(
              isExpanded: true,
              value: route,
              hint: const Text('Route'),
              items: [for (final r in routes) DropdownMenuItem(value: r, child: Text('${r['code']} — ${r['name']}'))],
              onChanged: (v) => set(() {
                route = v;
                stopId = null;
              }),
            ),
            if (route != null)
              DropdownButton<String>(
                isExpanded: true,
                value: stopId,
                hint: const Text('Stop'),
                items: [
                  for (final s in ((route!['stops'] as List?) ?? const []).cast<Map<String, dynamic>>())
                    DropdownMenuItem(value: '${s['id']}', child: Text('${s['name']} · ${_hm(s['pickup_time'])} · ${_rupees(s['fee_paise'])}')),
                ],
                onChanged: (v) => set(() => stopId = v),
              ),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Request'))],
        ),
      ),
    );
    if (ok != true || route == null || stopId == null) return;
    try {
      await ref.read(transportRepositoryProvider).request('${route!['id']}', stopId!);
      if (mounted) _snack(context, 'Requested — the transport office will confirm');
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Transport')),
      floatingActionButton: FloatingActionButton.extended(onPressed: _request, icon: const Icon(Icons.swap_horiz), label: const Text('Request')),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = ref.read(transportRepositoryProvider).me()),
        child: FutureBuilder<Map<String, dynamic>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final v = snap.data!;
            return ListView(padding: const EdgeInsets.all(8), children: [
              _PassengerCard(v: v),
              for (final t in ((v['today_trips'] as List?) ?? const []).cast<Map<String, dynamic>>())
                ListTile(leading: const Icon(Icons.schedule), title: Text('${t['direction']} · ${t['status']}')),
            ]);
          },
        ),
      ),
    );
  }
}

class WardTransportScreen extends ConsumerStatefulWidget {
  const WardTransportScreen({super.key});

  @override
  ConsumerState<WardTransportScreen> createState() => _WardTransportScreenState();
}

class _WardTransportScreenState extends ConsumerState<WardTransportScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(transportRepositoryProvider).wards();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ward transport')),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = ref.read(transportRepositoryProvider).wards()),
        child: FutureBuilder<List<Map<String, dynamic>>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            if (snap.data!.isEmpty) return ListView(children: const [ListTile(title: Text('No ward uses college transport.'))]);
            return ListView(padding: const EdgeInsets.all(8), children: [
              for (final v in snap.data!) _PassengerCard(v: v, title: '${(v['allocation'] as Map)['person_name']} — ${(v['route'] as Map)['code']}'),
              const ListTile(leading: Icon(Icons.notifications_active_outlined), title: Text('Boarding, alighting and bus-approaching alerts arrive as notifications.')),
            ]);
          },
        ),
      ),
    );
  }
}

// ---- transport manager ------------------------------------------------------------------------------------------------------------
class FleetStatusScreen extends ConsumerStatefulWidget {
  const FleetStatusScreen({super.key});

  @override
  ConsumerState<FleetStatusScreen> createState() => _FleetStatusScreenState();
}

class _FleetStatusScreenState extends ConsumerState<FleetStatusScreen> {
  late Future<List<dynamic>> _f = _load();

  Future<List<dynamic>> _load() {
    final r = ref.read(transportRepositoryProvider);
    return Future.wait<dynamic>([r.stats(), r.trips(), r.live(), r.compliance()]);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Fleet')),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _f = _load()),
        child: FutureBuilder<List<dynamic>>(
          future: _f,
          builder: (context, snap) {
            if (snap.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)))]);
            if (!snap.hasData) return const Center(child: CircularProgressIndicator());
            final s = snap.data![0] as Map<String, dynamic>;
            final trips = (snap.data![1] as List).cast<Map<String, dynamic>>();
            final live = (snap.data![2] as List).cast<Map<String, dynamic>>();
            final comp = (snap.data![3] as List).cast<Map<String, dynamic>>();
            return ListView(padding: const EdgeInsets.all(8), children: [
              Wrap(spacing: 8, runSpacing: 8, children: [
                Chip(label: Text('${s['vehicles_active']}/${s['vehicles']} vehicles active')),
                Chip(label: Text('${s['trips_today']} trips · ${s['in_progress']} running')),
                Chip(label: Text('${s['delayed']} delayed'), backgroundColor: ((s['delayed'] ?? 0) as num) > 0 ? Colors.orange.shade100 : null),
                Chip(label: Text('occupancy ${s['occupancy_pct']}%')),
                Chip(label: Text('on time ${s['on_time_pct'] ?? '—'}%')),
                Chip(label: Text('${s['compliance_alerts']} compliance alerts')),
              ]),
              const Padding(padding: EdgeInsets.all(8), child: Text('Live', style: TextStyle(fontWeight: FontWeight.w600))),
              if (live.isEmpty) const ListTile(title: Text('No vehicle reporting.')),
              for (final v in live)
                ListTile(
                  leading: Icon(Icons.directions_bus, color: v['deviation'] == true ? Colors.red : Colors.green),
                  title: Text('${v['registration_no']} · ${v['route'] ?? ''}'),
                  subtitle: Text('${v['speed'] ?? 0} km/h${v['eta_min'] != null ? ' · ${v['next_stop']} in ${v['eta_min']} min' : ''}'),
                ),
              const Padding(padding: EdgeInsets.all(8), child: Text('Trips today', style: TextStyle(fontWeight: FontWeight.w600))),
              for (final t in trips)
                ListTile(
                  dense: true,
                  title: Text('${t['route_code']} ${t['direction']} · ${t['status']}'),
                  subtitle: Text('${t['stops_done']}/${t['stops_total']} stops${t['delay_minutes'] != null ? ' · delay ${t['delay_minutes']} min' : ''}'),
                ),
              if (comp.isNotEmpty) const Padding(padding: EdgeInsets.all(8), child: Text('Compliance', style: TextStyle(fontWeight: FontWeight.w600))),
              for (final c in comp)
                ListTile(dense: true, leading: const Icon(Icons.warning_amber, color: Colors.orange), title: Text('${c['registration_no']} · ${c['document']}'), subtitle: Text('${c['state']} ${c['expiry'] ?? ''}')),
            ]);
          },
        ),
      ),
    );
  }
}
