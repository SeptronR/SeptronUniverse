import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/providers.dart';

/// Phase 36 mobile (Prompts/36 §36.10). Registrar / HOD / COE / accountant / placement / IQAC shells: **Reports** —
/// the catalogue for the role (favourites first) → parameter sheet generated from `params_schema` → run as a job →
/// progress tile → open / share the PDF / xlsx; runs list. No builder / statutory / schedules on mobile (web-first).
/// Scope narrowing, PII masking and permissions are the API's.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class ReportsRepository {
  ReportsRepository(this._dio);

  final Dio _dio;

  Future<List<Map<String, dynamic>>> catalogue() async {
    final r = await _dio.get<Map<String, dynamic>>('/reports/catalogue');
    return ((r.data?['data'] as List?) ?? const []).cast<Map<dynamic, dynamic>>().map((e) => e.cast<String, dynamic>()).toList();
  }

  Future<List<Map<String, dynamic>>> runs() async {
    final r = await _dio.get<Map<String, dynamic>>('/reports/runs', queryParameters: {'scope': 'mine', 'size': 50});
    final data = r.data?['data'];
    final items = data is Map ? data['items'] : data;
    return ((items as List?) ?? const []).cast<Map<dynamic, dynamic>>().map((e) => e.cast<String, dynamic>()).toList();
  }

  Future<Map<String, dynamic>> run(String key, Map<String, dynamic> params, String format) async {
    final r = await _dio.post<Map<String, dynamic>>('/reports/run', data: {'key': key, 'params': params, 'format': format});
    return ((r.data?['data'] as Map?) ?? const {}).cast<String, dynamic>();
  }

  Future<Map<String, dynamic>> runOne(String id) async {
    final r = await _dio.get<Map<String, dynamic>>('/reports/runs/$id');
    return ((r.data?['data'] as Map?) ?? const {}).cast<String, dynamic>();
  }

  Future<String?> downloadUrl(String id) async {
    final r = await _dio.get<Map<String, dynamic>>('/reports/runs/$id/download', queryParameters: {'redirect': false});
    return (r.data?['data'] as Map?)?['url'] as String?;
  }

  Future<void> toggleFavourite(String key) => _dio.post<void>('/reports/favourites/toggle', data: {'key': key});
}

final reportsRepositoryProvider = Provider<ReportsRepository>((ref) => ReportsRepository(ref.watch(dioProvider)));

class ReportsScreen extends ConsumerStatefulWidget {
  const ReportsScreen({super.key});

