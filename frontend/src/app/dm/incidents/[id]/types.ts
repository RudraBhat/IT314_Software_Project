export type IncidentDetail = {
  incident_id: string;
  incident_ref: string;
  scenario: string;
  description: string;
  reported_urgency: string | null;
  people_affected: number | null;
  status: string;
  withdrawal_requested: boolean;
  verified_priority: string | null;
  priority_rationale: string | null;
  verified_at: string | null;
  verified_by_name: string | null;
  canonical_incident_id: string | null;
  canonical_incident_ref: string | null;
  location_source: string;
  latitude: string | null;
  longitude: string | null;
  accuracy_m: string | null;
  address_text: string | null;
  landmark: string | null;
  details: Record<string, unknown>;
  version: number;
  submitted_at: string;
  updated_at: string;
  closed_at: string | null;
  reporter: { user_id: string; full_name: string; email: string; phone: string | null };
  evidence: {
    evidence_id: string;
    file_name: string;
    mime_type: string;
    size_bytes: number;
    sha256: string;
    scan_state: string;
    uploaded_at: string;
  }[];
  history: {
    history_id: number;
    from_status: string | null;
    to_status: string;
    reason: string | null;
    changed_at: string;
    changed_by_name: string | null;
  }[];
  dispatches: {
    dispatch_id: string;
    dispatch_ref: string;
    status: string;
    priority: string;
    created_at: string;
    acknowledged_at: string | null;
    acknowledged_by: string | null;
    agency_name: string | null;
  }[];
  agency_messages: {
    message_id: string;
    subject: string | null;
    body: string;
    status: string;
    created_at: string;
    acknowledged_at: string | null;
    dispatch_id: string | null;
    agency_name: string;
    sender_name: string;
  }[];
  linked_duplicates: { incident_id: string; incident_ref: string; status: string; scenario: string; submitted_at: string }[];
  audit_trail: { audit_id: number; occurred_at: string; action: string; result: string; rationale: string | null; actor_name: string }[];
  open_dependencies: {
    dispatches: { dispatch_id: string; dispatch_ref: string; status: string }[];
    allocations: { contribution_id: string; aid_type: string; quantity: string; unit: string; status: string }[];
  };
  allowed_actions: Record<
    | "verify"
    | "request_information"
    | "set_priority"
    | "dispatch"
    | "resolve"
    | "close"
    | "reopen"
    | "ai_triage"
    | "message_agencies",
    boolean
  >;
};
