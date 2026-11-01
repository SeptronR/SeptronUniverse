-- =====================================================================================
-- SeptronUniverse — Database Schema (canonical, single source of truth for names)
-- PostgreSQL 15+.  Generated from docs/Academic_Core_Design.md and docs/Technical_Architecture.md
-- Conventions: UUID PKs, institution_id on every tenant table (RLS), college_id where scoped,
--   soft delete (is_active, deleted_at, deleted_by), optimistic lock (version), money in INTEGER paise,
--   status columns VARCHAR(30) validated by Python enums, TIMESTAMPTZ (UTC), DATE in institution timezone.
-- Sections: 1 Extensions & helpers · 2 Tenancy · 3 Auth · 4 RBAC · 5 Features · 6 Platform services
--   7 Academic structure · 8 Students · 9 HR · 10 Admissions · 11 Offerings & registration
--   12 Timetable & attendance · 13 Fees & scholarships · 14 Internal assessment, LMS, projects, OBE definitions
--   15 Examinations · 16 Results, credentials, post-result · 17 OBE attainment · 18 Library · 19 Hostel
--   20 Transport · 21 Inventory & procurement · 22 Accounting · 23 Communication · 24 Calendar, events, facilities
--   25 Documents & certificates · 26 Student support · 27 Placement & alumni · 28 Research & PhD
--   29 Accreditation · 30 Governance · 31 Affiliation · 32 SaaS & website · 33 Deferred FKs & indexes
--   34 RLS · 35 Triggers · 36 Seed data
-- =====================================================================================

-- ===================================== 1. EXTENSIONS & HELPERS =====================================
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

CREATE OR REPLACE FUNCTION trigger_set_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION attach_updated_at_trigger(tbl TEXT) RETURNS VOID AS $$
BEGIN
  EXECUTE format('DROP TRIGGER IF EXISTS set_updated_at ON %I', tbl);
  EXECUTE format('CREATE TRIGGER set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at()', tbl);
END; $$ LANGUAGE plpgsql;

-- Current tenant for RLS (set per request/task: SET LOCAL app.institution_id = '<uuid>')
CREATE OR REPLACE FUNCTION current_institution_id() RETURNS UUID AS $$
  SELECT NULLIF(current_setting('app.institution_id', TRUE), '')::UUID;
$$ LANGUAGE sql STABLE;

-- Optimistic lock bump
CREATE OR REPLACE FUNCTION trigger_bump_version() RETURNS TRIGGER AS $$
BEGIN NEW.version = COALESCE(OLD.version, 1) + 1; RETURN NEW; END; $$ LANGUAGE plpgsql;

-- ===================================== 2. TENANCY =====================================
CREATE TABLE institutions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(200) NOT NULL, short_name VARCHAR(60), slug VARCHAR(60) NOT NULL UNIQUE, code VARCHAR(20),
  institution_type VARCHAR(30) NOT NULL,            -- university | deemed_university | autonomous_college | affiliated_college | standalone_college | multi_campus
  regulatory_pack VARCHAR(10) NOT NULL DEFAULT 'IN', pack_version VARCHAR(20),
  timezone VARCHAR(60) NOT NULL DEFAULT 'Asia/Kolkata', locale VARCHAR(10) NOT NULL DEFAULT 'en-IN', currency CHAR(3) NOT NULL DEFAULT 'INR',
  parent_university_name VARCHAR(200), aishe_code VARCHAR(20), aicte_pid VARCHAR(30), naac_id VARCHAR(30), ugc_status VARCHAR(40), gstin VARCHAR(20),
  address JSONB, contact JSONB, logo_url TEXT, website_url TEXT,
  status VARCHAR(30) NOT NULL DEFAULT 'active',     -- pending | active | suspended | archived
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID
);

CREATE TABLE institution_profile (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL UNIQUE REFERENCES institutions(id) ON DELETE CASCADE,
  established_year SMALLINT, vision TEXT, mission TEXT, accreditations JSONB, recognitions JSONB, social_links JSONB,
  head_title VARCHAR(60), head_name VARCHAR(200), head_signature_url TEXT, seal_url TEXT, letterhead_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE colleges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  code VARCHAR(20) NOT NULL, name VARCHAR(200) NOT NULL, slug VARCHAR(60),
  college_type VARCHAR(30) NOT NULL DEFAULT 'constituent', -- constituent | affiliated | autonomous | campus | deemed_unit | study_centre | main
  affiliation_number VARCHAR(40), affiliated_since DATE, principal_staff_id UUID,
  exam_centre_code VARCHAR(20), is_exam_centre BOOLEAN NOT NULL DEFAULT FALSE,
  aishe_code VARCHAR(20), aicte_pid VARCHAR(30), gstin VARCHAR(20), address JSONB, contact JSONB, logo_url TEXT, timezone VARCHAR(60),
  is_main BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, code)
);

CREATE TABLE faculties (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  code VARCHAR(20) NOT NULL, name VARCHAR(200) NOT NULL, dean_staff_id UUID,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, code)
);

CREATE TABLE departments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  faculty_id UUID REFERENCES faculties(id) ON DELETE SET NULL,
  code VARCHAR(20) NOT NULL, name VARCHAR(200) NOT NULL,
  department_type VARCHAR(30) NOT NULL DEFAULT 'academic', -- academic | administrative | research_centre
  hod_staff_id UUID, established_year SMALLINT, description TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, code)
);

CREATE TABLE institution_settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE,
  category VARCHAR(40) NOT NULL, key VARCHAR(80) NOT NULL, value JSONB, value_type VARCHAR(20) NOT NULL DEFAULT 'string', is_public BOOLEAN NOT NULL DEFAULT FALSE,
  updated_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE NULLS NOT DISTINCT (institution_id, college_id, category, key) -- 0045: institution-wide rows (college_id NULL) collide
);

CREATE TABLE holidays (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE,
  name VARCHAR(120) NOT NULL, holiday_date DATE NOT NULL, end_date DATE, holiday_type VARCHAR(30) NOT NULL DEFAULT 'public', -- public | institution | restricted | exam_break
  applies_to VARCHAR(20) NOT NULL DEFAULT 'all', -- all | students | staff
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, holiday_date, name)
);

CREATE TABLE number_sequences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE,
  scope_key VARCHAR(120) NOT NULL, pattern VARCHAR(120) NOT NULL, next_value INTEGER NOT NULL DEFAULT 1, padding SMALLINT NOT NULL DEFAULT 4,
  reset_policy VARCHAR(20) NOT NULL DEFAULT 'never', -- never | yearly | per_term
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, college_id, scope_key)
);

-- ===================================== 3. AUTH =====================================
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,   -- NULL for platform users
  username VARCHAR(80) NOT NULL, email VARCHAR(200), phone VARCHAR(20), password_hash VARCHAR(255),
  display_name VARCHAR(200), avatar_url TEXT, user_type VARCHAR(30) NOT NULL DEFAULT 'staff', -- staff | student | guardian | alumni | applicant | recruiter | external | platform
  is_super_admin BOOLEAN NOT NULL DEFAULT FALSE, is_verified BOOLEAN NOT NULL DEFAULT FALSE, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  must_change_password BOOLEAN NOT NULL DEFAULT FALSE, password_changed_at TIMESTAMPTZ, last_login_at TIMESTAMPTZ,
  mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE, locale VARCHAR(10), timezone VARCHAR(60), preferences JSONB,
  valid_from TIMESTAMPTZ, valid_to TIMESTAMPTZ,
  version INT NOT NULL DEFAULT 1, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, username)
);
CREATE UNIQUE INDEX uq_users_email ON users (institution_id, LOWER(email)) WHERE email IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX uq_users_phone ON users (institution_id, phone) WHERE phone IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE password_reset_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash VARCHAR(64) NOT NULL UNIQUE, expires_at TIMESTAMPTZ NOT NULL, used_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE user_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  refresh_jti VARCHAR(64) NOT NULL UNIQUE, refresh_family VARCHAR(64) NOT NULL, device_label VARCHAR(120), platform VARCHAR(20), ip INET, user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ, revoked_reason VARCHAR(60)
);

CREATE TABLE mfa_secrets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  secret_encrypted BYTEA NOT NULL, recovery_codes_hashed JSONB NOT NULL, confirmed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE login_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL, identifier VARCHAR(200), outcome VARCHAR(30) NOT NULL, -- success | bad_password | locked | mfa_failed | sso
  ip INET, user_agent TEXT, occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE ip_allowlists (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  purpose VARCHAR(40) NOT NULL, -- exam_decode | results_publish | features | admin
  cidr CIDR NOT NULL, label VARCHAR(80), is_active BOOLEAN NOT NULL DEFAULT TRUE, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, purpose, cidr)
);

CREATE TABLE device_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider VARCHAR(20) NOT NULL, -- fcm | webpush | expo
  platform VARCHAR(20) NOT NULL, token TEXT NOT NULL, topics JSONB, is_active BOOLEAN NOT NULL DEFAULT TRUE, last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (provider, token)
);

CREATE TABLE credential_sheets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  batch_label VARCHAR(120), audience VARCHAR(20) NOT NULL, -- students | guardians | staff
  file_url TEXT, generated_by UUID, generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), job_id UUID
);

-- ===================================== 4. RBAC =====================================
CREATE TABLE permissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  module VARCHAR(60) NOT NULL, action VARCHAR(60) NOT NULL, description TEXT, is_platform BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (module, action)
);

CREATE TABLE roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,   -- NULL = platform role template
  name VARCHAR(80) NOT NULL, slug VARCHAR(60) NOT NULL, description TEXT,
  is_system BOOLEAN NOT NULL DEFAULT FALSE, default_scope_type VARCHAR(20) NOT NULL DEFAULT 'institution', portal VARCHAR(30),
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, slug)
);

CREATE TABLE role_permissions (
  role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE user_roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  scope_type VARCHAR(20) NOT NULL DEFAULT 'institution', -- institution | college | faculty | department | program | offering | self | committee | hostel
  scope_id UUID, valid_from TIMESTAMPTZ, valid_to TIMESTAMPTZ, assigned_by UUID, assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (user_id, role_id, scope_type, scope_id)
);

-- ===================================== 5. FEATURES =====================================
CREATE TABLE platform_features (
  key VARCHAR(80) PRIMARY KEY, group_name VARCHAR(40) NOT NULL, name VARCHAR(120) NOT NULL, description TEXT,
  default_enabled BOOLEAN NOT NULL DEFAULT TRUE, min_plan_tier VARCHAR(20) NOT NULL DEFAULT 'starter', depends_on JSONB NOT NULL DEFAULT '[]',
  is_core BOOLEAN NOT NULL DEFAULT FALSE, config_schema JSONB, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE institution_feature_flags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  feature_key VARCHAR(80) NOT NULL REFERENCES platform_features(key) ON DELETE CASCADE,
  platform_enabled BOOLEAN NOT NULL DEFAULT TRUE, institution_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  source VARCHAR(20) NOT NULL DEFAULT 'plan', -- plan | override
  config JSONB, set_by UUID, set_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, feature_key)
);

CREATE TABLE feature_flag_changes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  feature_key VARCHAR(80) NOT NULL, old_value JSONB, new_value JSONB, changed_by UUID, changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), reason TEXT
);

-- ===================================== 6. PLATFORM SERVICES =====================================
CREATE TABLE background_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  job_type VARCHAR(80) NOT NULL, params JSONB, status VARCHAR(20) NOT NULL DEFAULT 'queued', -- queued | running | succeeded | failed | cancelled
  progress_pct SMALLINT NOT NULL DEFAULT 0, message VARCHAR(255), result_url TEXT, result JSONB, error TEXT,
  requested_by UUID REFERENCES users(id), celery_task_id VARCHAR(64), cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, expires_at TIMESTAMPTZ
);
CREATE INDEX ix_background_jobs_user ON background_jobs (requested_by, created_at DESC);

CREATE TABLE domain_events (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  institution_id UUID, event_type VARCHAR(80) NOT NULL, aggregate_type VARCHAR(60), aggregate_id UUID, payload JSONB NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | dispatched | failed | dead
  attempts SMALLINT NOT NULL DEFAULT 0, next_attempt_at TIMESTAMPTZ, last_error TEXT, actor_user_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), dispatched_at TIMESTAMPTZ,
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE TABLE domain_events_default PARTITION OF domain_events DEFAULT;
CREATE INDEX ix_domain_events_pending ON domain_events (status, next_attempt_at) WHERE status = 'pending';

CREATE TABLE event_consumptions (
  consumer VARCHAR(80) NOT NULL, event_id UUID NOT NULL, consumed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (consumer, event_id)
);

CREATE TABLE idempotency_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID, user_id UUID, idempotency_key VARCHAR(120) NOT NULL, route VARCHAR(200) NOT NULL, request_hash VARCHAR(64) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'in_progress', response_code SMALLINT, response_body JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), expires_at TIMESTAMPTZ NOT NULL,
  UNIQUE (user_id, route, idempotency_key)
);

CREATE TABLE workflow_definitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  module VARCHAR(60) NOT NULL, key VARCHAR(80) NOT NULL, name VARCHAR(120) NOT NULL, description TEXT,
  steps JSONB NOT NULL, -- [{order, approver:{type: role|scope_rule|user, value}, mode: sequential|parallel, sla_hours, escalate_to}]
  version INT NOT NULL DEFAULT 1, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, key, version)
);

CREATE TABLE workflow_instances (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  definition_id UUID NOT NULL REFERENCES workflow_definitions(id),
  entity_type VARCHAR(60) NOT NULL, entity_id UUID NOT NULL, title VARCHAR(200),
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | approved | rejected | cancelled | escalated
  current_step SMALLINT NOT NULL DEFAULT 1, started_by UUID, started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), closed_at TIMESTAMPTZ, context JSONB
);
-- 0046: one OPEN instance per record; a closed instance may be followed by a resubmission
CREATE UNIQUE INDEX workflow_instances_one_open ON workflow_instances (entity_type, entity_id, definition_id)
  WHERE status IN ('pending', 'escalated');

CREATE TABLE workflow_steps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  instance_id UUID NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
  step_order SMALLINT NOT NULL, approver_user_id UUID REFERENCES users(id), approver_role_slug VARCHAR(60),
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | approved | rejected | skipped | escalated | delegated
  acted_by UUID, acted_at TIMESTAMPTZ, comment TEXT, sla_due_at TIMESTAMPTZ, escalated_to UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_workflow_steps_inbox ON workflow_steps (approver_user_id, status) WHERE status = 'pending';

CREATE TABLE workflow_delegations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  from_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, to_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  module VARCHAR(60), from_on DATE NOT NULL, to_on DATE NOT NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(120) NOT NULL, key_prefix VARCHAR(12) NOT NULL, hashed_key VARCHAR(64) NOT NULL UNIQUE, scopes JSONB NOT NULL DEFAULT '[]',
  rate_limit_per_minute INT NOT NULL DEFAULT 600, expires_at TIMESTAMPTZ, last_used_at TIMESTAMPTZ, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), revoked_at TIMESTAMPTZ
);

CREATE TABLE webhooks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(120) NOT NULL, url TEXT NOT NULL, secret_encrypted BYTEA NOT NULL, events JSONB NOT NULL DEFAULT '[]', is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE webhook_deliveries (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL, webhook_id UUID NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE, event_id UUID NOT NULL, event_type VARCHAR(80) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending', attempts SMALLINT NOT NULL DEFAULT 0, response_code SMALLINT, response_body TEXT, next_retry_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), delivered_at TIMESTAMPTZ,
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE TABLE webhook_deliveries_default PARTITION OF webhook_deliveries DEFAULT;

CREATE TABLE integration_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  capability VARCHAR(40) NOT NULL, provider VARCHAR(40) NOT NULL, label VARCHAR(120), config_encrypted BYTEA, public_config JSONB,
  is_sandbox BOOLEAN NOT NULL DEFAULT TRUE, status VARCHAR(20) NOT NULL DEFAULT 'configured', -- configured | healthy | degraded | failed | disabled
  last_health_at TIMESTAMPTZ, last_error TEXT, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, capability, provider, label)
);

CREATE TABLE integration_health_checks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  connection_id UUID NOT NULL REFERENCES integration_connections(id) ON DELETE CASCADE,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), ok BOOLEAN NOT NULL, latency_ms INT, detail TEXT
);

CREATE TABLE data_imports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  entity VARCHAR(60) NOT NULL, file_url TEXT NOT NULL, mapping JSONB, mode VARCHAR(20) NOT NULL DEFAULT 'dry_run', -- dry_run | apply
  status VARCHAR(20) NOT NULL DEFAULT 'uploaded', -- uploaded | validated | applying | applied | failed | rolled_back
  total_rows INT, valid_rows INT, error_rows INT, report JSONB, job_id UUID, requested_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), applied_at TIMESTAMPTZ, rolled_back_at TIMESTAMPTZ
);

CREATE TABLE data_import_rows (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL, import_id UUID NOT NULL REFERENCES data_imports(id) ON DELETE CASCADE,
  row_no INT NOT NULL, raw JSONB NOT NULL, normalized JSONB, errors JSONB, status VARCHAR(20) NOT NULL DEFAULT 'pending', created_entity_id UUID
);

CREATE TABLE consent_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose VARCHAR(40) NOT NULL, -- academic | communication | marketing | health | photo | third_party
  granted BOOLEAN NOT NULL, text_version VARCHAR(20), granted_by_user_id UUID, ip INET, recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), withdrawn_at TIMESTAMPTZ
);

CREATE TABLE data_subject_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id), request_type VARCHAR(20) NOT NULL, -- access | export | correction | erasure
  details TEXT, status VARCHAR(20) NOT NULL DEFAULT 'received', -- received | in_progress | completed | rejected
  due_at TIMESTAMPTZ, handled_by UUID, result_url TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), closed_at TIMESTAMPTZ
);

CREATE TABLE read_only_modes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE, -- NULL = platform-wide
  reason VARCHAR(200), starts_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), ends_at TIMESTAMPTZ, is_active BOOLEAN NOT NULL DEFAULT TRUE, set_by UUID
);

CREATE TABLE help_articles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE, -- NULL = platform article
  slug VARCHAR(120) NOT NULL, title VARCHAR(200) NOT NULL, body TEXT NOT NULL, module VARCHAR(60), audience JSONB, is_published BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, slug)
);

CREATE TABLE feedback_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id), page VARCHAR(200), category VARCHAR(30), rating SMALLINT, message TEXT, screenshot_url TEXT, client VARCHAR(20),
  status VARCHAR(20) NOT NULL DEFAULT 'new', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_logs (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  institution_id UUID, user_id UUID, impersonator_id UUID, module VARCHAR(60) NOT NULL, action VARCHAR(40) NOT NULL,
  record_type VARCHAR(60), record_id UUID, old_values JSONB, new_values JSONB, ip INET, user_agent TEXT, request_id VARCHAR(40),
  prev_hash VARCHAR(64), hash VARCHAR(64) NOT NULL, occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);
CREATE TABLE audit_logs_default PARTITION OF audit_logs DEFAULT;
CREATE INDEX ix_audit_logs_record ON audit_logs (institution_id, record_type, record_id, occurred_at DESC);

-- ===================================== 7. ACADEMIC STRUCTURE =====================================
CREATE TABLE academic_years (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE,
  name VARCHAR(20) NOT NULL, start_date DATE NOT NULL, end_date DATE NOT NULL,
  is_current BOOLEAN NOT NULL DEFAULT FALSE, is_locked BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, name)
);
CREATE UNIQUE INDEX one_current_year ON academic_years (institution_id, COALESCE(college_id, '00000000-0000-0000-0000-000000000000'::uuid)) WHERE is_current;

CREATE TABLE academic_terms (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE,
  academic_year_id UUID NOT NULL REFERENCES academic_years(id) ON DELETE CASCADE,
  name VARCHAR(60) NOT NULL, term_type VARCHAR(20) NOT NULL, -- odd | even | summer | trimester | annual
  sequence SMALLINT NOT NULL, start_date DATE NOT NULL, end_date DATE NOT NULL,
  registration_start DATE, registration_end DATE, add_drop_end DATE, last_instruction_date DATE,
  is_current BOOLEAN NOT NULL DEFAULT FALSE, is_locked BOOLEAN NOT NULL DEFAULT FALSE,
  status VARCHAR(30) NOT NULL DEFAULT 'planned', -- planned | registration | in_progress | exam | result_processing | closed
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, academic_year_id, term_type, sequence)
);

CREATE TABLE grading_scales (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  regulation_id UUID, name VARCHAR(80) NOT NULL, scale_type VARCHAR(20) NOT NULL DEFAULT 'absolute', -- absolute | relative
  ranges JSONB NOT NULL, relative_config JSONB, special_grades JSONB, max_grade_point NUMERIC(3,1) NOT NULL DEFAULT 10,
  is_default BOOLEAN NOT NULL DEFAULT FALSE, is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, name)
);

CREATE TABLE programs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  faculty_id UUID REFERENCES faculties(id) ON DELETE SET NULL,
  department_id UUID NOT NULL REFERENCES departments(id),
  code VARCHAR(30) NOT NULL, name VARCHAR(200) NOT NULL, degree_name VARCHAR(80) NOT NULL, specialization VARCHAR(120),
  level VARCHAR(20) NOT NULL, -- certificate | diploma | ug | pg | pg_diploma | integrated | mphil | phd
  mode VARCHAR(20) NOT NULL DEFAULT 'regular', -- regular | part_time | distance | online
  term_pattern VARCHAR(20) NOT NULL DEFAULT 'semester', duration_years NUMERIC(3,1) NOT NULL, total_terms SMALLINT NOT NULL, max_duration_years NUMERIC(3,1),
  sanctioned_intake SMALLINT, lateral_intake SMALLINT, approving_body VARCHAR(40),
  exam_authority VARCHAR(30) NOT NULL DEFAULT 'autonomous_college', -- university | autonomous_college
  is_nep_multidisciplinary BOOLEAN NOT NULL DEFAULT FALSE, is_open_enrolment BOOLEAN NOT NULL DEFAULT FALSE,
  status VARCHAR(20) NOT NULL DEFAULT 'active', -- draft | active | closed
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, code)
);

CREATE TABLE regulations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE,
  code VARCHAR(20) NOT NULL, name VARCHAR(120) NOT NULL, effective_from_admission_year SMALLINT NOT NULL,
  grading_scale_id UUID REFERENCES grading_scales(id), rules JSONB NOT NULL DEFAULT '{}',
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | approved | active | superseded
  approved_by UUID, approved_at TIMESTAMPTZ, approval_resolution_id UUID, locked_at TIMESTAMPTZ, superseded_by_id UUID REFERENCES regulations(id),
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, code)
);
ALTER TABLE grading_scales ADD CONSTRAINT fk_grading_scales_regulation FOREIGN KEY (regulation_id) REFERENCES regulations(id) ON DELETE SET NULL;

CREATE TABLE program_regulations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  program_id UUID NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
  regulation_id UUID NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  rules_override JSONB, total_credits_required NUMERIC(5,1) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | active | closed
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (program_id, regulation_id)
);

CREATE TABLE program_structure_terms (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  program_regulation_id UUID NOT NULL REFERENCES program_regulations(id) ON DELETE CASCADE,
  term_number SMALLINT NOT NULL, name VARCHAR(60) NOT NULL, min_credits NUMERIC(4,1) NOT NULL, max_credits NUMERIC(4,1) NOT NULL, normal_credits NUMERIC(4,1) NOT NULL,
  is_exit_point BOOLEAN NOT NULL DEFAULT FALSE, exit_award VARCHAR(30),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (program_regulation_id, term_number)
);

CREATE TABLE assessment_schemes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  regulation_id UUID NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  code VARCHAR(30) NOT NULL, name VARCHAR(120) NOT NULL, applies_to_course_types JSONB NOT NULL DEFAULT '[]',
  cia_weight SMALLINT NOT NULL DEFAULT 40, ese_weight SMALLINT NOT NULL DEFAULT 60, cia_max SMALLINT NOT NULL DEFAULT 40, ese_max SMALLINT NOT NULL DEFAULT 60,
  pass_rules JSONB NOT NULL DEFAULT '{}', is_default BOOLEAN NOT NULL DEFAULT FALSE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (regulation_id, code)
);

CREATE TABLE assessment_components (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scheme_id UUID NOT NULL REFERENCES assessment_schemes(id) ON DELETE CASCADE,
  code VARCHAR(20) NOT NULL, name VARCHAR(80) NOT NULL, category VARCHAR(20) NOT NULL, -- cia | ese_theory | ese_practical | viva | project_review
  max_marks SMALLINT NOT NULL, scaled_to NUMERIC(5,2), weight_pct NUMERIC(5,2), best_of JSONB, sequence SMALLINT NOT NULL DEFAULT 1,
  is_mandatory BOOLEAN NOT NULL DEFAULT TRUE, co_mappable BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (scheme_id, code)
);

CREATE TABLE courses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE,
  department_id UUID NOT NULL REFERENCES departments(id),
  regulation_id UUID NOT NULL REFERENCES regulations(id) ON DELETE CASCADE,
  code VARCHAR(30) NOT NULL, title VARCHAR(200) NOT NULL, short_title VARCHAR(60),
  course_type VARCHAR(30) NOT NULL, -- core | program_elective | open_elective | lab | integrated_lab | project | internship | seminar | mooc | audit | mandatory_non_credit | ability_enhancement | skill_enhancement | value_added | minor | honours
  lecture_hours SMALLINT NOT NULL DEFAULT 0, tutorial_hours SMALLINT NOT NULL DEFAULT 0, practical_hours SMALLINT NOT NULL DEFAULT 0,
  credits NUMERIC(4,1) NOT NULL DEFAULT 0, contact_hours_per_week SMALLINT,
  assessment_scheme_id UUID REFERENCES assessment_schemes(id), cia_max SMALLINT, ese_max SMALLINT,
  is_credit_bearing BOOLEAN NOT NULL DEFAULT TRUE, is_gradable BOOLEAN NOT NULL DEFAULT TRUE, min_seats SMALLINT, max_seats SMALLINT,
  syllabus JSONB, textbooks JSONB, references_list JSONB, is_public_catalog BOOLEAN NOT NULL DEFAULT TRUE,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | approved | active | retired
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, regulation_id, code)
);

CREATE TABLE course_prerequisites (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  related_course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  relation VARCHAR(20) NOT NULL, -- prerequisite | corequisite | antirequisite
  min_grade VARCHAR(3), is_hard BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (course_id, related_course_id, relation)
);

CREATE TABLE elective_baskets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  program_regulation_id UUID NOT NULL REFERENCES program_regulations(id) ON DELETE CASCADE,
  code VARCHAR(30) NOT NULL, name VARCHAR(120) NOT NULL, basket_type VARCHAR(20) NOT NULL, -- program_elective | open_elective | minor | honours | mooc | vertical
  term_number SMALLINT, min_choose SMALLINT NOT NULL DEFAULT 1, max_choose SMALLINT NOT NULL DEFAULT 1, credits_required NUMERIC(4,1),
  allocation_mode VARCHAR(20) NOT NULL DEFAULT 'priority_cgpa', -- priority_cgpa | fcfs | lottery | manual
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (program_regulation_id, code)
);

CREATE TABLE elective_basket_courses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  basket_id UUID NOT NULL REFERENCES elective_baskets(id) ON DELETE CASCADE,
  course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  offering_department_id UUID REFERENCES departments(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (basket_id, course_id)
);

CREATE TABLE curriculum_courses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  program_regulation_id UUID NOT NULL REFERENCES program_regulations(id) ON DELETE CASCADE,
  term_number SMALLINT NOT NULL, course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  elective_basket_id UUID REFERENCES elective_baskets(id) ON DELETE SET NULL, is_mandatory BOOLEAN NOT NULL DEFAULT TRUE,
  credit_bucket VARCHAR(30), sequence SMALLINT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (program_regulation_id, term_number, course_id)
);

CREATE TABLE batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  program_id UUID NOT NULL REFERENCES programs(id), program_regulation_id UUID NOT NULL REFERENCES program_regulations(id),
  admission_year SMALLINT NOT NULL, entry_type VARCHAR(20) NOT NULL DEFAULT 'regular', -- regular | lateral
  code VARCHAR(40) NOT NULL, name VARCHAR(120), expected_graduation_year SMALLINT, current_term_number SMALLINT NOT NULL DEFAULT 1,
  status VARCHAR(20) NOT NULL DEFAULT 'active', -- active | graduating | graduated | closed
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, program_id, admission_year, entry_type)
);

CREATE TABLE batch_sections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  batch_id UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
  name VARCHAR(10) NOT NULL, capacity SMALLINT, class_advisor_staff_id UUID,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (batch_id, name)
);

-- ===================================== 8. STUDENTS =====================================
CREATE TABLE students (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  user_id UUID UNIQUE REFERENCES users(id) ON DELETE SET NULL,
  registration_number VARCHAR(30) NOT NULL, enrolment_number VARCHAR(30), apaar_id VARCHAR(20), abc_id VARCHAR(20), aadhaar_encrypted BYTEA,
  first_name VARCHAR(100) NOT NULL, middle_name VARCHAR(100), last_name VARCHAR(100), dob DATE NOT NULL, gender VARCHAR(10) NOT NULL, blood_group VARCHAR(5),
  category VARCHAR(20), sub_category VARCHAR(40), is_pwd BOOLEAN NOT NULL DEFAULT FALSE, pwd_pct SMALLINT, pwd_type VARCHAR(60),
  is_minority BOOLEAN NOT NULL DEFAULT FALSE, minority_type VARCHAR(40), religion VARCHAR(40), nationality VARCHAR(60) NOT NULL DEFAULT 'Indian',
  is_international BOOLEAN NOT NULL DEFAULT FALSE, passport JSONB, visa JSONB, frro JSONB, domicile_state VARCHAR(60), mother_tongue VARCHAR(40),
  photo_url TEXT, phone VARCHAR(20), email VARCHAR(200), permanent_address JSONB, current_address JSONB, bank_details_encrypted BYTEA,
  guardian_portal_consent BOOLEAN NOT NULL DEFAULT TRUE, admission_quota VARCHAR(30), admission_mode VARCHAR(30), admission_date DATE,
  status VARCHAR(20) NOT NULL DEFAULT 'provisional', -- provisional | admitted | active | on_break | detained | dropped_out | transferred | exited | graduated | alumni | expelled | deceased
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, registration_number)
);
CREATE UNIQUE INDEX uq_student_apaar ON students (institution_id, apaar_id) WHERE apaar_id IS NOT NULL;
CREATE INDEX ix_students_name_trgm ON students USING gin ((first_name || ' ' || COALESCE(last_name, '')) gin_trgm_ops);

CREATE TABLE student_guardians (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  relation VARCHAR(20) NOT NULL, -- father | mother | guardian | spouse | other
  name VARCHAR(200) NOT NULL, phone VARCHAR(20), email VARCHAR(200), occupation VARCHAR(100), annual_income_paise BIGINT, address JSONB,
  is_primary BOOLEAN NOT NULL DEFAULT FALSE, portal_access BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (student_id, relation, name)
);

CREATE TABLE student_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  doc_type VARCHAR(60) NOT NULL, file_url TEXT NOT NULL, verified_by UUID, verified_at TIMESTAMPTZ, expires_on DATE, remarks TEXT,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE student_undertakings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  undertaking_type VARCHAR(30) NOT NULL, -- anti_ragging | conduct | hostel_rules | data_consent | photo_consent | custom
  template_id UUID, accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), ip INET, user_agent TEXT, signature_url TEXT,
  UNIQUE (student_id, undertaking_type, template_id)
);

CREATE TABLE student_program_enrollments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  program_id UUID NOT NULL REFERENCES programs(id), batch_id UUID NOT NULL REFERENCES batches(id),
  program_regulation_id UUID NOT NULL REFERENCES program_regulations(id), department_id UUID NOT NULL REFERENCES departments(id),
  admission_date DATE NOT NULL, entry_type VARCHAR(20) NOT NULL DEFAULT 'regular', -- regular | lateral | migrated | readmission | exit_reentry
  entry_term_number SMALLINT NOT NULL DEFAULT 1, specialization VARCHAR(120), minor_program_id UUID REFERENCES programs(id), is_honours BOOLEAN NOT NULL DEFAULT FALSE,
  expected_exit_term SMALLINT, status VARCHAR(20) NOT NULL DEFAULT 'active', -- active | break | detained | completed | exited_early | withdrawn | transferred | expelled
  exit_award VARCHAR(30), exit_date DATE, credits_earned NUMERIC(6,1) NOT NULL DEFAULT 0, cgpa NUMERIC(4,2),
  academic_standing VARCHAR(20) NOT NULL DEFAULT 'good', -- good | warning | probation | dismissal
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (student_id, program_id, batch_id)
);
CREATE UNIQUE INDEX one_active_enrollment ON student_program_enrollments (student_id) WHERE status IN ('active','break','detained');

