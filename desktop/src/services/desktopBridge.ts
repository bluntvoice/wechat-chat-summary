import { invoke } from "@tauri-apps/api/core";

import type { BridgeResponse } from "../types/desktop";

export async function bridge<T>(command: string, payload: Record<string, unknown> = {}) {
  const response = await invoke<BridgeResponse<T>>("bridge_call", { command, payload });
  if (!response.ok) throw new Error(response.error || "Python 分析服务未返回有效结果。");
  return response.result as T;
}

export async function openSystemPath(path?: string) {
  if (!path) return;
  await invoke("open_system_path", { path });
}
