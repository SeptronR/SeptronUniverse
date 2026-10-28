import 'dart:async';

import 'package:dio/dio.dart';
import 'package:razorpay_flutter/razorpay_flutter.dart';
import 'package:url_launcher/url_launcher.dart';

/// Online payments (Prompts/42 §42.6 `payments/`): Razorpay SDK checkout (order from `/fees/online/initiate`,
/// callback → `/fees/online/verify`) and UPI intent (`upi://pay?…` handed to Google Pay / PhonePe / BHIM).
/// A UPI intent result is never trusted on its own — the app polls the order status the gateway webhook updates.
enum PaymentOutcome { success, failed, cancelled, pending }

class PaymentResult {
  const PaymentResult(this.outcome, {this.paymentId, this.orderId, this.message});

  final PaymentOutcome outcome;
  final String? paymentId;
  final String? orderId;
  final String? message;
}

class PaymentsService {
  PaymentsService(this._dio);

  final Dio _dio;

  /// Razorpay checkout for an order created server-side. `initiate` returns `{order_id, key_id, amount, currency,
  /// prefill}` (Phase 12 envelope); the signature is verified by the API.
  Future<PaymentResult> razorpay({required Map<String, dynamic> initiateBody, String description = 'Fee payment'}) async {
    final res = await _dio.post<Map<String, dynamic>>('/fees/online/initiate', data: initiateBody);
    final order = (res.data?['data'] as Map?)?.cast<String, dynamic>() ?? const {};
    final completer = Completer<PaymentResult>();
    final rp = Razorpay();
    rp.on(Razorpay.EVENT_PAYMENT_SUCCESS, (PaymentSuccessResponse r) async {
      try {
        await _dio.post<void>('/fees/online/verify', data: {
          'order_id': r.orderId ?? order['order_id'],
          'payment_id': r.paymentId,
          'signature': r.signature,
        });
        completer.complete(PaymentResult(PaymentOutcome.success, paymentId: r.paymentId, orderId: r.orderId));
      } catch (e) {
        // captured at the gateway; the webhook will settle it
        completer.complete(PaymentResult(PaymentOutcome.pending, paymentId: r.paymentId, orderId: r.orderId, message: '$e'));
      }
    });
    rp.on(Razorpay.EVENT_PAYMENT_ERROR, (PaymentFailureResponse r) {
      completer.complete(PaymentResult(r.code == Razorpay.PAYMENT_CANCELLED ? PaymentOutcome.cancelled : PaymentOutcome.failed,
          message: r.message));
    });
    rp.on(Razorpay.EVENT_EXTERNAL_WALLET, (ExternalWalletResponse r) {
      completer.complete(PaymentResult(PaymentOutcome.pending, message: r.walletName));
    });
    rp.open({
      'key': order['key_id'],
      'order_id': order['order_id'],
      'amount': order['amount'],
      'currency': order['currency'] ?? 'INR',
      'name': order['merchant_name'] ?? 'SeptronUniverse',
      'description': description,
      'prefill': order['prefill'] ?? const {},
    });
    try {
      return await completer.future;
    } finally {
      rp.clear();
    }
  }

  /// UPI intent from the collect parameters the API returns (`pa`, `pn`, `am`, `tr`, `tn`).
  static Uri upiUri({required String payee, required String name, required num amount, required String ref, String? note}) =>
      Uri(scheme: 'upi', host: 'pay', queryParameters: {
        'pa': payee,
        'pn': name,
        'am': amount.toStringAsFixed(2),
        'cu': 'INR',
        'tr': ref,
        if (note != null) 'tn': note,
      });

  /// Opens the UPI chooser, then polls `/fees/online/{order}/status` (up to ~2 min) for the webhook result.
  Future<PaymentResult> upiIntent(Uri uri, {required String orderId}) async {
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      return const PaymentResult(PaymentOutcome.failed, message: 'No UPI app found');
    }
    for (var i = 0; i < 24; i++) {
      await Future<void>.delayed(const Duration(seconds: 5));
      try {
        final r = await _dio.get<Map<String, dynamic>>('/fees/online/$orderId/status');
        final status = (r.data?['data'] as Map?)?['status'];
        if (status == 'success' || status == 'captured') return PaymentResult(PaymentOutcome.success, orderId: orderId);
        if (status == 'failed') return PaymentResult(PaymentOutcome.failed, orderId: orderId);
      } catch (_) {}
    }
    return PaymentResult(PaymentOutcome.pending, orderId: orderId, message: 'Awaiting confirmation from the bank');
  }
}
