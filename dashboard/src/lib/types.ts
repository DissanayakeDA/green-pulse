// The dashboard API's JSON (backend/greenpulse_ai/device_state.py and api.py).

export type Priority = "low" | "medium" | "high" | "critical";
export type MetricState = "too_low" | "low" | "optimal" | "high" | "too_high" | "sensor_error";
export type MetricKey = "soil_moisture" | "temperature" | "humidity";

export interface Metric {
  value: number | null;
  unit: string;
  ideal_min: number;
  ideal_max: number;
  state: MetricState;
}

export interface Weather {
  source: string;
  location: string;
  summary: string;
  temperature_c: number | null;
  max_temperature_c: number | null;
  humidity: number | null;
  rain_expected: boolean;
  heat_alert: boolean;
}

export interface Reminder {
  kind: "watering" | "fertilising" | "repotting" | "travel" | "other";
  title: string;
  detail: string;
  sender: string;
  received: string | null;
}

export interface Notifications {
  source: string;
  summary: string;
  reminders: Reminder[];
}

export interface Analysis {
  generated_at: string;
  trigger: string;
  priority: Priority;
  priority_code: number;
  headline: string;
  message: string;
  actions: string[];
  reasoning: string;
  source: string; // llm | rules | rules-fallback
  model: string | null;
  guardrail_note: string | null;
  condition: string;
  summary: string;
  concerns: string[];
  weather: Weather;
  notifications: Notifications;
}

export interface PumpEvent {
  at: string;
  state: "on" | "off" | "rejected";
  source: string;
  seconds: number | null;
  detail: string;
}

export interface Watering {
  auto_enabled: boolean;
  pump_running: boolean;
  last_watered: string | null;
  last_decision: { auto_enabled: boolean; decision: "water" | "skip"; duration_s: number; reason: string } | null;
  events: PumpEvent[];
}

export type Range = [number, number];

export interface PlantProfile {
  key: string;
  name: string;
  scientific_name: string;
  moisture: Range;
  temperature: Range;
  humidity: Range;
  care_notes: string;
  source: "built-in" | "ai" | "custom";
  /** GET /api/plants only: the devices watching this plant */
  devices?: string[];
}

/** The Plant Profile Agent's suggestion for a plant name, after the checkpoint. Not saved yet. */
export interface ProfileDraft {
  name: string;
  scientific_name: string;
  moisture: Range;
  temperature: Range;
  humidity: Range;
  care_notes: string;
  recognised: boolean;
  source: string; // llm | rules | rules-fallback
  model: string | null;
  note: string;
  checks: string[];
}

export interface Snapshot {
  device_id: string;
  plant: PlantProfile;
  online: boolean;
  last_seen: string | null;
  reading: { timestamp: string; soil_moisture: number | null; temperature: number | null; humidity: number | null } | null;
  metrics: Record<MetricKey, Metric> | null;
  moisture_trend_per_hour: number | null;
  hours_until_dry: number | null;
  sensor_priority: Priority | null;
  analysis: Analysis | null;
  watering: Watering;
}

export interface DeviceSummary {
  device_id: string;
  online: boolean;
  last_seen: string | null;
}

export interface HistoryPoint {
  t: number;
  soil_moisture: number | null;
  temperature: number | null;
  humidity: number | null;
}

export interface History {
  device_id: string;
  hours: number;
  points: HistoryPoint[];
  waterings: { t: number; source: string; seconds: number | null }[];
}

/** GET /api/alerts (backend/greenpulse_ai/alerts.py) */
export interface AlertRecipient {
  id: string;
  email: string;
  verified: boolean;
  alerts: boolean;
  min_priority: "high" | "critical";
  daily: boolean;
  added_at: string;
  /** a sign-up code was sent and not used yet */
  code_pending: boolean;
}

export interface SentEmail {
  at: string;
  to: string;
  kind: "alert" | "offline" | "daily" | "code" | "test";
  subject: string;
  ok: boolean;
  error: string | null;
}

export interface AlertSettings {
  configured: boolean;
  sender: string | null;
  smtp_host: string | null;
  daily_hour: number;
  timezone: string;
  rules: { repeat_after_h: number; offline_after_min: number };
  recipients: AlertRecipient[];
  recent: SentEmail[];
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatAnswer {
  answer: string;
  source: string; // llm | rules | rules-fallback
  tools: string[];
  model: string | null;
}
