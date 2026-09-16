import 'package:flutter/material.dart';

/// Fallback for unregistered routes and not-yet-built screens (docs/Mobile_App_UI_Structure.md §1).
class PlaceholderScreen extends StatelessWidget {
  const PlaceholderScreen(
      {super.key, required this.title, this.notFound = false});

  final String title;
  final bool notFound;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(notFound ? 'Not found' : title)),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                notFound ? Icons.help_outline : Icons.construction_outlined,
                size: 48,
                color: theme.colorScheme.outline,
              ),
              const SizedBox(height: 12),
              Text(
                notFound ? 'Screen not found' : title,
                style: theme.textTheme.titleMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 4),
              Text(
                notFound
                    ? 'This route is not registered in screen_registry.dart.'
                    : 'This screen arrives with its module phase.',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