CREATE TABLE student_term_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  term_id UUID NOT NULL REFERENCES academic_terms(id), term_number SMALLINT NOT NULL,
  section_id UUID REFERENCES batch_sections(id) ON DELETE SET NULL, roll_number VARCHAR(20),
  status VARCHAR(30) NOT NULL DEFAULT 'pending_registration', -- pending_registration | registered | in_progress | exam_pending | completed | detained | on_break | withdrawn
  credits_registered NUMERIC(5,1) NOT NULL DEFAULT 0, credits_earned NUMERIC(5,1) NOT NULL DEFAULT 0, sgpa NUMERIC(4,2), cgpa NUMERIC(4,2), attendance_pct NUMERIC(5,2), result_status VARCHAR(20),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (student_program_enrollment_id, term_id)
);

CREATE TABLE student_holds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  hold_type VARCHAR(20) NOT NULL, -- registration | exam | transcript | graduation | hostel | library | all
  reason TEXT NOT NULL, placed_by UUID NOT NULL, placed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), released_by UUID, released_at TIMESTAMPTZ,
  source_type VARCHAR(40), source_id UUID
);
CREATE INDEX ix_student_holds_open ON student_holds (student_program_enrollment_id) WHERE released_at IS NULL;

CREATE TABLE student_transfers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  transfer_type VARCHAR(30) NOT NULL, -- migration_in | migration_out | inter_college | program_change | inter_university
  from_ref JSONB, to_ref JSONB, migration_certificate_no VARCHAR(50), tc_no VARCHAR(50), reason TEXT, requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  approved_by UUID, effective_date DATE, status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | dues_check | approved | rejected | completed
  fee_invoice_id UUID, workflow_instance_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE credit_transfers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  term_id UUID REFERENCES academic_terms(id),
  source VARCHAR(30) NOT NULL, -- swayam | nptel | coursera | other_mooc | abc | other_university | prior_learning | internal_prior
  source_course_code VARCHAR(40), source_title VARCHAR(200) NOT NULL, source_institution VARCHAR(200), credits NUMERIC(4,1) NOT NULL, source_grade VARCHAR(10), source_score_pct NUMERIC(5,2),
  equivalent_course_id UUID REFERENCES courses(id), elective_basket_id UUID REFERENCES elective_baskets(id), certificate_url TEXT, abc_credit_ref VARCHAR(60),
  status VARCHAR(20) NOT NULL DEFAULT 'submitted', -- submitted | verified | approved | rejected | credited
  approved_by UUID, approved_at TIMESTAMPTZ, result_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 9. HR =====================================
CREATE TABLE designations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL, code VARCHAR(20), cadre VARCHAR(30), category VARCHAR(20) NOT NULL DEFAULT 'teaching', -- teaching | non_teaching | administrative
  level SMALLINT, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, name)
);

CREATE TABLE staff (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE SET NULL,
  user_id UUID UNIQUE REFERENCES users(id) ON DELETE SET NULL,
  employee_id VARCHAR(30) NOT NULL, department_id UUID REFERENCES departments(id), designation_id UUID REFERENCES designations(id),
  first_name VARCHAR(100) NOT NULL, middle_name VARCHAR(100), last_name VARCHAR(100), dob DATE, gender VARCHAR(10), blood_group VARCHAR(5),
  phone VARCHAR(20), email VARCHAR(200), photo_url TEXT, address JSONB, emergency_contact JSONB,
  employment_type VARCHAR(20) NOT NULL DEFAULT 'regular', -- regular | contract | guest | visiting | adjunct | outsourced
  staff_category VARCHAR(20) NOT NULL DEFAULT 'teaching', joining_date DATE, confirmation_date DATE, retirement_date DATE, exit_date DATE, exit_reason TEXT,
  pan_encrypted BYTEA, aadhaar_encrypted BYTEA, bank_details_encrypted BYTEA, pf_number VARCHAR(30), esi_number VARCHAR(30), uan VARCHAR(20),
  hourly_rate_paise INTEGER, reports_to_staff_id UUID REFERENCES staff(id),
  status VARCHAR(20) NOT NULL DEFAULT 'active', -- active | on_leave | suspended | exited
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, employee_id)
);

CREATE TABLE staff_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  doc_type VARCHAR(60) NOT NULL, file_url TEXT NOT NULL, expires_on DATE, verified_by UUID, verified_at TIMESTAMPTZ, uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE service_book_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  entry_type VARCHAR(30) NOT NULL, -- joining | promotion | increment | transfer | award | disciplinary | leave_without_pay | exit
  effective_date DATE NOT NULL, details JSONB, document_url TEXT, recorded_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE faculty_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL UNIQUE REFERENCES staff(id) ON DELETE CASCADE,
  aicte_faculty_id VARCHAR(30), orcid VARCHAR(20), scopus_id VARCHAR(20), google_scholar_id VARCHAR(30), vidwan_id VARCHAR(20),
  highest_qualification VARCHAR(60), is_phd BOOLEAN NOT NULL DEFAULT FALSE, phd_year SMALLINT, is_phd_guide BOOLEAN NOT NULL DEFAULT FALSE, guide_recognition_no VARCHAR(40), max_scholars SMALLINT,
  experience_teaching_months SMALLINT NOT NULL DEFAULT 0, experience_industry_months SMALLINT NOT NULL DEFAULT 0, experience_research_months SMALLINT NOT NULL DEFAULT 0,
  specializations JSONB, api_score NUMERIC(6,2), api_updated_at TIMESTAMPTZ, cadre VARCHAR(20), -- professor | associate | assistant | lecturer | adjunct | visiting | guest
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE faculty_qualifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  degree VARCHAR(60) NOT NULL, discipline VARCHAR(120), university VARCHAR(200), year SMALLINT, is_highest BOOLEAN NOT NULL DEFAULT FALSE, certificate_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE leave_types (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  code VARCHAR(10) NOT NULL, name VARCHAR(80) NOT NULL, annual_quota NUMERIC(5,1), accrual VARCHAR(20) NOT NULL DEFAULT 'yearly', -- yearly | monthly | none
  carry_forward_max NUMERIC(5,1), is_paid BOOLEAN NOT NULL DEFAULT TRUE, is_encashable BOOLEAN NOT NULL DEFAULT FALSE, requires_document BOOLEAN NOT NULL DEFAULT FALSE,
  applies_to JSONB, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, code)
);

CREATE TABLE staff_leaves (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE, leave_type_id UUID NOT NULL REFERENCES leave_types(id),
  from_date DATE NOT NULL, to_date DATE NOT NULL, days_count NUMERIC(4,1) NOT NULL, half_day VARCHAR(10), reason TEXT, document_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | approved | rejected | cancelled
  reviewed_by UUID, reviewed_at TIMESTAMPTZ, review_comment TEXT, workflow_instance_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE staff_leave_balances (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE, leave_type_id UUID NOT NULL REFERENCES leave_types(id), year SMALLINT NOT NULL,
  opening NUMERIC(5,1) NOT NULL DEFAULT 0, accrued NUMERIC(5,1) NOT NULL DEFAULT 0, used NUMERIC(5,1) NOT NULL DEFAULT 0, encashed NUMERIC(5,1) NOT NULL DEFAULT 0, balance NUMERIC(5,1) NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (staff_id, leave_type_id, year)
);

CREATE TABLE attendance_devices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), name VARCHAR(100) NOT NULL, device_type VARCHAR(20) NOT NULL, -- biometric | rfid | qr_kiosk
  serial_no VARCHAR(80), location VARCHAR(120), token_hash VARCHAR(64) NOT NULL UNIQUE, applies_to VARCHAR(20) NOT NULL DEFAULT 'staff', -- staff | students | both
  last_seen_at TIMESTAMPTZ, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE staff_attendance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE, attendance_date DATE NOT NULL,
  status VARCHAR(20) NOT NULL, -- present | absent | half_day | on_leave | on_duty | holiday | week_off
  check_in_time TIMESTAMPTZ, check_out_time TIMESTAMPTZ, source VARCHAR(20) NOT NULL DEFAULT 'manual', -- manual | biometric | self_checkin | geo | import
  device_id UUID REFERENCES attendance_devices(id), geo JSONB, remarks TEXT, marked_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (staff_id, attendance_date)
);

CREATE TABLE payroll_components (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  code VARCHAR(20) NOT NULL, name VARCHAR(80) NOT NULL, component_type VARCHAR(30) NOT NULL, -- earning | deduction | employer_contribution | reimbursement
  calc_type VARCHAR(20) NOT NULL DEFAULT 'fixed', -- fixed | pct_of_basic | formula | statutory
  formula JSONB, is_statutory BOOLEAN NOT NULL DEFAULT FALSE, statutory_kind VARCHAR(20), -- pf | esi | pt | tds | lwf
  is_taxable BOOLEAN NOT NULL DEFAULT TRUE, sequence SMALLINT NOT NULL DEFAULT 1, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, code)
);

CREATE TABLE staff_salary_structures (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE, effective_from DATE NOT NULL, effective_to DATE,
  pay_level VARCHAR(20), basic_paise INTEGER NOT NULL, components JSONB NOT NULL, ctc_paise INTEGER, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE staff_payrolls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE, month SMALLINT NOT NULL, year SMALLINT NOT NULL,
  working_days SMALLINT, paid_days NUMERIC(4,1), lop_days NUMERIC(4,1) NOT NULL DEFAULT 0,
  gross_paise INTEGER NOT NULL, deductions_paise INTEGER NOT NULL DEFAULT 0, employer_contrib_paise INTEGER NOT NULL DEFAULT 0, net_paise INTEGER NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | approved | paid | cancelled
  approved_by UUID, approved_at TIMESTAMPTZ, paid_at TIMESTAMPTZ, payment_ref VARCHAR(60), payslip_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (staff_id, month, year)
);

CREATE TABLE staff_payroll_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  payroll_id UUID NOT NULL REFERENCES staff_payrolls(id) ON DELETE CASCADE,
  component_id UUID REFERENCES payroll_components(id), label VARCHAR(80) NOT NULL, component_type VARCHAR(30) NOT NULL, amount_paise INTEGER NOT NULL,
  source_type VARCHAR(40), source_id UUID -- exam remuneration | guest lecture | loan EMI | fellowship
);

CREATE TABLE loans_advances (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  loan_type VARCHAR(30) NOT NULL, -- festival | vehicle | housing | salary_advance | computer
  principal_paise INTEGER NOT NULL, emi_paise INTEGER NOT NULL, start_month DATE NOT NULL, balance_paise INTEGER NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active', workflow_instance_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE job_postings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), department_id UUID REFERENCES departments(id),
  title VARCHAR(200) NOT NULL, cadre VARCHAR(30), vacancies SMALLINT NOT NULL DEFAULT 1, reservation JSONB, qualifications JSONB, description TEXT,
  opens_at TIMESTAMPTZ, closes_at TIMESTAMPTZ, status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | open | closed | filled | cancelled
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE job_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  posting_id UUID NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
  applicant JSONB NOT NULL, documents JSONB, category VARCHAR(20), api_score NUMERIC(6,2), screening_score NUMERIC(6,2),
  status VARCHAR(20) NOT NULL DEFAULT 'applied', -- applied | screened | shortlisted | interviewed | selected | offered | joined | rejected
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE interview_panels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  posting_id UUID NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
  scheduled_at TIMESTAMPTZ NOT NULL, venue VARCHAR(200), members JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE interview_scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  panel_id UUID NOT NULL REFERENCES interview_panels(id) ON DELETE CASCADE, application_id UUID NOT NULL REFERENCES job_applications(id) ON DELETE CASCADE,
  scores JSONB NOT NULL, total NUMERIC(6,2), remarks TEXT, recorded_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (panel_id, application_id)
);

CREATE TABLE appraisals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE, academic_year_id UUID NOT NULL REFERENCES academic_years(id),
  self_assessment JSONB, self_score NUMERIC(6,2), reviewer_staff_id UUID REFERENCES staff(id), reviewer_score NUMERIC(6,2), final_score NUMERIC(6,2),
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | submitted | reviewed | approved
  workflow_instance_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (staff_id, academic_year_id)
);

CREATE TABLE cas_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  from_cadre VARCHAR(30) NOT NULL, to_cadre VARCHAR(30) NOT NULL, eligibility_date DATE, api_breakdown JSONB, documents JSONB,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | submitted | screened | interviewed | approved | rejected
  workflow_instance_id UUID, decided_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE faculty_workloads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE, term_id UUID NOT NULL REFERENCES academic_terms(id),
  theory_hours NUMERIC(4,1) NOT NULL DEFAULT 0, tutorial_hours NUMERIC(4,1) NOT NULL DEFAULT 0, lab_hours NUMERIC(4,1) NOT NULL DEFAULT 0, project_hours NUMERIC(4,1) NOT NULL DEFAULT 0,
  admin_hours NUMERIC(4,1) NOT NULL DEFAULT 0, research_hours NUMERIC(4,1) NOT NULL DEFAULT 0, total_hours NUMERIC(4,1) NOT NULL DEFAULT 0, max_allowed_hours NUMERIC(4,1),
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | hod_approved | dean_approved
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (staff_id, term_id)
);

CREATE TABLE course_allocation_proposals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  department_id UUID NOT NULL REFERENCES departments(id), term_id UUID NOT NULL REFERENCES academic_terms(id),
  proposals JSONB NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | submitted | dean_approved | applied
  submitted_by UUID, approved_by UUID, workflow_instance_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (department_id, term_id)
);

-- ===================================== 10. ADMISSIONS =====================================
CREATE TABLE admission_cycles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE,
  academic_year_id UUID NOT NULL REFERENCES academic_years(id),
  name VARCHAR(120) NOT NULL, slug VARCHAR(60) NOT NULL, level VARCHAR(20) NOT NULL, -- ug | pg | phd | diploma | lateral | certificate
  application_fee_paise INTEGER NOT NULL DEFAULT 0, opens_at TIMESTAMPTZ, closes_at TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | open | closed | merit_processing | counselling | completed | archived
  form_config JSONB, required_documents JSONB, de_reservation_policy JSONB,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, slug)
);

CREATE TABLE admission_cycle_programs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  cycle_id UUID NOT NULL REFERENCES admission_cycles(id) ON DELETE CASCADE,
  program_id UUID NOT NULL REFERENCES programs(id), college_id UUID NOT NULL REFERENCES colleges(id),
  intake SMALLINT NOT NULL, lateral_intake SMALLINT NOT NULL DEFAULT 0,
  entrance_source VARCHAR(30) NOT NULL DEFAULT 'merit_only', -- jee | neet | cuet | state_cet | gate | cat | institution_test | merit_only
  eligibility_rules JSONB, merit_formula JSONB, tie_break JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (cycle_id, program_id, college_id)
);

CREATE TABLE seat_matrix (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  cycle_id UUID NOT NULL REFERENCES admission_cycles(id) ON DELETE CASCADE,
  program_id UUID NOT NULL REFERENCES programs(id), college_id UUID NOT NULL REFERENCES colleges(id),
  quota VARCHAR(30) NOT NULL, category VARCHAR(20) NOT NULL, seats SMALLINT NOT NULL, filled SMALLINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (cycle_id, program_id, college_id, quota, category)
);

CREATE TABLE applicants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  cycle_id UUID NOT NULL REFERENCES admission_cycles(id) ON DELETE CASCADE,
  application_number VARCHAR(30) NOT NULL, user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  first_name VARCHAR(100) NOT NULL, middle_name VARCHAR(100), last_name VARCHAR(100), dob DATE, gender VARCHAR(10), category VARCHAR(20), is_pwd BOOLEAN NOT NULL DEFAULT FALSE,
  quota_claimed VARCHAR(30), nationality VARCHAR(60), domicile_state VARCHAR(60), contact JSONB, entrance JSONB, qualifying_exams JSONB, documents JSONB,
  merit_score NUMERIC(8,3), status VARCHAR(30) NOT NULL DEFAULT 'draft', application_fee_invoice_id UUID, admitted_student_id UUID REFERENCES students(id),
  entry_type VARCHAR(20) NOT NULL DEFAULT 'regular', -- regular | lateral | migration
  source VARCHAR(30) NOT NULL DEFAULT 'online', -- online | offline | counselling_import
  remarks TEXT, submitted_at TIMESTAMPTZ,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, application_number)
);

CREATE TABLE applicant_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  applicant_id UUID NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
  program_id UUID NOT NULL REFERENCES programs(id), college_id UUID NOT NULL REFERENCES colleges(id), priority SMALLINT NOT NULL,
  UNIQUE (applicant_id, priority)
);

CREATE TABLE applicant_document_verifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  applicant_id UUID NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
  doc_type VARCHAR(60) NOT NULL, file_url TEXT, status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | verified | rejected | resubmit
  verified_by UUID, verified_at TIMESTAMPTZ, remarks TEXT, UNIQUE (applicant_id, doc_type)
);

CREATE TABLE merit_lists (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  cycle_id UUID NOT NULL REFERENCES admission_cycles(id) ON DELETE CASCADE,
  program_id UUID REFERENCES programs(id), college_id UUID REFERENCES colleges(id), name VARCHAR(160) NOT NULL, quota VARCHAR(30), category VARCHAR(20),
  formula_snapshot JSONB, status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | published | superseded
  generated_at TIMESTAMPTZ, published_at TIMESTAMPTZ, job_id UUID, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE merit_list_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  merit_list_id UUID NOT NULL REFERENCES merit_lists(id) ON DELETE CASCADE, applicant_id UUID NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
  rank INT NOT NULL, category_rank INT, score NUMERIC(8,3), tie_break JSONB, UNIQUE (merit_list_id, applicant_id)
);

CREATE TABLE counselling_rounds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  cycle_id UUID NOT NULL REFERENCES admission_cycles(id) ON DELETE CASCADE,
  round_number SMALLINT NOT NULL, name VARCHAR(80), choice_filling_start TIMESTAMPTZ, choice_filling_end TIMESTAMPTZ, allotment_at TIMESTAMPTZ, reporting_deadline TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'planned', -- planned | choice_filling | allotted | reporting | closed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (cycle_id, round_number)
);

CREATE TABLE seat_allotments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  round_id UUID NOT NULL REFERENCES counselling_rounds(id) ON DELETE CASCADE, applicant_id UUID NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
  program_id UUID NOT NULL REFERENCES programs(id), college_id UUID NOT NULL REFERENCES colleges(id), seat_matrix_id UUID NOT NULL REFERENCES seat_matrix(id),
  quota VARCHAR(30) NOT NULL, category VARCHAR(20) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'allotted', -- allotted | accepted | float | freeze | upgraded | declined | lapsed | admitted
  admission_fee_paise INTEGER, fee_invoice_id UUID, accepted_at TIMESTAMPTZ, reported_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (round_id, applicant_id)
);

CREATE TABLE admission_offers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  applicant_id UUID NOT NULL REFERENCES applicants(id) ON DELETE CASCADE, program_id UUID NOT NULL REFERENCES programs(id), college_id UUID NOT NULL REFERENCES colleges(id),
  offer_type VARCHAR(20) NOT NULL DEFAULT 'provisional', -- provisional | confirmed
  valid_until DATE, conditions JSONB, letter_url TEXT, status VARCHAR(20) NOT NULL DEFAULT 'issued', -- issued | accepted | expired | withdrawn
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE enquiries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), source VARCHAR(20) NOT NULL DEFAULT 'web', -- walk_in | web | phone | referral | event | agent
  name VARCHAR(200) NOT NULL, phone VARCHAR(20), email VARCHAR(200), program_interest JSONB, stage VARCHAR(20) NOT NULL DEFAULT 'new', -- new | contacted | counselled | applied | admitted | lost
  assigned_to UUID, follow_up_on DATE, notes JSONB, applicant_id UUID REFERENCES applicants(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 11. OFFERINGS & REGISTRATION =====================================
CREATE TABLE course_offerings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  term_id UUID NOT NULL REFERENCES academic_terms(id), course_id UUID NOT NULL REFERENCES courses(id), department_id UUID NOT NULL REFERENCES departments(id),
  section_code VARCHAR(20) NOT NULL DEFAULT 'A', coordinator_staff_id UUID REFERENCES staff(id),
  max_seats SMALLINT, enrolled_count SMALLINT NOT NULL DEFAULT 0, waitlist_count SMALLINT NOT NULL DEFAULT 0,
  delivery_mode VARCHAR(20) NOT NULL DEFAULT 'offline', -- offline | online | hybrid
  online_class_link TEXT, assessment_scheme_id UUID REFERENCES assessment_schemes(id), is_arrear_only BOOLEAN NOT NULL DEFAULT FALSE,
  status VARCHAR(20) NOT NULL DEFAULT 'planned', -- planned | open | closed | in_progress | marks_entry | completed | cancelled
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, term_id, course_id, section_code)
);

CREATE TABLE course_offering_faculty (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
  role VARCHAR(20) NOT NULL DEFAULT 'instructor', -- coordinator | instructor | lab_instructor | teaching_assistant
  hours_per_week SMALLINT NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (offering_id, staff_id, role)
);

CREATE TABLE course_offering_targets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, batch_id UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
  section_id UUID REFERENCES batch_sections(id) ON DELETE CASCADE, term_number SMALLINT NOT NULL, UNIQUE (offering_id, batch_id, section_id)
);

CREATE TABLE registration_windows (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE, term_id UUID NOT NULL REFERENCES academic_terms(id),
  name VARCHAR(120) NOT NULL, window_type VARCHAR(20) NOT NULL, -- regular | add_drop | late | arrear | summer | audit | minor_honours
  applies_to JSONB, starts_at TIMESTAMPTZ NOT NULL, ends_at TIMESTAMPTZ NOT NULL, late_fee_paise INTEGER NOT NULL DEFAULT 0,
  requires_advisor_approval BOOLEAN NOT NULL DEFAULT TRUE, requires_fee_clearance BOOLEAN NOT NULL DEFAULT FALSE, max_credits_override NUMERIC(4,1),
  status VARCHAR(20) NOT NULL DEFAULT 'scheduled', -- scheduled | open | closed
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE course_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  term_id UUID NOT NULL REFERENCES academic_terms(id), student_term_record_id UUID NOT NULL REFERENCES student_term_records(id), window_id UUID REFERENCES registration_windows(id),
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | submitted | advisor_pending | approved | changes_requested | rejected | locked
  total_credits NUMERIC(4,1) NOT NULL DEFAULT 0, fee_invoice_id UUID, submitted_at TIMESTAMPTZ, approved_by UUID, approved_at TIMESTAMPTZ, locked_at TIMESTAMPTZ, workflow_instance_id UUID,
  version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (student_program_enrollment_id, term_id)
);

CREATE TABLE course_registration_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  registration_id UUID NOT NULL REFERENCES course_registrations(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id), course_id UUID NOT NULL REFERENCES courses(id),
  registration_type VARCHAR(20) NOT NULL DEFAULT 'regular', -- regular | arrear | improvement | audit | minor | honours | re_registration | mooc
  attempt_number SMALLINT NOT NULL DEFAULT 1, priority SMALLINT,
  status VARCHAR(20) NOT NULL DEFAULT 'selected', -- selected | waitlisted | confirmed | dropped | withdrawn | rejected | substituted
  is_credit_bearing BOOLEAN NOT NULL DEFAULT TRUE, added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), dropped_at TIMESTAMPTZ, drop_reason TEXT, prerequisite_override_by UUID,
  UNIQUE (registration_id, offering_id)
);

CREATE TABLE elective_choice_forms (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  elective_basket_id UUID NOT NULL REFERENCES elective_baskets(id) ON DELETE CASCADE, term_id UUID NOT NULL REFERENCES academic_terms(id),
  choices JSONB NOT NULL, allocated_course_id UUID REFERENCES courses(id), allocation_run_id UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'submitted', -- submitted | allocated | unallocated | manual
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (student_program_enrollment_id, elective_basket_id, term_id)
);

CREATE TABLE elective_allocation_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  elective_basket_id UUID NOT NULL REFERENCES elective_baskets(id) ON DELETE CASCADE, term_id UUID NOT NULL REFERENCES academic_terms(id),
  mode VARCHAR(20) NOT NULL, params JSONB, run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), run_by UUID, summary JSONB, job_id UUID
);
ALTER TABLE elective_choice_forms ADD CONSTRAINT fk_choice_forms_run FOREIGN KEY (allocation_run_id) REFERENCES elective_allocation_runs(id) ON DELETE SET NULL;

CREATE TABLE offering_waitlists (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  position SMALLINT NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'waiting', -- waiting | offered | promoted | expired | cancelled
  offered_until TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (offering_id, student_program_enrollment_id)
);

CREATE TABLE student_arrears (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  course_id UUID NOT NULL REFERENCES courses(id), first_failed_term_id UUID REFERENCES academic_terms(id), last_attempt_term_id UUID REFERENCES academic_terms(id),
  attempts SMALLINT NOT NULL DEFAULT 1, status VARCHAR(20) NOT NULL DEFAULT 'open', -- open | registered | cleared | waived
  cleared_result_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (student_program_enrollment_id, course_id)
);

-- ===================================== 12. TIMETABLE & ATTENDANCE =====================================
CREATE TABLE buildings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  code VARCHAR(20) NOT NULL, name VARCHAR(120) NOT NULL, address JSONB, floors SMALLINT, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, college_id, code)
);

CREATE TABLE rooms (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE, building_id UUID REFERENCES buildings(id) ON DELETE SET NULL,
  code VARCHAR(20) NOT NULL, name VARCHAR(120) NOT NULL, room_type VARCHAR(20) NOT NULL DEFAULT 'classroom', -- classroom | lab | seminar | auditorium | exam_hall | smart_class | sports | other
  floor SMALLINT, capacity SMALLINT NOT NULL DEFAULT 0, exam_capacity SMALLINT, features JSONB, is_bookable BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, code)
);

CREATE TABLE time_slots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  slot_group VARCHAR(40) NOT NULL DEFAULT 'Default', name VARCHAR(20) NOT NULL, sequence SMALLINT NOT NULL, start_time TIME NOT NULL, end_time TIME NOT NULL,
  slot_type VARCHAR(20) NOT NULL DEFAULT 'lecture', -- lecture | lab | break | lunch
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, college_id, slot_group, name)
);

CREATE TABLE timetables (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE, term_id UUID NOT NULL REFERENCES academic_terms(id),
  scope_type VARCHAR(20) NOT NULL, -- section | batch | department
  scope_id UUID NOT NULL, name VARCHAR(120), version SMALLINT NOT NULL DEFAULT 1, status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | published | archived
  effective_from DATE, published_by UUID, published_at TIMESTAMPTZ, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (term_id, scope_type, scope_id, version)
);

CREATE TABLE timetable_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  timetable_id UUID NOT NULL REFERENCES timetables(id) ON DELETE CASCADE, term_id UUID NOT NULL REFERENCES academic_terms(id),
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, section_id UUID REFERENCES batch_sections(id),
  day_of_week SMALLINT NOT NULL, time_slot_id UUID NOT NULL REFERENCES time_slots(id), room_id UUID REFERENCES rooms(id), staff_id UUID REFERENCES staff(id),
  session_type VARCHAR(20) NOT NULL DEFAULT 'lecture', -- lecture | tutorial | lab | project
  week_pattern VARCHAR(10) NOT NULL DEFAULT 'all', -- all | odd | even
  slot_span SMALLINT NOT NULL DEFAULT 1, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX uq_tt_room ON timetable_entries (term_id, room_id, day_of_week, time_slot_id, week_pattern) WHERE is_active AND room_id IS NOT NULL;
CREATE UNIQUE INDEX uq_tt_staff ON timetable_entries (term_id, staff_id, day_of_week, time_slot_id, week_pattern) WHERE is_active AND staff_id IS NOT NULL;
CREATE UNIQUE INDEX uq_tt_section ON timetable_entries (term_id, section_id, day_of_week, time_slot_id, week_pattern) WHERE is_active AND section_id IS NOT NULL;

CREATE TABLE timetable_substitutions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  timetable_entry_id UUID NOT NULL REFERENCES timetable_entries(id) ON DELETE CASCADE, on_date DATE NOT NULL,
  substitute_staff_id UUID REFERENCES staff(id), reason TEXT, source VARCHAR(20) NOT NULL DEFAULT 'manual', -- manual | leave_auto
  status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | approved | rejected
  approved_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (timetable_entry_id, on_date)
);

CREATE TABLE class_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE, term_id UUID NOT NULL REFERENCES academic_terms(id),
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, timetable_entry_id UUID REFERENCES timetable_entries(id) ON DELETE SET NULL,
  session_date DATE NOT NULL, time_slot_id UUID REFERENCES time_slots(id), start_time TIME NOT NULL, end_time TIME NOT NULL, staff_id UUID REFERENCES staff(id),
  session_type VARCHAR(20) NOT NULL DEFAULT 'lecture', topic VARCHAR(255), lesson_plan_item_id UUID, online_link TEXT, room_id UUID REFERENCES rooms(id),
  status VARCHAR(20) NOT NULL DEFAULT 'scheduled', -- scheduled | conducted | cancelled | rescheduled
  attendance_status VARCHAR(20) NOT NULL DEFAULT 'not_taken', -- not_taken | taken | finalized
  attendance_taken_at TIMESTAMPTZ, finalized_at TIMESTAMPTZ, finalized_by UUID, qr_token VARCHAR(64), qr_expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (offering_id, session_date, start_time)
);
CREATE INDEX ix_class_sessions_staff_date ON class_sessions (staff_id, session_date);

CREATE TABLE student_class_attendance (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL, session_id UUID NOT NULL REFERENCES class_sessions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  session_date DATE NOT NULL, status VARCHAR(20) NOT NULL, -- present | absent | late | on_duty | leave | medical | exempt
  source VARCHAR(20) NOT NULL DEFAULT 'manual', -- manual | biometric | qr | app | rfid
  marked_by UUID, marked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), remarks VARCHAR(255),
  PRIMARY KEY (id, session_date), UNIQUE (session_id, student_program_enrollment_id, session_date)
) PARTITION BY RANGE (session_date);
CREATE TABLE student_class_attendance_default PARTITION OF student_class_attendance DEFAULT;
CREATE INDEX ix_sca_student ON student_class_attendance (student_program_enrollment_id, session_date);

CREATE TABLE on_duty_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  from_date DATE NOT NULL, to_date DATE NOT NULL, reason_type VARCHAR(20) NOT NULL, -- sports | nss | ncc | placement | conference | other
  reason TEXT, documents JSONB, recommended_by UUID, approved_by UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | recommended | approved | rejected
  sessions_applied JSONB, workflow_instance_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE attendance_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  total_sessions SMALLINT NOT NULL DEFAULT 0, present SMALLINT NOT NULL DEFAULT 0, absent SMALLINT NOT NULL DEFAULT 0, on_duty SMALLINT NOT NULL DEFAULT 0, late SMALLINT NOT NULL DEFAULT 0, exempt SMALLINT NOT NULL DEFAULT 0,
  pct NUMERIC(5,2) NOT NULL DEFAULT 0, eligibility VARCHAR(20) NOT NULL DEFAULT 'eligible', -- eligible | condonable | not_eligible | condoned
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (offering_id, student_program_enrollment_id)
);

CREATE TABLE attendance_condonations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  term_id UUID NOT NULL REFERENCES academic_terms(id), offering_id UUID REFERENCES course_offerings(id), actual_pct NUMERIC(5,2) NOT NULL,
  reason_type VARCHAR(20) NOT NULL, -- medical | sports | bereavement | other
  reason TEXT, documents JSONB, fee_invoice_id UUID, workflow_instance_id UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | hod_recommended | approved | rejected
  approved_by UUID, approved_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE term_eligibility (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_term_record_id UUID NOT NULL REFERENCES student_term_records(id) ON DELETE CASCADE, offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
  attendance_pct NUMERIC(5,2), cia_marks NUMERIC(6,2), cia_max NUMERIC(6,2),
  is_attendance_ok BOOLEAN NOT NULL DEFAULT TRUE, is_cia_ok BOOLEAN NOT NULL DEFAULT TRUE, is_fee_ok BOOLEAN NOT NULL DEFAULT TRUE, is_hold_ok BOOLEAN NOT NULL DEFAULT TRUE,
  decision VARCHAR(20) NOT NULL DEFAULT 'pending', -- eligible | detained | condoned | debarred | pending
  reason_codes JSONB, decided_by UUID, decided_at TIMESTAMPTZ, version SMALLINT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (student_term_record_id, offering_id, version)
);

