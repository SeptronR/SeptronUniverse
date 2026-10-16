import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers.dart';
import '../../core/router/routes.dart';

/// Phase 09 mobile (Prompts/09 §09.10): student **Registration** (catalog → cart with the same server checks,
/// submit, status, waitlist accept, elective ranking), faculty **My offerings** (roster) and advisor **Registration
/// approvals** (cards with items; approve / reject / request changes). Rules and visibility live in the API.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) {
      return '${(data['error'] as Map)['message']}';
    }
    return e.message ?? 'Request failed';
  }
  return '$e';
}

String _label(Object? s) => s == null
    ? '—'
    : '$s'
        .replaceAll('_', ' ')
        .replaceFirstMapped(RegExp(r'^\w'), (m) => m.group(0)!.toUpperCase());

class RegistrationRepository {
  RegistrationRepository(this._dio);

  final Dio _dio;

  Options get _once => Options(headers: {
        'Idempotency-Key': DateTime.now().microsecondsSinceEpoch.toString()
      });

  Future<Map<String, dynamic>?> _one(String path,
      [Map<String, dynamic>? q]) async {
    final res = await _dio.get<Map<String, dynamic>>(path, queryParameters: q);
    return (res.data?['data'] as Map?)?.cast<String, dynamic>();
  }

  Future<List<Map<String, dynamic>>> _list(String path,
      [Map<String, dynamic>? q]) async {
    final res = await _dio.get<Map<String, dynamic>>(path, queryParameters: q);
    return ((res.data?['data'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
  }

  Future<Map<String, dynamic>?> catalog() => _one('/registration/me/catalog');
  Future<Map<String, dynamic>?> mine() => _one('/registration/me');
  Future<void> add(String offeringId, String type) =>
      _dio.post('/registration/me/items',
          data: {'offering_id': offeringId, 'registration_type': type},
          options: _once);
  Future<void> drop(String itemId) =>
      _dio.delete('/registration/me/items/$itemId');
  Future<void> submit(String key) => _dio.post('/registration/me/submit',
      options: Options(headers: {'Idempotency-Key': key}));
  Future<void> acceptWaitlist(String id) =>
      _dio.post('/registration/me/waitlist/$id/accept', options: _once);
  Future<void> saveChoices(
          String basketId, String termId, List<String> order, bool replace) =>
      replace
          ? _dio.put('/elective-baskets/$basketId/choices/me', data: {
              'term_id': termId,
              'choices': [
                for (var i = 0; i < order.length; i++)
                  {'course_id': order[i], 'priority': i + 1}
              ]
            })
          : _dio.post('/elective-baskets/$basketId/choices/me',
              data: {
                'term_id': termId,
                'choices': [
                  for (var i = 0; i < order.length; i++)
                    {'course_id': order[i], 'priority': i + 1}
                ]
              },
              options: _once);
  Future<List<Map<String, dynamic>>> myOfferings() =>
      _list('/course-offerings/mine');
  Future<List<Map<String, dynamic>>> roster(String id) =>
      _list('/course-offerings/$id/roster');
  Future<List<Map<String, dynamic>>> pending() => _list('/registration',
      {'status': 'advisor_pending', 'scope': 'self', 'page_size': 100});
  Future<Map<String, dynamic>?> registration(String id) =>
      _one('/registration/$id');
  Future<void> decide(String id, String action, String? comment) =>
      _dio.post('/registration/$id/$action',
          data: {
            'decision':
                action == 'request-changes' ? 'request_changes' : action,
            if (comment != null && comment.isNotEmpty) 'comment': comment
          },
          options: _once);
}

final registrationRepositoryProvider = Provider<RegistrationRepository>(
    (ref) => RegistrationRepository(ref.watch(dioProvider)));

void _toast(BuildContext context, String msg) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));

// ---- student cart ---------------------------------------------------------------------------------------------------------
class StudentRegistrationScreen extends ConsumerStatefulWidget {
  const StudentRegistrationScreen({super.key});

