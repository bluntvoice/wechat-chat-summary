export type Settings = {
  wechat_api_url: string;
  provider: "deepseek" | "openai-compatible";
  api_url: string;
  model: string;
  thinking: boolean;
  export_root: string;
  image_dpi: number;
  range_mode: "single" | "custom";
  last_chat_id: string;
  last_chat_name: string;
  schedule_enabled: boolean;
  schedule_time: string;
  schedule_chat_id: string;
  schedule_chat_name: string;
  schedule_last_attempt_date: string;
  schedule_last_run_date: string;
  schedule_last_status: string;
  summarized_chat_ids?: string[];
  api_key_configured?: boolean;
};

export type Chat = { id: string; name: string };

export type BridgeResponse<T> = {
  id: string;
  ok: boolean;
  result?: T;
  error?: string;
};

export type GenerationResult = {
  completed: boolean;
  protocol_version?: number;
  version?: number;
  redaction_count?: number;
  chat_dir?: string;
  data_dir?: string;
  image_dir?: string;
  json_path?: string;
  html_path?: string;
  png_path?: string;
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
  export_root: "",
  image_dpi: 300,
  range_mode: "single",
  last_chat_id: "",
  last_chat_name: "",
  schedule_enabled: false,
  schedule_time: "22:30",
  schedule_chat_id: "",
  schedule_chat_name: "",
  schedule_last_attempt_date: "",
  schedule_last_run_date: "",
  schedule_last_status: "",
};
