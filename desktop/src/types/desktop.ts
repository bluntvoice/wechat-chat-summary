export type Settings = {
  wechat_api_url: string;
  provider: "deepseek" | "openai-compatible";
  api_url: string;
  model: string;
  thinking: boolean;
  reasoning_effort: "high" | "max";
  export_root: string;
  image_dpi: number;
  range_mode: "single" | "custom";
  last_chat_id: string;
  last_chat_name: string;
  schedule_enabled: boolean;
  schedule_time: string;
  schedule_date_mode: "today" | "yesterday";
  schedule_chat_id: string;
  schedule_chat_name: string;
  schedule_last_attempt_date: string;
  schedule_last_run_date: string;
  schedule_last_status: string;
  mcp_enabled: boolean;
  mcp_port: number;
  mcp_host?: string;
  mcp_endpoint?: string;
  summarized_chat_ids?: string[];
  api_key_configured?: boolean;
  deepseek_api_key_configured?: boolean;
  openai_compatible_api_key_configured?: boolean;
};

export type McpServerStatus = {
  running: boolean;
  pid?: number | null;
  transport: "streamable-http";
  host: "127.0.0.1";
  port: number;
  endpoint: string;
};

export type Chat = { id: string; name: string; summarized?: boolean };

export type HeatmapMetric = "message_count" | "participant_count" | "effective_message_count";

export type HeatmapReportLink = {
  report_id: string;
  report_date: string;
  version: number;
  headline: string;
  one_line_summary: string;
};

export type HeatmapDay = {
  date: string;
  status: "known" | "unknown";
  message_count: number | null;
  effective_message_count: number | null;
  participant_count: number | null;
  effective_char_count: number | null;
  link_count: number | null;
  file_count: number | null;
  calculated_at: string;
  report: HeatmapReportLink | null;
};

export type HeatmapData = {
  version: number;
  chat_id: string;
  chat_name: string;
  start_date: string;
  end_date: string;
  days: HeatmapDay[];
  missing_ranges: Array<{ start: string; end: string }>;
  known_days: number;
  unknown_days: number;
  ai_called?: boolean;
  scan?: {
    cache_hit: boolean;
    scanned_days: number;
    scanned_ranges: Array<{ start: string; end: string }>;
  };
};

export type HistoryNavigationTarget = {
  chatId: string;
  date: string;
  reportId: string;
  requestId: number;
};

export type BridgeResponse<T> = {
  id: string;
  ok: boolean;
  result?: T;
  error?: string;
};

export type GenerationResult = {
  completed: boolean;
  protocol_version?: number;
  report_id?: string;
  version?: number;
  redaction_count?: number;
  chat_dir?: string;
  data_dir?: string;
  image_dir?: string;
  json_path?: string;
  html_path?: string;
  png_path?: string;
  summarized_chat_ids?: string[];
};

export type HistoryChat = {
  chat_id: string;
  display_name: string;
  report_count: number;
  latest_report_date: string;
  latest_generated_at: string;
};

export type HistoryReport = {
  report_id: string;
  chat_id: string;
  display_name: string;
  report_date: string;
  period_start: string;
  period_end: string;
  version: number;
  schema_version: string;
  generated_at: string;
  provider: string;
  model: string;
  headline: string;
  one_line_summary: string;
  message_count: number;
  participant_count: number;
  resource_count: number;
  modules: string[];
};

export type HistoryModule = {
  module_key: string;
  module_label: string;
  ordinal: number;
  title: string;
  content: unknown;
  redaction_target_id?: string;
};

export type HistoryExport = { path: string; exists: boolean };

export type HistoryReportDetail = Omit<HistoryReport, "modules"> & {
  content: Record<string, unknown>;
  stats: Record<string, unknown>;
  modules: HistoryModule[];
  resources: Array<Record<string, unknown>>;
  redactions: Array<Record<string, unknown>>;
  exports: { json: HistoryExport; html: HistoryExport; png: HistoryExport };
};

export type HistorySearchHit = {
  report_id: string;
  chat_id: string;
  chat_name: string;
  report_date: string;
  period_start: string;
  period_end: string;
  version: number;
  generated_at: string;
  module_key: string;
  module_label: string;
  title: string;
  snippet: string;
};

export type Paginated<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
};

export type Progress = {
  stage: string;
  percent: number;
  message: string;
  elapsed_seconds: number;
};

export type RedactionTarget = {
  id: string;
  module_key: string;
  module_label: string;
  preview: string;
  time_label: string;
  redacted: boolean;
};

export const INITIAL_SETTINGS: Settings = {
  wechat_api_url: "http://127.0.0.1:10392",
  provider: "deepseek",
  api_url: "https://api.deepseek.com/chat/completions",
  model: "deepseek-v4-flash",
  thinking: false,
  reasoning_effort: "high",
  export_root: "",
  image_dpi: 300,
  range_mode: "single",
  last_chat_id: "",
  last_chat_name: "",
  schedule_enabled: false,
  schedule_time: "22:30",
  schedule_date_mode: "today",
  schedule_chat_id: "",
  schedule_chat_name: "",
  schedule_last_attempt_date: "",
  schedule_last_run_date: "",
  schedule_last_status: "",
  mcp_enabled: false,
  mcp_port: 8765,
};