  @override
  ConsumerState<StudentRegistrationScreen> createState() => _CartState();
}

class _CartState extends ConsumerState<StudentRegistrationScreen> {
  Map<String, dynamic>? _catalog;
  Map<String, dynamic>? _reg;
  Object? _err;
  String _key = DateTime.now().microsecondsSinceEpoch.toString();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final repo = ref.read(registrationRepositoryProvider);
    try {
      final reg = await repo.mine();
      Map<String, dynamic>? cat;
      Object? err;
      try {
        cat = await repo.catalog();
      } catch (e) {
        err = e;
      }
      if (mounted) {
        setState(() {
          _reg = reg;
          _catalog = cat;
          _err = cat == null && reg == null ? err : null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = e);
    }
  }

  Future<void> _run(Future<void> Function() f, String ok) async {
    try {
      await f();
      if (mounted) _toast(context, ok);
    } catch (e) {
      if (mounted) _toast(context, _error(e));
    }
    await _load();
  }

  List<Map<String, dynamic>> get _items =>
      ((_reg?['items'] as List?) ?? const []).cast<Map<String, dynamic>>();

  Map<String, dynamic>? _itemFor(String offeringId) {
    for (final i in _items) {
      if (i['offering_id'] == offeringId &&
          ['selected', 'confirmed', 'waitlisted'].contains(i['status'])) {
        return i;
      }
    }
    return null;
  }

  Widget _course(Map<String, dynamic> c, [String type = 'regular']) {
    final repo = ref.read(registrationRepositoryProvider);
    final offerings =
        ((c['offerings'] as List?) ?? const []).cast<Map<String, dynamic>>();
    final reqs =
        ((c['requisites'] as List?) ?? const []).cast<Map<String, dynamic>>();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${c['code']} · ${c['credits']} cr',
              style: const TextStyle(fontWeight: FontWeight.w600)),
          Text('${c['title']}'),
          for (final r in reqs)
            Text(
                '${_label(r['relation'])}: ${r['course_code']} ${r['met'] == true ? '✓' : '✗'}',
                style: TextStyle(
                    fontSize: 12,
                    color: r['met'] == true ? null : Colors.red.shade700)),
          for (final o in offerings)
            Builder(builder: (context) {
              final item = _itemFor('${o['offering_id']}');
              final full =
                  o['seats_left'] != null && (o['seats_left'] as num) <= 0;
              return ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(
                    'Section ${o['section_code']} · ${o['enrolled_count']}/${o['max_seats'] ?? '∞'}'),
                subtitle:
                    Text(((o['faculty'] as List?) ?? const []).join(', ')),
                trailing: item != null
                    ? TextButton(
                        onPressed: () =>
                            _run(() => repo.drop('${item['id']}'), 'Dropped'),
                        child: Text('${_label(item['status'])} · drop'))
                    : c['in_cart'] != null
                        ? null
                        : FilledButton.tonal(
                            onPressed: () => _run(
                                () => repo.add('${o['offering_id']}', type),
                                full ? 'Waitlisted' : 'Added'),
                            child: Text(full ? 'Waitlist' : 'Add')),
              );
            }),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.read(registrationRepositoryProvider);
    final c = _catalog;
    final reg = _reg;
    final limits = (c?['limits'] ?? reg?['limits']) as Map?;
    final holds = (c?['holds'] as List?) ?? const [];
    final pending = (c?['undertakings_pending'] as List?) ?? const [];
    final offers = _items
        .where((i) => (i['waitlist'] as Map?)?['status'] == 'offered')
        .toList();
    return Scaffold(
      appBar: AppBar(title: const Text('Course registration')),
      body: _err != null
          ? Center(child: Text(_error(_err!)))
          : c == null && reg == null
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(padding: const EdgeInsets.all(12), children: [
                    if (holds.isNotEmpty)
                      Card(
                          color: Colors.red.shade50,
                          child: const ListTile(
                              leading: Icon(Icons.block),
                              title: Text(
                                  'Registration hold — submission is blocked'))),
                    if (pending.isNotEmpty)
                      Card(
                          color: Colors.orange.shade50,
                          child: ListTile(
                              title: Text(
                                  'Accept pending undertakings: ${pending.join(', ')}'))),
                    if (reg != null)
                      Card(
                        child: ListTile(
                          title: Text(
                              '${_label(reg['status'])} · ${reg['total_credits']} credits'),
                          subtitle: limits == null
                              ? null
                              : Text(
                                  'min ${limits['min']} · max ${limits['max']}${reg['advisor_comment'] != null ? '\nAdvisor: ${reg['advisor_comment']}' : ''}'),
                          trailing: ['draft', 'changes_requested', 'rejected']
                                  .contains(reg['status'])
                              ? FilledButton(
                                  onPressed: () async {
                                    await _run(
                                        () => repo.submit(_key), 'Submitted');
                                    _key = DateTime.now()
                                        .microsecondsSinceEpoch
                                        .toString();
                                  },
                                  child: const Text('Submit'))
                              : null,
                        ),
                      ),
                    for (final i in offers)
                      Card(
                          child: ListTile(
                              title: Text('Seat offered: ${i['course_code']}'),
                              trailing: FilledButton(
                                  onPressed: () => _run(
                                      () => repo.acceptWaitlist(
                                          '${(i['waitlist'] as Map)['id']}'),
                                      'Seat accepted'),
                                  child: const Text('Accept')))),
                    if (c != null) ...[
                      const Padding(
                          padding: EdgeInsets.symmetric(vertical: 8),
                          child: Text('Curriculum courses',
                              style: TextStyle(fontWeight: FontWeight.bold))),
                      for (final course
                          in ((c['curriculum'] as List?) ?? const [])
                              .cast<Map<String, dynamic>>())
                        _course(course),
                      for (final b in ((c['baskets'] as List?) ?? const [])
                          .cast<Map<String, dynamic>>())
                        _BasketCard(
                            basket: b,
                            termId: '${(c['term'] as Map)['id']}',
                            onSaved: _load),
                      if (((c['arrears'] as List?) ?? const []).isNotEmpty)
                        const Padding(
                            padding: EdgeInsets.symmetric(vertical: 8),
                            child: Text('Arrears',
                                style: TextStyle(fontWeight: FontWeight.bold))),
                      for (final a in ((c['arrears'] as List?) ?? const [])
                          .cast<Map<String, dynamic>>())
                        _course(a, 'arrear'),
                    ],
                  ]),
                ),
    );
  }
}

