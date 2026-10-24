import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../core/offline/cache_repository.dart';
import '../../core/providers.dart';

/// Phase 22 mobile (Prompts/22 §22.10): store keeper **Stock** (lookup by barcode / item code, issue with scan) and
/// **Receive goods** (GRN checklist against an open PO); faculty / staff **Indents** (create / track) and **My assets**
/// (accept custody); asset auditor **Audit scanner** (QR labels with an offline queue flushed as one batch, condition
/// picker). Indent / PO / bill approvals use the generic Approvals inbox. Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class InventoryRepository {
  InventoryRepository(this._dio, this._cache);

  final Dio _dio;
  final CacheRepository _cache;
  static const _auditQueue = 'inventory.audit_queue';

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) async =>
      (await _dio.get<Map<String, dynamic>>(path, queryParameters: q)).data?['data'];
  Future<dynamic> _post(String path, [Object? body]) async => (await _dio.post<Map<String, dynamic>>(path,
          data: body ?? {}, options: Options(headers: {'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()})))
      .data?['data'];
  List<Map<String, dynamic>> _list(dynamic v) => ((v as List?) ?? const []).cast<Map<String, dynamic>>();

  Future<List<Map<String, dynamic>>> stores() async => _list(await _get('/inventory/stores'));
  Future<List<Map<String, dynamic>>> stock(String storeId) async => _list(await _get('/inventory/stores/$storeId/stock'));
  Future<List<Map<String, dynamic>>> items(String q) async => _list(await _get('/inventory/items', {'q': q}));
  Future<void> issue(String storeId, String itemId, num qty, String toType, {bool safetyAck = false}) => _post('/inventory/stock/issue', {
        'store_id': storeId,
        'issued_to_type': toType,
        'safety_ack': safetyAck,
        'items': [
          {'item_id': itemId, 'quantity': qty}
        ],
      });
  Future<List<Map<String, dynamic>>> openPos() async => [
        ..._list(await _get('/inventory/purchase-orders', {'status': 'sent'})),
        ..._list(await _get('/inventory/purchase-orders', {'status': 'partially_received'})),
      ];
  Future<void> receive(Map<String, dynamic> body) => _post('/inventory/goods-receipts', body);
  Future<List<Map<String, dynamic>>> myIndents() async => _list(await _get('/inventory/indents/me'));
  Future<void> createIndent(String purpose, String itemId, num qty) async {
    final r = (await _post('/inventory/indents', {
      'purpose': purpose,
      'items': [
        {'item_id': itemId, 'qty': qty}
      ],
    })) as Map;
    await _post('/inventory/indents/${r['id']}/submit');
  }

  Future<List<Map<String, dynamic>>> myAssets() async => _list(await _get('/inventory/assets/me'));
  Future<void> acceptCustody(String id) => _post('/inventory/assets/$id/accept-custody');
  Future<List<Map<String, dynamic>>> audits() async => _list(await _get('/inventory/asset-audits'));

  Future<List<Map<String, dynamic>>> queued() async {
    final hit = await _cache.read(_auditQueue);
    return hit == null ? [] : (jsonDecode(hit.json) as List).cast<Map<String, dynamic>>();
  }

  Future<void> enqueue(String auditId, String code, String condition) async {
    final q = await queued()
      ..add({'audit_id': auditId, if (code.length == 48) 'qr': code else 'asset_tag': code, 'condition': condition});
    await _cache.write(_auditQueue, jsonEncode(q), ttl: const Duration(days: 7));
  }

  Future<int> flush() async {
    final q = await queued();
    if (q.isEmpty) return 0;
    final byAudit = <String, List<Map<String, dynamic>>>{};
    for (final s in q) {
      byAudit.putIfAbsent('${s['audit_id']}', () => []).add({...s}..remove('audit_id'));
    }
    for (final e in byAudit.entries) {
      await _post('/inventory/asset-audits/${e.key}/scan', {'scans': e.value});
    }
    await _cache.write(_auditQueue, jsonEncode([]), ttl: const Duration(days: 7));
    return q.length;
  }
}

final inventoryRepositoryProvider = Provider<InventoryRepository>((ref) => InventoryRepository(ref.watch(dioProvider), CacheRepository()));

void _snack(BuildContext context, String m) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

Future<String?> _scan(BuildContext context, String title) => Navigator.of(context).push<String>(MaterialPageRoute(
      builder: (ctx) => Scaffold(
        appBar: AppBar(title: Text(title)),
        body: MobileScanner(onDetect: (c) {
          final v = c.barcodes.isEmpty ? null : c.barcodes.first.rawValue;
          if (v != null) Navigator.of(ctx).pop(v);
        }),
      ),
    ));

// ---- store keeper: stock ----------------------------------------------------------------------------------------------------------
class StockLookupScreen extends ConsumerStatefulWidget {
  const StockLookupScreen({super.key});

  @override
  ConsumerState<StockLookupScreen> createState() => _StockLookupScreenState();
}

class _StockLookupScreenState extends ConsumerState<StockLookupScreen> {
  String? _store;
  String _filter = '';
  int _tick = 0;

  Future<void> _issue(Map<String, dynamic> row) async {
    final qty = TextEditingController(text: '1');
    var to = 'department';
    var ack = false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: Text('Issue ${row['item_name']}'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: qty, keyboardType: TextInputType.number, decoration: InputDecoration(labelText: 'Quantity (${row['quantity']} ${row['unit']} on hand)')),
            DropdownButton<String>(
              value: to,
              items: const [
                DropdownMenuItem(value: 'department', child: Text('Department')),
                DropdownMenuItem(value: 'lab', child: Text('Lab')),
                DropdownMenuItem(value: 'staff', child: Text('Staff')),
                DropdownMenuItem(value: 'event', child: Text('Event')),
              ],
              onChanged: (v) => set(() => to = v ?? 'department'),
            ),
            if (row['is_hazardous'] == true)
              CheckboxListTile(value: ack, onChanged: (v) => set(() => ack = v ?? false), title: const Text('Receiver acknowledged the safety data')),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Issue'))],
        ),
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(inventoryRepositoryProvider).issue(_store!, '${row['item_id']}', num.tryParse(qty.text) ?? 1, to, safetyAck: ack);
      if (mounted) _snack(context, 'Issued');
      setState(() => _tick++);
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(inventoryRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Stock'), actions: [
        IconButton(
          icon: const Icon(Icons.qr_code_scanner),
          onPressed: () async {
            final code = await _scan(context, 'Scan item barcode');
            if (code != null) setState(() => _filter = code);
          },
        ),
      ]),
      body: Column(children: [
        FutureBuilder<List<Map<String, dynamic>>>(
          future: repo.stores(),
          builder: (context, snap) => Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: DropdownButton<String>(
              isExpanded: true,
              value: _store,
              hint: const Text('Store'),
              items: [for (final s in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${s['id']}', child: Text('${s['name']}'))],
              onChanged: (v) => setState(() => _store = v),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: TextField(decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Item code or name'), controller: TextEditingController(text: _filter), onSubmitted: (v) => setState(() => _filter = v)),
        ),
        if (_store != null)
          Expanded(
            child: FutureBuilder<List<Map<String, dynamic>>>(
              key: ValueKey('$_store$_tick'),
              future: repo.stock(_store!),
              builder: (context, snap) {
                if (snap.hasError) return Text(_error(snap.error!));
                if (!snap.hasData) return const Center(child: CircularProgressIndicator());
                final f = _filter.toLowerCase();
                final rows = snap.data!.where((r) => f.isEmpty || '${r['item_code']} ${r['item_name']}'.toLowerCase().contains(f)).toList();
                return ListView(children: [
                  for (final r in rows)
                    ListTile(
                      title: Text('${r['item_code']} · ${r['item_name']}'),
                      subtitle: Text('${r['quantity']} ${r['unit']}${r['below_min'] == true ? ' · below min' : ''}${r['is_hazardous'] == true ? ' · hazardous' : ''}'),
                      trailing: TextButton(onPressed: () => _issue(r), child: const Text('Issue')),
                    ),
                ]);
              },
            ),
          ),
      ]),
    );
  }
}

// ---- store keeper: receive goods --------------------------------------------------------------------------------------------------
class GrnReceiveScreen extends ConsumerStatefulWidget {
  const GrnReceiveScreen({super.key});

  @override
  ConsumerState<GrnReceiveScreen> createState() => _GrnReceiveScreenState();
}

class _GrnReceiveScreenState extends ConsumerState<GrnReceiveScreen> {
  Map<String, dynamic>? _po;
  String? _store;
  final _qty = <String, TextEditingController>{};

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(inventoryRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Receive goods')),
      body: ListView(padding: const EdgeInsets.all(8), children: [
        FutureBuilder<List<Map<String, dynamic>>>(
          future: repo.openPos(),
          builder: (context, snap) => DropdownButton<String>(
            isExpanded: true,
            value: _po?['id'] as String?,
            hint: const Text('Purchase order'),
            items: [for (final p in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${p['id']}', child: Text('${p['po_number']} · ${p['supplier_name']}'))],
            onChanged: (v) => setState(() => _po = (snap.data ?? const <Map<String, dynamic>>[]).firstWhere((p) => p['id'] == v)),
          ),
        ),
        FutureBuilder<List<Map<String, dynamic>>>(
          future: repo.stores(),
          builder: (context, snap) => DropdownButton<String>(
            isExpanded: true,
            value: _store,
            hint: const Text('Receiving store'),
            items: [for (final s in snap.data ?? const <Map<String, dynamic>>[]) DropdownMenuItem(value: '${s['id']}', child: Text('${s['name']}'))],
            onChanged: (v) => setState(() => _store = v),
          ),
        ),
        if (_po != null)
          for (final x in ((_po!['items'] as List?) ?? const []).cast<Map<String, dynamic>>())
            ListTile(
              title: Text('${x['item_name']}'),
              subtitle: Text('received ${x['received_qty']} of ${x['quantity']}'),
              trailing: SizedBox(width: 80, child: TextField(controller: _qty.putIfAbsent('${x['id']}', () => TextEditingController()), keyboardType: TextInputType.number, decoration: const InputDecoration(hintText: 'Qty'))),
            ),
        if (_po != null && _store != null)
          FilledButton(
            onPressed: () async {
              final lines = [
                for (final e in _qty.entries)
                  if ((num.tryParse(e.value.text) ?? 0) > 0) {'po_item_id': e.key, 'qty_received': num.parse(e.value.text), 'qty_rejected': 0}
              ];
              if (lines.isEmpty) return;
              try {
                await repo.receive({'po_id': _po!['id'], 'store_id': _store, 'received_on': DateTime.now().toIso8601String().substring(0, 10), 'items': lines});
                if (context.mounted) _snack(context, 'Received');
                setState(() {
                  _po = null;
                  _qty.clear();
                });
              } catch (e) {
                if (context.mounted) _snack(context, _error(e));
              }
            },
            child: const Text('Record receipt'),
          ),
      ]),
    );
  }
}

// ---- staff: indents & assets ------------------------------------------------------------------------------------------------------
class MyIndentsScreen extends ConsumerStatefulWidget {
  const MyIndentsScreen({super.key});

  @override
  ConsumerState<MyIndentsScreen> createState() => _MyIndentsScreenState();
}

class _MyIndentsScreenState extends ConsumerState<MyIndentsScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(inventoryRepositoryProvider).myIndents();

  Future<void> _new() async {
    final repo = ref.read(inventoryRepositoryProvider);
    final purpose = TextEditingController();
    final search = TextEditingController();
    final qty = TextEditingController(text: '1');
    List<Map<String, dynamic>> found = [];
    Map<String, dynamic>? item;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('New indent'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: purpose, decoration: const InputDecoration(labelText: 'Purpose')),
            TextField(
              controller: search,
              decoration: const InputDecoration(labelText: 'Find item'),
              onSubmitted: (v) async {
                final r = await repo.items(v);
                set(() => found = r.take(8).toList());
              },
            ),
            for (final i in found) ListTile(dense: true, selected: item?['id'] == i['id'], leading: Icon(item?['id'] == i['id'] ? Icons.check_circle : Icons.circle_outlined), title: Text('${i['name']}'), onTap: () => set(() => item = i)),
            TextField(controller: qty, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Quantity')),
          ]),
          actions: [TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Submit'))],
        ),
      ),
    );
    if (ok != true || item == null || purpose.text.length < 3) return;
    try {
      await repo.createIndent(purpose.text, '${item!['id']}', num.tryParse(qty.text) ?? 1);
      if (mounted) _snack(context, 'Submitted for approval');
      setState(() => _f = repo.myIndents());
    } catch (e) {
      if (mounted) _snack(context, _error(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('My indents')),
      floatingActionButton: FloatingActionButton.extended(onPressed: _new, icon: const Icon(Icons.add), label: const Text('Indent')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _f,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          return ListView(children: [
            for (final r in snap.data!)
              ListTile(
                title: Text('${r['indent_number']} · ${r['status']}'),
                subtitle: Text('${r['purpose']}\n${r['workflow_step'] ?? ''} · ${r['fulfilment_pct']}% done'),
                isThreeLine: true,
              ),
          ]);
        },
      ),
    );
  }
}

class MyAssetsScreen extends ConsumerStatefulWidget {
  const MyAssetsScreen({super.key});

  @override
  ConsumerState<MyAssetsScreen> createState() => _MyAssetsScreenState();
}

class _MyAssetsScreenState extends ConsumerState<MyAssetsScreen> {
  late Future<List<Map<String, dynamic>>> _f = ref.read(inventoryRepositoryProvider).myAssets();

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(inventoryRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('My assets')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _f,
        builder: (context, snap) {
          if (snap.hasError) return Padding(padding: const EdgeInsets.all(16), child: Text(_error(snap.error!)));
          if (!snap.hasData) return const Center(child: CircularProgressIndicator());
          if (snap.data!.isEmpty) return const ListTile(title: Text('No assets in your custody.'));
          return ListView(children: [
            for (final a in snap.data!)
              ListTile(
                leading: const Icon(Icons.inventory_2_outlined),
                title: Text('${a['asset_tag']} · ${a['name']}'),
                subtitle: Text('${a['location'] ?? ''} · ${a['status']}'),
                trailing: TextButton(
                  child: const Text('Accept'),
                  onPressed: () async {
                    try {
                      await repo.acceptCustody('${a['id']}');
                      if (context.mounted) _snack(context, 'Custody accepted');
                      setState(() => _f = repo.myAssets());
                    } catch (e) {
                      if (context.mounted) _snack(context, _error(e));
                    }
                  },
                ),
              ),
          ]);
        },
      ),
    );
  }
}