-- ===================================== 13. FEES & SCHOLARSHIPS =====================================
CREATE TABLE fee_heads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  code VARCHAR(20) NOT NULL, name VARCHAR(100) NOT NULL, head_type VARCHAR(30) NOT NULL DEFAULT 'tuition', -- tuition | admission | exam | hostel | mess | transport | library | lab | caution_deposit | fine | certificate | reval | condonation | convocation | affiliation | other
  is_refundable BOOLEAN NOT NULL DEFAULT FALSE, is_taxable BOOLEAN NOT NULL DEFAULT FALSE, gst_rate NUMERIC(4,2), ledger_account_id UUID,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, code)
);

CREATE TABLE fee_structures (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE, academic_year_id UUID REFERENCES academic_years(id),
  program_id UUID REFERENCES programs(id), program_regulation_id UUID REFERENCES program_regulations(id), batch_id UUID REFERENCES batches(id),
  term_number SMALLINT, category VARCHAR(20), quota VARCHAR(30), name VARCHAR(160) NOT NULL,
  effective_from DATE NOT NULL, effective_to DATE, total_paise INTEGER NOT NULL DEFAULT 0, per_credit_paise INTEGER,
  status VARCHAR(20) NOT NULL DEFAULT 'active', is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID
);

CREATE TABLE fee_structure_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  structure_id UUID NOT NULL REFERENCES fee_structures(id) ON DELETE CASCADE, fee_head_id UUID NOT NULL REFERENCES fee_heads(id),
  amount_paise INTEGER NOT NULL, instalment_no SMALLINT NOT NULL DEFAULT 1, due_date DATE, due_offset_days SMALLINT, is_optional BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (structure_id, fee_head_id, instalment_no)
);

CREATE TABLE fee_discounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  code VARCHAR(20) NOT NULL, name VARCHAR(120) NOT NULL, discount_type VARCHAR(20) NOT NULL, -- percentage | fixed
  value NUMERIC(10,2) NOT NULL, applies_to_heads JSONB, eligibility_rules JSONB, requires_approval BOOLEAN NOT NULL DEFAULT TRUE, max_per_year SMALLINT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, code)
);

CREATE TABLE student_fee_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  structure_id UUID NOT NULL REFERENCES fee_structures(id), term_id UUID REFERENCES academic_terms(id), assigned_by UUID, assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (student_program_enrollment_id, structure_id)
);

CREATE TABLE student_discount_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, discount_id UUID NOT NULL REFERENCES fee_discounts(id),
  academic_year_id UUID REFERENCES academic_years(id), reason TEXT, approved_by UUID, workflow_instance_id UUID, status VARCHAR(20) NOT NULL DEFAULT 'approved',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE fine_configurations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  applies_to VARCHAR(30) NOT NULL, -- late_fee | library_overdue | hostel | discipline
  calc_type VARCHAR(20) NOT NULL, -- per_day | flat | slab
  amount_paise INTEGER, grace_days SMALLINT NOT NULL DEFAULT 0, max_paise INTEGER, slabs JSONB, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE fee_invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE,
  payer_type VARCHAR(20) NOT NULL DEFAULT 'student', -- student | applicant | college | alumni | staff | company
  payer_id UUID NOT NULL, student_program_enrollment_id UUID REFERENCES student_program_enrollments(id),
  invoice_number VARCHAR(40) NOT NULL, academic_year_id UUID REFERENCES academic_years(id), term_id UUID REFERENCES academic_terms(id),
  source_type VARCHAR(40), source_id UUID, description VARCHAR(255),
  total_paise INTEGER NOT NULL DEFAULT 0, discount_paise INTEGER NOT NULL DEFAULT 0, tax_paise INTEGER NOT NULL DEFAULT 0, fine_paise INTEGER NOT NULL DEFAULT 0,
  paid_paise INTEGER NOT NULL DEFAULT 0, balance_paise INTEGER NOT NULL DEFAULT 0, due_date DATE,
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | partial | paid | overdue | cancelled | refunded
  gst_number VARCHAR(20), version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), cancelled_at TIMESTAMPTZ, cancelled_reason TEXT,
  UNIQUE (institution_id, invoice_number)
);
CREATE INDEX ix_fee_invoices_payer ON fee_invoices (payer_type, payer_id, status);
CREATE INDEX ix_fee_invoices_source ON fee_invoices (source_type, source_id);

CREATE TABLE fee_invoice_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  invoice_id UUID NOT NULL REFERENCES fee_invoices(id) ON DELETE CASCADE, fee_head_id UUID REFERENCES fee_heads(id),
  description VARCHAR(200) NOT NULL, amount_paise INTEGER NOT NULL, tax_paise INTEGER NOT NULL DEFAULT 0, instalment_no SMALLINT, due_date DATE
);

CREATE TABLE fee_payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  invoice_id UUID NOT NULL REFERENCES fee_invoices(id), receipt_number VARCHAR(40) NOT NULL, amount_paise INTEGER NOT NULL, payment_date DATE NOT NULL,
  payment_mode VARCHAR(20) NOT NULL, -- cash | upi | card | netbanking | cheque | dd | neft | challan | gateway | adjustment | scholarship_credit | wallet
  gateway VARCHAR(30), gateway_order_id VARCHAR(80), gateway_payment_id VARCHAR(80), gateway_signature VARCHAR(255), reference_no VARCHAR(80), utr VARCHAR(40), bank_name VARCHAR(100),
  status VARCHAR(20) NOT NULL DEFAULT 'success', -- initiated | success | failed | bounced | cancelled | reconciled
  collected_by UUID, counter VARCHAR(40), receipt_url TEXT, cancelled_at TIMESTAMPTZ, cancelled_by UUID, cancel_reason TEXT, cancel_workflow_instance_id UUID,
  idempotency_key VARCHAR(120), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, receipt_number)
);

CREATE TABLE offline_payment_reconciliations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  statement_file_url TEXT, bank_account VARCHAR(60), statement_date DATE, utr VARCHAR(40), amount_paise INTEGER, payer_hint VARCHAR(200),
  matched_payment_id UUID REFERENCES fee_payments(id), status VARCHAR(20) NOT NULL DEFAULT 'unmatched', -- unmatched | matched | ignored
  matched_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE fee_refunds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  invoice_id UUID REFERENCES fee_invoices(id), payment_id UUID REFERENCES fee_payments(id), payer_type VARCHAR(20) NOT NULL, payer_id UUID NOT NULL,
  amount_paise INTEGER NOT NULL, reason TEXT NOT NULL, refund_mode VARCHAR(20), reference_no VARCHAR(80),
  status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | approved | processed | rejected
  workflow_instance_id UUID, approved_by UUID, processed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE day_book_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), entry_date DATE NOT NULL, counter VARCHAR(40), collected_by UUID,
  cash_paise INTEGER NOT NULL DEFAULT 0, digital_paise INTEGER NOT NULL DEFAULT 0, cheque_paise INTEGER NOT NULL DEFAULT 0, deposited_paise INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'open', -- open | closed | deposited
  closed_at TIMESTAMPTZ, remarks TEXT, UNIQUE (institution_id, college_id, entry_date, counter, collected_by)
);

CREATE TABLE scholarships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(160) NOT NULL, provider VARCHAR(20) NOT NULL, -- central_govt | state_govt | institution | private | alumni
  scheme_code VARCHAR(40), amount_paise INTEGER, amount_type VARCHAR(20) NOT NULL DEFAULT 'fixed', -- fixed | fee_pct | fee_full
  eligibility_rules JSONB, academic_year_id UUID REFERENCES academic_years(id), applications_open DATE, applications_close DATE, description TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE scholarship_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scholarship_id UUID NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  income_paise BIGINT, documents JSONB, status VARCHAR(20) NOT NULL DEFAULT 'applied', -- applied | verified | recommended | sanctioned | disbursed | rejected
  sanctioned_paise INTEGER, disbursement_mode VARCHAR(20), -- fee_credit | bank_transfer | external_portal
  external_ref VARCHAR(60), fee_discount_id UUID REFERENCES fee_discounts(id), disbursed_at TIMESTAMPTZ, workflow_instance_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (scholarship_id, student_program_enrollment_id)
);

CREATE TABLE no_dues_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  purpose VARCHAR(30) NOT NULL, -- graduation | transfer | hostel_vacate | exit | transcript
  status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | in_progress | cleared | blocked
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), cleared_at TIMESTAMPTZ, certificate_document_id UUID
);

CREATE TABLE no_dues_signoffs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  request_id UUID NOT NULL REFERENCES no_dues_requests(id) ON DELETE CASCADE,
  department_key VARCHAR(30) NOT NULL, -- accounts | library | hostel | lab | department | sports | transport | placement
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | cleared | dues_pending
  dues_paise INTEGER NOT NULL DEFAULT 0, remarks TEXT, signed_by UUID, signed_at TIMESTAMPTZ, UNIQUE (request_id, department_key)
);

-- ===================================== 14. INTERNAL ASSESSMENT, LMS, PROJECTS, OBE DEFINITIONS =====================================
CREATE TABLE outcome_definitions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scope_type VARCHAR(20) NOT NULL, -- institution | program
  scope_id UUID NOT NULL, outcome_type VARCHAR(10) NOT NULL, -- PEO | PO | PSO
  code VARCHAR(10) NOT NULL, statement TEXT NOT NULL, framework VARCHAR(30), sequence SMALLINT NOT NULL DEFAULT 1,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (scope_type, scope_id, outcome_type, code)
);

CREATE TABLE peo_po_mappings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  peo_id UUID NOT NULL REFERENCES outcome_definitions(id) ON DELETE CASCADE, po_id UUID NOT NULL REFERENCES outcome_definitions(id) ON DELETE CASCADE,
  level SMALLINT NOT NULL CHECK (level BETWEEN 1 AND 3), UNIQUE (peo_id, po_id)
);

CREATE TABLE course_outcomes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  code VARCHAR(10) NOT NULL, statement TEXT NOT NULL, bloom_level VARCHAR(20), sequence SMALLINT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (course_id, code)
);

CREATE TABLE co_po_mappings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  course_outcome_id UUID NOT NULL REFERENCES course_outcomes(id) ON DELETE CASCADE, outcome_id UUID NOT NULL REFERENCES outcome_definitions(id) ON DELETE CASCADE,
  level SMALLINT NOT NULL CHECK (level BETWEEN 1 AND 3), justification TEXT, UNIQUE (course_outcome_id, outcome_id)
);

CREATE TABLE offering_assessments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, component_id UUID NOT NULL REFERENCES assessment_components(id),
  name VARCHAR(80) NOT NULL, max_marks NUMERIC(6,2) NOT NULL, scheduled_on DATE, marks_entry_deadline DATE,
  status VARCHAR(20) NOT NULL DEFAULT 'planned', -- planned | conducted | marks_entry | submitted | verified | locked
  question_paper_id UUID, submitted_by UUID, submitted_at TIMESTAMPTZ, verified_by UUID, verified_at TIMESTAMPTZ, locked_by UUID, locked_at TIMESTAMPTZ,
  version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (offering_id, component_id)
);

CREATE TABLE assessment_questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_assessment_id UUID NOT NULL REFERENCES offering_assessments(id) ON DELETE CASCADE,
  question_no VARCHAR(10) NOT NULL, max_marks NUMERIC(5,2) NOT NULL, co_id UUID REFERENCES course_outcomes(id), bloom_level VARCHAR(20), part VARCHAR(5),
  UNIQUE (offering_assessment_id, question_no)
);

CREATE TABLE internal_marks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_assessment_id UUID NOT NULL REFERENCES offering_assessments(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  marks NUMERIC(6,2), is_absent BOOLEAN NOT NULL DEFAULT FALSE, is_exempt BOOLEAN NOT NULL DEFAULT FALSE, question_wise JSONB,
  entered_by UUID, entered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), verified_by UUID, version SMALLINT NOT NULL DEFAULT 1, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (offering_assessment_id, student_program_enrollment_id)
);

CREATE TABLE cia_consolidations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  component_breakdown JSONB NOT NULL, cia_total NUMERIC(6,2) NOT NULL, cia_scaled NUMERIC(6,2) NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'computed', -- computed | hod_approved | locked | submitted_to_university
  locked_by UUID, locked_at TIMESTAMPTZ, computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (offering_id, student_program_enrollment_id)
);

CREATE TABLE marks_change_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  target_type VARCHAR(20) NOT NULL, -- internal_mark | script_final | course_result
  target_id UUID NOT NULL, old_value JSONB, new_value JSONB NOT NULL, reason TEXT NOT NULL, evidence_url TEXT,
  requested_by UUID NOT NULL, approved_by UUID, workflow_instance_id UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | hod_approved | coe_approved | applied | rejected
  applied_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE student_projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
  title VARCHAR(255) NOT NULL, project_type VARCHAR(20) NOT NULL DEFAULT 'major', -- mini | major | dissertation | internship_project
  guide_staff_id UUID REFERENCES staff(id), co_guide_staff_id UUID REFERENCES staff(id), external_guide JSONB, abstract TEXT, repository_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'proposed', -- proposed | approved | in_progress | submitted | evaluated
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE project_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES student_projects(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  role VARCHAR(10) NOT NULL DEFAULT 'member', UNIQUE (project_id, student_program_enrollment_id)
);

CREATE TABLE project_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  project_id UUID NOT NULL REFERENCES student_projects(id) ON DELETE CASCADE, review_no SMALLINT NOT NULL, scheduled_on DATE, panel JSONB,
  rubric_scores JSONB, marks NUMERIC(6,2), remarks TEXT, offering_assessment_id UUID REFERENCES offering_assessments(id), recorded_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (project_id, review_no)
);

-- Question bank / blueprints / paper builder / study materials (carried from Orbit content module)
CREATE TABLE syllabus_topics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE, unit_no SMALLINT, title VARCHAR(200) NOT NULL, parent_id UUID REFERENCES syllabus_topics(id), sequence SMALLINT NOT NULL DEFAULT 1, hours NUMERIC(4,1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE questions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  course_id UUID REFERENCES courses(id), topic_id UUID REFERENCES syllabus_topics(id), co_id UUID REFERENCES course_outcomes(id),
  question_type VARCHAR(20) NOT NULL, -- mcq | msq | true_false | short | long | numeric | fill_blank | match
  body_primary TEXT NOT NULL, body_secondary TEXT, marks NUMERIC(5,2) NOT NULL DEFAULT 1, difficulty VARCHAR(10) NOT NULL DEFAULT 'medium', bloom_level VARCHAR(20),
  answer_key JSONB, explanation TEXT, tags JSONB, media JSONB, created_by UUID, is_active BOOLEAN NOT NULL DEFAULT TRUE, usage_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID
);

CREATE TABLE question_options (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  question_id UUID NOT NULL REFERENCES questions(id) ON DELETE CASCADE, label VARCHAR(5), body_primary TEXT NOT NULL, body_secondary TEXT, is_correct BOOLEAN NOT NULL DEFAULT FALSE, sequence SMALLINT NOT NULL DEFAULT 1
);

CREATE TABLE question_blueprints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  course_id UUID REFERENCES courses(id), name VARCHAR(160) NOT NULL, total_marks NUMERIC(6,2) NOT NULL, duration_minutes SMALLINT, pattern JSONB NOT NULL, -- parts, counts, marks, CO/bloom/difficulty distribution
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE question_papers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  course_id UUID REFERENCES courses(id), blueprint_id UUID REFERENCES question_blueprints(id), title VARCHAR(200) NOT NULL, purpose VARCHAR(20) NOT NULL DEFAULT 'internal', -- internal | quiz | ese | practice
  total_marks NUMERIC(6,2), duration_minutes SMALLINT, sections JSONB NOT NULL, -- [{title, questions:[{question_id, marks, sequence}]}]
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | frozen | used
  is_bilingual BOOLEAN NOT NULL DEFAULT FALSE, created_by UUID, frozen_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE offering_assessments ADD CONSTRAINT fk_offering_assessments_qp FOREIGN KEY (question_paper_id) REFERENCES question_papers(id) ON DELETE SET NULL;

CREATE TABLE study_materials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  course_id UUID REFERENCES courses(id), offering_id UUID REFERENCES course_offerings(id), title VARCHAR(200) NOT NULL, material_type VARCHAR(20) NOT NULL DEFAULT 'notes',
  body_primary TEXT, body_secondary TEXT, file_url TEXT, is_published BOOLEAN NOT NULL DEFAULT FALSE, published_at TIMESTAMPTZ, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- LMS-lite
CREATE TABLE course_modules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, title VARCHAR(200) NOT NULL, sequence SMALLINT NOT NULL DEFAULT 1, is_published BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE course_contents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  module_id UUID NOT NULL REFERENCES course_modules(id) ON DELETE CASCADE, content_type VARCHAR(20) NOT NULL, -- file | video | link | text | scorm | embed
  title VARCHAR(200) NOT NULL, body TEXT, file_url TEXT, duration_minutes SMALLINT, release_at TIMESTAMPTZ, co_ids JSONB, sequence SMALLINT NOT NULL DEFAULT 1, view_count INT NOT NULL DEFAULT 0,
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE content_views (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  content_id UUID NOT NULL REFERENCES course_contents(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  first_viewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_viewed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), progress_pct SMALLINT NOT NULL DEFAULT 0, UNIQUE (content_id, student_program_enrollment_id)
);

CREATE TABLE lms_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, offering_assessment_id UUID REFERENCES offering_assessments(id),
  title VARCHAR(200) NOT NULL, instructions TEXT, attachments JSONB, due_at TIMESTAMPTZ, max_marks NUMERIC(6,2), allow_late BOOLEAN NOT NULL DEFAULT TRUE, late_penalty_pct_per_day NUMERIC(5,2),
  max_file_mb SMALLINT NOT NULL DEFAULT 10, rubric JSONB, co_ids JSONB, is_group BOOLEAN NOT NULL DEFAULT FALSE, similarity_check BOOLEAN NOT NULL DEFAULT FALSE,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | published | closed
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE assignment_submissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  assignment_id UUID NOT NULL REFERENCES lms_assignments(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  files JSONB, text_answer TEXT, submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), is_late BOOLEAN NOT NULL DEFAULT FALSE, attempt SMALLINT NOT NULL DEFAULT 1,
  marks NUMERIC(6,2), rubric_scores JSONB, feedback TEXT, graded_by UUID, graded_at TIMESTAMPTZ, similarity_pct NUMERIC(5,2), similarity_report_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'submitted', -- submitted | graded | returned | resubmit
  UNIQUE (assignment_id, student_program_enrollment_id, attempt)
);

CREATE TABLE quizzes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, question_paper_id UUID NOT NULL REFERENCES question_papers(id), offering_assessment_id UUID REFERENCES offering_assessments(id),
  title VARCHAR(200) NOT NULL, starts_at TIMESTAMPTZ, ends_at TIMESTAMPTZ, duration_minutes SMALLINT NOT NULL, attempts_allowed SMALLINT NOT NULL DEFAULT 1, shuffle_questions BOOLEAN NOT NULL DEFAULT TRUE,
  show_result VARCHAR(20) NOT NULL DEFAULT 'after_close', -- immediate | after_close | never
  proctoring JSONB, status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | published | closed
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE quiz_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  quiz_id UUID NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  attempt_no SMALLINT NOT NULL DEFAULT 1, started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), submitted_at TIMESTAMPTZ, answers JSONB, auto_score NUMERIC(6,2), manual_score NUMERIC(6,2), total_score NUMERIC(6,2),
  proctor_events JSONB, status VARCHAR(20) NOT NULL DEFAULT 'in_progress', -- in_progress | submitted | auto_submitted | graded
  UNIQUE (quiz_id, student_program_enrollment_id, attempt_no)
);

CREATE TABLE course_announcements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, title VARCHAR(200) NOT NULL, body TEXT, posted_by UUID, pinned BOOLEAN NOT NULL DEFAULT FALSE, posted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE discussion_threads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, title VARCHAR(200) NOT NULL, created_by UUID, is_locked BOOLEAN NOT NULL DEFAULT FALSE, is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE discussion_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  thread_id UUID NOT NULL REFERENCES discussion_threads(id) ON DELETE CASCADE, parent_post_id UUID REFERENCES discussion_posts(id) ON DELETE CASCADE,
  author_user_id UUID NOT NULL, body TEXT NOT NULL, attachments JSONB, is_answer BOOLEAN NOT NULL DEFAULT FALSE, upvotes INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ
);

CREATE TABLE lesson_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, unit_no SMALLINT, topic VARCHAR(255) NOT NULL, planned_date DATE, planned_hours NUMERIC(4,1) NOT NULL DEFAULT 1,
  delivery_method VARCHAR(30), co_id UUID REFERENCES course_outcomes(id), resources JSONB, actual_date DATE, actual_session_id UUID REFERENCES class_sessions(id),
  status VARCHAR(20) NOT NULL DEFAULT 'planned', -- planned | delivered | deferred
  sequence SMALLINT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE class_sessions ADD CONSTRAINT fk_class_sessions_lesson_plan FOREIGN KEY (lesson_plan_item_id) REFERENCES lesson_plans(id) ON DELETE SET NULL;

CREATE TABLE course_files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL UNIQUE REFERENCES course_offerings(id) ON DELETE CASCADE, checklist JSONB NOT NULL DEFAULT '[]', completion_pct SMALLINT NOT NULL DEFAULT 0,
  audited_by UUID, audited_at TIMESTAMPTZ, remarks TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 15. EXAMINATIONS =====================================
CREATE TABLE exam_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE, -- NULL = central (university)
  term_id UUID NOT NULL REFERENCES academic_terms(id), name VARCHAR(120) NOT NULL,
  exam_kind VARCHAR(20) NOT NULL DEFAULT 'regular', -- regular | supplementary | arrear | improvement | special | summer | practical
  coe_staff_id UUID REFERENCES staff(id), registration_start TIMESTAMPTZ, registration_end TIMESTAMPTZ, late_fee_until TIMESTAMPTZ, fee_rules JSONB,
  hall_ticket_release_at TIMESTAMPTZ, start_date DATE, end_date DATE, valuation_mode VARCHAR(10) NOT NULL DEFAULT 'single', -- single | double
  discrepancy_pct NUMERIC(5,2) NOT NULL DEFAULT 15, grading_scale_id UUID REFERENCES grading_scales(id),
  status VARCHAR(30) NOT NULL DEFAULT 'draft', -- draft | registration_open | registration_closed | scheduled | in_progress | valuation | result_processing | results_published | closed
  is_locked BOOLEAN NOT NULL DEFAULT FALSE, is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID
);

CREATE TABLE exam_papers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_session_id UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE, course_id UUID NOT NULL REFERENCES courses(id),
  paper_code VARCHAR(30), paper_type VARCHAR(20) NOT NULL DEFAULT 'theory', -- theory | practical | project_viva | dissertation | online
  exam_date DATE, session_slot VARCHAR(5), -- FN | AN | EVE
  start_time TIME, duration_minutes SMALLINT, max_marks NUMERIC(6,2) NOT NULL, qp_pattern JSONB, quiz_id UUID REFERENCES quizzes(id),
  status VARCHAR(20) NOT NULL DEFAULT 'planned', -- planned | qp_ready | conducted | scripts_received | valuation | finalized
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (exam_session_id, course_id, paper_type)
);

CREATE TABLE exam_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  exam_session_id UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | submitted | fee_pending | confirmed | cancelled | debarred
  fee_invoice_id UUID REFERENCES fee_invoices(id), total_fee_paise INTEGER NOT NULL DEFAULT 0,
  hall_ticket_number VARCHAR(30), hall_ticket_issued_at TIMESTAMPTZ, hall_ticket_qr_token VARCHAR(64), hall_ticket_pdf_url TEXT, eligibility_snapshot JSONB,
  version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (exam_session_id, student_program_enrollment_id)
);
CREATE UNIQUE INDEX uq_hall_ticket ON exam_registrations (exam_session_id, hall_ticket_number) WHERE hall_ticket_number IS NOT NULL;

CREATE TABLE exam_registration_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_registration_id UUID NOT NULL REFERENCES exam_registrations(id) ON DELETE CASCADE,
  exam_paper_id UUID NOT NULL REFERENCES exam_papers(id), course_id UUID NOT NULL REFERENCES courses(id),
  attempt_type VARCHAR(20) NOT NULL DEFAULT 'regular', -- regular | arrear | improvement | grade_improvement
  attempt_number SMALLINT NOT NULL DEFAULT 1, fee_paise INTEGER NOT NULL DEFAULT 0,
  eligibility VARCHAR(20) NOT NULL DEFAULT 'pending', -- eligible | condoned | detained | debarred | pending
  status VARCHAR(20) NOT NULL DEFAULT 'registered', -- registered | cancelled | absent | appeared | malpractice | withheld
  UNIQUE (exam_registration_id, exam_paper_id)
);

CREATE TABLE exam_seating_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_session_id UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE, exam_date DATE NOT NULL, session_slot VARCHAR(5) NOT NULL, room_id UUID NOT NULL REFERENCES rooms(id),
  capacity_used SMALLINT NOT NULL DEFAULT 0, layout JSONB, status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | published
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (exam_session_id, exam_date, session_slot, room_id)
);

CREATE TABLE exam_seat_allocations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  seating_plan_id UUID NOT NULL REFERENCES exam_seating_plans(id) ON DELETE CASCADE, exam_registration_item_id UUID NOT NULL UNIQUE REFERENCES exam_registration_items(id) ON DELETE CASCADE,
  seat_number VARCHAR(10) NOT NULL, row_no SMALLINT, col_no SMALLINT, UNIQUE (seating_plan_id, seat_number)
);

CREATE TABLE invigilation_duties (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_session_id UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE, exam_date DATE NOT NULL, session_slot VARCHAR(5) NOT NULL, room_id UUID REFERENCES rooms(id),
  staff_id UUID NOT NULL REFERENCES staff(id), role VARCHAR(30) NOT NULL DEFAULT 'invigilator', -- chief_superintendent | hall_superintendent | invigilator | reliever | flying_squad | observer
  status VARCHAR(20) NOT NULL DEFAULT 'assigned', -- assigned | accepted | swap_requested | swapped | absent | completed
  swap_with_staff_id UUID REFERENCES staff(id), remuneration_paise INTEGER, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (exam_session_id, exam_date, session_slot, staff_id)
);

CREATE TABLE exam_attendance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_registration_item_id UUID NOT NULL UNIQUE REFERENCES exam_registration_items(id) ON DELETE CASCADE,
  status VARCHAR(20) NOT NULL, -- present | absent | late | malpractice
  answer_booklet_number VARCHAR(30), face_match_score NUMERIC(5,2), marked_by UUID, marked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE question_paper_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_paper_id UUID NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE, setter_staff_id UUID REFERENCES staff(id), external_setter JSONB, set_label VARCHAR(5) NOT NULL DEFAULT 'A',
  blueprint_id UUID REFERENCES question_blueprints(id), status VARCHAR(20) NOT NULL DEFAULT 'invited', -- invited | accepted | submitted | scrutinised | approved | selected | printed | rejected
  file_key_encrypted TEXT, submitted_at TIMESTAMPTZ, scrutiny_by UUID, scrutiny_remarks TEXT, remuneration_paise INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (exam_paper_id, set_label)
);

CREATE TABLE question_paper_print_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_paper_id UUID NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE, set_label VARCHAR(5) NOT NULL, printed_by UUID NOT NULL, printed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  copies SMALLINT NOT NULL, watermark_text VARCHAR(120), ip INET
);

CREATE TABLE answer_script_bundles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_paper_id UUID NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE, room_id UUID REFERENCES rooms(id), exam_centre_id UUID,
  bundle_number VARCHAR(30) NOT NULL, script_count SMALLINT NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'created', -- created | coded | dispatched | received | in_valuation | valuated | decoded | archived
  coded_by UUID, coded_at TIMESTAMPTZ, custody_holder_staff_id UUID REFERENCES staff(id), custody_location VARCHAR(120),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (exam_paper_id, bundle_number)
);

CREATE TABLE answer_scripts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_registration_item_id UUID NOT NULL UNIQUE REFERENCES exam_registration_items(id) ON DELETE CASCADE,
  bundle_id UUID NOT NULL REFERENCES answer_script_bundles(id), dummy_number VARCHAR(20) NOT NULL, barcode VARCHAR(40), pages SMALLINT, scan_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'received', -- received | coded | in_valuation | valuated | discrepancy | third_valuation | finalized | moderated | decoded | revaluation | archived | destroyed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (bundle_id, dummy_number)
);
-- Evaluator projection: exposes id, dummy_number, bundle_id, pages, scan_url, status only (no identity columns)
CREATE VIEW answer_scripts_for_evaluation AS
  SELECT s.id, s.institution_id, s.bundle_id, s.dummy_number, s.pages, s.scan_url, s.status FROM answer_scripts s;

CREATE TABLE script_custody_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  bundle_id UUID NOT NULL REFERENCES answer_script_bundles(id) ON DELETE CASCADE,
  action VARCHAR(20) NOT NULL, -- created | dispatched | received | handed_over | returned | archived | destroyed
  from_staff_id UUID, to_staff_id UUID, at TIMESTAMPTZ NOT NULL DEFAULT NOW(), location VARCHAR(120), remarks TEXT
);

CREATE TABLE valuation_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_paper_id UUID NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE, bundle_id UUID NOT NULL REFERENCES answer_script_bundles(id) ON DELETE CASCADE,
  evaluator_staff_id UUID REFERENCES staff(id), evaluator_user_id UUID REFERENCES users(id), external_evaluator JSONB,
  evaluator_type VARCHAR(10) NOT NULL DEFAULT 'internal', -- internal | external
  valuation_round SMALLINT NOT NULL DEFAULT 1, status VARCHAR(20) NOT NULL DEFAULT 'assigned', -- assigned | accepted | in_progress | submitted | verified
  assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), due_at TIMESTAMPTZ, submitted_at TIMESTAMPTZ, remuneration_paise INTEGER,
  UNIQUE (bundle_id, valuation_round)
);

CREATE TABLE script_valuations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  answer_script_id UUID NOT NULL REFERENCES answer_scripts(id) ON DELETE CASCADE, valuation_round SMALLINT NOT NULL, evaluator_user_id UUID NOT NULL,
  marks NUMERIC(6,2) NOT NULL, question_wise JSONB, annotations_url TEXT, submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), is_locked BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (answer_script_id, valuation_round)
);

CREATE TABLE script_final_marks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  answer_script_id UUID NOT NULL UNIQUE REFERENCES answer_scripts(id) ON DELETE CASCADE,
  marks_v1 NUMERIC(6,2), marks_v2 NUMERIC(6,2), marks_v3 NUMERIC(6,2), discrepancy NUMERIC(6,2), rule_applied VARCHAR(40), computed_marks NUMERIC(6,2),
  moderated_marks NUMERIC(6,2), moderation_action_id UUID, final_marks NUMERIC(6,2),
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | resolved | needs_third | moderated | final
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE moderation_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_paper_id UUID NOT NULL REFERENCES exam_papers(id) ON DELETE CASCADE,
  action_type VARCHAR(20) NOT NULL, -- scale_up | scale_down | add_flat | grace | normalize | cap
  rule JSONB NOT NULL, justification TEXT NOT NULL, proposed_by UUID NOT NULL, approved_by UUID, affected_count INT,
  status VARCHAR(20) NOT NULL DEFAULT 'proposed', -- proposed | approved | applied | reverted
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE script_final_marks ADD CONSTRAINT fk_final_marks_moderation FOREIGN KEY (moderation_action_id) REFERENCES moderation_actions(id) ON DELETE SET NULL;

