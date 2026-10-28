// Portal parity (Prompts/42 §42.11 step 2): compares the tab routes of `GET /portal/config` (saved per persona into
// tool/portal_config/<persona>.json by scripts/verify/42_mobile.ps1) with the persona's `roleTabs` in
// role_shells.dart. Tabs are compared by their last path segment (web `/student/fees` ↔ app `/app/fees`).
//
//   dart run tool/check_portal_parity.dart
import 'dart:convert';
import 'dart:io';

const personaRole = {
  'student': 'student',
  'parent': 'parent',
  'faculty': 'faculty',
  'alumni': 'alumni',
  'warden': 'hostelWarden',
  'gate': 'hostelGateStaff',
  'scholar': 'researchScholar',
  'recruiter': 'recruiter',
  'driver': 'driver',
  'evaluator': 'externalExaminer',
};

void main() {
  final dir = Directory('tool/portal_config');
  if (!dir.existsSync()) {
    stdout.writeln('portal parity: no saved /portal/config snapshots (run scripts/verify/42_mobile.ps1) — skipped');
    return;
  }
  final shells = File('lib/core/router/role_shells.dart').readAsStringSync();
  var diffs = 0;
  personaRole.forEach((persona, role) {
    final f = File('${dir.path}/$persona.json');
    if (!f.existsSync()) return;
    final cfg = jsonDecode(f.readAsStringSync()) as Map<String, dynamic>;
    final web = ((cfg['tabs'] as List?) ?? const [])
        .map((t) => '${(t as Map)['key'] ?? ''}'.toLowerCase())
        .where((k) => k.isNotEmpty)
        .toSet();
    final block = RegExp('Roles\\.$role: \\[(.*?)\\],\\n', dotAll: true).firstMatch(shells)?.group(1) ?? '';
    final app = RegExp(r"_t\('(\w+)'").allMatches(block).map((m) => m.group(1)!.toLowerCase()).toSet()
      ..addAll(RegExp(r'_(home|more|approvals|alerts)\b').allMatches(block).map((m) => m.group(1)!.replaceAll('alerts', 'notifications')));
    final onlyWeb = web.difference(app);
    if (onlyWeb.isNotEmpty) {
      diffs += onlyWeb.length;
      stdout.writeln('$persona: web-only tabs ${onlyWeb.join(', ')} (app: ${app.join(', ')})');
    }
  });
  stdout.writeln('portal parity: $diffs diffs');
  exit(diffs == 0 ? 0 : 1);
}