// ---- auditor: scanner with offline queue ---------------------------------------------------------------------------------------------
class AssetAuditScanScreen extends ConsumerStatefulWidget {
  const AssetAuditScanScreen({super.key});

  @override
  ConsumerState<AssetAuditScanScreen> createState() => _AssetAuditScanScreenState();
}

class _AssetAuditScanScreenState extends ConsumerState<AssetAuditScanScreen> {
  String? _audit;
  String _condition = 'good';
  int _queued = 0;

  Future<void> _refreshQueue() async {
    final q = await ref.read(inventoryRepositoryProvider).queued();
    if (mounted) setState(() => _queued = q.length);
  }

  @override
  void initState() {
    super.initState();
    _refreshQueue();
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(inventoryRepositoryProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Asset audit'), actions: [
        TextButton(
          onPressed: () async {
            try {
              final n = await repo.flush();
              if (context.mounted) _snack(context, '$n scan(s) sent');
            } catch (e) {
              if (context.mounted) _snack(context, 'Offline — kept for later (${_error(e)})');
            }
            await _refreshQueue();
          },
          child: Text('Send $_queued'),
        ),
      ]),
      body: ListView(padding: const EdgeInsets.all(8), children: [
        FutureBuilder<List<Map<String, dynamic>>>(
          future: repo.audits(),
          builder: (context, snap) => DropdownButton<String>(
            isExpanded: true,
            value: _audit,
            hint: const Text('Open audit cycle'),
            items: [
              for (final a in (snap.data ?? const <Map<String, dynamic>>[]).where((a) => a['status'] == 'open'))
                DropdownMenuItem(value: '${a['id']}', child: Text('${a['name']} · ${a['scanned']}/${a['expected']}')),
            ],
            onChanged: (v) => setState(() => _audit = v),
          ),
        ),
        Wrap(spacing: 6, children: [
          for (final c in const ['good', 'fair', 'poor', 'damaged']) ChoiceChip(label: Text(c), selected: _condition == c, onSelected: (_) => setState(() => _condition = c)),
        ]),
        const SizedBox(height: 12),
        FilledButton.icon(
          icon: const Icon(Icons.qr_code_scanner),
          label: const Text('Scan label'),
          onPressed: _audit == null
              ? null
              : () async {
                  final code = await _scan(context, 'Scan asset label');
                  if (code == null) return;
                  final token = code.contains('/') ? code.split('/').last : code;
                  await repo.enqueue(_audit!, token, _condition);
                  await _refreshQueue();
                  if (context.mounted) _snack(context, 'Queued ($_queued)');
                },
        ),
      ]),
    );
  }
}