class _BasketCard extends ConsumerStatefulWidget {
  const _BasketCard(
      {required this.basket, required this.termId, required this.onSaved});

  final Map<String, dynamic> basket;
  final String termId;
  final Future<void> Function() onSaved;

  @override
  ConsumerState<_BasketCard> createState() => _BasketState();
}

class _BasketState extends ConsumerState<_BasketCard> {
  late List<Map<String, dynamic>> _order;

  @override
  void initState() {
    super.initState();
    final courses = ((widget.basket['courses'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    final form = widget.basket['choice_form'] as Map?;
    if (form != null) {
      final ids = ((form['choices'] as List?) ?? const [])
          .map((c) => '${(c as Map)['course_id']}')
          .toList();
      _order = [
        for (final id in ids) ...courses.where((c) => c['course_id'] == id)
      ];
    } else {
      _order = List.of(courses);
    }
  }

  @override
  Widget build(BuildContext context) {
    final form = widget.basket['choice_form'] as Map?;
    return Card(
      child: Column(children: [
        ListTile(
            title: Text('${widget.basket['code']} — ${widget.basket['name']}'),
            subtitle: Text(form == null
                ? 'Drag to rank your choices'
                : '${_label(form['status'])}${form['allocated_course_code'] != null ? ' · ${form['allocated_course_code']}' : ''}')),
        ReorderableListView(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          // ignore: deprecated_member_use
          onReorder: (a, b) => setState(() {
            if (b > a) b -= 1;
            _order.insert(b, _order.removeAt(a));
          }),
          children: [
            for (var i = 0; i < _order.length; i++)
              ListTile(
                  key: ValueKey(_order[i]['course_id']),
                  leading: Text('${i + 1}.'),
                  title: Text('${_order[i]['code']} ${_order[i]['title']}')),
          ],
        ),
        Padding(
          padding: const EdgeInsets.all(8),
          child: FilledButton(
              onPressed: () async {
                try {
                  await ref.read(registrationRepositoryProvider).saveChoices(
                      '${widget.basket['basket_id']}',
                      widget.termId,
                      _order.map((c) => '${c['course_id']}').toList(),
                      form != null);
                  if (context.mounted) _toast(context, 'Choices saved');
                  await widget.onSaved();
                } catch (e) {
                  if (context.mounted) _toast(context, _error(e));
                }
              },
              child: Text(form == null ? 'Submit choices' : 'Update choices')),
        ),
      ]),
    );
  }
}

// ---- faculty offerings / roster ------------------------------------------------------------------------------------------
class MyOfferingsScreen extends ConsumerWidget {
  const MyOfferingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('My offerings')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: ref.read(registrationRepositoryProvider).myOfferings(),
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final rows = snap.data!;
          if (rows.isEmpty) {
            return const Center(child: Text('No offerings allocated to you.'));
          }
          return ListView.separated(
            itemCount: rows.length,
            separatorBuilder: (_, __) => const Divider(height: 1),
            itemBuilder: (_, i) {
              final o = rows[i];
              return ListTile(
                title:
                    Text('${o['course_code']} · section ${o['section_code']}'),
                subtitle: Text('${o['course_title']}'),
                trailing:
                    Text('${o['enrolled_count']}/${o['max_seats'] ?? '∞'}'),
                onTap: () =>
                    context.push('${AppRoutes.offeringRoster}?id=${o['id']}'),
              );
            },
          );
        },
      ),
    );
  }
}

