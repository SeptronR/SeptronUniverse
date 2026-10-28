import 'package:flutter/material.dart';

/// `AttendanceGrid` (Prompts/42 §42.6 faculty / roll call): tap cycles P → A → L → OD, bulk "all present", search;
/// cells carry semantics labels for TalkBack / VoiceOver and are ≥ 48 dp.
class AttendanceGrid extends StatefulWidget {
  const AttendanceGrid({super.key, required this.students, required this.onChanged, this.initial = const {}, this.readOnly = false});

  /// `{id, name, roll_no}`
  final List<Map<String, dynamic>> students;
  final Map<String, String> initial;
  final bool readOnly;
  final ValueChanged<Map<String, String>> onChanged;

  static const cycle = ['present', 'absent', 'late', 'od'];

  @override
  State<AttendanceGrid> createState() => _AttendanceGridState();
}

class _AttendanceGridState extends State<AttendanceGrid> {
  late final Map<String, String> _marks = {
    for (final s in widget.students) '${s['id']}': widget.initial['${s['id']}'] ?? 'present',
  };
  String _q = '';

  void _set(String id, String status) {
    setState(() => _marks[id] = status);
    widget.onChanged(Map.of(_marks));
  }

  Color _color(BuildContext context, String s) => switch (s) {
        'absent' => Colors.red.shade400,
        'late' => Colors.orange.shade400,
        'od' => Colors.blue.shade400,
        _ => Colors.green.shade500,
      };

  @override
  Widget build(BuildContext context) {
    final shown = widget.students
        .where((s) => _q.isEmpty || '${s['name']} ${s['roll_no']}'.toLowerCase().contains(_q.toLowerCase()))
        .toList();
    final absent = _marks.values.where((v) => v == 'absent').length;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        child: Row(children: [
          Expanded(
            child: TextField(
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search', isDense: true),
              onChanged: (v) => setState(() => _q = v),
            ),
          ),
          const SizedBox(width: 8),
          if (!widget.readOnly)
            TextButton(
              onPressed: () {
                for (final id in _marks.keys) {
                  _marks[id] = 'present';
                }
                setState(() {});
                widget.onChanged(Map.of(_marks));
              },
              child: const Text('All present'),
            ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Align(alignment: Alignment.centerLeft, child: Text('${_marks.length - absent} present · $absent absent')),
      ),
      Expanded(
        child: GridView.builder(
          padding: const EdgeInsets.all(8),
          gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: 120, mainAxisExtent: 72, crossAxisSpacing: 6, mainAxisSpacing: 6),
          itemCount: shown.length,
          itemBuilder: (context, i) {
            final s = shown[i];
            final id = '${s['id']}';
            final status = _marks[id]!;
            return Semantics(
              button: true,
              label: '${s['name']}, ${status.replaceAll('od', 'on duty')}',
              child: InkWell(
                onTap: widget.readOnly
                    ? null
                    : () => _set(id, AttendanceGrid.cycle[(AttendanceGrid.cycle.indexOf(status) + 1) % AttendanceGrid.cycle.length]),
                borderRadius: BorderRadius.circular(8),
                child: Ink(
                  decoration: BoxDecoration(color: _color(context, status).withOpacity(0.18), borderRadius: BorderRadius.circular(8), border: Border.all(color: _color(context, status))),
                  child: Padding(
                    padding: const EdgeInsets.all(6),
                    child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                      Text('${s['roll_no'] ?? ''}', style: Theme.of(context).textTheme.labelSmall, overflow: TextOverflow.ellipsis),
                      Text('${s['name']}', maxLines: 1, overflow: TextOverflow.ellipsis),
                      Text(status.toUpperCase(), style: TextStyle(color: _color(context, status), fontWeight: FontWeight.bold, fontSize: 11)),
                    ]),
                  ),
                ),
              ),
            );
          },
        ),
      ),
    ]);
  }
}