-- ===================================== 16. RESULTS, CREDENTIALS, POST-RESULT =====================================
CREATE TABLE result_processing_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_session_id UUID REFERENCES exam_sessions(id) ON DELETE CASCADE, scope JSONB,
  run_type VARCHAR(30) NOT NULL DEFAULT 'provisional', -- provisional | final | revaluation | supplementary_merge | correction | legacy_import
  status VARCHAR(20) NOT NULL DEFAULT 'queued', -- queued | computing | computed | verified | approved | published | rolled_back | failed
  triggered_by UUID, verified_by UUID, verified_at TIMESTAMPTZ, approved_by UUID, approved_at TIMESTAMPTZ, approval_resolution_id UUID, published_at TIMESTAMPTZ,
  stats JSONB, config_snapshot JSONB, checksum VARCHAR(64), error_log JSONB, job_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE student_course_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  term_id UUID NOT NULL REFERENCES academic_terms(id), course_id UUID NOT NULL REFERENCES courses(id), offering_id UUID REFERENCES course_offerings(id),
  exam_session_id UUID REFERENCES exam_sessions(id), exam_registration_item_id UUID REFERENCES exam_registration_items(id),
  attempt_number SMALLINT NOT NULL DEFAULT 1, attempt_type VARCHAR(20) NOT NULL DEFAULT 'regular', -- regular | arrear | improvement | credit_transfer | audit | re_registration | legacy
  credits NUMERIC(4,1) NOT NULL, cia_marks NUMERIC(6,2), cia_max NUMERIC(6,2), ese_marks NUMERIC(6,2), ese_max NUMERIC(6,2),
  grace_marks NUMERIC(4,1) NOT NULL DEFAULT 0, grace_reason VARCHAR(120), moderation_delta NUMERIC(5,2),
  total_marks NUMERIC(6,2), total_max NUMERIC(6,2), percentage NUMERIC(5,2), letter_grade VARCHAR(3), grade_point NUMERIC(3,1),
  result_status VARCHAR(20) NOT NULL, -- pass | fail | absent | withheld | malpractice | detained | incomplete | withdrawn | exempted | audit_pass | audit_fail
  counts_toward_cgpa BOOLEAN NOT NULL DEFAULT TRUE, is_current BOOLEAN NOT NULL DEFAULT TRUE, version SMALLINT NOT NULL DEFAULT 1,
  supersedes_id UUID REFERENCES student_course_results(id), run_id UUID NOT NULL REFERENCES result_processing_runs(id),
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | computed | verified | approved | published | superseded
  published_at TIMESTAMPTZ, hash VARCHAR(64), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (student_program_enrollment_id, course_id, attempt_number, version)
);
CREATE INDEX ix_scr_current ON student_course_results (student_program_enrollment_id, course_id) WHERE is_current;
ALTER TABLE credit_transfers ADD CONSTRAINT fk_credit_transfers_result FOREIGN KEY (result_id) REFERENCES student_course_results(id) ON DELETE SET NULL;
ALTER TABLE student_arrears ADD CONSTRAINT fk_arrears_cleared_result FOREIGN KEY (cleared_result_id) REFERENCES student_course_results(id) ON DELETE SET NULL;

CREATE TABLE student_term_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_term_record_id UUID NOT NULL REFERENCES student_term_records(id) ON DELETE CASCADE, run_id UUID NOT NULL REFERENCES result_processing_runs(id),
  credits_registered NUMERIC(5,1) NOT NULL DEFAULT 0, credits_earned NUMERIC(5,1) NOT NULL DEFAULT 0, sgpa NUMERIC(4,2), cgpa NUMERIC(4,2), cumulative_credits NUMERIC(6,1),
  backlog_count SMALLINT NOT NULL DEFAULT 0, result_class VARCHAR(30), status VARCHAR(20) NOT NULL DEFAULT 'computed', -- computed | approved | published | withheld | superseded
  version SMALLINT NOT NULL DEFAULT 1, is_current BOOLEAN NOT NULL DEFAULT TRUE, published_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (student_term_record_id, version)
);

CREATE TABLE result_publications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  run_id UUID NOT NULL REFERENCES result_processing_runs(id) ON DELETE CASCADE, exam_session_id UUID REFERENCES exam_sessions(id),
  published_by UUID NOT NULL, published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), audience VARCHAR(20) NOT NULL DEFAULT 'student', -- student | college | public
  notify JSONB, withheld_list JSONB
);

CREATE TABLE grade_cards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_term_result_id UUID NOT NULL REFERENCES student_term_results(id) ON DELETE CASCADE,
  document_number VARCHAR(40) NOT NULL, pdf_url TEXT, qr_token VARCHAR(64) NOT NULL UNIQUE, template_id UUID, generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), version SMALLINT NOT NULL DEFAULT 1,
  UNIQUE (institution_id, document_number)
);

CREATE TABLE transcripts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  transcript_type VARCHAR(20) NOT NULL DEFAULT 'consolidated', -- provisional | consolidated | final | duplicate | migration
  document_number VARCHAR(40), pdf_url TEXT, verification_token VARCHAR(64) UNIQUE, fee_invoice_id UUID REFERENCES fee_invoices(id), workflow_instance_id UUID,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), issued_at TIMESTAMPTZ, issued_by UUID, copies SMALLINT NOT NULL DEFAULT 1,
  status VARCHAR(20) NOT NULL DEFAULT 'requested' -- requested | fee_pending | generated | issued | cancelled
);

CREATE TABLE reval_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_session_id UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE, exam_registration_item_id UUID NOT NULL REFERENCES exam_registration_items(id) ON DELETE CASCADE,
  answer_script_id UUID REFERENCES answer_scripts(id), request_type VARCHAR(20) NOT NULL, -- retotaling | photocopy | revaluation | challenge
  fee_invoice_id UUID REFERENCES fee_invoices(id), status VARCHAR(20) NOT NULL DEFAULT 'submitted', -- submitted | fee_paid | assigned | evaluated | marks_changed | no_change | rejected | closed
  original_marks NUMERIC(6,2), revised_marks NUMERIC(6,2), delta NUMERIC(6,2), evaluator_assignment_id UUID REFERENCES valuation_assignments(id), photocopy_url TEXT,
  decided_by UUID, decided_at TIMESTAMPTZ, refund_due BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (exam_registration_item_id, request_type)
);

CREATE TABLE malpractice_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_session_id UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE, exam_registration_item_id UUID NOT NULL REFERENCES exam_registration_items(id),
  case_number VARCHAR(30) NOT NULL, reported_by UUID NOT NULL, reported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  category VARCHAR(20) NOT NULL, -- copying | impersonation | device | material | misconduct | tampering | other
  evidence JSONB, invigilator_report TEXT, student_statement TEXT, committee_id UUID, hearing_at TIMESTAMPTZ,
  punishment VARCHAR(20), -- none | warning | cancel_paper | cancel_session | debar_terms | expel
  debar_until_term_id UUID REFERENCES academic_terms(id), decision_text TEXT, decided_by UUID, decided_at TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'reported', -- reported | under_inquiry | hearing_scheduled | decided | appealed | appeal_decided | closed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, case_number)
);

CREATE TABLE legacy_result_imports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  batch_id UUID NOT NULL REFERENCES batches(id), term_number SMALLINT NOT NULL, file_url TEXT NOT NULL, mapping JSONB, validation_report JSONB,
  status VARCHAR(20) NOT NULL DEFAULT 'uploaded', -- uploaded | validated | applied | rolled_back
  run_id UUID REFERENCES result_processing_runs(id), job_id UUID, requested_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE degree_eligibility_checks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), credits_earned NUMERIC(6,1), credits_required NUMERIC(6,1), bucket_breakdown JSONB, backlog_count SMALLINT, cgpa NUMERIC(4,2),
  min_cgpa_ok BOOLEAN, duration_ok BOOLEAN, dues_cleared BOOLEAN, holds_clear BOOLEAN, mandatory_noncredit_ok BOOLEAN, is_eligible BOOLEAN NOT NULL, reasons JSONB, run_id UUID
);

CREATE TABLE convocations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(160) NOT NULL, held_on DATE, venue VARCHAR(200), registration_deadline DATE, fee_paise INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'planned', -- planned | registration_open | closed | completed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE convocation_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  convocation_id UUID NOT NULL REFERENCES convocations(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  mode VARCHAR(20) NOT NULL DEFAULT 'in_person', -- in_person | absentia
  fee_invoice_id UUID REFERENCES fee_invoices(id), gown_size VARCHAR(10), guests SMALLINT, status VARCHAR(20) NOT NULL DEFAULT 'registered',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (convocation_id, student_program_enrollment_id)
);

CREATE TABLE degrees_awarded (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  award_type VARCHAR(20) NOT NULL, -- certificate | diploma | degree | honours | pg_diploma | phd
  degree_name VARCHAR(120) NOT NULL, specialization VARCHAR(120), result_class VARCHAR(30), cgpa NUMERIC(4,2), date_of_award DATE,
  certificate_number VARCHAR(40), serial_no VARCHAR(40), convocation_id UUID REFERENCES convocations(id), pdf_url TEXT, esign_ref VARCHAR(120),
  status VARCHAR(20) NOT NULL DEFAULT 'recommended', -- recommended | council_approved | issued | cancelled | reissued
  approved_by UUID, approval_resolution_id UUID, digital_credential_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX uq_degree_certificate_no ON degrees_awarded (institution_id, certificate_number) WHERE certificate_number IS NOT NULL;

CREATE TABLE digital_credentials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  entity_type VARCHAR(30) NOT NULL, -- grade_card | transcript | degree | provisional_certificate
  entity_id UUID NOT NULL, channel VARCHAR(20) NOT NULL, -- digilocker | nad | abc | internal
  payload_hash VARCHAR(64) NOT NULL, payload JSONB, pushed_at TIMESTAMPTZ, ack_ref VARCHAR(120),
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | pushed | acknowledged | failed | revoked
  response JSONB, attempts SMALLINT NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (entity_type, entity_id, channel)
);
ALTER TABLE degrees_awarded ADD CONSTRAINT fk_degrees_digital_credential FOREIGN KEY (digital_credential_id) REFERENCES digital_credentials(id) ON DELETE SET NULL;

CREATE TABLE abc_credit_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE, apaar_id VARCHAR(20), student_course_result_id UUID NOT NULL UNIQUE REFERENCES student_course_results(id),
  term_id UUID REFERENCES academic_terms(id), course_code VARCHAR(30) NOT NULL, course_title VARCHAR(200) NOT NULL, credits NUMERIC(4,1) NOT NULL, letter_grade VARCHAR(3), grade_point NUMERIC(3,1), academic_year VARCHAR(20),
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | pushed | acknowledged | failed | revoked
  push_batch_id UUID, response JSONB, attempts SMALLINT NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 17. OBE ATTAINMENT =====================================
CREATE TABLE attainment_configs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scope_type VARCHAR(20) NOT NULL, -- regulation | program
  scope_id UUID NOT NULL, target_student_pct NUMERIC(5,2) NOT NULL DEFAULT 60, target_marks_pct NUMERIC(5,2) NOT NULL DEFAULT 60,
  levels JSONB NOT NULL DEFAULT '[{"level":1,"min_pct":40},{"level":2,"min_pct":50},{"level":3,"min_pct":60}]',
  direct_weight SMALLINT NOT NULL DEFAULT 80, indirect_weight SMALLINT NOT NULL DEFAULT 20, cia_weight_in_direct SMALLINT NOT NULL DEFAULT 30, ese_weight_in_direct SMALLINT NOT NULL DEFAULT 70,
  po_target_level NUMERIC(3,2) NOT NULL DEFAULT 2.0, co_target_level NUMERIC(3,2) NOT NULL DEFAULT 2.0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (scope_type, scope_id)
);

CREATE TABLE attainment_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scope_type VARCHAR(20) NOT NULL, -- offering | program_batch
  scope_id UUID NOT NULL, batch_id UUID REFERENCES batches(id), config_snapshot JSONB, status VARCHAR(20) NOT NULL DEFAULT 'queued', -- queued | computed | failed
  run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), run_by UUID, job_id UUID
);

CREATE TABLE co_attainments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  offering_id UUID NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE, course_outcome_id UUID NOT NULL REFERENCES course_outcomes(id) ON DELETE CASCADE, run_id UUID NOT NULL REFERENCES attainment_runs(id) ON DELETE CASCADE,
  students_assessed SMALLINT NOT NULL DEFAULT 0, students_above_target SMALLINT NOT NULL DEFAULT 0, direct_pct NUMERIC(5,2), direct_level NUMERIC(3,2), cia_level NUMERIC(3,2), ese_level NUMERIC(3,2),
  indirect_level NUMERIC(3,2), final_level NUMERIC(3,2), target_level NUMERIC(3,2), gap NUMERIC(3,2), breakdown JSONB, computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (offering_id, course_outcome_id, run_id)
);

CREATE TABLE po_attainments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  program_id UUID NOT NULL REFERENCES programs(id) ON DELETE CASCADE, batch_id UUID NOT NULL REFERENCES batches(id) ON DELETE CASCADE, outcome_id UUID NOT NULL REFERENCES outcome_definitions(id) ON DELETE CASCADE,
  run_id UUID NOT NULL REFERENCES attainment_runs(id) ON DELETE CASCADE, direct_level NUMERIC(3,2), indirect_level NUMERIC(3,2), final_level NUMERIC(3,2), target_level NUMERIC(3,2), gap NUMERIC(3,2),
  contributing_courses SMALLINT NOT NULL DEFAULT 0, breakdown JSONB, computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (program_id, batch_id, outcome_id, run_id)
);

CREATE TABLE cqi_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scope_type VARCHAR(20) NOT NULL, -- offering | course | program
  scope_id UUID NOT NULL, outcome_id UUID REFERENCES outcome_definitions(id), gap NUMERIC(3,2), action_text TEXT NOT NULL, owner_staff_id UUID REFERENCES staff(id), due_on DATE,
  status VARCHAR(20) NOT NULL DEFAULT 'planned', -- planned | in_progress | done | verified
  evidence_url TEXT, reviewed_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 18. LIBRARY =====================================
CREATE TABLE book_categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL, parent_id UUID REFERENCES book_categories(id), ddc_code VARCHAR(20), is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, name)
);

CREATE TABLE books (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), category_id UUID REFERENCES book_categories(id),
  title VARCHAR(255) NOT NULL, authors JSONB, publisher VARCHAR(160), edition VARCHAR(40), year SMALLINT, isbn VARCHAR(20), language VARCHAR(30), subject VARCHAR(120), call_number VARCHAR(40),
  resource_type VARCHAR(20) NOT NULL DEFAULT 'book', -- book | journal | thesis | ebook | ejournal | cd | reference
  pages SMALLINT, price_paise INTEGER, cover_url TEXT, description TEXT, total_copies SMALLINT NOT NULL DEFAULT 0, available_copies SMALLINT NOT NULL DEFAULT 0, external_ref VARCHAR(60),
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID
);
CREATE INDEX ix_books_title_trgm ON books USING gin (title gin_trgm_ops);

CREATE TABLE library_copies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE, accession_number VARCHAR(30) NOT NULL, barcode VARCHAR(40), rfid_tag VARCHAR(60), location VARCHAR(80),
  status VARCHAR(20) NOT NULL DEFAULT 'available', -- available | issued | reserved | lost | damaged | withdrawn | reference_only
  acquired_on DATE, price_paise INTEGER, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, accession_number)
);

CREATE TABLE library_eresources (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  title VARCHAR(255) NOT NULL, provider VARCHAR(120), resource_type VARCHAR(20) NOT NULL, -- ejournal | ebook_db | database | repository
  url TEXT NOT NULL, access_type VARCHAR(20) NOT NULL DEFAULT 'ip', subscription_from DATE, subscription_to DATE, cost_paise BIGINT, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE library_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, member_type VARCHAR(20) NOT NULL, -- student | faculty | staff | scholar | alumni | external
  member_code VARCHAR(30) NOT NULL, max_books_allowed SMALLINT NOT NULL DEFAULT 3, loan_days SMALLINT NOT NULL DEFAULT 14, valid_to DATE, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, member_code)
);

CREATE TABLE book_issues (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  copy_id UUID NOT NULL REFERENCES library_copies(id), member_id UUID NOT NULL REFERENCES library_members(id),
  issued_on DATE NOT NULL, due_on DATE NOT NULL, returned_on DATE, renewals SMALLINT NOT NULL DEFAULT 0, issued_by UUID, returned_to UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'issued', -- issued | returned | overdue | lost
  fine_paise INTEGER NOT NULL DEFAULT 0, fine_invoice_id UUID REFERENCES fee_invoices(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE library_reservations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE, member_id UUID NOT NULL REFERENCES library_members(id), reserved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), expires_at TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'waiting', -- waiting | available | fulfilled | cancelled | expired
  UNIQUE (book_id, member_id, status)
);

CREATE TABLE library_ill_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  member_id UUID NOT NULL REFERENCES library_members(id), title VARCHAR(255) NOT NULL, source_library VARCHAR(200), requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  status VARCHAR(20) NOT NULL DEFAULT 'requested', received_on DATE, returned_on DATE, cost_paise INTEGER
);

-- ===================================== 19. HOSTEL, MESS & STAFF ACCOMMODATION =====================================
CREATE TABLE hostels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE,
  name VARCHAR(120) NOT NULL, hostel_type VARCHAR(20) NOT NULL, -- boys | girls | coed | pg | international | staff
  warden_staff_id UUID REFERENCES staff(id), address JSONB, capacity SMALLINT NOT NULL DEFAULT 0, mess_id UUID, rules_template_id UUID,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, college_id, name)
);

CREATE TABLE hostel_blocks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  hostel_id UUID NOT NULL REFERENCES hostels(id) ON DELETE CASCADE, name VARCHAR(40) NOT NULL, floors SMALLINT NOT NULL DEFAULT 1, UNIQUE (hostel_id, name)
);

CREATE TABLE hostel_rooms (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  block_id UUID NOT NULL REFERENCES hostel_blocks(id) ON DELETE CASCADE, room_number VARCHAR(20) NOT NULL, floor SMALLINT, capacity SMALLINT NOT NULL,
  room_type VARCHAR(20) NOT NULL DEFAULT 'double', -- single | double | triple | dorm
  has_ac BOOLEAN NOT NULL DEFAULT FALSE, amenities JSONB, status VARCHAR(20) NOT NULL DEFAULT 'available', -- available | full | maintenance | blocked
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (block_id, room_number)
);

CREATE TABLE hostel_beds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  room_id UUID NOT NULL REFERENCES hostel_rooms(id) ON DELETE CASCADE, bed_label VARCHAR(10) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'vacant', -- vacant | allocated | blocked
  UNIQUE (room_id, bed_label)
);

CREATE TABLE hostel_fee_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  hostel_id UUID NOT NULL REFERENCES hostels(id) ON DELETE CASCADE, room_type VARCHAR(20) NOT NULL, academic_year_id UUID NOT NULL REFERENCES academic_years(id),
  fee_per_term_paise INTEGER NOT NULL, caution_deposit_paise INTEGER NOT NULL DEFAULT 0, mess_advance_paise INTEGER NOT NULL DEFAULT 0, UNIQUE (hostel_id, room_type, academic_year_id)
);

CREATE TABLE hostel_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, academic_year_id UUID NOT NULL REFERENCES academic_years(id),
  hostel_preference JSONB, room_type_pref VARCHAR(20), distance_km NUMERIC(6,1), priority_score NUMERIC(6,2),
  status VARCHAR(20) NOT NULL DEFAULT 'applied', -- applied | waitlisted | allotted | declined | cancelled
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (student_program_enrollment_id, academic_year_id)
);

CREATE TABLE hostel_allocations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, bed_id UUID NOT NULL REFERENCES hostel_beds(id), hostel_id UUID NOT NULL REFERENCES hostels(id),
  academic_year_id UUID NOT NULL REFERENCES academic_years(id), from_on DATE NOT NULL, to_on DATE,
  status VARCHAR(20) NOT NULL DEFAULT 'allotted', -- allotted | checked_in | vacated | transferred | evicted
  fee_invoice_id UUID REFERENCES fee_invoices(id), caution_deposit_invoice_id UUID REFERENCES fee_invoices(id), check_in_at TIMESTAMPTZ, check_out_at TIMESTAMPTZ, room_condition JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX one_active_bed ON hostel_allocations (bed_id) WHERE status IN ('allotted','checked_in');
CREATE UNIQUE INDEX one_active_resident ON hostel_allocations (student_program_enrollment_id) WHERE status IN ('allotted','checked_in');

CREATE TABLE room_change_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  allocation_id UUID NOT NULL REFERENCES hostel_allocations(id) ON DELETE CASCADE, requested_bed_id UUID REFERENCES hostel_beds(id), reason TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | approved | rejected | applied
  decided_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE hostel_roll_calls (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  hostel_id UUID NOT NULL REFERENCES hostels(id) ON DELETE CASCADE, on_date DATE NOT NULL, taken_by UUID, taken_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (hostel_id, on_date)
);

CREATE TABLE hostel_roll_call_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  roll_call_id UUID NOT NULL REFERENCES hostel_roll_calls(id) ON DELETE CASCADE, allocation_id UUID NOT NULL REFERENCES hostel_allocations(id) ON DELETE CASCADE,
  status VARCHAR(20) NOT NULL, -- present | absent | on_leave
  UNIQUE (roll_call_id, allocation_id)
);

CREATE TABLE mess_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  hostel_id UUID REFERENCES hostels(id) ON DELETE CASCADE, name VARCHAR(80) NOT NULL, diet VARCHAR(20) NOT NULL DEFAULT 'veg', -- veg | nonveg | jain | special
  monthly_fee_paise INTEGER NOT NULL, menu JSONB, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE hostels ADD CONSTRAINT fk_hostels_mess FOREIGN KEY (mess_id) REFERENCES mess_plans(id) ON DELETE SET NULL;

CREATE TABLE mess_subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, mess_plan_id UUID NOT NULL REFERENCES mess_plans(id),
  from_on DATE NOT NULL, to_on DATE, status VARCHAR(20) NOT NULL DEFAULT 'active', fee_invoice_id UUID REFERENCES fee_invoices(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE mess_attendance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  mess_subscription_id UUID NOT NULL REFERENCES mess_subscriptions(id) ON DELETE CASCADE, on_date DATE NOT NULL, meal VARCHAR(10) NOT NULL, -- breakfast | lunch | snacks | dinner
  status VARCHAR(10) NOT NULL DEFAULT 'taken', -- taken | skipped | rebate
  source VARCHAR(20) NOT NULL DEFAULT 'manual', UNIQUE (mess_subscription_id, on_date, meal)
);

CREATE TABLE mess_bills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  mess_subscription_id UUID NOT NULL REFERENCES mess_subscriptions(id) ON DELETE CASCADE, month DATE NOT NULL, days_billed SMALLINT NOT NULL, rebate_days SMALLINT NOT NULL DEFAULT 0,
  amount_paise INTEGER NOT NULL, fee_invoice_id UUID REFERENCES fee_invoices(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (mess_subscription_id, month)
);

CREATE TABLE hostel_visitors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  hostel_id UUID NOT NULL REFERENCES hostels(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id),
  visitor_name VARCHAR(160) NOT NULL, relation VARCHAR(40), phone VARCHAR(20), id_proof_type VARCHAR(30), id_proof_no VARCHAR(40), in_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), out_at TIMESTAMPTZ, approved_by UUID
);

CREATE TABLE hostel_leaves (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, hostel_id UUID NOT NULL REFERENCES hostels(id),
  leave_type VARCHAR(20) NOT NULL, -- out_pass | day_leave | home_leave | medical
  from_at TIMESTAMPTZ NOT NULL, to_at TIMESTAMPTZ NOT NULL, destination VARCHAR(200), reason TEXT,
  guardian_consent VARCHAR(20) NOT NULL DEFAULT 'not_required', -- pending | otp_verified | not_required
  status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | approved | rejected | out | returned | late_return | absconding
  approved_by UUID, actual_out_at TIMESTAMPTZ, actual_return_at TIMESTAMPTZ, late_minutes INT, qr_token VARCHAR(64), workflow_instance_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE hostel_complaints (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  hostel_id UUID NOT NULL REFERENCES hostels(id) ON DELETE CASCADE, room_id UUID REFERENCES hostel_rooms(id), student_program_enrollment_id UUID REFERENCES student_program_enrollments(id),
  category VARCHAR(20) NOT NULL, description TEXT NOT NULL, service_request_id UUID, status VARCHAR(20) NOT NULL DEFAULT 'open', -- open | assigned | in_progress | resolved | closed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), resolved_at TIMESTAMPTZ
);

CREATE TABLE hostel_disciplinary_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, hostel_id UUID NOT NULL REFERENCES hostels(id),
  incident_on DATE NOT NULL, description TEXT NOT NULL, action VARCHAR(20) NOT NULL, -- warning | fine | suspension | eviction
  fine_paise INTEGER, fee_invoice_id UUID REFERENCES fee_invoices(id), decided_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE staff_quarters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id), unit_code VARCHAR(20) NOT NULL, quarter_type VARCHAR(20), rent_paise INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'vacant', -- vacant | allocated | maintenance
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, college_id, unit_code)
);

CREATE TABLE staff_quarter_allocations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  quarter_id UUID NOT NULL REFERENCES staff_quarters(id) ON DELETE CASCADE, staff_id UUID NOT NULL REFERENCES staff(id), from_on DATE NOT NULL, to_on DATE, rent_deduction BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX one_active_quarter ON staff_quarter_allocations (quarter_id) WHERE to_on IS NULL;

-- ===================================== 20. TRANSPORT =====================================
CREATE TABLE vehicles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), registration_no VARCHAR(20) NOT NULL, vehicle_type VARCHAR(20) NOT NULL DEFAULT 'bus', capacity SMALLINT, make_model VARCHAR(80), year SMALLINT,
  driver_staff_id UUID REFERENCES staff(id), insurance_expiry DATE, fitness_expiry DATE, permit_expiry DATE, puc_expiry DATE, gps_device_id UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'active', is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, registration_no)
);

CREATE TABLE transport_routes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), code VARCHAR(20) NOT NULL, name VARCHAR(120) NOT NULL, vehicle_id UUID REFERENCES vehicles(id), distance_km NUMERIC(6,1), fee_paise INTEGER,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, code)
);

CREATE TABLE transport_stops (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  route_id UUID NOT NULL REFERENCES transport_routes(id) ON DELETE CASCADE, name VARCHAR(120) NOT NULL, sequence SMALLINT NOT NULL, lat NUMERIC(9,6), lng NUMERIC(9,6), pickup_time TIME, drop_time TIME, fee_paise INTEGER,
  UNIQUE (route_id, sequence)
);

CREATE TABLE transport_allocations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  person_type VARCHAR(10) NOT NULL, -- student | staff
  person_id UUID NOT NULL, route_id UUID NOT NULL REFERENCES transport_routes(id), stop_id UUID REFERENCES transport_stops(id), academic_year_id UUID REFERENCES academic_years(id),
  from_on DATE, to_on DATE, fee_invoice_id UUID REFERENCES fee_invoices(id), status VARCHAR(20) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE vehicle_maintenance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  vehicle_id UUID NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE, maintenance_type VARCHAR(40), service_date DATE NOT NULL, odometer INT, cost_paise INTEGER, vendor VARCHAR(120), next_due_date DATE, notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE vehicle_fuel_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  vehicle_id UUID NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE, filled_on DATE NOT NULL, litres NUMERIC(7,2), cost_paise INTEGER, odometer INT, filled_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE gps_devices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  device_id VARCHAR(60) NOT NULL, vehicle_id UUID REFERENCES vehicles(id), token_hash VARCHAR(64) NOT NULL UNIQUE, is_active BOOLEAN NOT NULL DEFAULT TRUE, last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, device_id)
);
ALTER TABLE vehicles ADD CONSTRAINT fk_vehicles_gps_device FOREIGN KEY (gps_device_id) REFERENCES gps_devices(id) ON DELETE SET NULL;

CREATE TABLE transport_trips (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  route_id UUID NOT NULL REFERENCES transport_routes(id), vehicle_id UUID NOT NULL REFERENCES vehicles(id), driver_staff_id UUID REFERENCES staff(id),
  trip_date DATE NOT NULL, direction VARCHAR(10) NOT NULL, -- pickup | drop
  started_at TIMESTAMPTZ, ended_at TIMESTAMPTZ, status VARCHAR(20) NOT NULL DEFAULT 'scheduled', -- scheduled | in_progress | completed | cancelled
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE vehicle_gps_logs (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL, vehicle_id UUID NOT NULL, trip_id UUID, lat NUMERIC(9,6) NOT NULL, lng NUMERIC(9,6) NOT NULL, speed_kmh NUMERIC(5,1), heading SMALLINT, recorded_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (id, recorded_at)
) PARTITION BY RANGE (recorded_at);
CREATE TABLE vehicle_gps_logs_default PARTITION OF vehicle_gps_logs DEFAULT;

CREATE TABLE trip_stop_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  trip_id UUID NOT NULL REFERENCES transport_trips(id) ON DELETE CASCADE, stop_id UUID NOT NULL REFERENCES transport_stops(id), arrived_at TIMESTAMPTZ, departed_at TIMESTAMPTZ
);

CREATE TABLE trip_passenger_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  trip_id UUID NOT NULL REFERENCES transport_trips(id) ON DELETE CASCADE, person_type VARCHAR(10) NOT NULL, person_id UUID NOT NULL, event VARCHAR(10) NOT NULL, -- board | alight
  stop_id UUID REFERENCES transport_stops(id), occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), source VARCHAR(20) NOT NULL DEFAULT 'app'
);

-- ===================================== 21. INVENTORY & PROCUREMENT =====================================
CREATE TABLE suppliers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(200) NOT NULL, code VARCHAR(20), gstin VARCHAR(20), pan VARCHAR(12), contact JSONB, address JSONB, categories JSONB, bank_details_encrypted BYTEA, rating NUMERIC(3,2),
  portal_user_id UUID REFERENCES users(id), status VARCHAR(20) NOT NULL DEFAULT 'active', -- registered | active | blacklisted
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, name)
);

CREATE TABLE stores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), department_id UUID REFERENCES departments(id), name VARCHAR(120) NOT NULL, store_type VARCHAR(20) NOT NULL DEFAULT 'central', -- central | department | lab | hostel
  keeper_staff_id UUID REFERENCES staff(id), is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, name)
);

CREATE TABLE inventory_categories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(100) NOT NULL, parent_id UUID REFERENCES inventory_categories(id), is_consumable BOOLEAN NOT NULL DEFAULT TRUE, is_active BOOLEAN NOT NULL DEFAULT TRUE, UNIQUE (institution_id, name)
);

CREATE TABLE items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  category_id UUID REFERENCES inventory_categories(id), item_code VARCHAR(30) NOT NULL, name VARCHAR(200) NOT NULL, unit VARCHAR(20) NOT NULL DEFAULT 'nos', description TEXT,
  is_consumable BOOLEAN NOT NULL DEFAULT TRUE, is_hazardous BOOLEAN NOT NULL DEFAULT FALSE, safety_data JSONB, min_stock_level NUMERIC(10,2), reorder_qty NUMERIC(10,2), unit_cost_paise INTEGER, gst_rate NUMERIC(4,2),
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, item_code)
);

CREATE TABLE stock_levels (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  store_id UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE, item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE, quantity NUMERIC(12,2) NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (store_id, item_id)
);

CREATE TABLE indents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  indent_number VARCHAR(30) NOT NULL, department_id UUID REFERENCES departments(id), store_id UUID REFERENCES stores(id), requested_by UUID NOT NULL, purpose TEXT, priority VARCHAR(10) NOT NULL DEFAULT 'normal',
  items JSONB NOT NULL, estimated_paise INTEGER, budget_head_id UUID, workflow_instance_id UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | submitted | hod_approved | approved | rejected | fulfilled | closed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, indent_number)
);

CREATE TABLE quotations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  indent_id UUID NOT NULL REFERENCES indents(id) ON DELETE CASCADE, supplier_id UUID NOT NULL REFERENCES suppliers(id), reference VARCHAR(60), tender_ref VARCHAR(60), gem_ref VARCHAR(60),
  items JSONB NOT NULL, total_paise INTEGER NOT NULL, valid_until DATE, file_url TEXT, is_selected BOOLEAN NOT NULL DEFAULT FALSE, comparison_notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE purchase_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  po_number VARCHAR(30) NOT NULL, supplier_id UUID NOT NULL REFERENCES suppliers(id), indent_id UUID REFERENCES indents(id), quotation_id UUID REFERENCES quotations(id),
  order_date DATE NOT NULL, expected_date DATE, terms TEXT, subtotal_paise INTEGER NOT NULL DEFAULT 0, tax_paise INTEGER NOT NULL DEFAULT 0, total_paise INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | approved | sent | partially_received | received | cancelled | closed
  approved_by UUID, workflow_instance_id UUID, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, po_number)
);

CREATE TABLE purchase_order_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  po_id UUID NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE, item_id UUID NOT NULL REFERENCES items(id), quantity NUMERIC(12,2) NOT NULL, unit_price_paise INTEGER NOT NULL, tax_rate NUMERIC(4,2), received_qty NUMERIC(12,2) NOT NULL DEFAULT 0
);

