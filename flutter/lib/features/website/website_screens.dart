import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/providers.dart';

/// Phase 40 mobile (Prompts/40 §40.10): institution admin quick actions — publish a website notice (title / body /
/// category) and work the website enquiries (call / WhatsApp / status). No site builder on mobile.
String _error(Object e) {
  if (e is DioException) {
    final data = e.response?.data;
    if (data is Map && data['error'] is Map) return '${(data['error'] as Map)['message']}';
    return e.message ?? 'Request failed';
  }
  return '$e';
}

class WebsiteRepository {
  WebsiteRepository(this._dio);

  final Dio _dio;

  Future<List<Map<String, dynamic>>> enquiries() async {
    final r = await _dio.get<Map<String, dynamic>>('/website/enquiries');
    return ((r.data?['data'] as List?) ?? const []).cast<Map>().map((e) => e.cast<String, dynamic>()).toList();
  }

  Future<void> status(String id, String status) => _dio.put<void>('/website/enquiries/$id/status', data: {'status': status});

  Future<void> publishNotice(String title, String body, String category) => _dio.post<void>('/website/notices',
      data: {'title': title, 'body': body, 'category': category, 'is_published': true});
}

final websiteRepositoryProvider = Provider<WebsiteRepository>((ref) => WebsiteRepository(ref.watch(dioProvider)));

class WebsiteQuickScreen extends ConsumerStatefulWidget {
  const WebsiteQuickScreen({super.key});

  @override
  ConsumerState<WebsiteQuickScreen> createState() => _WebsiteQuickScreenState();
}

class _WebsiteQuickScreenState extends ConsumerState<WebsiteQuickScreen> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  String _category = 'general';
  int _tick = 0;

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  Future<void> _run(Future<void> Function() fn, String done) async {
    try {
      await fn();
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
      setState(() => _tick++);
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_error(e))));
    }
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.watch(websiteRepositoryProvider);
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Website'),
          bottom: const TabBar(tabs: [Tab(text: 'Quick notice'), Tab(text: 'Enquiries')]),
        ),
        body: TabBarView(children: [
          ListView(padding: const EdgeInsets.all(16), children: [
            TextField(controller: _title, decoration: const InputDecoration(labelText: 'Title')),
            TextField(controller: _body, maxLines: 4, decoration: const InputDecoration(labelText: 'Body')),
            DropdownButton<String>(
              value: _category,
              items: const ['general', 'admissions', 'examinations', 'events', 'results', 'scholarships']
                  .map((c) => DropdownMenuItem(value: c, child: Text(c)))
                  .toList(),
              onChanged: (v) => setState(() => _category = v ?? 'general'),
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: () => _run(() => repo.publishNotice(_title.text, _body.text, _category), 'Notice published'),
              child: const Text('Publish'),
            ),
          ]),
          FutureBuilder<List<Map<String, dynamic>>>(
            key: ValueKey(_tick),
            future: repo.enquiries(),
            builder: (context, snap) {
              if (snap.hasError) return Center(child: Text(_error(snap.error!)));
              if (!snap.hasData) return const Center(child: CircularProgressIndicator());
              final rows = snap.data!;
              if (rows.isEmpty) return const Center(child: Text('No enquiries.'));
              return ListView.separated(
                itemCount: rows.length,
                separatorBuilder: (_, __) => const Divider(height: 1),
                itemBuilder: (_, i) {
                  final e = rows[i];
                  final phone = '${e['phone'] ?? ''}';
                  return ListTile(
                    title: Text('${e['name']}'),
                    subtitle: Text('${e['subject'] ?? ''} · ${e['status']}'),
                    trailing: Wrap(children: [
                      if (phone.isNotEmpty && !phone.contains('•'))
                        IconButton(
                            tooltip: 'Call', icon: const Icon(Icons.call), onPressed: () => launchUrl(Uri.parse('tel:$phone'))),
                      if (phone.isNotEmpty && !phone.contains('•'))
                        IconButton(
                            tooltip: 'WhatsApp',
                            icon: const Icon(Icons.chat),
                            onPressed: () => launchUrl(Uri.parse('https://wa.me/${phone.replaceAll(RegExp(r'[^0-9]'), '')}'))),
                      IconButton(
                          tooltip: 'Mark contacted',
                          icon: const Icon(Icons.check),
                          onPressed: () => _run(() => repo.status('${e['id']}', 'contacted'), 'Updated')),
                    ]),
                  );
                },
              );
            },
          ),
        ]),
      ),
    );
  }
}
