export type DeviceStatus = "device" | "offline" | "unauthorized" | "unknown";

export interface Device {
  id: string;
  status?: DeviceStatus | string;
}

export interface Decision {
  goal?: string;
  decision_mode?: string;
  attempt?: number;
  done?: boolean;
  stop_reason?: string;
  actions?: unknown[];
  plan_verify?: string;
}

export interface StepSummary {
  id: string;
  step_id?: string;
  decision?: Decision;
  has_screen?: boolean;
  updated_time?: number;
}

export interface StepDetails extends StepSummary {
  run_id?: string;
  prompt?: string;
  response?: string;
  context?: unknown;
  ocr_payload?: unknown;
  verification?: unknown;
  screen_url?: string;
  step_screen_url?: string;
  step_after_url?: string;
}

export interface RunMeta {
  id: string;
  goal?: string;
  status?: string;
  device_id?: string;
  device?: string;
  updated_time?: number;
  start_time?: number;
  end_time?: number;
  exit_code?: number;
  command?: string[];
  trace_dir?: string;
  output_path?: string;
  log_path?: string;
  pid?: number;
  stop_requested?: number;
  steps?: StepSummary[];
}

export interface RunLogResponse {
  run_id: string;
  text: string;
  lines: number;
  total_lines: number;
  truncated: boolean;
  updated_time?: number;
  log_path?: string;
}

export interface WebrtcConfig {
  ice_servers?: Array<string | RTCIceServer>;
}

export interface RunRequest {
  goal: string;
  device?: string;
  execute: boolean;
  plan: boolean;
  plan_max_steps: number;
  plan_verify: string;
  plan_resume: boolean;
  max_steps: number;
  max_actions?: number;
  skills: boolean;
  skills_only?: boolean;
  text_only: boolean;
  decision_mode?: string;
}

export interface WebRTCOffer {
  device_id: string;
  sdp: string;
  type: RTCSdpType;
}

export interface WebRTCAnswer {
  sdp: string;
  type: RTCSdpType;
}

export interface StopRunResponse {
  id: string;
  status: string;
}

export type DeviceCommandType =
  | "tap"
  | "swipe"
  | "keyevent"
  | "input_text"
  | "start_app"
  | "back"
  | "home"
  | "recent"
  | "wait";

export interface DeviceCommandRequest {
  type: DeviceCommandType;
  x?: number;
  y?: number;
  x1?: number;
  y1?: number;
  x2?: number;
  y2?: number;
  duration_ms?: number;
  keycode?: string;
  text?: string;
  package?: string;
  activity?: string;
  wait_ms?: number;
}

export interface DeviceCommand {
  id: string;
  type: DeviceCommandType;
  status: string;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
  error?: string | null;
  payload: Record<string, unknown>;
}

export interface DeviceSession {
  device_id: string;
  status: string;
  pending: number;
  current_command_id?: string | null;
  last_error?: string | null;
  created_at: number;
  updated_at: number;
}

export interface DeviceQueueClearResponse {
  device_id: string;
  drained: number;
}

export interface DeviceSessionCloseResponse {
  device_id: string;
  closed: boolean;
}