CREATE TABLE goods_receipts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  grn_number VARCHAR(30) NOT NULL, po_id UUID NOT NULL REFERENCES purchase_orders(id), store_id UUID NOT NULL REFERENCES stores(id), received_on DATE NOT NULL, received_by UUID, invoice_no VARCHAR(60), items JSONB NOT NULL, remarks TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, grn_number)
);

CREATE TABLE stock_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  store_id UUID NOT NULL REFERENCES stores(id), item_id UUID NOT NULL REFERENCES items(id), txn_type VARCHAR(20) NOT NULL, -- receipt | issue | return | adjustment | transfer_in | transfer_out | write_off
  quantity NUMERIC(12,2) NOT NULL, unit_cost_paise INTEGER, reference_type VARCHAR(30), reference_id UUID, issued_to_type VARCHAR(20), issued_to_id UUID, remarks TEXT, performed_by UUID,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), asset_tag VARCHAR(40) NOT NULL, name VARCHAR(200) NOT NULL, category VARCHAR(60), item_id UUID REFERENCES items(id), serial_no VARCHAR(80),
  location_room_id UUID REFERENCES rooms(id), custodian_staff_id UUID REFERENCES staff(id), department_id UUID REFERENCES departments(id),
  purchase_date DATE, cost_paise BIGINT, po_id UUID REFERENCES purchase_orders(id), warranty_until DATE, depreciation_method VARCHAR(20), depreciation_rate NUMERIC(5,2), current_value_paise BIGINT,
  qr_code_url TEXT, is_bookable BOOLEAN NOT NULL DEFAULT FALSE, status VARCHAR(20) NOT NULL DEFAULT 'in_use', -- in_use | idle | under_repair | condemned | disposed
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, asset_tag)
);

CREATE TABLE asset_audits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE, audited_on DATE NOT NULL, audited_by UUID, found BOOLEAN NOT NULL, condition VARCHAR(20), remarks TEXT, scanned_qr BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE vendor_bills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  supplier_id UUID NOT NULL REFERENCES suppliers(id), po_id UUID REFERENCES purchase_orders(id), grn_id UUID REFERENCES goods_receipts(id), bill_number VARCHAR(60) NOT NULL, bill_date DATE NOT NULL, due_date DATE,
  subtotal_paise INTEGER NOT NULL, tax_paise INTEGER NOT NULL DEFAULT 0, tds_paise INTEGER NOT NULL DEFAULT 0, total_paise INTEGER NOT NULL, file_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'received', -- received | verified | approved | paid | rejected | on_hold
  workflow_instance_id UUID, paid_at TIMESTAMPTZ, payment_ref VARCHAR(60), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (supplier_id, bill_number)
);

CREATE TABLE amc_contracts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  supplier_id UUID NOT NULL REFERENCES suppliers(id), asset_category VARCHAR(60), asset_ids JSONB, from_on DATE NOT NULL, to_on DATE NOT NULL, value_paise BIGINT, sla JSONB, document_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 22. ACCOUNTING & BUDGET =====================================
CREATE TABLE ledger_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  code VARCHAR(20) NOT NULL, name VARCHAR(120) NOT NULL, account_type VARCHAR(20) NOT NULL, -- income | expense | asset | liability | equity
  parent_id UUID REFERENCES ledger_accounts(id), external_ref VARCHAR(60), is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, code)
);
ALTER TABLE fee_heads ADD CONSTRAINT fk_fee_heads_ledger FOREIGN KEY (ledger_account_id) REFERENCES ledger_accounts(id) ON DELETE SET NULL;

CREATE TABLE income_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), ledger_account_id UUID NOT NULL REFERENCES ledger_accounts(id), amount_paise BIGINT NOT NULL, received_on DATE NOT NULL, source_type VARCHAR(40), source_id UUID,
  description VARCHAR(255), reference_no VARCHAR(80), payment_mode VARCHAR(20), recorded_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE expense_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), department_id UUID REFERENCES departments(id), ledger_account_id UUID NOT NULL REFERENCES ledger_accounts(id), budget_head_id UUID,
  amount_paise BIGINT NOT NULL, spent_on DATE NOT NULL, payee VARCHAR(200), description VARCHAR(255), reference_no VARCHAR(80), vendor_bill_id UUID REFERENCES vendor_bills(id), document_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'recorded', -- recorded | approved | paid | rejected
  approved_by UUID, workflow_instance_id UUID, recorded_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE budget_heads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  academic_year_id UUID NOT NULL REFERENCES academic_years(id), college_id UUID REFERENCES colleges(id), department_id UUID REFERENCES departments(id), name VARCHAR(120) NOT NULL, ledger_account_id UUID REFERENCES ledger_accounts(id),
  allocated_paise BIGINT NOT NULL DEFAULT 0, utilised_paise BIGINT NOT NULL DEFAULT 0, committed_paise BIGINT NOT NULL DEFAULT 0, status VARCHAR(20) NOT NULL DEFAULT 'approved',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (academic_year_id, college_id, department_id, name)
);
ALTER TABLE expense_records ADD CONSTRAINT fk_expense_budget_head FOREIGN KEY (budget_head_id) REFERENCES budget_heads(id) ON DELETE SET NULL;
ALTER TABLE indents ADD CONSTRAINT fk_indents_budget_head FOREIGN KEY (budget_head_id) REFERENCES budget_heads(id) ON DELETE SET NULL;

CREATE TABLE grant_ledgers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  research_project_id UUID, name VARCHAR(160) NOT NULL, funding_agency VARCHAR(160), sanctioned_paise BIGINT NOT NULL, received_paise BIGINT NOT NULL DEFAULT 0, utilised_paise BIGINT NOT NULL DEFAULT 0,
  budget_heads JSONB, status VARCHAR(20) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE bank_reconciliations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  bank_account VARCHAR(60) NOT NULL, statement_date DATE NOT NULL, statement_balance_paise BIGINT NOT NULL, ledger_balance_paise BIGINT NOT NULL, difference_paise BIGINT NOT NULL, items JSONB,
  status VARCHAR(20) NOT NULL DEFAULT 'open', reconciled_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE accounting_exports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  target VARCHAR(20) NOT NULL, -- tally | zoho | csv
  period_from DATE NOT NULL, period_to DATE NOT NULL, file_url TEXT, status VARCHAR(20) NOT NULL DEFAULT 'queued', job_id UUID, requested_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 23. COMMUNICATION =====================================
CREATE TABLE notification_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE, -- NULL = platform default
  event_trigger VARCHAR(80) NOT NULL, name VARCHAR(120) NOT NULL, channels JSONB NOT NULL DEFAULT '["in_app"]', subject_template TEXT, body_template TEXT NOT NULL, variables JSONB,
  language VARCHAR(10) NOT NULL DEFAULT 'en', version INT NOT NULL DEFAULT 1, is_active BOOLEAN NOT NULL DEFAULT TRUE, dlt_template_id VARCHAR(40), whatsapp_template_name VARCHAR(120),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, event_trigger, language, version)
);

CREATE TABLE dlt_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  sender_id VARCHAR(10) NOT NULL, entity_id VARCHAR(30), template_id VARCHAR(40) NOT NULL, template_text TEXT NOT NULL, category VARCHAR(20) NOT NULL DEFAULT 'transactional', status VARCHAR(20) NOT NULL DEFAULT 'approved',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, template_id)
);

CREATE TABLE whatsapp_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(120) NOT NULL, language VARCHAR(10) NOT NULL DEFAULT 'en', category VARCHAR(20) NOT NULL, body TEXT NOT NULL, components JSONB, status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | approved | rejected
  meta_template_id VARCHAR(60), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, name, language)
);

CREATE TABLE notification_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, category VARCHAR(40) NOT NULL, channels JSONB NOT NULL, quiet_hours JSONB, digest VARCHAR(20) NOT NULL DEFAULT 'none', -- none | daily | weekly
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (user_id, category)
);

CREATE TABLE notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, title VARCHAR(200) NOT NULL, body TEXT, category VARCHAR(40), event_type VARCHAR(80), link JSONB, is_read BOOLEAN NOT NULL DEFAULT FALSE, read_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_notifications_user_unread ON notifications (user_id, created_at DESC) WHERE NOT is_read;

CREATE TABLE message_logs (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  institution_id UUID, user_id UUID, recipient VARCHAR(200) NOT NULL, channel VARCHAR(20) NOT NULL, -- sms | whatsapp | email | push | in_app
  event_type VARCHAR(80), template_id UUID, campaign_id UUID, subject VARCHAR(255), body_preview VARCHAR(255), provider VARCHAR(30), provider_message_id VARCHAR(120),
  status VARCHAR(20) NOT NULL DEFAULT 'queued', -- queued | sent | delivered | failed | bounced | read
  error TEXT, cost_paise INTEGER, event_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), sent_at TIMESTAMPTZ, delivered_at TIMESTAMPTZ,
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE TABLE message_logs_default PARTITION OF message_logs DEFAULT;

CREATE TABLE bulk_campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(160) NOT NULL, channels JSONB NOT NULL, audience_rules JSONB NOT NULL, template_id UUID REFERENCES notification_templates(id), body_override TEXT, scheduled_at TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | scheduled | sending | sent | cancelled
  is_emergency BOOLEAN NOT NULL DEFAULT FALSE, total_recipients INT, sent_count INT NOT NULL DEFAULT 0, failed_count INT NOT NULL DEFAULT 0, job_id UUID, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE announcements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), title VARCHAR(200) NOT NULL, body TEXT NOT NULL, category VARCHAR(30), audience_rules JSONB, attachments JSONB,
  publish_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, requires_ack BOOLEAN NOT NULL DEFAULT FALSE, is_pinned BOOLEAN NOT NULL DEFAULT FALSE, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ
);

CREATE TABLE announcement_acknowledgements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  announcement_id UUID NOT NULL REFERENCES announcements(id) ON DELETE CASCADE, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, read_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), acknowledged_at TIMESTAMPTZ,
  UNIQUE (announcement_id, user_id)
);

CREATE TABLE emergency_alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  raised_by_user_id UUID NOT NULL, alert_type VARCHAR(20) NOT NULL, -- sos | fire | medical | security
  location JSONB, message TEXT, status VARCHAR(20) NOT NULL DEFAULT 'raised', -- raised | acknowledged | resolved
  responders JSONB, acknowledged_by UUID, acknowledged_at TIMESTAMPTZ, resolved_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE conversation_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  channel VARCHAR(20) NOT NULL, -- web | whatsapp
  external_id VARCHAR(120), user_id UUID REFERENCES users(id), flow_key VARCHAR(60), state JSONB, messages JSONB, last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE wa_processed_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE, wa_message_id VARCHAR(120) NOT NULL UNIQUE, processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 24. CALENDAR, EVENTS, FACILITIES =====================================
CREATE TABLE calendar_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), title VARCHAR(200) NOT NULL, description TEXT, event_type VARCHAR(30) NOT NULL DEFAULT 'general', -- general | academic | exam | holiday | registration | deadline | meeting
  starts_at TIMESTAMPTZ NOT NULL, ends_at TIMESTAMPTZ, all_day BOOLEAN NOT NULL DEFAULT FALSE, location VARCHAR(200), audience_rules JSONB, source_type VARCHAR(40), source_id UUID, color VARCHAR(10),
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ
);

CREATE TABLE calendar_feed_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash VARCHAR(64) NOT NULL UNIQUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), revoked_at TIMESTAMPTZ
);

CREATE TABLE events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), event_type VARCHAR(20) NOT NULL, -- conference | seminar | workshop | fdp | guest_lecture | cultural | sports | outreach | exhibition | alumni | convocation | other
  title VARCHAR(200) NOT NULL, description TEXT, organiser_department_id UUID REFERENCES departments(id), organiser_staff_id UUID REFERENCES staff(id), from_on DATE NOT NULL, to_on DATE NOT NULL,
  venue_room_id UUID REFERENCES rooms(id), venue_text VARCHAR(200), budget_paise BIGINT, sponsor JSONB, participants_count INT, external_participants_count INT, report_url TEXT, images JSONB,
  naac_criterion VARCHAR(10), registration_fee_paise INTEGER, status VARCHAR(20) NOT NULL DEFAULT 'proposed', -- proposed | approved | scheduled | completed | cancelled
  workflow_instance_id UUID, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ
);

CREATE TABLE event_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE, person_type VARCHAR(20) NOT NULL, -- student | staff | external
  person_id UUID, external JSONB, fee_invoice_id UUID REFERENCES fee_invoices(id), attended BOOLEAN NOT NULL DEFAULT FALSE, certificate_document_id UUID, registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE room_bookings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  room_id UUID NOT NULL REFERENCES rooms(id), requested_by UUID NOT NULL, purpose VARCHAR(200) NOT NULL, from_at TIMESTAMPTZ NOT NULL, to_at TIMESTAMPTZ NOT NULL, expected_headcount SMALLINT, event_id UUID REFERENCES events(id),
  workflow_instance_id UUID, status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | approved | rejected | cancelled
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE equipment_bookings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  asset_id UUID NOT NULL REFERENCES assets(id), requested_by UUID NOT NULL, from_at TIMESTAMPTZ NOT NULL, to_at TIMESTAMPTZ NOT NULL, purpose VARCHAR(200), status VARCHAR(20) NOT NULL DEFAULT 'requested', approved_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE service_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), ticket_number VARCHAR(30) NOT NULL, category VARCHAR(20) NOT NULL, -- electrical | plumbing | it | network | furniture | cleaning | civil | security | other
  location_room_id UUID REFERENCES rooms(id), location_text VARCHAR(200), description TEXT NOT NULL, attachments JSONB, priority VARCHAR(10) NOT NULL DEFAULT 'normal',
  requested_by UUID NOT NULL, assigned_to UUID, vendor_id UUID REFERENCES suppliers(id), sla_due_at TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'open', -- open | assigned | in_progress | resolved | closed | reopened
  resolution TEXT, rating SMALLINT, resolved_at TIMESTAMPTZ, closed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, ticket_number)
);
ALTER TABLE hostel_complaints ADD CONSTRAINT fk_hostel_complaints_sr FOREIGN KEY (service_request_id) REFERENCES service_requests(id) ON DELETE SET NULL;

CREATE TABLE visitor_passes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), visitor JSONB NOT NULL, host_user_id UUID, purpose VARCHAR(200), valid_from TIMESTAMPTZ NOT NULL, valid_to TIMESTAMPTZ NOT NULL,
  gate_in_at TIMESTAMPTZ, gate_out_at TIMESTAMPTZ, vehicle_no VARCHAR(20), id_proof JSONB, pass_code VARCHAR(20), status VARCHAR(20) NOT NULL DEFAULT 'issued', -- issued | inside | exited | expired | cancelled
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE health_visits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  person_type VARCHAR(10) NOT NULL, person_id UUID NOT NULL, visited_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), complaint TEXT, diagnosis TEXT, treatment TEXT, referred_to VARCHAR(200), attended_by UUID,
  is_confidential BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE insurance_policies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  person_type VARCHAR(10) NOT NULL, person_id UUID NOT NULL, provider VARCHAR(120) NOT NULL, policy_no VARCHAR(60) NOT NULL, coverage_paise BIGINT, valid_from DATE, valid_to DATE, document_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE counselling_appointments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  counsellor_staff_id UUID NOT NULL REFERENCES staff(id), slot_at TIMESTAMPTZ NOT NULL, duration_minutes SMALLINT NOT NULL DEFAULT 30, person_type VARCHAR(10), person_id UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'available', -- available | booked | completed | cancelled | no_show
  is_confidential BOOLEAN NOT NULL DEFAULT TRUE, notes_encrypted BYTEA, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE sports_teams (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), sport VARCHAR(60) NOT NULL, name VARCHAR(120), level VARCHAR(20) NOT NULL DEFAULT 'institution', coach_staff_id UUID REFERENCES staff(id), members JSONB,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE sports_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  title VARCHAR(200) NOT NULL, sport VARCHAR(60), level VARCHAR(20) NOT NULL, -- institution | inter_college | university | state | national | international
  from_on DATE NOT NULL, to_on DATE, venue VARCHAR(200), organiser VARCHAR(200), event_id UUID REFERENCES events(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE sports_participation (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  sports_event_id UUID NOT NULL REFERENCES sports_events(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id), team_id UUID REFERENCES sports_teams(id),
  result VARCHAR(60), position VARCHAR(20), evidence_url TEXT, verified_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE lost_found_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  description TEXT NOT NULL, found_at TIMESTAMPTZ, location VARCHAR(200), image_url TEXT, reported_by UUID, status VARCHAR(20) NOT NULL DEFAULT 'reported', -- reported | claimed | disposed
  claimant JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE canteens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), name VARCHAR(120) NOT NULL, location VARCHAR(200), vendor_id UUID REFERENCES suppliers(id), menu JSONB, is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE wallet_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  person_type VARCHAR(10) NOT NULL, person_id UUID NOT NULL, balance_paise INTEGER NOT NULL DEFAULT 0, status VARCHAR(20) NOT NULL DEFAULT 'active', updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (person_type, person_id)
);

CREATE TABLE wallet_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  account_id UUID NOT NULL REFERENCES wallet_accounts(id) ON DELETE CASCADE, txn_type VARCHAR(10) NOT NULL, -- topup | debit | refund
  amount_paise INTEGER NOT NULL, merchant VARCHAR(120), reference VARCHAR(80), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 25. DOCUMENTS & CERTIFICATES =====================================
CREATE TABLE document_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE, -- NULL = platform/pack default
  template_type VARCHAR(40) NOT NULL, -- id_card | bonafide | character | conduct | noc | tc | migration | course_completion | provisional | degree | grade_card | transcript | hall_ticket | receipt | experience | service | internship_noc | hostel_allotment | event_certificate | undertaking | custom
  name VARCHAR(120) NOT NULL, layout JSONB, html_template TEXT, css TEXT, page_size VARCHAR(20) NOT NULL DEFAULT 'A4', is_bilingual BOOLEAN NOT NULL DEFAULT FALSE, secondary_language VARCHAR(10),
  variables JSONB, is_default BOOLEAN NOT NULL DEFAULT FALSE, version INT NOT NULL DEFAULT 1, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ
);
ALTER TABLE student_undertakings ADD CONSTRAINT fk_undertakings_template FOREIGN KEY (template_id) REFERENCES document_templates(id) ON DELETE SET NULL;
ALTER TABLE grade_cards ADD CONSTRAINT fk_grade_cards_template FOREIGN KEY (template_id) REFERENCES document_templates(id) ON DELETE SET NULL;
ALTER TABLE hostels ADD CONSTRAINT fk_hostels_rules_template FOREIGN KEY (rules_template_id) REFERENCES document_templates(id) ON DELETE SET NULL;

CREATE TABLE certificate_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  requester_user_id UUID NOT NULL REFERENCES users(id), person_type VARCHAR(10) NOT NULL, -- student | staff | alumni
  person_id UUID NOT NULL, template_type VARCHAR(40) NOT NULL, purpose VARCHAR(200), copies SMALLINT NOT NULL DEFAULT 1, delivery VARCHAR(20) NOT NULL DEFAULT 'digital', -- digital | pickup | post
  fee_invoice_id UUID REFERENCES fee_invoices(id), workflow_instance_id UUID, status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | fee_pending | approved | generated | issued | rejected
  issued_document_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE issued_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  template_id UUID REFERENCES document_templates(id), template_type VARCHAR(40) NOT NULL, person_type VARCHAR(10), person_id UUID, entity_type VARCHAR(40), entity_id UUID,
  document_number VARCHAR(40) NOT NULL, serial_no VARCHAR(40), pdf_url TEXT NOT NULL, verification_token VARCHAR(64) NOT NULL UNIQUE, content_hash VARCHAR(64) NOT NULL, watermark_text VARCHAR(120),
  issued_by UUID, issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), revoked_at TIMESTAMPTZ, revoke_reason TEXT, job_id UUID, UNIQUE (institution_id, document_number)
);
ALTER TABLE certificate_requests ADD CONSTRAINT fk_certificate_requests_document FOREIGN KEY (issued_document_id) REFERENCES issued_documents(id) ON DELETE SET NULL;
ALTER TABLE event_registrations ADD CONSTRAINT fk_event_registrations_certificate FOREIGN KEY (certificate_document_id) REFERENCES issued_documents(id) ON DELETE SET NULL;
ALTER TABLE no_dues_requests ADD CONSTRAINT fk_no_dues_certificate FOREIGN KEY (certificate_document_id) REFERENCES issued_documents(id) ON DELETE SET NULL;

CREATE TABLE document_serials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  register VARCHAR(40) NOT NULL, serial_no VARCHAR(40) NOT NULL, issued_document_id UUID REFERENCES issued_documents(id), status VARCHAR(20) NOT NULL DEFAULT 'used', -- reserved | used | void
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, register, serial_no)
);

-- ===================================== 26. STUDENT SUPPORT =====================================
CREATE TABLE mentor_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  mentor_staff_id UUID NOT NULL REFERENCES staff(id), student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, term_id UUID NOT NULL REFERENCES academic_terms(id),
  from_on DATE, to_on DATE, status VARCHAR(20) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (student_program_enrollment_id, term_id)
);

CREATE TABLE mentoring_slots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  mentor_staff_id UUID NOT NULL REFERENCES staff(id), starts_at TIMESTAMPTZ NOT NULL, ends_at TIMESTAMPTZ NOT NULL, capacity SMALLINT NOT NULL DEFAULT 1, location VARCHAR(120), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE mentoring_bookings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  slot_id UUID NOT NULL REFERENCES mentoring_slots(id) ON DELETE CASCADE, student_program_enrollment_id UUID REFERENCES student_program_enrollments(id), guardian_user_id UUID REFERENCES users(id),
  status VARCHAR(20) NOT NULL DEFAULT 'booked', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE mentoring_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  mentor_assignment_id UUID NOT NULL REFERENCES mentor_assignments(id) ON DELETE CASCADE, held_on DATE NOT NULL, mode VARCHAR(20) NOT NULL DEFAULT 'in_person', notes TEXT, concerns JSONB, action_items JSONB, follow_up_on DATE,
  is_confidential BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE counselling_referrals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, referred_by UUID NOT NULL, counsellor_staff_id UUID REFERENCES staff(id), reason TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'referred', -- referred | scheduled | in_progress | closed
  is_confidential BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE risk_flags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, term_id UUID REFERENCES academic_terms(id), score NUMERIC(5,2) NOT NULL, factors JSONB NOT NULL,
  level VARCHAR(10) NOT NULL, -- low | medium | high
  computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), acknowledged_by UUID, acknowledged_at TIMESTAMPTZ, UNIQUE (student_program_enrollment_id, term_id)
);

CREATE TABLE grievances (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), ticket_number VARCHAR(30) NOT NULL, raised_by_user_id UUID REFERENCES users(id), student_program_enrollment_id UUID REFERENCES student_program_enrollments(id),
  category VARCHAR(20) NOT NULL, -- academic | exam | fee | hostel | harassment | ragging | discrimination | infrastructure | other
  is_anonymous BOOLEAN NOT NULL DEFAULT FALSE, description TEXT NOT NULL, attachments JSONB, priority VARCHAR(10) NOT NULL DEFAULT 'normal',
  committee VARCHAR(20), -- grievance_cell | icc | anti_ragging | sc_st_cell | obc_cell
  committee_id UUID, assigned_to UUID, sla_due_at TIMESTAMPTZ, status VARCHAR(20) NOT NULL DEFAULT 'open', -- open | acknowledged | under_review | resolved | closed | escalated | reopened
  resolution TEXT, resolved_at TIMESTAMPTZ, satisfaction_rating SMALLINT, workflow_instance_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, ticket_number)
);

CREATE TABLE grievance_updates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  grievance_id UUID NOT NULL REFERENCES grievances(id) ON DELETE CASCADE, by_user_id UUID, note TEXT NOT NULL, is_internal BOOLEAN NOT NULL DEFAULT FALSE, attachments JSONB, at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE disciplinary_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  subject_type VARCHAR(10) NOT NULL, -- student | staff
  subject_id UUID NOT NULL, case_number VARCHAR(30) NOT NULL, category VARCHAR(40) NOT NULL, description TEXT NOT NULL, evidence JSONB, reported_by UUID, committee_id UUID, hearing_at TIMESTAMPTZ,
  sanctions JSONB, fee_invoice_id UUID REFERENCES fee_invoices(id), appeal_status VARCHAR(20), decided_by UUID, decided_at TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'reported', -- reported | inquiry | hearing | decided | appealed | closed
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, case_number)
);

CREATE TABLE feedback_surveys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), survey_type VARCHAR(20) NOT NULL, -- course | faculty | institution | course_exit | program_exit | alumni | employer | hostel | parent | sss
  term_id UUID REFERENCES academic_terms(id), title VARCHAR(200) NOT NULL, questions JSONB NOT NULL, audience_rules JSONB, is_anonymous BOOLEAN NOT NULL DEFAULT TRUE, opens_at TIMESTAMPTZ, closes_at TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | open | closed | analysed
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE feedback_responses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  survey_id UUID NOT NULL REFERENCES feedback_surveys(id) ON DELETE CASCADE, respondent_hash VARCHAR(64) NOT NULL, target_type VARCHAR(20) NOT NULL, -- offering | staff | institution | program | hostel
  target_id UUID, answers JSONB NOT NULL, submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (survey_id, respondent_hash, target_id)
);

CREATE TABLE clubs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), name VARCHAR(120) NOT NULL, club_type VARCHAR(20) NOT NULL, -- technical | cultural | sports | social | professional_chapter | nss | ncc | extension
  faculty_advisor_id UUID REFERENCES staff(id), description TEXT, budget_paise BIGINT, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (institution_id, name)
);

CREATE TABLE club_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  club_id UUID NOT NULL REFERENCES clubs(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  role VARCHAR(20) NOT NULL DEFAULT 'member', from_on DATE, to_on DATE, UNIQUE (club_id, student_program_enrollment_id)
);

CREATE TABLE club_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  club_id UUID NOT NULL REFERENCES clubs(id) ON DELETE CASCADE, title VARCHAR(200) NOT NULL, held_on DATE, venue VARCHAR(200), participants_count INT, budget_paise BIGINT, report_url TEXT, images JSONB, event_id UUID REFERENCES events(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE activity_hours (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, activity_type VARCHAR(20) NOT NULL, -- nss | ncc | community_service | club | sports
  hours NUMERIC(5,1) NOT NULL, on_date DATE NOT NULL, description VARCHAR(200), evidence_url TEXT, verified_by UUID, verified_at TIMESTAMPTZ, credits_course_id UUID REFERENCES courses(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE student_achievements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, category VARCHAR(20) NOT NULL, -- sports | cultural | technical | research | hackathon | other
  title VARCHAR(200) NOT NULL, level VARCHAR(20), position VARCHAR(20), held_on DATE, evidence_url TEXT, verified_by UUID, verified_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 27. PLACEMENT & ALUMNI =====================================
CREATE TABLE companies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(200) NOT NULL, sector VARCHAR(80), website TEXT, hq_city VARCHAR(80), tier VARCHAR(20), -- dream | super_dream | core | mass
  contacts JSONB, recruiter_user_ids JSONB, is_blacklisted BOOLEAN NOT NULL DEFAULT FALSE, notes TEXT, logo_url TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, version INT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), deleted_at TIMESTAMPTZ, deleted_by UUID,
  UNIQUE (institution_id, name)
);

CREATE TABLE placement_drives (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), company_id UUID NOT NULL REFERENCES companies(id), title VARCHAR(200) NOT NULL, job_role VARCHAR(120), job_type VARCHAR(20) NOT NULL DEFAULT 'full_time', -- full_time | internship | intern_ppo | part_time
  ctc_min_paise BIGINT, ctc_max_paise BIGINT, stipend_paise INTEGER, locations JSONB, bond JSONB, eligibility_rules JSONB NOT NULL DEFAULT '{}', registration_deadline TIMESTAMPTZ, drive_on DATE,
  mode VARCHAR(20) NOT NULL DEFAULT 'on_campus', -- on_campus | off_campus | virtual | pooled
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | open | closed | in_progress | completed | cancelled
  jd_url TEXT, owner_staff_id UUID REFERENCES staff(id), created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE drive_rounds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  drive_id UUID NOT NULL REFERENCES placement_drives(id) ON DELETE CASCADE, round_no SMALLINT NOT NULL, name VARCHAR(80) NOT NULL, round_type VARCHAR(20) NOT NULL, -- pre_placement_talk | aptitude | coding | gd | technical | hr | final
  scheduled_at TIMESTAMPTZ, venue VARCHAR(200), UNIQUE (drive_id, round_no)
);

CREATE TABLE drive_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  drive_id UUID NOT NULL REFERENCES placement_drives(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  eligibility_snapshot JSONB, is_eligible BOOLEAN NOT NULL DEFAULT TRUE, override_by UUID, override_reason TEXT, resume_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'applied', -- applied | ineligible | shortlisted | in_process | rejected | selected | offer_accepted | offer_declined | withdrawn | absent
  applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (drive_id, student_program_enrollment_id)
);

CREATE TABLE drive_round_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  application_id UUID NOT NULL REFERENCES drive_applications(id) ON DELETE CASCADE, round_id UUID NOT NULL REFERENCES drive_rounds(id) ON DELETE CASCADE,
  status VARCHAR(20) NOT NULL DEFAULT 'pending', -- cleared | not_cleared | absent | pending
  score NUMERIC(6,2), remarks TEXT, recorded_by UUID, recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (application_id, round_id)
);

CREATE TABLE placement_offers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  application_id UUID NOT NULL UNIQUE REFERENCES drive_applications(id) ON DELETE CASCADE, company_id UUID NOT NULL REFERENCES companies(id), role VARCHAR(120), ctc_paise BIGINT NOT NULL, ctc_breakup JSONB, location VARCHAR(120),
  offer_letter_url TEXT, offered_on DATE, joining_on DATE, status VARCHAR(20) NOT NULL DEFAULT 'offered', -- offered | accepted | declined | revoked | joined | not_joined
  is_ppo BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE placement_policies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  batch_id UUID REFERENCES batches(id), program_id UUID REFERENCES programs(id), max_offers SMALLINT NOT NULL DEFAULT 1, dream_ctc_threshold_paise BIGINT, allow_upgrade_if_dream BOOLEAN NOT NULL DEFAULT TRUE,
  opt_out_allowed BOOLEAN NOT NULL DEFAULT TRUE, rules JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE student_placement_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL UNIQUE REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  resume_url TEXT, resume_json JSONB, skills JSONB, is_opted_out BOOLEAN NOT NULL DEFAULT FALSE, opt_out_reason VARCHAR(30), higher_studies JSONB,
  placement_status VARCHAR(20) NOT NULL DEFAULT 'unplaced', -- unplaced | placed | multiple | opted_out
  is_blacklisted BOOLEAN NOT NULL DEFAULT FALSE, blacklist_reason TEXT, consent_share_profile BOOLEAN NOT NULL DEFAULT TRUE, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE internships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE, company_id UUID REFERENCES companies(id), company_name VARCHAR(200), role VARCHAR(120),
  from_on DATE NOT NULL, to_on DATE, stipend_paise INTEGER, mentor VARCHAR(160), evaluation JSONB, certificate_url TEXT, noc_document_id UUID REFERENCES issued_documents(id), credits_course_id UUID REFERENCES courses(id),
  status VARCHAR(20) NOT NULL DEFAULT 'ongoing', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE training_programs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  training_type VARCHAR(20) NOT NULL, -- aptitude | soft_skills | technical | mock_interview
  title VARCHAR(200) NOT NULL, trainer VARCHAR(160), from_on DATE, to_on DATE, batches JSONB, sessions JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE training_attendance (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  program_id UUID NOT NULL REFERENCES training_programs(id) ON DELETE CASCADE, student_program_enrollment_id UUID NOT NULL REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  sessions_attended SMALLINT NOT NULL DEFAULT 0, score NUMERIC(6,2), UNIQUE (program_id, student_program_enrollment_id)
);

