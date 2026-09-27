/** Workflow engine types (Prompts/04 §04.4 — mirrors app/schemas/workflow.py). */
export interface ApproverSpec {
  type: 'role' | 'scope_rule' | 'user';
  value: string;
}

export interface StepSpec {
  order: number;
  approver: ApproverSpec;
  mode?: 'sequential' | 'parallel';
  sla_hours?: number | null;
  escalate_to?: ApproverSpec | null;
}

export interface WorkflowDefinition {
  id: string;
  module: string;
  key: string;
  name: string;
  description: string | null;
  steps: StepSpec[];
  version: number;
  is_active: boolean;
  updated_at: string;
  versions: number[];
}

export interface WorkflowStep {
  id: string;
  order: number;
  approver_user_id: string | null;
  approver_name: string | null;
  approver_role_slug: string | null;
  status: string;
  acted_by: string | null;
  acted_by_name: string | null;
  delegated_from: string | null;
  acted_at: string | null;
  comment: string | null;
  sla_due_at: string | null;
  escalated_to: string | null;
}

export interface WorkflowInstance {
  id: string;
  definition_id: string;
  key: string;
  module: string;
  version: number;
  entity_type: string;
  entity_id: string;
  title: string | null;
  status: string;
  current_step: number;
  total_steps: number;
  started_by: string | null;
  started_by_name: string | null;
  started_at: string;
  closed_at: string | null;
  steps: WorkflowStep[];
  can_act: boolean;
  can_cancel: boolean;
}

export interface InboxItem {
  instance: WorkflowInstance;
  step_id: string;
  entity_summary: string | null;
  route: string | null;
  via: 'direct' | 'role' | 'delegation' | 'escalation';
}

export interface Delegation {
  id: string;
  from_user_id: string;
  to_user_id: string;
  from_user_name: string | null;
  to_user_name: string | null;
  module: string | null;
  from_on: string;
  to_on: string;
  is_active: boolean;
}