class OfferingRosterScreen extends ConsumerWidget {
  const OfferingRosterScreen({super.key, required this.id});

  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Roster')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: ref.read(registrationRepositoryProvider).roster(id),
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final rows = snap.data!;
          return ListView.builder(
            itemCount: rows.length,
            itemBuilder: (_, i) => ListTile(
              title: Text('${rows[i]['name']}'),
              subtitle: Text(
                  '${rows[i]['registration_number']} · ${rows[i]['batch_code']} ${rows[i]['section_name'] ?? ''}'),
              trailing: Text(_label(rows[i]['status'])),
            ),
          );
        },
      ),
    );
  }
}

// ---- advisor approvals --------------------------------------------------------------------------------------------------
class RegistrationApprovalsScreen extends ConsumerStatefulWidget {
  const RegistrationApprovalsScreen({super.key});

  @override
  ConsumerState<RegistrationApprovalsScreen> createState() => _ApprovalsState();
}

class _ApprovalsState extends ConsumerState<RegistrationApprovalsScreen> {
  late Future<List<Map<String, dynamic>>> _future;

  @override
  void initState() {
    super.initState();
    _future = ref.read(registrationRepositoryProvider).pending();
  }

  Future<void> _decide(String id, String action) async {
    String? comment;
    if (action != 'approve') {
      final ctl = TextEditingController();
      comment = await showDialog<String>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(_label(action.replaceAll('-', '_'))),
          content: TextField(
              controller: ctl,
              decoration:
                  const InputDecoration(hintText: 'Comment (required)')),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel')),
            FilledButton(
                onPressed: () => Navigator.pop(ctx, ctl.text),
                child: const Text('Send')),
          ],
        ),
      );
      if (comment == null || comment.trim().isEmpty) return;
    }
    try {
      await ref
          .read(registrationRepositoryProvider)
          .decide(id, action, comment);
      if (mounted) _toast(context, 'Done');
    } catch (e) {
      if (mounted) _toast(context, _error(e));
    }
    setState(
        () => _future = ref.read(registrationRepositoryProvider).pending());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Registration approvals')),
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _future,
        builder: (context, snap) {
          if (snap.hasError) return Center(child: Text(_error(snap.error!)));
          if (!snap.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final rows = snap.data!;
          if (rows.isEmpty) {
            return const Center(child: Text('Nothing awaiting your approval.'));
          }
          return ListView(
            padding: const EdgeInsets.all(8),
            children: [
              for (final r in rows)
                Card(
                  child: Column(children: [
                    ListTile(
                      title: Text(
                          '${r['student_name']} · ${r['registration_number']}'),
                      subtitle: Text(
                          '${r['batch_code']} ${r['section_name'] ?? ''} · ${r['total_credits']} credits · ${r['items_count']} courses'),
                    ),
                    OverflowBar(children: [
                      TextButton(
                          onPressed: () => _decide('${r['id']}', 'reject'),
                          child: const Text('Reject')),
                      TextButton(
                          onPressed: () =>
                              _decide('${r['id']}', 'request-changes'),
                          child: const Text('Request changes')),
                      FilledButton(
                          onPressed: () => _decide('${r['id']}', 'approve'),
                          child: const Text('Approve')),
                    ]),
                  ]),
                ),
            ],
          );
        },
      ),
    );
  }
}