CREATE TABLE company_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  drive_id UUID NOT NULL REFERENCES placement_drives(id) ON DELETE CASCADE, ratings JSONB, remarks TEXT, submitted_by UUID, submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE alumni_profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_id UUID NOT NULL UNIQUE REFERENCES students(id), user_id UUID REFERENCES users(id), graduation_year SMALLINT, program_id UUID REFERENCES programs(id),
  current_company VARCHAR(200), designation VARCHAR(120), city VARCHAR(80), country VARCHAR(80), linkedin_url TEXT, email VARCHAR(200), phone VARCHAR(20),
  is_verified BOOLEAN NOT NULL DEFAULT FALSE, willing_to_mentor BOOLEAN NOT NULL DEFAULT FALSE, willing_to_recruit BOOLEAN NOT NULL DEFAULT FALSE, consent_contact BOOLEAN NOT NULL DEFAULT FALSE,
  last_updated_by_alumni_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE alumni_employment_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  alumni_id UUID NOT NULL REFERENCES alumni_profiles(id) ON DELETE CASCADE, company VARCHAR(200) NOT NULL, designation VARCHAR(120), from_on DATE, to_on DATE, is_current BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE alumni_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  title VARCHAR(200) NOT NULL, held_on DATE, venue VARCHAR(200), event_type VARCHAR(20) NOT NULL DEFAULT 'meet', -- meet | webinar | reunion | mentorship
  registrations_count INT NOT NULL DEFAULT 0, event_id UUID REFERENCES events(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE alumni_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  posted_by_alumni_id UUID REFERENCES alumni_profiles(id), title VARCHAR(200) NOT NULL, company VARCHAR(200), location VARCHAR(120), description TEXT, apply_url TEXT, expires_on DATE, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE fundraising_campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  title VARCHAR(200) NOT NULL, purpose TEXT, goal_paise BIGINT, raised_paise BIGINT NOT NULL DEFAULT 0, from_on DATE, to_on DATE, status VARCHAR(20) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE donations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  donor_type VARCHAR(20) NOT NULL, -- alumni | corporate | individual
  donor_ref JSONB NOT NULL, campaign_id UUID REFERENCES fundraising_campaigns(id), amount_paise BIGINT NOT NULL, on_date DATE NOT NULL, mode VARCHAR(20), receipt_no VARCHAR(40), is_80g BOOLEAN NOT NULL DEFAULT FALSE,
  pan_encrypted BYTEA, receipt_document_id UUID REFERENCES issued_documents(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 28. RESEARCH & PHD =====================================
CREATE TABLE publications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID REFERENCES staff(id), scholar_id UUID, pub_type VARCHAR(20) NOT NULL, -- journal | conference | book | chapter | patent_pub
  title VARCHAR(500) NOT NULL, venue VARCHAR(300), year SMALLINT, doi VARCHAR(120), issn_isbn VARCHAR(30), indexing VARCHAR(20), -- sci | scie | scopus | wos | ugc_care | other | none
  impact_factor NUMERIC(6,3), authors JSONB, author_position SMALLINT, citations INT, evidence_url TEXT, is_verified BOOLEAN NOT NULL DEFAULT FALSE, verified_by UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE patents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID REFERENCES staff(id), title VARCHAR(500) NOT NULL, application_no VARCHAR(60), country VARCHAR(60), filed_on DATE, published_on DATE, granted_on DATE,
  status VARCHAR(20) NOT NULL DEFAULT 'filed', -- filed | published | granted | commercialised
  co_inventors JSONB, evidence_url TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE ethics_committees (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  committee_type VARCHAR(10) NOT NULL, -- iec | iaec | ibsc
  committee_id UUID, members JSONB, registration_no VARCHAR(60), is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE ethics_approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  ethics_committee_id UUID NOT NULL REFERENCES ethics_committees(id), project_title VARCHAR(500) NOT NULL, pi_staff_id UUID REFERENCES staff(id), submitted_on DATE, decision VARCHAR(20), -- approved | revise | rejected
  approval_no VARCHAR(60), valid_to DATE, document_url TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE research_projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  pi_staff_id UUID NOT NULL REFERENCES staff(id), co_pi JSONB, title VARCHAR(500) NOT NULL, funding_agency VARCHAR(200), scheme VARCHAR(160), sanctioned_paise BIGINT, received_paise BIGINT NOT NULL DEFAULT 0,
  start_on DATE, end_on DATE, status VARCHAR(20) NOT NULL DEFAULT 'applied', -- applied | sanctioned | ongoing | completed | closed
  utilisation JSONB, budget_heads JSONB, ethics_approval_id UUID REFERENCES ethics_approvals(id), grant_ledger_id UUID REFERENCES grant_ledgers(id), sanction_letter_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE grant_ledgers ADD CONSTRAINT fk_grant_ledgers_project FOREIGN KEY (research_project_id) REFERENCES research_projects(id) ON DELETE SET NULL;

CREATE TABLE consultancies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id), client VARCHAR(200) NOT NULL, title VARCHAR(300), amount_paise BIGINT, institution_share_paise BIGINT, start_on DATE, end_on DATE, status VARCHAR(20) NOT NULL DEFAULT 'ongoing',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE research_incentives (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  incentive_type VARCHAR(30) NOT NULL, -- seed_grant | publication_incentive | travel_grant | patent_filing_support
  staff_id UUID NOT NULL REFERENCES staff(id), amount_paise BIGINT NOT NULL, justification TEXT, linked_entity JSONB, workflow_instance_id UUID,
  status VARCHAR(20) NOT NULL DEFAULT 'requested', -- requested | approved | disbursed | rejected
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE faculty_developments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE, event_type VARCHAR(20) NOT NULL, -- fdp | workshop | conference | certification | mooc | industry_training
  title VARCHAR(300) NOT NULL, organiser VARCHAR(200), from_on DATE, to_on DATE, role VARCHAR(20) NOT NULL DEFAULT 'attended', -- attended | organised | resource_person
  hours NUMERIC(5,1), certificate_url TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE faculty_awards (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  staff_id UUID NOT NULL REFERENCES staff(id) ON DELETE CASCADE, title VARCHAR(300) NOT NULL, agency VARCHAR(200), year SMALLINT, level VARCHAR(20), evidence_url TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE mous (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  partner VARCHAR(200) NOT NULL, partner_type VARCHAR(20) NOT NULL, -- industry | university | government | ngo
  country VARCHAR(60), mou_type VARCHAR(20) NOT NULL, -- academic | research | placement | exchange
  signed_on DATE, valid_to DATE, activities JSONB, document_url TEXT, coordinator_staff_id UUID REFERENCES staff(id), status VARCHAR(20) NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE collaborations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  mou_id UUID REFERENCES mous(id), title VARCHAR(300) NOT NULL, collaboration_type VARCHAR(20) NOT NULL, -- joint_research | exchange | joint_degree | internship
  participants JSONB, from_on DATE, to_on DATE, outcomes JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE incubation_startups (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(200) NOT NULL, founders JSONB, sector VARCHAR(80), stage VARCHAR(20) NOT NULL DEFAULT 'idea', -- idea | prototype | incubated | funded | graduated
  funding_paise BIGINT, mentor_staff_id UUID REFERENCES staff(id), registered_on DATE, status VARCHAR(20) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE research_scholars (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  student_program_enrollment_id UUID NOT NULL UNIQUE REFERENCES student_program_enrollments(id) ON DELETE CASCADE,
  guide_staff_id UUID NOT NULL REFERENCES staff(id), co_guide_staff_id UUID REFERENCES staff(id), external_co_guide JSONB, mode VARCHAR(20) NOT NULL DEFAULT 'full_time', -- full_time | part_time
  fellowship_type VARCHAR(20) NOT NULL DEFAULT 'none', -- jrf | srf | institution | project | none
  registration_date DATE, coursework_status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | in_progress | completed | exempted
  coursework_exemption_reason TEXT, research_area VARCHAR(300), max_duration_end DATE,
  status VARCHAR(30) NOT NULL DEFAULT 'admitted', -- admitted | coursework | registered | synopsis_submitted | thesis_submitted | under_evaluation | viva_scheduled | awarded | discontinued
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE publications ADD CONSTRAINT fk_publications_scholar FOREIGN KEY (scholar_id) REFERENCES research_scholars(id) ON DELETE SET NULL;

CREATE TABLE doctoral_committees (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scholar_id UUID NOT NULL UNIQUE REFERENCES research_scholars(id) ON DELETE CASCADE, members JSONB NOT NULL, constituted_on DATE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE dc_meetings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scholar_id UUID NOT NULL REFERENCES research_scholars(id) ON DELETE CASCADE, meeting_no SMALLINT NOT NULL, held_on DATE, minutes TEXT, recommendations JSONB, minutes_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'scheduled', -- scheduled | held | approved
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (scholar_id, meeting_no)
);

CREATE TABLE scholar_progress_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scholar_id UUID NOT NULL REFERENCES research_scholars(id) ON DELETE CASCADE, period_label VARCHAR(20) NOT NULL, report_url TEXT, summary TEXT, guide_remarks TEXT, dc_rating VARCHAR(20), -- satisfactory | unsatisfactory
  status VARCHAR(20) NOT NULL DEFAULT 'submitted', -- submitted | guide_reviewed | dc_reviewed
  submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), reviewed_at TIMESTAMPTZ, UNIQUE (scholar_id, period_label)
);

CREATE TABLE scholar_fellowships (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scholar_id UUID NOT NULL REFERENCES research_scholars(id) ON DELETE CASCADE, fellowship_type VARCHAR(20) NOT NULL, monthly_paise INTEGER NOT NULL, from_on DATE NOT NULL, to_on DATE, contingency_paise INTEGER, hra_applicable BOOLEAN NOT NULL DEFAULT FALSE,
  funding_source VARCHAR(120), status VARCHAR(20) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE fellowship_disbursements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  fellowship_id UUID NOT NULL REFERENCES scholar_fellowships(id) ON DELETE CASCADE, month DATE NOT NULL, amount_paise INTEGER NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'pending', payroll_ref VARCHAR(60), paid_at TIMESTAMPTZ,
  UNIQUE (fellowship_id, month)
);

CREATE TABLE scholar_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scholar_id UUID NOT NULL REFERENCES research_scholars(id) ON DELETE CASCADE, request_type VARCHAR(30) NOT NULL, -- extension | change_of_guide | mode_change | leave | coursework_exemption
  details JSONB, workflow_instance_id UUID, status VARCHAR(20) NOT NULL DEFAULT 'requested', decided_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE thesis_submissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  scholar_id UUID NOT NULL REFERENCES research_scholars(id) ON DELETE CASCADE, stage VARCHAR(20) NOT NULL, -- pre_synopsis | synopsis | thesis | revised_thesis
  title VARCHAR(500), file_url TEXT NOT NULL, submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), similarity_pct NUMERIC(5,2), plagiarism_report_url TEXT, ai_generated_pct NUMERIC(5,2),
  status VARCHAR(20) NOT NULL DEFAULT 'submitted', -- submitted | plagiarism_checked | dc_approved | rejected
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE thesis_examiners (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  thesis_id UUID NOT NULL REFERENCES thesis_submissions(id) ON DELETE CASCADE, examiner JSONB NOT NULL, is_external BOOLEAN NOT NULL DEFAULT TRUE, state VARCHAR(60), country VARCHAR(60),
  invited_at TIMESTAMPTZ, accepted_at TIMESTAMPTZ, report_url TEXT, report_received_at TIMESTAMPTZ, recommendation VARCHAR(20), -- accept | minor | major | reject
  remuneration_paise INTEGER, status VARCHAR(20) NOT NULL DEFAULT 'proposed', -- proposed | approved | invited | accepted | declined | report_received
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE viva_voce (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  thesis_id UUID NOT NULL UNIQUE REFERENCES thesis_submissions(id) ON DELETE CASCADE, scheduled_at TIMESTAMPTZ, venue_or_link VARCHAR(300), panel JSONB, held_at TIMESTAMPTZ,
  result VARCHAR(20), -- recommended | re_viva | not_recommended
  report_url TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE etd_uploads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  thesis_id UUID NOT NULL REFERENCES thesis_submissions(id) ON DELETE CASCADE, repository VARCHAR(20) NOT NULL, -- shodhganga | institutional
  handle VARCHAR(200), uploaded_at TIMESTAMPTZ, status VARCHAR(20) NOT NULL DEFAULT 'pending', job_id UUID, response JSONB
);

-- ===================================== 29. ACCREDITATION =====================================
CREATE TABLE accreditation_frameworks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code VARCHAR(30) NOT NULL UNIQUE, name VARCHAR(160) NOT NULL, version VARCHAR(20), pack VARCHAR(10) NOT NULL DEFAULT 'IN', is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE framework_criteria (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  framework_id UUID NOT NULL REFERENCES accreditation_frameworks(id) ON DELETE CASCADE, code VARCHAR(20) NOT NULL, parent_id UUID REFERENCES framework_criteria(id), title VARCHAR(300) NOT NULL, description TEXT,
  metric_type VARCHAR(20) NOT NULL DEFAULT 'quantitative', -- quantitative | qualitative | qn_ql
  max_score NUMERIC(6,2), period_type VARCHAR(20) NOT NULL DEFAULT 'academic_year', metric_key VARCHAR(80), sequence SMALLINT NOT NULL DEFAULT 1, UNIQUE (framework_id, code)
);

CREATE TABLE metric_definitions (
  key VARCHAR(80) PRIMARY KEY, name VARCHAR(160) NOT NULL, description TEXT, unit VARCHAR(20), source_module VARCHAR(40), computation_key VARCHAR(80) NOT NULL, params_schema JSONB,
  is_derived BOOLEAN NOT NULL DEFAULT FALSE, depends_on JSONB, pack VARCHAR(10) NOT NULL DEFAULT 'IN'
);

CREATE TABLE metric_values (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id) ON DELETE CASCADE, metric_key VARCHAR(80) NOT NULL REFERENCES metric_definitions(key), period_label VARCHAR(20) NOT NULL, program_id UUID REFERENCES programs(id),
  value NUMERIC(14,4), numerator NUMERIC(14,4), denominator NUMERIC(14,4), breakdown JSONB, computed_at TIMESTAMPTZ, source VARCHAR(20) NOT NULL DEFAULT 'auto', -- auto | manual | override
  overridden_by UUID, override_reason TEXT, verified_by UUID, verified_at TIMESTAMPTZ, job_id UUID,
  UNIQUE (institution_id, college_id, metric_key, period_label, program_id)
);

CREATE TABLE evidence_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  framework_criterion_id UUID REFERENCES framework_criteria(id), metric_key VARCHAR(80), period_label VARCHAR(20), title VARCHAR(200) NOT NULL, doc_type VARCHAR(40), file_url TEXT NOT NULL,
  uploaded_by UUID, verified_by UUID, verified_at TIMESTAMPTZ, tags JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE accreditation_cycles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  framework_id UUID NOT NULL REFERENCES accreditation_frameworks(id), college_id UUID REFERENCES colleges(id), program_id UUID REFERENCES programs(id), name VARCHAR(160) NOT NULL,
  period_from DATE, period_to DATE, submission_due_on DATE, coordinator_staff_id UUID REFERENCES staff(id),
  status VARCHAR(20) NOT NULL DEFAULT 'planning', -- planning | data_collection | drafting | internal_review | submitted | peer_visit | result
  score NUMERIC(5,2), grade VARCHAR(5), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE criterion_responses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  cycle_id UUID NOT NULL REFERENCES accreditation_cycles(id) ON DELETE CASCADE, framework_criterion_id UUID NOT NULL REFERENCES framework_criteria(id), narrative TEXT, metric_value_ids JSONB, evidence_ids JSONB,
  owner_staff_id UUID REFERENCES staff(id), status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | in_review | approved | final
  reviewed_by UUID, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (cycle_id, framework_criterion_id)
);

CREATE TABLE compliance_submissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  framework_id UUID REFERENCES accreditation_frameworks(id), period_label VARCHAR(20) NOT NULL, submission_type VARCHAR(20) NOT NULL, -- aqar | nirf_data | aishe | aicte_approval | ugc_annual | nsp_return
  payload JSONB, file_url TEXT, status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | generated | submitted | acknowledged
  submitted_on DATE, ack_ref VARCHAR(80), job_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_registers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  audit_type VARCHAR(30) NOT NULL, -- academic | administrative | green | energy | gender | financial_statutory | ag
  period_label VARCHAR(20) NOT NULL, auditor VARCHAR(200), report_url TEXT, findings JSONB, status VARCHAR(20) NOT NULL DEFAULT 'open', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 30. GOVERNANCE =====================================
CREATE TABLE committees (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID REFERENCES colleges(id), name VARCHAR(160) NOT NULL, committee_type VARCHAR(30) NOT NULL, -- bos | academic_council | executive_council | senate | finance | iqac | anti_ragging | icc | grievance | research_board | purchase | discipline | custom
  department_id UUID REFERENCES departments(id), chair_staff_id UUID REFERENCES staff(id), secretary_staff_id UUID REFERENCES staff(id), constituted_on DATE, valid_to DATE, quorum_rule JSONB,
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE malpractice_cases ADD CONSTRAINT fk_malpractice_committee FOREIGN KEY (committee_id) REFERENCES committees(id) ON DELETE SET NULL;
ALTER TABLE grievances ADD CONSTRAINT fk_grievances_committee FOREIGN KEY (committee_id) REFERENCES committees(id) ON DELETE SET NULL;
ALTER TABLE disciplinary_cases ADD CONSTRAINT fk_discipline_committee FOREIGN KEY (committee_id) REFERENCES committees(id) ON DELETE SET NULL;
ALTER TABLE ethics_committees ADD CONSTRAINT fk_ethics_committee FOREIGN KEY (committee_id) REFERENCES committees(id) ON DELETE SET NULL;

CREATE TABLE committee_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  committee_id UUID NOT NULL REFERENCES committees(id) ON DELETE CASCADE, member_type VARCHAR(10) NOT NULL DEFAULT 'staff', -- staff | external | student
  staff_id UUID REFERENCES staff(id), user_id UUID REFERENCES users(id), external JSONB, role VARCHAR(40) NOT NULL DEFAULT 'member', from_on DATE, to_on DATE
);

CREATE TABLE meetings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  committee_id UUID NOT NULL REFERENCES committees(id) ON DELETE CASCADE, meeting_no VARCHAR(20), held_on TIMESTAMPTZ NOT NULL, venue_or_link VARCHAR(300), agenda JSONB, quorum_met BOOLEAN, attendance JSONB,
  minutes_url TEXT, minutes_text TEXT, status VARCHAR(20) NOT NULL DEFAULT 'scheduled', -- scheduled | held | minutes_draft | minutes_approved
  created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE resolutions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE, number VARCHAR(40) NOT NULL, subject VARCHAR(300) NOT NULL, text TEXT NOT NULL, action_owner_staff_id UUID REFERENCES staff(id), due_on DATE,
  status VARCHAR(20) NOT NULL DEFAULT 'passed', -- passed | deferred | rejected | implemented
  linked_entity JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, number)
);
ALTER TABLE regulations ADD CONSTRAINT fk_regulations_resolution FOREIGN KEY (approval_resolution_id) REFERENCES resolutions(id) ON DELETE SET NULL;
ALTER TABLE result_processing_runs ADD CONSTRAINT fk_result_runs_resolution FOREIGN KEY (approval_resolution_id) REFERENCES resolutions(id) ON DELETE SET NULL;
ALTER TABLE degrees_awarded ADD CONSTRAINT fk_degrees_resolution FOREIGN KEY (approval_resolution_id) REFERENCES resolutions(id) ON DELETE SET NULL;

CREATE TABLE action_taken_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  resolution_id UUID NOT NULL REFERENCES resolutions(id) ON DELETE CASCADE, report_text TEXT NOT NULL, attachments JSONB, submitted_by UUID, submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), status VARCHAR(20) NOT NULL DEFAULT 'submitted'
);

CREATE TABLE legal_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  case_no VARCHAR(60) NOT NULL, court VARCHAR(160), case_type VARCHAR(60), parties JSONB, counsel VARCHAR(200), filed_on DATE, next_hearing DATE, status VARCHAR(20) NOT NULL DEFAULT 'open', -- open | hearing | judgement | appeal | closed
  documents JSONB, outcome TEXT, owner_staff_id UUID REFERENCES staff(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, case_no)
);

CREATE TABLE rti_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  request_no VARCHAR(40) NOT NULL, applicant JSONB NOT NULL, received_on DATE NOT NULL, due_on DATE NOT NULL, subject TEXT NOT NULL, pio_staff_id UUID REFERENCES staff(id), fee_paise INTEGER, response_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'received', -- received | assigned | responded | appealed | closed
  first_appeal JSONB, responded_on DATE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, request_no)
);

CREATE TABLE audit_paras (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  audit_register_id UUID NOT NULL REFERENCES audit_registers(id) ON DELETE CASCADE, para_no VARCHAR(20) NOT NULL, description TEXT NOT NULL, amount_paise BIGINT, owner_staff_id UUID REFERENCES staff(id), reply_text TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'open', -- open | replied | settled | dropped
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (audit_register_id, para_no)
);

CREATE TABLE efiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  file_no VARCHAR(40) NOT NULL, subject VARCHAR(300) NOT NULL, category VARCHAR(60), created_by UUID NOT NULL, current_holder_user_id UUID, priority VARCHAR(10) NOT NULL DEFAULT 'normal',
  status VARCHAR(20) NOT NULL DEFAULT 'open', -- open | in_movement | closed
  closed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, file_no)
);

CREATE TABLE efile_movements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  efile_id UUID NOT NULL REFERENCES efiles(id) ON DELETE CASCADE, from_user_id UUID, to_user_id UUID, noting TEXT, attachments JSONB, action VARCHAR(20) NOT NULL DEFAULT 'forward', -- forward | return | approve | reject
  moved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE policies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  title VARCHAR(200) NOT NULL, category VARCHAR(60), version VARCHAR(20) NOT NULL DEFAULT '1.0', approved_resolution_id UUID REFERENCES resolutions(id), effective_from DATE, file_url TEXT,
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | approved | superseded
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 31. AFFILIATION =====================================
CREATE TABLE affiliation_applications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE, academic_year_id UUID NOT NULL REFERENCES academic_years(id),
  application_type VARCHAR(30) NOT NULL, -- new | renewal | extension | intake_increase | program_addition | program_closure | autonomy
  programs JSONB, documents JSONB, fee_invoice_id UUID REFERENCES fee_invoices(id), inspection_committee JSONB, inspection_on DATE, inspection_report_url TEXT, deficiencies JSONB, workflow_instance_id UUID,
  status VARCHAR(30) NOT NULL DEFAULT 'draft', -- draft | submitted | fee_paid | scrutiny | inspection_scheduled | inspected | compliance_pending | approved | conditional | rejected | withdrawn
  decided_by UUID, order_no VARCHAR(60), order_url TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE affiliation_program_approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE, program_id UUID NOT NULL REFERENCES programs(id), academic_year_id UUID NOT NULL REFERENCES academic_years(id),
  sanctioned_intake SMALLINT NOT NULL, lateral_intake SMALLINT NOT NULL DEFAULT 0, approval_status VARCHAR(20) NOT NULL DEFAULT 'provisional', -- provisional | permanent | conditional | withdrawn
  order_no VARCHAR(60), valid_from DATE, valid_to DATE, conditions JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (college_id, program_id, academic_year_id)
);

CREATE TABLE affiliation_fee_schedules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  academic_year_id UUID NOT NULL REFERENCES academic_years(id), fee_type VARCHAR(30) NOT NULL, -- affiliation | continuation | inspection | intake_increase | exam_processing_per_student | recognition
  amount_paise BIGINT NOT NULL, per_unit VARCHAR(20) NOT NULL DEFAULT 'flat', -- flat | per_program | per_student
  UNIQUE (academic_year_id, fee_type)
);

CREATE TABLE college_data_submissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  college_id UUID NOT NULL REFERENCES colleges(id) ON DELETE CASCADE, term_id UUID NOT NULL REFERENCES academic_terms(id), exam_session_id UUID REFERENCES exam_sessions(id),
  submission_type VARCHAR(30) NOT NULL, -- student_registrations | course_registrations | cia_marks | attendance_eligibility | practical_marks | exam_registrations | internal_faculty_list
  status VARCHAR(20) NOT NULL DEFAULT 'draft', -- draft | submitted | verified | returned | accepted | locked
  record_count INT, file_url TEXT, submitted_by UUID, submitted_at TIMESTAMPTZ, verified_by UUID, verified_at TIMESTAMPTZ, remarks TEXT, locked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (college_id, term_id, submission_type)
);

CREATE TABLE exam_centres (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  exam_session_id UUID NOT NULL REFERENCES exam_sessions(id) ON DELETE CASCADE, college_id UUID NOT NULL REFERENCES colleges(id), centre_code VARCHAR(20) NOT NULL,
  chief_superintendent_staff_id UUID REFERENCES staff(id), capacity SMALLINT, assigned_colleges JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (exam_session_id, centre_code)
);
ALTER TABLE answer_script_bundles ADD CONSTRAINT fk_bundles_exam_centre FOREIGN KEY (exam_centre_id) REFERENCES exam_centres(id) ON DELETE SET NULL;

-- ===================================== 32. SAAS & WEBSITE =====================================
CREATE TABLE subscription_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code VARCHAR(30) NOT NULL UNIQUE, name VARCHAR(80) NOT NULL, tier VARCHAR(20) NOT NULL, -- starter | standard | professional | university
  price_paise_monthly BIGINT, price_paise_yearly BIGINT, student_limit INT, staff_limit INT, storage_gb INT, sms_credits INT, enabled_features JSONB NOT NULL DEFAULT '[]',
  is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE institution_subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  plan_id UUID NOT NULL REFERENCES subscription_plans(id), starts_on DATE NOT NULL, ends_on DATE, billing_cycle VARCHAR(10) NOT NULL DEFAULT 'yearly', status VARCHAR(20) NOT NULL DEFAULT 'active', -- trial | active | grace | expired | cancelled
  grace_until DATE, payment_ref VARCHAR(80), amount_paise BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE usage_meters (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  period_month DATE NOT NULL, active_students INT NOT NULL DEFAULT 0, active_staff INT NOT NULL DEFAULT 0, storage_bytes BIGINT NOT NULL DEFAULT 0, sms_sent INT NOT NULL DEFAULT 0, whatsapp_sent INT NOT NULL DEFAULT 0, emails_sent INT NOT NULL DEFAULT 0,
  api_calls BIGINT NOT NULL DEFAULT 0, computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, period_month)
);

CREATE TABLE impersonation_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  impersonator_id UUID NOT NULL REFERENCES users(id), target_user_id UUID NOT NULL REFERENCES users(id), reason TEXT, started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), ended_at TIMESTAMPTZ, ip INET
);

CREATE TABLE platform_settings (
  key VARCHAR(80) PRIMARY KEY, value JSONB, updated_by UUID, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE platform_announcements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title VARCHAR(200) NOT NULL, body TEXT NOT NULL, audience JSONB, starts_at TIMESTAMPTZ, ends_at TIMESTAMPTZ, is_active BOOLEAN NOT NULL DEFAULT TRUE, created_by UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE support_tickets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID REFERENCES institutions(id) ON DELETE CASCADE,
  ticket_number VARCHAR(30) NOT NULL UNIQUE, raised_by UUID REFERENCES users(id), subject VARCHAR(200) NOT NULL, description TEXT, priority VARCHAR(10) NOT NULL DEFAULT 'normal', module VARCHAR(60),
  status VARCHAR(20) NOT NULL DEFAULT 'open', -- open | in_progress | waiting | resolved | closed
  assigned_to UUID, messages JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), resolved_at TIMESTAMPTZ
);

CREATE TABLE pending_registrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_name VARCHAR(200) NOT NULL, institution_type VARCHAR(30) NOT NULL, slug VARCHAR(60) NOT NULL, admin_name VARCHAR(200), admin_email VARCHAR(200) NOT NULL, admin_phone VARCHAR(20), plan_id UUID REFERENCES subscription_plans(id),
  payment_ref VARCHAR(80), status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending | paid | provisioned | failed | expired
  institution_id UUID REFERENCES institutions(id), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE demo_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(200) NOT NULL, institution_name VARCHAR(200), email VARCHAR(200), phone VARCHAR(20), institution_type VARCHAR(30), message TEXT, status VARCHAR(20) NOT NULL DEFAULT 'new', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE institution_website_config (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL UNIQUE REFERENCES institutions(id) ON DELETE CASCADE,
  is_enabled BOOLEAN NOT NULL DEFAULT TRUE, theme JSONB, hero JSONB, sections JSONB, seo JSONB, contact JSONB, social JSONB, show_catalog BOOLEAN NOT NULL DEFAULT TRUE, show_apply BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE institution_domains (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  hostname VARCHAR(255) NOT NULL UNIQUE, is_primary BOOLEAN NOT NULL DEFAULT FALSE, verification_token VARCHAR(64), verified_at TIMESTAMPTZ, ssl_status VARCHAR(20) NOT NULL DEFAULT 'pending', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE gallery_albums (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  title VARCHAR(200) NOT NULL, description TEXT, cover_url TEXT, is_published BOOLEAN NOT NULL DEFAULT TRUE, sequence SMALLINT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE gallery_images (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  album_id UUID NOT NULL REFERENCES gallery_albums(id) ON DELETE CASCADE, image_url TEXT NOT NULL, caption VARCHAR(200), sequence SMALLINT NOT NULL DEFAULT 1, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE website_notices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  title VARCHAR(200) NOT NULL, slug VARCHAR(120) NOT NULL, body TEXT, attachments JSONB, category VARCHAR(40), publish_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, is_published BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, slug)
);

CREATE TABLE website_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  event_id UUID REFERENCES events(id), title VARCHAR(200) NOT NULL, slug VARCHAR(120) NOT NULL, description TEXT, starts_at TIMESTAMPTZ, ends_at TIMESTAMPTZ, image_url TEXT, is_published BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, slug)
);

CREATE TABLE website_content_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  section VARCHAR(60) NOT NULL, slug VARCHAR(120) NOT NULL, title VARCHAR(200), body TEXT, media JSONB, sequence SMALLINT NOT NULL DEFAULT 1, is_published BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE (institution_id, section, slug)
);

CREATE TABLE website_enquiries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_id UUID NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name VARCHAR(200) NOT NULL, email VARCHAR(200), phone VARCHAR(20), subject VARCHAR(200), message TEXT, source_page VARCHAR(200), enquiry_id UUID REFERENCES enquiries(id), status VARCHAR(20) NOT NULL DEFAULT 'new',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===================================== 33. DEFERRED FOREIGN KEYS & INDEXES =====================================
ALTER TABLE colleges ADD CONSTRAINT fk_colleges_principal FOREIGN KEY (principal_staff_id) REFERENCES staff(id) ON DELETE SET NULL;
ALTER TABLE faculties ADD CONSTRAINT fk_faculties_dean FOREIGN KEY (dean_staff_id) REFERENCES staff(id) ON DELETE SET NULL;
ALTER TABLE departments ADD CONSTRAINT fk_departments_hod FOREIGN KEY (hod_staff_id) REFERENCES staff(id) ON DELETE SET NULL;
ALTER TABLE batch_sections ADD CONSTRAINT fk_batch_sections_advisor FOREIGN KEY (class_advisor_staff_id) REFERENCES staff(id) ON DELETE SET NULL;
ALTER TABLE student_transfers ADD CONSTRAINT fk_student_transfers_invoice FOREIGN KEY (fee_invoice_id) REFERENCES fee_invoices(id) ON DELETE SET NULL;
ALTER TABLE applicants ADD CONSTRAINT fk_applicants_fee_invoice FOREIGN KEY (application_fee_invoice_id) REFERENCES fee_invoices(id) ON DELETE SET NULL;
ALTER TABLE seat_allotments ADD CONSTRAINT fk_seat_allotments_invoice FOREIGN KEY (fee_invoice_id) REFERENCES fee_invoices(id) ON DELETE SET NULL;
ALTER TABLE course_registrations ADD CONSTRAINT fk_course_registrations_invoice FOREIGN KEY (fee_invoice_id) REFERENCES fee_invoices(id) ON DELETE SET NULL;
ALTER TABLE attendance_condonations ADD CONSTRAINT fk_condonations_invoice FOREIGN KEY (fee_invoice_id) REFERENCES fee_invoices(id) ON DELETE SET NULL;
ALTER TABLE disciplinary_cases ADD CONSTRAINT fk_discipline_invoice FOREIGN KEY (fee_invoice_id) REFERENCES fee_invoices(id) ON DELETE SET NULL;
ALTER TABLE student_undertakings ADD CONSTRAINT fk_undertakings_student_tmpl CHECK (TRUE);

