import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'network/dio_client.dart';

/// Shared infrastructure providers (docs/Mobile_App_UI_Structure.md §1).
final secureStorageProvider =
    Provider<FlutterSecureStorage>((ref) => const FlutterSecureStorage());

final dioClientProvider = Provider<DioClient>((ref) => DioClient(ref));

final dioProvider = Provider<Dio>((ref) => ref.watch(dioClientProvider).dio);

final connectivityProvider = Provider<Connectivity>((ref) => Connectivity());

final connectivityStreamProvider = StreamProvider<List<ConnectivityResult>>(
  (ref) => ref.watch(connectivityProvider).onConnectivityChanged,
);

final isOnlineProvider = Provider<bool>((ref) {
  final results = ref.watch(connectivityStreamProvider).valueOrNull;
  if (results == null) return true;
  return results.any((r) => r != ConnectivityResult.none);
});
