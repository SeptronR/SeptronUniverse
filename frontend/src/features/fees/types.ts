/** Fees, scholarships & no-dues (Prompts/12 §12.4). Money is integer paise everywhere. */
export interface FeeHead {
  id: string;
  code: string;
  name: string;
  head_type: string;
  is_refundable: boolean;
  is_taxable: boolean;
  gst_rate: number | null;
  ledger_account_id: string | null;
  is_active: boolean;
}

export interface StructureItem {
  id?: string;
  fee_head_id: string;
  head_code?: string | null;
  head_name?: string | null;
  amount_paise: number;
  instalment_no: number;
  due_date?: string | null;
  due_offset_days?: number | null;
  is_optional: boolean;
}

export interface FeeStructure {
  id: string;
  name: string;
  college_id: string | null;
  academic_year_id: string | null;
  program_id: string | null;
  program_regulation_id: string | null;
  batch_id: string | null;
  term_number: number | null;
  category: string | null;
  quota: string | null;
  effective_from: string;
  effective_to: string | null;
  total_paise: number;
  per_credit_paise: number | null;
  status: string;
  version: number;
  items: StructureItem[];
  assigned_count: number;
}

export interface Discount {
  id: string;
  code: string;
  name: string;
  discount_type: 'percentage' | 'fixed';
  value: number;
  applies_to_heads: string[] | null;
  requires_approval: boolean;
  max_per_year: number | null;
  is_active: boolean;
}

export interface DiscountAssignment {
  id: string;
  student_program_enrollment_id: string;
  discount_id: string;
  discount_code: string | null;
  discount_name: string | null;
  reason: string | null;
  status: string;
  workflow_instance_id: string | null;
  created_at: string;
}

export interface FineConfig {
  id?: string;
  applies_to: string;
  calc_type: string;
  amount_paise: number | null;
  grace_days: number;
  max_paise: number | null;
  is_active: boolean;
}

export interface InvoiceItem {
  id: string;
  fee_head_id: string | null;
  description: string;
  amount_paise: number;
  tax_paise: number;
  instalment_no: number | null;
  due_date: string | null;
}

export interface Payment {
  id: string;
  invoice_id: string;
  invoice_number: string | null;
  receipt_number: string;
  amount_paise: number;
  payment_date: string;
  payment_mode: string;
  gateway: string | null;
  gateway_order_id: string | null;
  reference_no: string | null;
  utr: string | null;
  bank_name: string | null;
  status: string;
  counter: string | null;
  receipt_url: string | null;
  cancel_reason: string | null;
  cancel_workflow_instance_id: string | null;
  payer_name: string | null;
  created_at: string;
}

export interface Invoice {
  id: string;
  invoice_number: string;
  payer_type: string;
  payer_id: string;
  payer_name: string | null;
  registration_number: string | null;
  student_program_enrollment_id: string | null;
  source_type: string | null;
  source_id: string | null;
  source_link: string | null;
  description: string | null;
  total_paise: number;
  discount_paise: number;
  tax_paise: number;
  fine_paise: number;
  paid_paise: number;
  balance_paise: number;
  due_date: string | null;
  status: string;
  gst_number: string | null;
  created_at: string;
  items: InvoiceItem[];
  payments: Payment[];
}

export interface Dues {
  invoices: Invoice[];
  total_due: number;
  overdue: number;
  next_due: string | null;
  student_name: string | null;
  enrollment_id: string | null;
}

export interface Receipt {
  receipt_numbers: string[];
  payments: Payment[];
  invoices: Invoice[];
  amount_paise: number;
}

export interface OnlineOrder {
  order_id: string;
  gateway: string;
  key: string | null;
  amount: number;
  checkout: Record<string, unknown>;
  payment_ids: string[];
}

export interface OrderStatus {
  order_id: string;
  status: string;
  amount_paise: number;
  receipt_numbers: string[];
}

