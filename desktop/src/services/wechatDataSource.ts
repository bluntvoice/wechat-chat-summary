export const WECHAT_DATA_ANALYSIS_NAME = "WeChatDataAnalysis";
export const WECHAT_DATA_ANALYSIS_HOMEPAGE = "https://github.com/LifeArchiveProject/WeChatDataAnalysis";
export const WECHAT_DATA_ANALYSIS_RELEASES = `${WECHAT_DATA_ANALYSIS_HOMEPAGE}/releases`;

export const DATA_SOURCE_UNAVAILABLE_MESSAGE =
  "未检测到 WeChatDataAnalysis 服务，它可能尚未安装或尚未启动。";

export type DataSourceCheckResult = {
  status: "connected" | "unreachable" | "invalid_response" | "service_error";
  connected: boolean;
  group_count: number;
  account?: string;
  source?: string;
  detail?: string;
};
