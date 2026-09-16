import { z } from 'zod';

/** Shared zod pieces for RHF forms (IN pack formats; the backend re-validates through the regulatory pack). */
export const phoneIN = z.string().regex(/^[6-9]\d{9}$/, 'Enter a valid 10-digit mobile number');
export const emailSchema = z.string().email('Enter a valid email');
export const pan = z.string().regex(/^[A-Z]{5}\d{4}[A-Z]$/, 'Enter a valid PAN');
export const aadhaar = z.string().regex(/^[2-9]\d{11}$/, 'Enter a valid 12-digit Aadhaar');
export const apaar = z.string().regex(/^\d{12}$/, 'Enter a valid 12-digit APAAR id');
export const gstin = z.string().regex(/^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/, 'Enter a valid GSTIN');
export const pincode = z.string().regex(/^\d{6}$/, 'Enter a 6-digit PIN code');
export const uuid = z.string().uuid();
export const code = z
  .string()
  .min(1, 'Required')
  .max(30)
  .regex(/^[A-Za-z0-9_-]+$/, 'Letters, digits, - and _ only');
export const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Use YYYY-MM-DD');
/** Money inputs are entered in rupees and converted to paise before the request. */
export const rupees = z.coerce.number().min(0, 'Must be zero or more');
export const optional = <T extends z.ZodTypeAny>(schema: T) =>
  schema.optional().or(z.literal('').transform(() => undefined));
