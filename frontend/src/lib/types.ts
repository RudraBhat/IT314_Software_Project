export type Paged<T> = {
  items: T[];
  page: number;
  pages: number;
  total: number;
  limit: number;
};

export type IncidentRow = {
  incident_id: string;
  incident_ref: string;
  scenario: string;
  status: string;
  verified_priority: string | null;
  reported_urgency: string | null;
  people_affected: number;
  address_text: string | null;
  latitude: number | null;
  longitude: number | null;
  canonical_incident_id: string | null;
  submitted_at: string;
  updated_at: string;
  version: number;
  evidence_count: number;
  active_dispatches: number;
  /** The reporter asked for this report to be withdrawn and it is still withdrawable. */
  withdrawal_requested: boolean;
};

export type Dispatch = {
  dispatch_id: string;
  dispatch_ref: string;
  incident_id: string;
  incident_ref: string;
  scenario: string;
  agency_name: string;
  status: string;
  priority: string;
  created_at: string;
  created_by_name: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  instructions: string | null;
  overdue: boolean;
  escalated: boolean;
};

export type Agency = {
  agency_id: string;
  name: string;
  is_active: boolean;
  contact_phone: string | null;
  // Returned by GET /agency-contacts; the dispatch screens only need the fields above.
  agency_type?: string;
  contact_email?: string | null;
  updated_at?: string;
};

export type Resource = {
  resource_id: string;
  agency_id: string | null;
  agency_name: string | null;
  name: string;
  type: string;
  status: string;
  capability: Record<string, unknown>;
  quantity_total: number | string;
  quantity_available: number | string;
  latitude: number | null;
  longitude: number | null;
  version: number;
  updated_at: string;
};

export type Dashboard = {
  generated_at: string;
  data_fresh_as_of: string | null;
  incidents: {
    total: number;
    pending_verification: number;
    needs_information: number;
    verified_active: number;
    critical_open: number;
    high_open: number;
    unprioritised_open: number;
  };
  dispatches: {
    active: number;
    awaiting_ack: number;
    overdue: number;
    ack_timeout_minutes: number;
  };
  resources: {
    available: number;
    total: number;
    by_type: { type: string; available: number; total: number }[];
  };
  aid: {
    awaiting_verification: number;
    open_needs: number;
  };
  moderation: {
    pending: number;
    oldest: string | null;
  };
  verification_queue: Pick<
    IncidentRow,
    "incident_id" | "incident_ref" | "scenario" | "status" | "reported_urgency" | "people_affected" | "address_text" | "submitted_at"
  >[];
  by_scenario: { scenario: string; open: number; total: number }[];
  recent_activity: {
    history_id: number;
    incident_id: string;
    incident_ref: string;
    changed_at: string;
    from_status: string | null;
    to_status: string;
    reason: string | null;
    changed_by_name: string | null;
  }[];
};
