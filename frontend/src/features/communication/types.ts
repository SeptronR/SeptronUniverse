/** Communication core types (Prompts/04 §04.4 — mirrors app/schemas/communication.py). */
export type Channel = 'in_app' | 'sms' | 'whatsapp' | 'email' | 'push';
export const CHANNELS: Channel[] = ['in_app', 'sms', 'whatsapp', 'email', 'push'];

export interface NotificationTemplate {
  id: string;
  institution_id: string | null;
  event_trigger: string;
  name: string;
  channels: Channel[];
  subject_template: string | null;
  body_template: string;
  variables: string[] | null;
  language: string;
  version: number;
  is_active: boolean;
  dlt_template_id: string | null;
  whatsapp_template_name: string | null;
  updated_at: string;
  is_platform: boolean;
  category: string | null;
}

export interface TemplatePreview {
  subject: string | null;
  body: string;
  missing_variables: string[];
}

export interface DltTemplate {
  id: string;
  sender_id: string;
  entity_id: string | null;
  template_id: string;
  template_text: string;
  category: string;
  status: string;
  created_at: string;
}

export interface WhatsappTemplate {
  id: string;
  name: string;
  language: string;
  category: string;
  body: string;
  status: string;
  meta_template_id: string | null;
  updated_at: string;
}

export interface MessageLog {
  id: string;
  user_id: string | null;
  recipient: string;
  channel: Channel;
  event_type: string | null;
  subject: string | null;
  body_preview: string | null;
  provider: string | null;
  provider_message_id: string | null;
  status: string;
  error: string | null;
  cost_paise: number | null;
  created_at: string;
  sent_at: string | null;
  delivered_at: string | null;
}

export interface AppNotification {
  id: string;
  title: string;
  body: string | null;
  category: string | null;
  event_type: string | null;
  link: Record<string, string> | null;
  is_read: boolean;
  read_at: string | null;
  created_at: string;
  route: string | null;
}

export interface PreferenceItem {
  category: string;
  channels: Channel[];
  quiet_hours: { from: string; to: string } | null;
  digest: 'none' | 'daily' | 'weekly';
  mandatory: boolean;
}

export interface AudienceRules {
  roles: string[];
  college_ids: string[];
  department_ids: string[];
  program_ids: string[];
  batch_ids: string[];
  user_ids: string[];
}

export interface Announcement {
  id: string;
  college_id: string | null;
  title: string;
  body: string;
  category: string | null;
  audience_rules: Partial<AudienceRules> | null;
  publish_at: string | null;
  expires_at: string | null;
  requires_ack: boolean;
  is_pinned: boolean;
  created_by: string | null;
  created_at: string;
  status: 'draft' | 'scheduled' | 'published' | 'expired';
  my_read_at: string | null;
  my_acknowledged_at: string | null;
  ack_stats: { total: number; read: number; acknowledged: number } | null;
}

export const EMPTY_AUDIENCE: AudienceRules = { roles: [], college_ids: [], department_ids: [], program_ids: [], batch_ids: [], user_ids: [] };
