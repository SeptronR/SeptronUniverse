import 'package:flutter/material.dart';

/// Tablet master-detail (`mobile.tablet_layout`, Prompts/42 §42.6): ≥ 840 dp wide shows the list and the selected
/// item side by side; phones push the detail as a page.
class MasterDetail<T> extends StatefulWidget {
  const MasterDetail({super.key, required this.items, required this.tile, required this.detail, this.enabled = true});

  final List<T> items;
  final Widget Function(BuildContext context, T item, bool selected, VoidCallback onTap) tile;
  final Widget Function(BuildContext context, T item) detail;
  final bool enabled;

  static bool isWide(BuildContext context) => MediaQuery.of(context).size.width >= 840;

  @override
  State<MasterDetail<T>> createState() => _MasterDetailState<T>();
}

class _MasterDetailState<T> extends State<MasterDetail<T>> {
  T? _selected;

  @override
  Widget build(BuildContext context) {
    final wide = widget.enabled && MasterDetail.isWide(context);
    final list = ListView.builder(
      itemCount: widget.items.length,
      itemBuilder: (ctx, i) {
        final item = widget.items[i];
        return widget.tile(ctx, item, wide && identical(item, _selected), () {
          if (wide) {
            setState(() => _selected = item);
          } else {
            Navigator.of(ctx).push(MaterialPageRoute<void>(builder: (c) => Scaffold(appBar: AppBar(), body: widget.detail(c, item))));
          }
        });
      },
    );
    if (!wide) return list;
    return Row(children: [
      SizedBox(width: 360, child: list),
      const VerticalDivider(width: 1),
      Expanded(child: _selected == null ? const Center(child: Text('Select an item')) : widget.detail(context, _selected as T)),
    ]);
  }
}
