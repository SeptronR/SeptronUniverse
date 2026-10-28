// l10n completeness (Prompts/42 §42.6): every key of lib/l10n/app_en.arb exists in all locale ARBs, and no widget
// passes a hard-coded literal to `Text('…')` outside the allow-listed files (shared catalogue placeholders, tools).
//
//   dart run tool/check_l10n.dart            # keys only
//   dart run tool/check_l10n.dart --strings  # also report hard-coded Text('…') literals
import 'dart:convert';
import 'dart:io';

void main(List<String> args) {
  final dir = Directory('lib/l10n');
  final en = jsonDecode(File('lib/l10n/app_en.arb').readAsStringSync()) as Map<String, dynamic>;
  final keys = en.keys.where((k) => !k.startsWith('@')).toSet();
  var problems = 0;
  final arbs = dir.listSync().whereType<File>().where((f) => f.path.endsWith('.arb') && !f.path.endsWith('app_en.arb'));
  for (final f in arbs) {
    final m = jsonDecode(f.readAsStringSync()) as Map<String, dynamic>;
    final absent = keys.difference(m.keys.toSet());
    if (absent.isNotEmpty) {
      problems += absent.length;
      stdout.writeln('${f.uri.pathSegments.last}: missing ${absent.length} — ${absent.take(10).join(', ')}');
    }
  }
  stdout.writeln('l10n: ${keys.length} keys × ${arbs.length + 1} locales, $problems missing');
  if (args.contains('--strings')) {
    final literal = RegExp(r"""Text\(\s*'[A-Za-z][^'$]*'""");
    var count = 0;
    for (final f in Directory('lib').listSync(recursive: true).whereType<File>()) {
      if (!f.path.endsWith('.dart') || f.path.contains('/l10n/')) continue;
      count += literal.allMatches(f.readAsStringSync()).length;
    }
    stdout.writeln('hard-coded Text literals: $count (reported, not failing until the ARB migration completes)');
  }
  exit(problems == 0 ? 0 : 1);
}