export interface UpiQr {
  qr_png: string | null;
  upi_uri: string;
  vpa: string;
  amount: number;
  ref: string;
  status: string;
}

export interface ReconcileRow {
  id: string;
  statement_date: string | null;
  utr: string | null;
  amount_paise: number | null;
  payer_hint: string | null;
  status: string;
  matched_payment_id: string | null;
  proposed_payment_id: string | null;
  proposed_receipt: string | null;
  created_at: string;
}

export interface Refund {
  id: string;
  invoice_id: string | null;
  invoice_number: string | null;
  payer_name: string | null;
  amount_paise: number;
  reason: string;
  refund_mode: string | null;
  reference_no: string | null;
  status: string;
  workflow_instance_id: string | null;
  processed_at: string | null;
  created_at: string;
  can_act: boolean;
}

export interface DayBookRow {
  id: string | null;
  entry_date: string;
  counter: string | null;
  collector_name: string | null;
  cash_paise: number;
  digital_paise: number;
  cheque_paise: number;
  deposited_paise: number;
  status: string;
  receipts: number;
}

export interface DayBook {
  date: string;
  rows: DayBookRow[];
  by_mode: Record<string, number>;
  total_paise: number;
}

export interface FeeDashboard {
  today_by_mode: Record<string, number>;
  today_total: number;
  dues_total: number;
  overdue_total: number;
  overdue_count: number;
  reconcile_pending: number;
  refunds_pending: number;
  cancel_pending: number;
  online_initiated: number;
}

export interface FeeReport {
  report: string;
  rows: { key: string; label: string | null; count: number; amount_paise: number; extra: Record<string, unknown> }[];
  total_paise: number;
}

export interface Scholarship {
  id: string;
  name: string;
  provider: string;
  scheme_code: string | null;
  amount_paise: number | null;
  amount_type: string;
  eligibility_rules: Record<string, unknown> | null;
  applications_open: string | null;
  applications_close: string | null;
  description: string | null;
  is_active: boolean;
  applications: number;
}

export interface ScholarshipApplication {
  id: string;
  scholarship_id: string;
  scholarship_name: string | null;
  student_name: string | null;
  registration_number: string | null;
  income_paise: number | null;
  status: string;
  sanctioned_paise: number | null;
  disbursement_mode: string | null;
  external_ref: string | null;
  disbursed_at: string | null;
  workflow_instance_id: string | null;
  created_at: string;
  can_act: boolean;
}

export interface Signoff {
  id: string;
  department_key: string;
  status: string;
  dues_paise: number;
  remarks: string | null;
  signed_at: string | null;
  can_sign: boolean;
}

export interface NoDues {
  id: string;
  student_program_enrollment_id: string;
  student_name: string | null;
  registration_number: string | null;
  purpose: string;
  status: string;
  requested_at: string;
  cleared_at: string | null;
  certificate_number: string | null;
  signoffs: Signoff[];
}

export const PAYMENT_MODES = ['cash', 'upi', 'card', 'cheque', 'dd', 'neft', 'challan'] as const;
export const NO_DUES_PURPOSES = ['graduation', 'transfer', 'hostel_vacate', 'exit', 'transcript'] as const;
export const DEPARTMENT_KEYS = ['accounts', 'library', 'hostel', 'department', 'lab', 'sports', 'transport', 'placement'] as const;

/** ₹ from paise (en-IN grouping). */
export const inr = (paise: number | null | undefined) =>
  `₹${((paise ?? 0) / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
/** Paise from a rupee string typed in a form. */
export const toPaise = (rupees: string | number) => Math.round(Number(rupees || 0) * 100);

export const INVOICE_VARIANT: Record<string, 'success' | 'warning' | 'destructive' | 'secondary' | 'info'> = {
  paid: 'success',
  partial: 'warning',
  pending: 'info',
  overdue: 'destructive',
  cancelled: 'secondary',
  refunded: 'secondary',
};