-- Workflow instance back-references (all optional)
DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['student_transfers','course_registrations','on_duty_requests','attendance_condonations','staff_leaves','loans_advances','appraisals','cas_applications',
                               'course_allocation_proposals','marks_change_requests','transcripts','fee_refunds','fee_payments','scholarship_applications','student_discount_assignments',
                               'indents','purchase_orders','vendor_bills','expense_records','events','room_bookings','certificate_requests','grievances','hostel_leaves','research_incentives',
                               'scholar_requests','affiliation_applications','bulk_campaigns'])
  LOOP
    IF t = 'fee_payments' THEN
      EXECUTE format('ALTER TABLE %I ADD CONSTRAINT fk_%s_workflow FOREIGN KEY (cancel_workflow_instance_id) REFERENCES workflow_instances(id) ON DELETE SET NULL', t, t);
    ELSIF t = 'bulk_campaigns' THEN
      CONTINUE;
    ELSE
      EXECUTE format('ALTER TABLE %I ADD CONSTRAINT fk_%s_workflow FOREIGN KEY (workflow_instance_id) REFERENCES workflow_instances(id) ON DELETE SET NULL', t, t);
    END IF;
  END LOOP;
END $$;

-- Job back-references
DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['credential_sheets','data_imports','merit_lists','elective_allocation_runs','result_processing_runs','legacy_result_imports','attainment_runs','metric_values',
                               'compliance_submissions','accounting_exports','bulk_campaigns','issued_documents','etd_uploads'])
  LOOP
    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT fk_%s_job FOREIGN KEY (job_id) REFERENCES background_jobs(id) ON DELETE SET NULL', t, t);
  END LOOP;
END $$;

-- Common tenant + lookup indexes
CREATE INDEX ix_users_institution ON users (institution_id);
CREATE INDEX ix_user_roles_user ON user_roles (user_id);
CREATE INDEX ix_user_roles_scope ON user_roles (scope_type, scope_id);
CREATE INDEX ix_students_college_status ON students (institution_id, college_id, status);
CREATE INDEX ix_spe_batch ON student_program_enrollments (batch_id, status);
CREATE INDEX ix_str_term ON student_term_records (term_id, status);
CREATE INDEX ix_offerings_term_dept ON course_offerings (term_id, department_id, status);
CREATE INDEX ix_registrations_term ON course_registrations (term_id, status);
CREATE INDEX ix_reg_items_offering ON course_registration_items (offering_id, status);
CREATE INDEX ix_timetable_entries_offering ON timetable_entries (offering_id);
CREATE INDEX ix_class_sessions_offering_date ON class_sessions (offering_id, session_date);
CREATE INDEX ix_attendance_summaries_student ON attendance_summaries (student_program_enrollment_id);
CREATE INDEX ix_fee_invoices_due ON fee_invoices (institution_id, status, due_date);
CREATE INDEX ix_fee_payments_invoice ON fee_payments (invoice_id);
CREATE INDEX ix_fee_payments_date ON fee_payments (institution_id, payment_date);
CREATE INDEX ix_internal_marks_student ON internal_marks (student_program_enrollment_id);
CREATE INDEX ix_exam_registrations_session ON exam_registrations (exam_session_id, status);
CREATE INDEX ix_exam_reg_items_paper ON exam_registration_items (exam_paper_id, status);
CREATE INDEX ix_answer_scripts_bundle ON answer_scripts (bundle_id, status);
CREATE INDEX ix_scr_run ON student_course_results (run_id, status);
CREATE INDEX ix_scr_term ON student_course_results (term_id, college_id);
CREATE INDEX ix_str_results_record ON student_term_results (student_term_record_id) WHERE is_current;
CREATE INDEX ix_staff_department ON staff (institution_id, department_id, status);
CREATE INDEX ix_staff_leaves_staff ON staff_leaves (staff_id, status);
CREATE INDEX ix_staff_attendance_date ON staff_attendance (institution_id, attendance_date);
CREATE INDEX ix_hostel_allocations_hostel ON hostel_allocations (hostel_id, status);
CREATE INDEX ix_hostel_leaves_status ON hostel_leaves (hostel_id, status);
CREATE INDEX ix_book_issues_member ON book_issues (member_id, status);
CREATE INDEX ix_notifications_user ON notifications (user_id, created_at DESC);
CREATE INDEX ix_message_logs_recipient ON message_logs (institution_id, recipient, created_at DESC);
CREATE INDEX ix_workflow_instances_entity ON workflow_instances (entity_type, entity_id);
CREATE INDEX ix_grievances_status ON grievances (institution_id, status, sla_due_at);
CREATE INDEX ix_service_requests_status ON service_requests (institution_id, status, sla_due_at);
CREATE INDEX ix_drive_applications_student ON drive_applications (student_program_enrollment_id);
CREATE INDEX ix_metric_values_period ON metric_values (institution_id, period_label);
CREATE INDEX ix_publications_staff ON publications (staff_id, year);
CREATE INDEX ix_events_dates ON events (institution_id, from_on);
CREATE INDEX ix_calendar_events_range ON calendar_events (institution_id, starts_at);

-- ===================================== 34. ROW-LEVEL SECURITY =====================================
-- Application role (used by the API/workers) is NOT BYPASSRLS; a separate platform role is used for cross-tenant super-admin queries.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'universe_app') THEN CREATE ROLE universe_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'universe_platform') THEN CREATE ROLE universe_platform NOLOGIN BYPASSRLS; END IF;
END $$;

DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN
    SELECT c.table_name FROM information_schema.columns c
    JOIN information_schema.tables tb ON tb.table_name = c.table_name AND tb.table_schema = c.table_schema
    WHERE c.table_schema = 'public' AND c.column_name = 'institution_id' AND tb.table_type = 'BASE TABLE'
      AND c.table_name NOT LIKE '%\_default' ESCAPE '\'
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    -- Rows with NULL institution_id (platform-level defaults) are readable by every tenant; writes require a tenant match.
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (institution_id IS NULL OR institution_id = current_institution_id()) WITH CHECK (institution_id = current_institution_id() OR institution_id IS NULL)', t);
  END LOOP;
END $$;

-- ===================================== 35. TRIGGERS =====================================
DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN
    SELECT c.table_name FROM information_schema.columns c
    JOIN information_schema.tables tb ON tb.table_name = c.table_name AND tb.table_schema = c.table_schema
    WHERE c.table_schema = 'public' AND c.column_name = 'updated_at' AND tb.table_type = 'BASE TABLE' AND c.table_name NOT LIKE '%\_default' ESCAPE '\'
  LOOP
    PERFORM attach_updated_at_trigger(t);
  END LOOP;
END $$;

-- Optimistic-lock bump on editable masters
DO $$
DECLARE t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['institutions','colleges','faculties','departments','users','roles','academic_years','academic_terms','programs','regulations','program_regulations',
                               'courses','elective_baskets','batches','students','student_program_enrollments','staff','fee_structures','fee_invoices','course_offerings',
                               'course_registrations','exam_sessions','exam_registrations','offering_assessments','grading_scales','assessment_schemes','rooms','books','hostels',
                               'vehicles','items','assets','companies','admission_cycles','applicants','document_templates'])
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS bump_version ON %I', t);
    EXECUTE format('CREATE TRIGGER bump_version BEFORE UPDATE ON %I FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*) EXECUTE FUNCTION trigger_bump_version()', t);
  END LOOP;
END $$;
-- workflow_definitions is NOT in the list: its version column is the definition version (immutable rows, UNIQUE (institution_id, key, version));
-- deactivating an old version must not renumber it (revision 0005 drops the trigger on databases created before).

-- Result immutability: published rows may only flip is_current / status -> superseded
CREATE OR REPLACE FUNCTION trigger_results_immutable() RETURNS TRIGGER AS $$
BEGIN
  IF OLD.status = 'published' THEN
    IF NEW.status NOT IN ('published','superseded') THEN
      RAISE EXCEPTION 'published result % cannot change status to %', OLD.id, NEW.status USING ERRCODE = 'check_violation';
    END IF;
    IF ROW(NEW.institution_id, NEW.student_program_enrollment_id, NEW.term_id, NEW.course_id, NEW.attempt_number, NEW.attempt_type, NEW.credits, NEW.cia_marks, NEW.ese_marks,
           NEW.grace_marks, NEW.total_marks, NEW.percentage, NEW.letter_grade, NEW.grade_point, NEW.result_status, NEW.counts_toward_cgpa, NEW.version, NEW.run_id, NEW.hash, NEW.published_at)
       IS DISTINCT FROM
       ROW(OLD.institution_id, OLD.student_program_enrollment_id, OLD.term_id, OLD.course_id, OLD.attempt_number, OLD.attempt_type, OLD.credits, OLD.cia_marks, OLD.ese_marks,
           OLD.grace_marks, OLD.total_marks, OLD.percentage, OLD.letter_grade, OLD.grade_point, OLD.result_status, OLD.counts_toward_cgpa, OLD.version, OLD.run_id, OLD.hash, OLD.published_at) THEN
      RAISE EXCEPTION 'published result % is immutable; create a new version', OLD.id USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_results_immutable BEFORE UPDATE ON student_course_results FOR EACH ROW EXECUTE FUNCTION trigger_results_immutable();

CREATE OR REPLACE FUNCTION trigger_term_results_immutable() RETURNS TRIGGER AS $$
BEGIN
  IF OLD.status = 'published' AND NEW.status NOT IN ('published','superseded') THEN
    RAISE EXCEPTION 'published term result % cannot change status to %', OLD.id, NEW.status USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status = 'published' AND (NEW.sgpa IS DISTINCT FROM OLD.sgpa OR NEW.cgpa IS DISTINCT FROM OLD.cgpa OR NEW.credits_earned IS DISTINCT FROM OLD.credits_earned OR NEW.result_class IS DISTINCT FROM OLD.result_class) THEN
    RAISE EXCEPTION 'published term result % is immutable; create a new version', OLD.id USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_term_results_immutable BEFORE UPDATE ON student_term_results FOR EACH ROW EXECUTE FUNCTION trigger_term_results_immutable();

-- Audit hash chain (per institution)
CREATE OR REPLACE FUNCTION trigger_audit_hash_chain() RETURNS TRIGGER AS $$
DECLARE prev TEXT;
BEGIN
  SELECT hash INTO prev FROM audit_logs WHERE institution_id IS NOT DISTINCT FROM NEW.institution_id ORDER BY occurred_at DESC LIMIT 1;
  NEW.prev_hash := prev;
  NEW.hash := encode(digest(COALESCE(prev,'') || NEW.module || NEW.action || COALESCE(NEW.record_id::text,'') || COALESCE(NEW.new_values::text,'') || NEW.occurred_at::text, 'sha256'), 'hex');
  RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_audit_hash_chain BEFORE INSERT ON audit_logs FOR EACH ROW EXECUTE FUNCTION trigger_audit_hash_chain();

-- Global search materialized view (refreshed by the outbox consumer)
CREATE MATERIALIZED VIEW search_documents AS
  SELECT 'student'::text AS entity_type, s.id AS entity_id, s.institution_id, s.college_id, s.first_name || ' ' || COALESCE(s.last_name,'') AS title, s.registration_number AS subtitle,
         to_tsvector('simple', s.first_name || ' ' || COALESCE(s.last_name,'') || ' ' || s.registration_number || ' ' || COALESCE(s.email,'')) AS tsv
  FROM students s WHERE s.deleted_at IS NULL
  UNION ALL
  SELECT 'staff', st.id, st.institution_id, st.college_id, st.first_name || ' ' || COALESCE(st.last_name,''), st.employee_id,
         to_tsvector('simple', st.first_name || ' ' || COALESCE(st.last_name,'') || ' ' || st.employee_id || ' ' || COALESCE(st.email,''))
  FROM staff st WHERE st.deleted_at IS NULL
  UNION ALL
  SELECT 'course', c.id, c.institution_id, c.college_id, c.title, c.code, to_tsvector('simple', c.code || ' ' || c.title) FROM courses c WHERE c.deleted_at IS NULL
  UNION ALL
  SELECT 'applicant', a.id, a.institution_id, NULL, a.first_name || ' ' || COALESCE(a.last_name,''), a.application_number,
         to_tsvector('simple', a.first_name || ' ' || COALESCE(a.last_name,'') || ' ' || a.application_number) FROM applicants a WHERE a.deleted_at IS NULL;
CREATE INDEX ix_search_documents_tsv ON search_documents USING gin (tsv);
CREATE UNIQUE INDEX uq_search_documents ON search_documents (entity_type, entity_id);

-- ===================================== 36. SEED DATA =====================================
-- 36.1 Permissions registry (modules × standard actions + bespoke actions)
INSERT INTO permissions (module, action, description)
SELECT m, a, m || ':' || a FROM unnest(ARRAY[
  'dashboard','institutions','colleges','faculties','departments','users','roles','features','sessions','programs','regulations','curriculum','courses','batches','offerings','registration',
  'timetable','attendance','marks','projects','exams','results','degrees','obe','lms','admissions','students','credit_transfers','faculty','hr','recruitment','leaves','payroll','research','phd',
  'fees','scholarships','no_dues','hostel','library','transport','inventory','procurement','accounting','events','facilities','health','sports','placement','alumni','fundraising','mentoring',
  'grievances','discipline','surveys','clubs','accreditation','governance','legal','rti','efile','affiliation','communication','calendar','templates','certificates','reports','analytics',
  'audit_logs','settings','integrations','jobs','website']) AS m
CROSS JOIN unnest(ARRAY['view','view_all','create','update','delete','approve','publish','export','manage','view_pii']) AS a
ON CONFLICT DO NOTHING;

INSERT INTO permissions (module, action, description) VALUES
  ('users','reset_password','Reset user passwords'), ('users','impersonate','Impersonate users (platform)'), ('roles','assign','Assign roles'), ('roles','clone','Clone roles'),
  ('features','institution_toggle','Institution-level feature switch'), ('sessions','rollover','Academic year rollover'), ('sessions','close','Close term'), ('sessions','lock','Lock term'),
  ('regulations','clone','Clone regulation'), ('batches','promote','Promote batch'), ('offerings','allocate_faculty','Allocate faculty'), ('offerings','bulk_create','Bulk create offerings'),
  ('registration','self','Self registration'), ('registration','allocate','Run elective allocation'), ('registration','override','Override registration rules'), ('registration','bulk','Bulk register'),
  ('timetable','generate','Auto-generate timetable'), ('timetable','substitute','Manage substitutions'),
  ('attendance','mark','Mark attendance'), ('attendance','self','View own attendance'), ('attendance','condone','Condonation'), ('attendance','edit_finalized','Edit finalized attendance'),
  ('attendance','staff_view_all','View all staff attendance'), ('attendance','staff_self','View own staff attendance'), ('attendance','device_manage','Manage attendance devices'),
  ('marks','enter','Enter marks'), ('marks','verify','Verify marks'), ('marks','lock','Lock marks'), ('marks','correct','Correct locked marks'), ('projects','guide','Guide projects'), ('projects','review','Review projects'),
  ('exams','configure','Configure exams'), ('exams','self','Student exam self-service'), ('exams','eligibility','Apply eligibility'), ('exams','hall_tickets','Generate hall tickets'), ('exams','seating','Seating plans'),
  ('exams','invigilation','Invigilation'), ('exams','conduct','Conduct exams'), ('exams','qp','Question paper management'), ('exams','qp_print','Print question papers'), ('exams','code','Code scripts'),
  ('exams','custody','Script custody'), ('exams','valuation_assign','Assign valuation'), ('exams','evaluate','Evaluate scripts'), ('exams','moderate','Moderation'), ('exams','decode','Decode dummy numbers'),
  ('exams','reval','Revaluation processing'), ('exams','malpractice','Malpractice cases'),
  ('results','compute','Compute results'), ('results','verify','Verify results'), ('results','self','View own results'), ('results','transcript','Transcripts'), ('results','legacy_import','Legacy result import'),
  ('degrees','award','Award degrees'), ('degrees','issue','Issue certificates'), ('degrees','convocation_manage','Manage convocation'),
  ('obe','configure','Configure attainment'), ('obe','compute','Compute attainment'), ('lms','grade','Grade LMS work'),
  ('admissions','verify','Verify documents'), ('admissions','merit','Merit lists'), ('admissions','allot','Seat allotment'), ('admissions','import','Import applicants'), ('admissions','admit','Admit applicants'), ('admissions','refund','Admission refunds'),
  ('students','holds','Manage holds'), ('students','standing','Manage academic standing'), ('students','exit','NEP exit'), ('students','transfer','Transfers'), ('students','undertakings','Undertakings'), ('students','id_card','ID cards'), ('students','bulk_import','Bulk import'), ('students','self','Student self-service'),
  ('credit_transfers','verify','Verify credit transfers'), ('faculty','research','Research profile'), ('faculty','workload_manage','Workload management'),
  ('hr','service_book','Service book'), ('hr','recruitment','Recruitment'), ('hr','appraisal','Appraisals'), ('hr','cas','CAS'), ('hr','guest_manage','Guest faculty'),
  ('leaves','self','Own leaves'), ('leaves','encash','Leave encashment'), ('payroll','self','Own payslips'), ('payroll','generate','Generate payroll'), ('payroll','mark_paid','Mark paid'), ('payroll','statutory','Statutory config'),
  ('research','ethics','Ethics approvals'), ('research','incentives','Research incentives'), ('research','mous','MoUs'), ('research','incubation','Incubation'),
  ('phd','self','Scholar self-service'), ('phd','guide','Guide actions'), ('phd','dc','Doctoral committee'), ('phd','examine','Thesis examination'), ('phd','fellowship','Fellowships'), ('phd','etd','ETD upload'),
  ('fees','self','Own fees'), ('fees','collect','Collect fees'), ('fees','refund','Refunds'), ('fees','cancel_receipt','Cancel receipts'), ('fees','reconcile','Reconciliation'), ('fees','structure_manage','Fee structures'), ('fees','concession','Concessions'),
  ('scholarships','verify','Verify scholarship'), ('scholarships','sanction','Sanction scholarship'), ('scholarships','disburse','Disburse scholarship'), ('no_dues','request','Request no-dues'),
  ('hostel','self','Own hostel'), ('hostel','allot','Allot hostel'), ('hostel','gate','Gate scanning'), ('hostel','warden','Warden operations'), ('hostel','roll_call','Roll call'), ('hostel','mess_manage','Mess management'), ('hostel','discipline','Hostel discipline'),
  ('library','self','Own library'), ('library','circulate','Circulation'), ('library','fines','Library fines'), ('transport','gps_ingest','GPS ingest'), ('transport','driver','Driver app'),
  ('inventory','indent','Raise indent'), ('inventory','approve_indent','Approve indent'), ('inventory','receive','Receive goods'), ('inventory','issue','Issue stock'), ('inventory','asset_audit','Asset audit'),
  ('procurement','quote','Quotations'), ('procurement','po_approve','Approve PO'), ('procurement','bill_approve','Approve vendor bills'), ('accounting','post','Post entries'), ('accounting','reconcile','Bank reconciliation'),
  ('events','organise','Organise events'), ('events','certify','Event certificates'), ('facilities','book','Book facilities'), ('facilities','approve_booking','Approve bookings'), ('facilities','service_assign','Assign service requests'),
  ('health','record','Health records'), ('placement','self','Own placement'), ('placement','drive_manage','Manage drives'), ('placement','override_eligibility','Override eligibility'), ('placement','offer_manage','Manage offers'), ('placement','recruiter','Recruiter portal'),
  ('alumni','self','Own alumni profile'), ('alumni','verify','Verify alumni'), ('alumni','campaign','Campaigns'), ('fundraising','receipt','Donation receipts'),
  ('mentoring','self','Own mentoring'), ('mentoring','wards','Wards mentoring'), ('mentoring','refer','Counselling referrals'),
  ('grievances','triage','Triage grievances'), ('grievances','resolve','Resolve grievances'), ('grievances','escalate','Escalate grievances'), ('grievances','committee','Committee routing'),
  ('discipline','decide','Decide cases'), ('discipline','appeal','Handle appeals'), ('surveys','respond','Respond to surveys'), ('surveys','analyse','Analyse surveys'), ('clubs','verify_hours','Verify activity hours'),
  ('accreditation','compute','Compute metrics'), ('accreditation','override','Override metrics'), ('accreditation','submit','Submit compliance'), ('accreditation','evidence','Manage evidence'),
  ('governance','committees','Committees'), ('governance','minutes','Minutes'), ('governance','resolutions','Resolutions'),
  ('affiliation','apply','Apply for affiliation'), ('affiliation','inspect','Inspections'), ('affiliation','decide','Decide affiliation'), ('affiliation','submit','Submit college data'), ('affiliation','verify_submission','Verify submissions'),
  ('communication','send','Send messages'), ('communication','bulk','Bulk campaigns'), ('communication','template_manage','Manage templates'), ('communication','emergency','Emergency broadcast'),
  ('templates','render','Render templates'), ('certificates','self','Request own certificates'), ('certificates','request_approve','Approve certificate requests'), ('certificates','issue','Issue certificates'),
  ('reports','run','Run reports'), ('reports','schedule','Schedule reports'), ('reports','statutory','Statutory reports'), ('audit_logs','verify_chain','Verify audit chain'),
  ('integrations','connect','Manage connections'), ('integrations','api_keys','API keys'), ('integrations','webhooks','Webhooks'), ('integrations','import','Data imports'), ('jobs','cancel','Cancel jobs')
ON CONFLICT DO NOTHING;

-- 36.2 Platform role templates (institution_id NULL); institution roles are cloned by seed_institution_defaults()
INSERT INTO roles (institution_id, name, slug, is_system, default_scope_type, portal) VALUES
  (NULL,'Super Admin','super_admin',TRUE,'institution','super_admin'), (NULL,'Support Agent','support_agent',TRUE,'institution','super_admin'),
  (NULL,'Institution Admin','institution_admin',TRUE,'institution','admin'), (NULL,'Vice Chancellor / Principal','vice_chancellor',TRUE,'institution','admin'),
  (NULL,'Registrar','registrar',TRUE,'institution','admin'), (NULL,'Controller of Examinations','controller_of_examinations',TRUE,'institution','admin'),
  (NULL,'Exam Cell','exam_cell',TRUE,'institution','admin'), (NULL,'Exam Decoder','exam_decoder',TRUE,'institution','admin'), (NULL,'Dean','dean',TRUE,'faculty','admin'),
  (NULL,'Head of Department','hod',TRUE,'department','admin'), (NULL,'Class Advisor','class_advisor',TRUE,'offering','admin'), (NULL,'Faculty','faculty',TRUE,'self','faculty'),
  (NULL,'Guest Faculty','guest_faculty',TRUE,'self','faculty'), (NULL,'External Examiner','external_examiner',TRUE,'self','evaluator'), (NULL,'Invigilator','invigilator',TRUE,'self','faculty'),
  (NULL,'Research Guide','research_guide',TRUE,'self','faculty'), (NULL,'Research Scholar','research_scholar',TRUE,'self','scholar'), (NULL,'Research Cell','research_cell',TRUE,'institution','admin'),
  (NULL,'IQAC Coordinator','iqac_coordinator',TRUE,'institution','admin'), (NULL,'OBE Coordinator','obe_coordinator',TRUE,'institution','admin'),
  (NULL,'Admissions Officer','admissions_officer',TRUE,'institution','admin'), (NULL,'Accountant','accountant',TRUE,'institution','admin'), (NULL,'HR Officer','hr_officer',TRUE,'institution','admin'),
  (NULL,'Placement Officer','placement_officer',TRUE,'institution','admin'), (NULL,'Alumni Coordinator','alumni_coordinator',TRUE,'institution','admin'),
  (NULL,'Hostel Warden','hostel_warden',TRUE,'self','warden'), (NULL,'Hostel Gate Staff','hostel_gate_staff',TRUE,'self','warden'), (NULL,'Librarian','librarian',TRUE,'institution','admin'),
  (NULL,'Transport Manager','transport_manager',TRUE,'institution','admin'), (NULL,'Inventory Manager','inventory_manager',TRUE,'institution','admin'), (NULL,'Estate Officer','estate_officer',TRUE,'institution','admin'),
  (NULL,'Security Officer','security_officer',TRUE,'institution','admin'), (NULL,'Medical Officer','medical_officer',TRUE,'institution','admin'), (NULL,'Sports Officer','sports_officer',TRUE,'institution','admin'),
  (NULL,'Grievance Officer','grievance_officer',TRUE,'institution','admin'), (NULL,'Discipline Committee','discipline_committee',TRUE,'institution','admin'), (NULL,'Committee Secretary','committee_secretary',TRUE,'committee','admin'),
  (NULL,'Legal Officer','legal_officer',TRUE,'institution','admin'), (NULL,'Public Information Officer','pio',TRUE,'institution','admin'), (NULL,'Receptionist','receptionist',TRUE,'institution','admin'),
  (NULL,'Driver','driver',TRUE,'self','driver'), (NULL,'Integration Admin','integration_admin',TRUE,'institution','admin'), (NULL,'College Admin','college_admin',TRUE,'college','admin'),
  (NULL,'College Exam Coordinator','college_exam_coordinator',TRUE,'college','admin'), (NULL,'Auditor','auditor',TRUE,'institution','admin'), (NULL,'Recruiter','recruiter',TRUE,'self','recruiter'),
  (NULL,'Learner','learner',TRUE,'self','student'), (NULL,'Student','student',TRUE,'self','student'), (NULL,'Parent','parent',TRUE,'self','parent'), (NULL,'Alumni','alumni',TRUE,'self','alumni'),
  (NULL,'Applicant','applicant',TRUE,'self','applicant')
ON CONFLICT DO NOTHING;

-- 36.3 Subscription plans
INSERT INTO subscription_plans (code, name, tier, student_limit, staff_limit, storage_gb, sms_credits, enabled_features) VALUES
  ('starter','Starter','starter',2000,200,20,5000,'[]'), ('standard','Standard','standard',10000,1000,100,25000,'[]'),
  ('professional','Professional','professional',50000,5000,500,100000,'[]'), ('university','University','university',200000,20000,2000,500000,'[]')
ON CONFLICT DO NOTHING;
-- enabled_features per plan are filled by the features registry seeder (scripts/seed_features.py) from docs/Feature_Flags.md.

-- 36.4 Accreditation frameworks (top-level criteria; full trees seeded by the IN pack)
INSERT INTO accreditation_frameworks (code, name, version, pack) VALUES
  ('NAAC_2024','NAAC Revised Assessment & Accreditation Framework','2024','IN'), ('NBA_UG_ENGG','NBA Tier-I/II UG Engineering (GAPC v4)','4.0','IN'),
  ('NIRF','National Institutional Ranking Framework','2026','IN'), ('AISHE','All India Survey on Higher Education','2026','IN'),
  ('AICTE_APPROVAL','AICTE Approval Process','2026','IN'), ('UGC_12B','UGC 2(f)/12(B) Recognition','2026','IN')
ON CONFLICT DO NOTHING;

INSERT INTO framework_criteria (framework_id, code, title, metric_type, max_score, sequence)
SELECT f.id, c.code, c.title, 'qn_ql', c.max_score, c.seq FROM accreditation_frameworks f
JOIN (VALUES ('1','Curricular Aspects',100,1),('2','Teaching-Learning and Evaluation',350,2),('3','Research, Innovations and Extension',110,3),('4','Infrastructure and Learning Resources',100,4),
             ('5','Student Support and Progression',140,5),('6','Governance, Leadership and Management',100,6),('7','Institutional Values and Best Practices',100,7)) AS c(code,title,max_score,seq) ON TRUE
WHERE f.code = 'NAAC_2024' ON CONFLICT DO NOTHING;

INSERT INTO framework_criteria (framework_id, code, title, metric_type, max_score, sequence)
SELECT f.id, c.code, c.title, 'qn_ql', c.max_score, c.seq FROM accreditation_frameworks f
JOIN (VALUES ('1','Vision, Mission and Programme Educational Objectives',50,1),('2','Programme Curriculum and Teaching-Learning Processes',100,2),('3','Course Outcomes and Programme Outcomes',175,3),
             ('4','Students Performance',100,4),('5','Faculty Information and Contributions',200,5),('6','Facilities and Technical Support',80,6),('7','Continuous Improvement',50,7),
             ('8','First Year Academics',50,8),('9','Student Support Systems',50,9),('10','Governance, Institutional Support and Financial Resources',120,10)) AS c(code,title,max_score,seq) ON TRUE
WHERE f.code = 'NBA_UG_ENGG' ON CONFLICT DO NOTHING;