  @override
  ConsumerState<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends ConsumerState<ReportsScreen> {
  late Future<List<Map<String, dynamic>>> _catalogue;
  late Future<List<Map<String, dynamic>>> _runs;
  final _active = <String, Map<String, dynamic>>{};
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  void _reload() {
    final repo = ref.read(reportsRepositoryProvider);
    _catalogue = repo.catalogue();
    _runs = repo.runs();
  }

  void _watch(String jobId) {
    _poll ??= Timer.periodic(const Duration(seconds: 3), (_) async {
      final repo = ref.read(reportsRepositoryProvider);
      for (final id in _active.keys.toList()) {
        try {
          final r = await repo.runOne(id);
          if (!mounted) return;
          setState(() => _active[id] = r);
          if (['succeeded', 'failed', 'cancelled'].contains(r['status'])) {
            _active.remove(id);
            setState(_reload);
          }
        } catch (_) {}
      }
      if (_active.isEmpty) {
        _poll?.cancel();
        _poll = null;
      }
    });
    _active[jobId] = {'job_id': jobId, 'status': 'queued'};
  }

  Future<void> _open(Map<String, dynamic> run, {bool share = false}) async {
    try {
      final url = await ref.read(reportsRepositoryProvider).downloadUrl('${run['job_id']}');
      if (url == null) return;
      if (share) {
        await Share.share(url, subject: '${run['key']}');
      } else {
        await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
      }
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  Future<void> _paramsSheet(Map<String, dynamic> report) async {
    final schema = ((report['params_schema'] as Map?) ?? const {}).cast<String, dynamic>();
    final props = ((schema['properties'] as Map?) ?? const {}).cast<String, dynamic>()
      ..removeWhere((_, v) => v is Map && v['x-dev'] == true);
    final required = ((schema['required'] as List?) ?? const []).cast<String>();
    final ctrls = {for (final k in props.keys) k: TextEditingController()};
    final formats = ((report['formats'] as List?) ?? const ['xlsx']).cast<String>();
    var format = formats.contains('pdf') ? 'pdf' : formats.first;
    final go = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => Padding(
          padding: EdgeInsets.fromLTRB(16, 16, 16, MediaQuery.of(ctx).viewInsets.bottom + 16),
          child: SingleChildScrollView(
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
              Text('${report['name']}', style: Theme.of(ctx).textTheme.titleMedium),
              const SizedBox(height: 8),
              for (final e in props.entries)
                if ((e.value as Map)['type'] != 'boolean')
                  TextField(
                    controller: ctrls[e.key],
                    decoration: InputDecoration(
                      labelText: '${(e.value as Map)['title'] ?? e.key}${required.contains(e.key) ? ' *' : ''}',
                      helperText: (e.value as Map)['format'] == 'date' ? 'yyyy-mm-dd' : ((e.value as Map)['x-picker'] as String?),
                    ),
                  ),
              const SizedBox(height: 8),
              SegmentedButton<String>(
                segments: [for (final f in formats.where((f) => f != 'json')) ButtonSegment(value: f, label: Text(f))],
                selected: {format},
                onSelectionChanged: (s) => setLocal(() => format = s.first),
              ),
              const SizedBox(height: 12),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Run as job')),
            ]),
          ),
        ),
      ),
    );
    if (go != true) return;
    final params = <String, dynamic>{
      for (final e in ctrls.entries)
        if (e.value.text.trim().isNotEmpty) e.key: e.value.text.trim(),
    };
    try {
      final r = await ref.read(reportsRepositoryProvider).run('${report['key']}', params, format);
      if (!mounted) return;
      setState(() => _watch('${r['job_id']}'));
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(title: const Text('Reports'), bottom: const TabBar(tabs: [Tab(text: 'Catalogue'), Tab(text: 'Runs')])),
        body: Column(children: [
          for (final j in _active.values)
            ListTile(
              leading: const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2)),
              title: Text('${j['key'] ?? 'Report'} — ${j['status']}'),
              subtitle: const Text('Running as a job…'),
            ),
          Expanded(
            child: TabBarView(children: [
              FutureBuilder<List<Map<String, dynamic>>>(
                future: _catalogue,
                builder: (context, snap) {
                  if (snap.hasError) return Center(child: Text(_error(snap.error!)));
                  if (!snap.hasData) return const Center(child: CircularProgressIndicator());
                  final items = snap.data!..sort((a, b) => (b['favourite'] == true ? 1 : 0) - (a['favourite'] == true ? 1 : 0));
                  return RefreshIndicator(
                    onRefresh: () async => setState(_reload),
                    child: ListView(children: [
                      for (final r in items)
                        ListTile(
                          leading: IconButton(
                            icon: Icon(r['favourite'] == true ? Icons.star : Icons.star_border, color: r['favourite'] == true ? Colors.amber : null),
                            onPressed: () async {
                              await ref.read(reportsRepositoryProvider).toggleFavourite('${r['key']}');
                              setState(_reload);
                            },
                          ),
                          title: Text('${r['name']}'),
                          subtitle: Text('${r['category']} · ${(r['formats'] as List?)?.join(' / ') ?? ''}'),
                          onTap: () => _paramsSheet(r),
                        ),
                    ]),
                  );
                },
              ),
              FutureBuilder<List<Map<String, dynamic>>>(
                future: _runs,
                builder: (context, snap) {
                  if (snap.hasError) return Center(child: Text(_error(snap.error!)));
                  if (!snap.hasData) return const Center(child: CircularProgressIndicator());
                  return RefreshIndicator(
                    onRefresh: () async => setState(_reload),
                    child: ListView(children: [
                      for (final r in snap.data!)
                        ListTile(
                          title: Text('${r['key']}'),
                          subtitle: Text('${r['status']} · ${r['format'] ?? ''} · ${r['rows'] ?? '—'} rows'),
                          trailing: r['status'] == 'succeeded' && r['purged'] != true
                              ? Row(mainAxisSize: MainAxisSize.min, children: [
                                  IconButton(icon: const Icon(Icons.open_in_new), onPressed: () => _open(r)),
                                  IconButton(icon: const Icon(Icons.share), onPressed: () => _open(r, share: true)),
                                ])
                              : null,
                        ),
                    ]),
                  );
                },
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}
