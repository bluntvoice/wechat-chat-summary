"""群聊拾遗 MCP Server：由外部 MCP Host 调用，本身不调用 AI。"""

from __future__ import annotations

import argparse
from typing import Any

from mcp.server.mcpserver import MCPServer

from .mcp_service import MCPService

MCP_HOST = "127.0.0.1"
MCP_PATH = "/mcp"


def create_mcp_server(service: MCPService | None = None) -> MCPServer:
    tools = service or MCPService()
    server = MCPServer(
        "wechat-chat-summary",
        title="群聊拾遗",
        description="向外部 AI 客户端提供受控群聊上下文、统计、历史与报告归档能力。",
        instructions="本服务不执行 AI 分析。请先读取上下文，再提交严格的 Report Schema 2.2 文档。",
        version="0.2.3",
        log_level="WARNING",
    )

    @server.tool(structured_output=True)
    def list_chats() -> dict[str, Any]:
        """列出 WeChatDataAnalysis 当前返回的可分析群聊。"""
        return tools.list_chats()

    @server.tool(structured_output=True)
    def get_chat_stats(chat_id: str, start: str, end: str) -> dict[str, Any]:
        """临时读取指定群聊与时间范围，并返回本地确定性统计。"""
        return tools.get_chat_stats(chat_id, start, end)

    @server.tool(structured_output=True)
    def get_chat_analysis_context(chat_id: str, start: str, end: str) -> dict[str, Any]:
        """返回外部 AI 完成分析所需的受控消息、统计和资源上下文。"""
        return tools.get_chat_analysis_context(chat_id, start, end)

    @server.tool(structured_output=True)
    def get_daily_stats(chat_id: str, start_date: str, end_date: str) -> dict[str, Any]:
        """读取第五阶段已保存在 HistoryStore 的每日聚合统计。"""
        return tools.get_daily_stats(chat_id, start_date, end_date)

    @server.tool(structured_output=True)
    def list_history(chat_id: str = "", start_date: str = "", end_date: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """分页列出历史总结，不返回本机文件路径。"""
        return tools.list_history(chat_id, start_date, end_date, limit, offset)

    @server.tool(structured_output=True)
    def search_history(query: str, chat_id: str = "", start_date: str = "", end_date: str = "", module_filter: str = "all", limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """搜索历史总结的 Schema 2.2 派生模块。"""
        return tools.search_history(query, chat_id, start_date, end_date, module_filter, limit, offset)

    @server.tool(structured_output=True)
    def get_report(report_id: str) -> dict[str, Any]:
        """读取一份结构化历史报告，不暴露本机导出路径。"""
        return tools.get_report(report_id)

    @server.tool(structured_output=True)
    def submit_report(document: dict[str, Any]) -> dict[str, Any]:
        """校验并归档外部 AI 提交的 Report Schema 2.2 文档，完成全部导出闭环。"""
        return tools.submit_report(document)

    @server.tool(structured_output=True)
    def render_report(report_id: str) -> dict[str, Any]:
        """恢复历史库中合法报告缺失的受控 JSON、HTML 或 PNG 导出。"""
        return tools.render_report(report_id)

    return server


def run_server(port: int) -> None:
    if port < 1024 or port > 65535:
        raise ValueError("MCP 端口必须在 1024 到 65535 之间。")
    create_mcp_server().run(
        transport="streamable-http",
        host=MCP_HOST,
        port=port,
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        max_request_body_size=4 * 1024 * 1024,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local 群聊拾遗 MCP Server.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run_server(args.port)


if __name__ == "__main__":
    main()