-- 36.5 Metric definitions (keys computed by app/services/accreditation/metrics/*.py)
INSERT INTO metric_definitions (key, name, unit, source_module, computation_key) VALUES
  ('students.enrolment_by_category','Enrolment by category','count','students','students.enrolment_by_category'), ('students.seats_filled_vs_reserved','Seats filled vs reserved','pct','admissions','students.seats_filled_vs_reserved'),
  ('faculty.fsr','Faculty-student ratio','ratio','hr','faculty.fsr'), ('results.pass_pct_final_year','Pass percentage (final year)','pct','results','results.pass_pct_final_year'),
  ('students.dropout_pct','Dropout percentage','pct','students','students.dropout_pct'), ('placement.placed_pct','Students placed','pct','placement','placement.placed_pct'),
  ('students.higher_studies_pct','Progression to higher studies','pct','placement','students.higher_studies_pct'), ('students.qualifying_exams','Qualifying exam clearers','count','placement','students.qualifying_exams'),
  ('scholarships.beneficiaries_pct','Scholarship beneficiaries','pct','fees','scholarships.beneficiaries_pct'), ('surveys.sss_score','Student satisfaction survey score','score','surveys','surveys.sss_score'),
  ('faculty.phd_pct','Faculty with PhD','pct','hr','faculty.phd_pct'), ('research.publications_per_teacher','Publications per teacher','ratio','research','research.publications_per_teacher'),
  ('research.grants_amount','Research grants received','paise','research','research.grants_amount'), ('research.consultancy_revenue','Consultancy revenue','paise','research','research.consultancy_revenue'),
  ('research.patents','Patents','count','research','research.patents'), ('research.fdp_participation','FDP participation','count','research','research.fdp_participation'),
  ('academics.cbcs_pct','Programmes with CBCS/electives','pct','academics','academics.cbcs_pct'), ('academics.value_added_courses','Value-added courses','count','academics','academics.value_added_courses'),
  ('academics.internships_pct','Students with internships/projects','pct','placement','academics.internships_pct'), ('obe.co_attainment','CO attainment','level','obe','obe.co_attainment'),
  ('obe.po_attainment','PO attainment','level','obe','obe.po_attainment'), ('finance.infra_spend_pct','Infrastructure spend share','pct','accounting','finance.infra_spend_pct'),
  ('library.spend','Library expenditure','paise','accounting','library.spend'), ('governance.grievance_sla_pct','Grievances resolved within SLA','pct','grievances','governance.grievance_sla_pct'),
  ('events.count_by_type','Events organised by type','count','events','events.count_by_type'), ('values.gender_ratio','Gender ratio','ratio','students','values.gender_ratio'),
  ('nirf.gms','Median salary of placed graduates','paise','placement','nirf.gms'), ('nirf.gph','Graduation outcome (on-time)','pct','results','nirf.gph'), ('nirf.gphd','PhD graduated','count','phd','nirf.gphd'),
  ('affiliation.colleges_count','Affiliated colleges','count','affiliation','affiliation.colleges_count')
ON CONFLICT DO NOTHING;

-- 36.6 Platform document templates and notification templates are seeded by the IN pack seeder (scripts/seed_pack.py); grading scale and assessment scheme defaults are copied per institution by seed_institution_defaults().

-- 36.7 Super admin bootstrap (password must be rotated on first login; INSTALL_SECRET_KEY-gated /install endpoint replaces this in practice)
INSERT INTO users (institution_id, username, email, password_hash, display_name, user_type, is_super_admin, is_verified, must_change_password)
VALUES (NULL, 'superadmin', 'superadmin@universe.local', crypt('ChangeMe@1234', gen_salt('bf', 12)), 'Platform Super Admin', 'platform', TRUE, TRUE, TRUE)
ON CONFLICT DO NOTHING;

-- ===================================== 37. ANALYTICS READ MODELS =====================================
-- Phase 35 materialized views (app/services/analytics/read_models.py is the single source; Alembic 0035 applies the
-- same statements). Refreshed CONCURRENTLY by the analytics.refresh_scheduler Beat task; no RLS on matviews — the
-- analytics repository applies institution_id + the scope-dimension predicate on every read.
-- mv_enrolment_daily: Enrolments by college / department / programme / batch / category / gender / quota / status per day
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_enrolment_daily AS
SELECT e.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id,
       COALESCE(s.category, '') AS category, COALESCE(s.gender, '') AS gender, COALESCE(s.admission_quota, '') AS quota,
       e.status, COALESCE(e.admission_date, e.created_at::date) AS day, COUNT(*)::int AS enrolments
FROM student_program_enrollments e
JOIN students s ON s.id = e.student_id
WHERE e.deleted_at IS NULL AND s.deleted_at IS NULL
GROUP BY e.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, COALESCE(s.category, ''),
         COALESCE(s.gender, ''), COALESCE(s.admission_quota, ''), e.status, COALESCE(e.admission_date, e.created_at::date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_enrolment_daily ON mv_enrolment_daily (institution_id, college_id, department_id, program_id, batch_id, category, gender, quota, status, day);
CREATE INDEX IF NOT EXISTS ix_mv_enrolment_daily_inst ON mv_enrolment_daily (institution_id);

-- mv_attendance_term: Per enrolment × offering: sessions held / present / %, shortfall vs threshold
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_attendance_term AS
SELECT a.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, o.term_id,
       o.department_id AS offering_department_id, a.offering_id, a.student_program_enrollment_id AS enrollment_id,
       a.total_sessions AS sessions_held, (a.present + a.late + a.on_duty) AS sessions_present, a.pct,
       GREATEST(0, 75 - a.pct)::numeric(5,2) AS shortfall_pct, (a.eligibility <> 'eligible') AS is_short,
       a.eligibility, a.computed_at AS last_computed
FROM attendance_summaries a
JOIN course_offerings o ON o.id = a.offering_id
JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_attendance_term ON mv_attendance_term (offering_id, enrollment_id);
CREATE INDEX IF NOT EXISTS ix_mv_attendance_term_inst ON mv_attendance_term (institution_id);

-- mv_fees_position: Per enrolment: billed / paid / overdue paise and aging bands
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_fees_position AS
SELECT i.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id,
       i.student_program_enrollment_id AS enrollment_id,
       SUM(i.total_paise - i.discount_paise + i.tax_paise + i.fine_paise)::bigint AS billed_paise,
       SUM(i.paid_paise)::bigint AS paid_paise, SUM(i.balance_paise)::bigint AS balance_paise,
       SUM(CASE WHEN i.due_date < CURRENT_DATE THEN i.balance_paise ELSE 0 END)::bigint AS overdue_paise,
       SUM(CASE WHEN i.due_date < CURRENT_DATE AND CURRENT_DATE - i.due_date <= 30 THEN i.balance_paise ELSE 0 END)::bigint AS aging_0_30_paise,
       SUM(CASE WHEN CURRENT_DATE - i.due_date BETWEEN 31 AND 60 THEN i.balance_paise ELSE 0 END)::bigint AS aging_31_60_paise,
       SUM(CASE WHEN CURRENT_DATE - i.due_date BETWEEN 61 AND 90 THEN i.balance_paise ELSE 0 END)::bigint AS aging_61_90_paise,
       SUM(CASE WHEN CURRENT_DATE - i.due_date > 90 THEN i.balance_paise ELSE 0 END)::bigint AS aging_90_plus_paise,
       COUNT(*)::int AS invoices, MAX(i.updated_at) AS last_activity_at
FROM fee_invoices i
JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id
WHERE i.student_program_enrollment_id IS NOT NULL AND i.status NOT IN ('cancelled', 'refunded')
GROUP BY i.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, i.student_program_enrollment_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_fees_position ON mv_fees_position (enrollment_id);
CREATE INDEX IF NOT EXISTS ix_mv_fees_position_inst ON mv_fees_position (institution_id);

-- mv_exam_progress: Per exam session: registrations, eligibility, hall tickets, scripts, valuation %, discrepancies, results stage
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_exam_progress AS
SELECT s.institution_id, s.college_id, s.term_id, s.id AS exam_session_id, s.name, s.exam_kind, s.status,
       COALESCE(r.registrations, 0) AS registrations, COALESCE(r.confirmed, 0) AS confirmed,
       COALESCE(r.eligibility_applied, 0) AS eligibility_applied, COALESCE(r.hall_tickets, 0) AS hall_tickets,
       COALESCE(sc.scripts, 0) AS scripts, COALESCE(sc.valuated, 0) AS scripts_valuated,
       COALESCE(sc.discrepancies, 0) AS discrepancies,
       CASE WHEN COALESCE(sc.scripts, 0) = 0 THEN 0
            ELSE ROUND(100.0 * sc.valuated / sc.scripts, 2) END::numeric(5,2) AS valuation_pct,
       CASE WHEN s.status IN ('results_published', 'closed') THEN 'published'
            WHEN s.status = 'result_processing' THEN 'processing' ELSE 'pending' END AS results_stage
FROM exam_sessions s
LEFT JOIN (
  SELECT exam_session_id, COUNT(*)::int AS registrations,
         COUNT(*) FILTER (WHERE status = 'confirmed')::int AS confirmed,
         COUNT(*) FILTER (WHERE eligibility_snapshot IS NOT NULL)::int AS eligibility_applied,
         COUNT(*) FILTER (WHERE hall_ticket_issued_at IS NOT NULL)::int AS hall_tickets
  FROM exam_registrations GROUP BY exam_session_id
) r ON r.exam_session_id = s.id
LEFT JOIN (
  SELECT er.exam_session_id, COUNT(a.id)::int AS scripts,
         COUNT(a.id) FILTER (WHERE a.status IN ('valuated', 'finalized', 'moderated', 'decoded', 'archived'))::int AS valuated,
         COUNT(a.id) FILTER (WHERE a.status IN ('discrepancy', 'third_valuation'))::int AS discrepancies
  FROM answer_scripts a
  JOIN exam_registration_items it ON it.id = a.exam_registration_item_id
  JOIN exam_registrations er ON er.id = it.exam_registration_id
  GROUP BY er.exam_session_id
) sc ON sc.exam_session_id = s.id
WHERE s.deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_exam_progress ON mv_exam_progress (exam_session_id);
CREATE INDEX IF NOT EXISTS ix_mv_exam_progress_inst ON mv_exam_progress (institution_id);

-- mv_results_summary: Per term × programme × batch: pass %, SGPA distribution, arrears, toppers
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_results_summary AS
SELECT e.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, tr.term_id,
       COUNT(*)::int AS students, COUNT(*) FILTER (WHERE r.backlog_count = 0)::int AS passed,
       ROUND(100.0 * COUNT(*) FILTER (WHERE r.backlog_count = 0) / NULLIF(COUNT(*), 0), 2)::numeric(5,2) AS pass_pct,
       ROUND(AVG(r.sgpa), 2)::numeric(4,2) AS avg_sgpa, MAX(r.sgpa) AS top_sgpa,
       SUM(r.backlog_count)::int AS arrears,
       COUNT(*) FILTER (WHERE r.sgpa < 5)::int AS sgpa_lt5,
       COUNT(*) FILTER (WHERE r.sgpa >= 5 AND r.sgpa < 6)::int AS sgpa_5_6,
       COUNT(*) FILTER (WHERE r.sgpa >= 6 AND r.sgpa < 7)::int AS sgpa_6_7,
       COUNT(*) FILTER (WHERE r.sgpa >= 7 AND r.sgpa < 8)::int AS sgpa_7_8,
       COUNT(*) FILTER (WHERE r.sgpa >= 8 AND r.sgpa < 9)::int AS sgpa_8_9,
       COUNT(*) FILTER (WHERE r.sgpa >= 9)::int AS sgpa_9_plus
FROM student_term_results r
JOIN student_term_records tr ON tr.id = r.student_term_record_id
JOIN student_program_enrollments e ON e.id = tr.student_program_enrollment_id
WHERE r.is_current AND r.status = 'published'
GROUP BY e.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, tr.term_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_results_summary ON mv_results_summary (institution_id, college_id, department_id, program_id, batch_id, term_id);
CREATE INDEX IF NOT EXISTS ix_mv_results_summary_inst ON mv_results_summary (institution_id);

-- mv_hr_snapshot: Staff by department / designation / cadre, leaves pending, attendance today
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hr_snapshot AS
SELECT s.institution_id, s.college_id, s.department_id, COALESCE(s.designation_id, '00000000-0000-0000-0000-000000000000'::uuid) AS designation_id,
       COALESCE(d.cadre, '') AS cadre, COALESCE(s.staff_category, '') AS staff_category,
       COUNT(*) FILTER (WHERE s.status IN ('active', 'on_leave'))::int AS headcount,
       COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM staff_leaves l WHERE l.staff_id = s.id AND l.status = 'approved'
                                      AND CURRENT_DATE BETWEEN l.from_date AND l.to_date))::int AS on_leave_today,
       COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM staff_attendance a WHERE a.staff_id = s.id
                                      AND a.attendance_date = CURRENT_DATE
                                      AND a.status IN ('present', 'half_day', 'on_duty')))::int AS present_today,
       COALESCE(SUM((SELECT COUNT(*) FROM staff_leaves l WHERE l.staff_id = s.id AND l.status = 'pending')), 0)::int AS leaves_pending
FROM staff s
LEFT JOIN designations d ON d.id = s.designation_id
WHERE s.deleted_at IS NULL AND s.status <> 'exited'
GROUP BY s.institution_id, s.college_id, s.department_id, COALESCE(s.designation_id, '00000000-0000-0000-0000-000000000000'::uuid), COALESCE(d.cadre, ''),
         COALESCE(s.staff_category, '');
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_hr_snapshot ON mv_hr_snapshot (institution_id, college_id, department_id, designation_id, cadre, staff_category);
CREATE INDEX IF NOT EXISTS ix_mv_hr_snapshot_inst ON mv_hr_snapshot (institution_id);

-- mv_admissions_funnel: Per cycle × programme: applications → verified → merit → allotted → admitted, by category / quota
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_admissions_funnel AS
SELECT a.institution_id, COALESCE(p.college_id, c.college_id) AS college_id, a.cycle_id,
       COALESCE(p.program_id, '00000000-0000-0000-0000-000000000000'::uuid) AS program_id, COALESCE(a.category, '') AS category,
       COALESCE(a.quota_claimed, '') AS quota,
       COUNT(*) FILTER (WHERE a.status <> 'draft')::int AS applications,
       COUNT(*) FILTER (WHERE a.status IN ('verified', 'waitlisted', 'merit_listed', 'allotted', 'accepted',
                                           'provisionally_admitted', 'admitted'))::int AS verified,
       COUNT(*) FILTER (WHERE a.status IN ('merit_listed', 'allotted', 'accepted', 'provisionally_admitted',
                                           'admitted'))::int AS merit,
       COUNT(*) FILTER (WHERE a.status IN ('allotted', 'accepted', 'provisionally_admitted', 'admitted'))::int AS allotted,
       COUNT(*) FILTER (WHERE a.status IN ('provisionally_admitted', 'admitted') OR a.admitted_student_id IS NOT NULL)::int AS admitted,
       COUNT(*)::int AS started
FROM applicants a
JOIN admission_cycles c ON c.id = a.cycle_id
LEFT JOIN applicant_preferences p ON p.applicant_id = a.id AND p.priority = 1
WHERE a.deleted_at IS NULL
GROUP BY a.institution_id, COALESCE(p.college_id, c.college_id), a.cycle_id, COALESCE(p.program_id, '00000000-0000-0000-0000-000000000000'::uuid),
         COALESCE(a.category, ''), COALESCE(a.quota_claimed, '');
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_admissions_funnel ON mv_admissions_funnel (institution_id, college_id, cycle_id, program_id, category, quota);
CREATE INDEX IF NOT EXISTS ix_mv_admissions_funnel_inst ON mv_admissions_funnel (institution_id);

-- mv_placement_funnel: Per drive / batch: eligible → applied → rounds → offers → accepted, CTC bands
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_placement_funnel AS
SELECT d.institution_id, COALESCE(e.college_id, d.college_id) AS college_id, e.department_id,
       COALESCE(e.batch_id, '00000000-0000-0000-0000-000000000000'::uuid) AS batch_id, d.id AS drive_id, d.status AS drive_status, d.drive_on,
       COUNT(da.id) FILTER (WHERE da.is_eligible)::int AS eligible, COUNT(da.id)::int AS applied,
       COUNT(da.id) FILTER (WHERE da.status IN ('shortlisted', 'in_process', 'selected', 'offer_accepted',
                                                'offer_declined'))::int AS in_rounds,
       COUNT(o.id)::int AS offers, COUNT(o.id) FILTER (WHERE o.status IN ('accepted', 'joined'))::int AS accepted,
       COUNT(o.id) FILTER (WHERE o.ctc_paise < 50000000)::int AS ctc_lt5l,
       COUNT(o.id) FILTER (WHERE o.ctc_paise >= 50000000 AND o.ctc_paise < 100000000)::int AS ctc_5_10l,
       COUNT(o.id) FILTER (WHERE o.ctc_paise >= 100000000 AND o.ctc_paise < 200000000)::int AS ctc_10_20l,
       COUNT(o.id) FILTER (WHERE o.ctc_paise >= 200000000)::int AS ctc_20l_plus,
       COALESCE(MAX(o.ctc_paise), 0)::bigint AS max_ctc_paise
FROM placement_drives d
LEFT JOIN drive_applications da ON da.drive_id = d.id
LEFT JOIN student_program_enrollments e ON e.id = da.student_program_enrollment_id
LEFT JOIN placement_offers o ON o.application_id = da.id
GROUP BY d.institution_id, COALESCE(e.college_id, d.college_id), e.department_id, COALESCE(e.batch_id, '00000000-0000-0000-0000-000000000000'::uuid), d.id,
         d.status, d.drive_on;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_placement_funnel ON mv_placement_funnel (institution_id, college_id, department_id, batch_id, drive_id);
CREATE INDEX IF NOT EXISTS ix_mv_placement_funnel_inst ON mv_placement_funnel (institution_id);

-- mv_hostel_occupancy: Per hostel / block: beds, occupied, leave-out today, complaints open
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hostel_occupancy AS
SELECT h.institution_id, h.college_id, h.id AS hostel_id, b.id AS block_id, h.name AS hostel_name, b.name AS block_name,
       h.warden_staff_id,
       COUNT(bd.id)::int AS beds, COUNT(bd.id) FILTER (WHERE bd.status = 'allocated')::int AS occupied,
       (SELECT COUNT(*) FROM hostel_leaves l WHERE l.hostel_id = h.id AND l.status = 'out')::int AS leave_out_today,
       (SELECT COUNT(*) FROM hostel_complaints c JOIN hostel_rooms cr ON cr.id = c.room_id
         WHERE cr.block_id = b.id AND c.status NOT IN ('resolved', 'closed'))::int AS complaints_open
FROM hostels h
JOIN hostel_blocks b ON b.hostel_id = h.id
LEFT JOIN hostel_rooms r ON r.block_id = b.id
LEFT JOIN hostel_beds bd ON bd.room_id = r.id
WHERE h.deleted_at IS NULL
GROUP BY h.institution_id, h.college_id, h.id, b.id, h.name, b.name, h.warden_staff_id;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_hostel_occupancy ON mv_hostel_occupancy (block_id);
CREATE INDEX IF NOT EXISTS ix_mv_hostel_occupancy_inst ON mv_hostel_occupancy (institution_id);

-- mv_research_counts: Per department / year: publications by indexing, projects / grants amount, PhD scholars by status
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_research_counts AS
SELECT x.institution_id, x.college_id, COALESCE(x.department_id, '00000000-0000-0000-0000-000000000000'::uuid) AS department_id, x.year, x.metric, x.sub_key,
       COUNT(*)::int AS count, COALESCE(SUM(x.amount_paise), 0)::bigint AS amount_paise
FROM (
  SELECT p.institution_id, s.college_id, s.department_id, COALESCE(p.year, 0)::int AS year, 'publications' AS metric,
         COALESCE(p.indexing, 'none') AS sub_key, 0::bigint AS amount_paise
  FROM publications p LEFT JOIN staff s ON s.id = p.staff_id
  UNION ALL
  SELECT rp.institution_id, s.college_id, s.department_id, COALESCE(EXTRACT(YEAR FROM rp.start_on), 0)::int, 'projects',
         rp.status, COALESCE(rp.sanctioned_paise, 0)::bigint
  FROM research_projects rp LEFT JOIN staff s ON s.id = rp.pi_staff_id
  UNION ALL
  SELECT rs.institution_id, e.college_id, e.department_id, COALESCE(EXTRACT(YEAR FROM rs.registration_date), 0)::int,
         'scholars', rs.status, 0::bigint
  FROM research_scholars rs JOIN student_program_enrollments e ON e.id = rs.student_program_enrollment_id
) x
GROUP BY x.institution_id, x.college_id, COALESCE(x.department_id, '00000000-0000-0000-0000-000000000000'::uuid), x.year, x.metric, x.sub_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_research_counts ON mv_research_counts (institution_id, college_id, department_id, year, metric, sub_key);
CREATE INDEX IF NOT EXISTS ix_mv_research_counts_inst ON mv_research_counts (institution_id);

-- mv_service_desk_sla: Per category: open, breached, MTTR
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_service_desk_sla AS
SELECT r.institution_id, COALESCE(r.college_id, '00000000-0000-0000-0000-000000000000'::uuid) AS college_id, r.category,
       COUNT(*) FILTER (WHERE r.status NOT IN ('resolved', 'closed'))::int AS open,
       COUNT(*) FILTER (WHERE r.status NOT IN ('resolved', 'closed') AND r.sla_due_at < NOW())::int AS breached,
       COUNT(*) FILTER (WHERE r.resolved_at IS NOT NULL)::int AS resolved,
       COUNT(*) FILTER (WHERE r.resolved_at IS NOT NULL AND (r.sla_due_at IS NULL OR r.resolved_at <= r.sla_due_at))::int AS within_sla,
       ROUND(AVG(EXTRACT(EPOCH FROM (r.resolved_at - r.created_at)) / 3600.0)
             FILTER (WHERE r.resolved_at IS NOT NULL), 2)::numeric(10,2) AS mttr_hours
FROM service_requests r
GROUP BY r.institution_id, COALESCE(r.college_id, '00000000-0000-0000-0000-000000000000'::uuid), r.category;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_service_desk_sla ON mv_service_desk_sla (institution_id, college_id, category);
CREATE INDEX IF NOT EXISTS ix_mv_service_desk_sla_inst ON mv_service_desk_sla (institution_id);

-- mv_risk_cohort: Per term × department × programme × batch × level: counts, factor means, acknowledged %, interventions
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_risk_cohort AS
SELECT f.institution_id, e.college_id, f.term_id, e.department_id, e.program_id, e.batch_id,
       COALESCE(s.category, '') AS category, COALESCE(h.hostel_id, '00000000-0000-0000-0000-000000000000'::uuid) AS hostel_id, f.level,
       COUNT(*)::int AS students,
       ROUND(AVG((f.factors -> 'attendance' ->> 'value')::numeric), 3) AS attendance_mean,
       ROUND(AVG((f.factors -> 'cia' ->> 'value')::numeric), 3) AS cia_mean,
       ROUND(AVG((f.factors -> 'dues' ->> 'value')::numeric), 3) AS dues_mean,
       ROUND(AVG((f.factors -> 'standing' ->> 'value')::numeric), 3) AS standing_mean,
       ROUND(AVG((f.factors -> 'hostel' ->> 'value')::numeric), 3) AS hostel_mean,
       ROUND(AVG((f.factors -> 'engagement' ->> 'value')::numeric), 3) AS engagement_mean,
       ROUND(AVG(f.score), 2) AS score_mean,
       COUNT(*) FILTER (WHERE f.acknowledged_at IS NOT NULL)::int AS acknowledged,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.acknowledged_at IS NOT NULL) / NULLIF(COUNT(*), 0), 2)::numeric(5,2) AS acknowledged_pct,
       COALESCE(SUM((SELECT COUNT(*) FROM mentoring_sessions ms JOIN mentor_assignments ma ON ma.id = ms.mentor_assignment_id
                      WHERE ma.student_program_enrollment_id = f.student_program_enrollment_id
                        AND ms.mode = 'intervention')), 0)::int AS interventions
FROM risk_flags f
JOIN student_program_enrollments e ON e.id = f.student_program_enrollment_id
JOIN students s ON s.id = e.student_id
LEFT JOIN LATERAL (
  SELECT ha.hostel_id FROM hostel_allocations ha
  WHERE ha.student_program_enrollment_id = e.id AND ha.status IN ('allotted', 'checked_in')
  ORDER BY ha.created_at DESC LIMIT 1
) h ON TRUE
GROUP BY f.institution_id, e.college_id, f.term_id, e.department_id, e.program_id, e.batch_id, COALESCE(s.category, ''),
         COALESCE(h.hostel_id, '00000000-0000-0000-0000-000000000000'::uuid), f.level;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_risk_cohort ON mv_risk_cohort (institution_id, college_id, term_id, department_id, program_id, batch_id, category, hostel_id, level);
CREATE INDEX IF NOT EXISTS ix_mv_risk_cohort_inst ON mv_risk_cohort (institution_id);

-- mv_kpi_daily: One row per institution × college × day: the headline numbers used by Home cards
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_kpi_daily AS
WITH keys AS (SELECT institution_id, id AS college_id, id::text AS ckey FROM colleges WHERE deleted_at IS NULL UNION ALL SELECT id, NULL::uuid, 'all' FROM institutions WHERE deleted_at IS NULL),
stu AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, COUNT(*) FILTER (WHERE status = 'active') AS students_active, COUNT(*) AS students_total FROM (SELECT e.institution_id, e.college_id, e.status FROM student_program_enrollments e WHERE e.deleted_at IS NULL) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
prg AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, COUNT(*) FILTER (WHERE status = 'active') AS programmes FROM (SELECT institution_id, college_id, status FROM programs WHERE deleted_at IS NULL) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
stf AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, COUNT(*) AS staff_active, COUNT(*) FILTER (WHERE staff_category = 'teaching') AS faculty_count FROM (SELECT institution_id, college_id, staff_category, status FROM staff WHERE deleted_at IS NULL AND status <> 'exited') s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
hrs AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, SUM(present_today) AS staff_present_today, SUM(on_leave_today) AS staff_on_leave_today, SUM(leaves_pending) AS leaves_pending FROM (SELECT institution_id, college_id, present_today, on_leave_today, leaves_pending FROM mv_hr_snapshot) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
att AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, ROUND(AVG(pct), 2) AS attendance_avg_pct, COUNT(DISTINCT enrollment_id) FILTER (WHERE is_short) AS attendance_shortfall FROM (SELECT institution_id, college_id, pct, is_short, enrollment_id FROM mv_attendance_term a WHERE a.term_id IN (SELECT id FROM academic_terms WHERE is_current)) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
fee AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, SUM(billed_paise) AS fee_billed_paise, SUM(paid_paise) AS fee_collected_paise, SUM(overdue_paise) AS fee_overdue_paise, COUNT(*) FILTER (WHERE overdue_paise > 0) AS fee_defaulters, ROUND(100.0 * SUM(paid_paise) / NULLIF(SUM(billed_paise), 0), 2) AS fee_collection_pct FROM (SELECT institution_id, college_id, billed_paise, paid_paise, overdue_paise FROM mv_fees_position) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
pay AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, SUM(amount_paise) AS fee_collected_today_paise FROM (SELECT p.institution_id, i.college_id, p.amount_paise FROM fee_payments p JOIN fee_invoices i ON i.id = p.invoice_id WHERE p.status IN ('success', 'reconciled') AND p.payment_date::date = CURRENT_DATE) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
exm AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, COUNT(*) FILTER (WHERE status NOT IN ('draft', 'results_published', 'closed')) AS exam_sessions_active, ROUND(AVG(valuation_pct) FILTER (WHERE status = 'valuation'), 2) AS valuation_pct FROM (SELECT institution_id, college_id, status, valuation_pct FROM mv_exam_progress) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
res AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, ROUND(100.0 * SUM(passed) / NULLIF(SUM(students), 0), 2) AS result_pass_pct, ROUND(AVG(avg_sgpa), 2) AS avg_sgpa FROM (SELECT institution_id, college_id, students, passed, avg_sgpa FROM mv_results_summary) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
adm AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, SUM(applications) AS applications, SUM(admitted) AS admitted FROM (SELECT f.institution_id, f.college_id, f.applications, f.admitted FROM mv_admissions_funnel f JOIN admission_cycles c ON c.id = f.cycle_id WHERE c.status NOT IN ('archived')) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
enq AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, COUNT(*) FILTER (WHERE stage NOT IN ('admitted', 'lost')) AS enquiries_open FROM (SELECT institution_id, college_id, stage FROM enquiries) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
plc AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, SUM(offers) AS placement_offers, SUM(accepted) AS placement_accepted, ROUND(100.0 * SUM(accepted) / NULLIF(SUM(eligible), 0), 2) AS placement_pct FROM (SELECT institution_id, college_id, offers, accepted, eligible FROM mv_placement_funnel) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
hst AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, SUM(beds) AS hostel_beds, SUM(occupied) AS hostel_occupied, SUM(leave_out_today) AS hostel_out_today, SUM(complaints_open) AS hostel_complaints_open FROM (SELECT institution_id, college_id, beds, occupied, leave_out_today, complaints_open FROM mv_hostel_occupancy) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
lib AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, COUNT(*) FILTER (WHERE returned_on IS NULL) AS library_issued, COUNT(*) FILTER (WHERE returned_on IS NULL AND due_on < CURRENT_DATE) AS library_overdue FROM (SELECT institution_id, NULL::uuid AS college_id, status, due_on, returned_on FROM book_issues) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
grv AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, COUNT(*) FILTER (WHERE status NOT IN ('resolved', 'closed')) AS grievances_open, COUNT(*) FILTER (WHERE status NOT IN ('resolved', 'closed') AND sla_due_at < NOW()) AS grievances_breached, ROUND(100.0 * COUNT(*) FILTER (WHERE resolved_at IS NOT NULL AND (sla_due_at IS NULL OR resolved_at <= sla_due_at)) / NULLIF(COUNT(*) FILTER (WHERE resolved_at IS NOT NULL), 0), 2) AS grievance_sla_pct FROM (SELECT institution_id, college_id, status, sla_due_at, resolved_at FROM grievances) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
srv AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, SUM(open) AS service_open, SUM(breached) AS service_breached FROM (SELECT institution_id, NULLIF(college_id, '00000000-0000-0000-0000-000000000000'::uuid) AS college_id, open, breached FROM mv_service_desk_sla) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
rsk AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, SUM(students) FILTER (WHERE level = 'high') AS risk_high, SUM(students) FILTER (WHERE level = 'medium') AS risk_medium FROM (SELECT institution_id, college_id, level, students FROM mv_risk_cohort WHERE term_id IN (SELECT id FROM academic_terms WHERE is_current)) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
rch AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, SUM(count) FILTER (WHERE metric = 'publications' AND year = EXTRACT(YEAR FROM CURRENT_DATE)) AS publications_year, SUM(count) FILTER (WHERE metric = 'projects' AND sub_key IN ('sanctioned', 'ongoing')) AS projects_active, SUM(count) FILTER (WHERE metric = 'scholars' AND sub_key NOT IN ('awarded', 'discontinued')) AS scholars_active FROM (SELECT institution_id, college_id, metric, sub_key, year, count FROM mv_research_counts) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id))),
hld AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' ELSE COALESCE(college_id::text, 'none') END AS ckey, COUNT(*) AS holds_active FROM (SELECT h.institution_id, e.college_id FROM student_holds h JOIN student_program_enrollments e ON e.id = h.student_program_enrollment_id WHERE h.released_at IS NULL) s GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id)))
SELECT k.institution_id, k.college_id, k.ckey AS college_key, CURRENT_DATE AS day, NOW() AS refreshed_at,
       COALESCE(stu.students_active, 0) AS students_active,
       COALESCE(stu.students_total, 0) AS students_total,
       COALESCE(prg.programmes, 0) AS programmes,
       COALESCE(stf.staff_active, 0) AS staff_active,
       COALESCE(stf.faculty_count, 0) AS faculty_count,
       COALESCE(hrs.staff_present_today, 0) AS staff_present_today,
       COALESCE(hrs.staff_on_leave_today, 0) AS staff_on_leave_today,
       COALESCE(hrs.leaves_pending, 0) AS leaves_pending,
       att.attendance_avg_pct AS attendance_avg_pct,
       COALESCE(att.attendance_shortfall, 0) AS attendance_shortfall,
       COALESCE(fee.fee_billed_paise, 0) AS fee_billed_paise,
       COALESCE(fee.fee_collected_paise, 0) AS fee_collected_paise,
       COALESCE(fee.fee_overdue_paise, 0) AS fee_overdue_paise,
       COALESCE(fee.fee_defaulters, 0) AS fee_defaulters,
       fee.fee_collection_pct AS fee_collection_pct,
       COALESCE(pay.fee_collected_today_paise, 0) AS fee_collected_today_paise,
       COALESCE(exm.exam_sessions_active, 0) AS exam_sessions_active,
       exm.valuation_pct AS valuation_pct,
       res.result_pass_pct AS result_pass_pct,
       res.avg_sgpa AS avg_sgpa,
       COALESCE(adm.applications, 0) AS applications,
       COALESCE(adm.admitted, 0) AS admitted,
       COALESCE(enq.enquiries_open, 0) AS enquiries_open,
       COALESCE(plc.placement_offers, 0) AS placement_offers,
       COALESCE(plc.placement_accepted, 0) AS placement_accepted,
       plc.placement_pct AS placement_pct,
       COALESCE(hst.hostel_beds, 0) AS hostel_beds,
       COALESCE(hst.hostel_occupied, 0) AS hostel_occupied,
       COALESCE(hst.hostel_out_today, 0) AS hostel_out_today,
       COALESCE(hst.hostel_complaints_open, 0) AS hostel_complaints_open,
       COALESCE(lib.library_issued, 0) AS library_issued,
       COALESCE(lib.library_overdue, 0) AS library_overdue,
       COALESCE(grv.grievances_open, 0) AS grievances_open,
       COALESCE(grv.grievances_breached, 0) AS grievances_breached,
       grv.grievance_sla_pct AS grievance_sla_pct,
       COALESCE(srv.service_open, 0) AS service_open,
       COALESCE(srv.service_breached, 0) AS service_breached,
       COALESCE(rsk.risk_high, 0) AS risk_high,
       COALESCE(rsk.risk_medium, 0) AS risk_medium,
       COALESCE(rch.publications_year, 0) AS publications_year,
       COALESCE(rch.projects_active, 0) AS projects_active,
       COALESCE(rch.scholars_active, 0) AS scholars_active,
       COALESCE(hld.holds_active, 0) AS holds_active
FROM keys k
LEFT JOIN stu ON stu.institution_id = k.institution_id AND stu.ckey = k.ckey
LEFT JOIN prg ON prg.institution_id = k.institution_id AND prg.ckey = k.ckey
LEFT JOIN stf ON stf.institution_id = k.institution_id AND stf.ckey = k.ckey
LEFT JOIN hrs ON hrs.institution_id = k.institution_id AND hrs.ckey = k.ckey
LEFT JOIN att ON att.institution_id = k.institution_id AND att.ckey = k.ckey
LEFT JOIN fee ON fee.institution_id = k.institution_id AND fee.ckey = k.ckey
LEFT JOIN pay ON pay.institution_id = k.institution_id AND pay.ckey = k.ckey
LEFT JOIN exm ON exm.institution_id = k.institution_id AND exm.ckey = k.ckey
LEFT JOIN res ON res.institution_id = k.institution_id AND res.ckey = k.ckey
LEFT JOIN adm ON adm.institution_id = k.institution_id AND adm.ckey = k.ckey
LEFT JOIN enq ON enq.institution_id = k.institution_id AND enq.ckey = k.ckey
LEFT JOIN plc ON plc.institution_id = k.institution_id AND plc.ckey = k.ckey
LEFT JOIN hst ON hst.institution_id = k.institution_id AND hst.ckey = k.ckey
LEFT JOIN lib ON lib.institution_id = k.institution_id AND lib.ckey = k.ckey
LEFT JOIN grv ON grv.institution_id = k.institution_id AND grv.ckey = k.ckey
LEFT JOIN srv ON srv.institution_id = k.institution_id AND srv.ckey = k.ckey
LEFT JOIN rsk ON rsk.institution_id = k.institution_id AND rsk.ckey = k.ckey
LEFT JOIN rch ON rch.institution_id = k.institution_id AND rch.ckey = k.ckey
LEFT JOIN hld ON hld.institution_id = k.institution_id AND hld.ckey = k.ckey;
CREATE UNIQUE INDEX IF NOT EXISTS uq_mv_kpi_daily ON mv_kpi_daily (institution_id, college_key, day);
CREATE INDEX IF NOT EXISTS ix_mv_kpi_daily_inst ON mv_kpi_daily (institution_id);

-- ===================================== END =====================================
-- Sanity: SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';
