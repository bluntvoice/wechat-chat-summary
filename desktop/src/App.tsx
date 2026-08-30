import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";

type Settings = {
  wechat_api_url: string;
  provider: "deepseek" | "openai-compatible";
  api_url: string;
  model: string;
  thinking: boolean;
  export_root: string;
  image_dpi: number;
  api_key_configured?: boolean;
};

type Chat = { id: string; name: string };
type BridgeResponse<T> = { id: string; ok: boolean; result?: T; error?: string };
type Result = {
  completed: boolean;
  chat_dir?: string;
  data_dir?: string;
  image_dir?: string;
  json_path?: string;
  html_path?: string;
  png_path?: string;
  log?: string;
};

const initialSettings: Settings = {
  wechat_api_url: "http://127.0.0.1:10392",
  provider: "deepseek",
  api_url: "https://api.deepseek.com/chat/completions",
  model: "deepseek-v4-flash",
  thinking: false,
  export_root: "F:\\应用数据\\微信群聊总结",
  image_dpi: 300,
};

function localDate(offsetDays = 0) {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

async function bridge<T>(command: string, payload: Record<string, unknown> = {}) {
  const response = await invoke<BridgeResponse<T>>("bridge_call", { command, payload });
  if (!response.ok) throw new Error(response.error || "Python 分析服务未返回有效结果。");
  return response.result as T;
}

function App() {
  const [settings, setSettings] = useState<Settings>(initialSettings);
  const [apiKey, setApiKey] = useState("");
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatId, setChatId] = useState("");
  const [query, setQuery] = useState("");
  const [startDate, setStartDate] = useState(localDate());
  const [endDate, setEndDate] = useState(localDate());
  const [wechatState, setWechatState] = useState<"idle" | "testing" | "ready" | "error">("idle");
  const [aiState, setAiState] = useState<"idle" | "testing" | "ready" | "error">("idle");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("先连接 WeChatDataAnalysis，再选择需要总结的群聊。");
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    bridge<Settings>("get_state")
      .then((saved) => setSettings({ ...initialSettings, ...saved }))
      .catch((error) => setMessage(String(error)));
  }, []);

  const filteredChats = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle ? chats.filter((chat) => chat.name.toLocaleLowerCase().includes(needle)) : chats;
  }, [chats, query]);

  const selectedChat = chats.find((chat) => chat.id === chatId);
  const statusSettings = () => ({
    ...settings,
    ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
  });

  async function connectWeChat() {
    setWechatState("testing");
    setMessage("正在读取本机群聊列表…");
    try {
      const data = await bridge<{ chats: Chat[]; account: string }>("list_chats", {
        settings: statusSettings(),
      });
      setChats(data.chats);
      setWechatState("ready");
      setMessage(`已连接，读取到 ${data.chats.length} 个群聊。`);
      if (data.chats.length && !chatId) setChatId(data.chats[0].id);
    } catch (error) {
      setWechatState("error");
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function testAi() {
    setAiState("testing");
    setMessage("正在测试 AI API，仅发送最小测试内容…");
    try {
      await bridge("test_ai", { settings: statusSettings() });
      setAiState("ready");
      setMessage("AI API 连接成功。聊天文本只会在正式生成时发送。");
    } catch (error) {
      setAiState("error");
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  async function chooseExportRoot() {
    const selected = await open({
      directory: true,
      multiple: false,
      defaultPath: settings.export_root || undefined,
      title: "选择群聊报告根目录",
    });
    if (typeof selected === "string") {
      setSettings((current) => ({ ...current, export_root: selected }));
    }
  }

  async function saveSettings() {
    const payload: Record<string, unknown> = { ...settings };
    if (apiKey.trim()) payload.api_key = apiKey.trim();
    const saved = await bridge<Settings>("save_settings", { settings: payload });
    setSettings((current) => ({ ...current, ...saved }));
    setApiKey("");
  }

  async function generate() {
    if (!chatId) {
      setMessage("请选择一个群聊。");
      return;
    }
    if (!settings.export_root.trim()) {
      setMessage("请先选择独立的报告根目录。");
      return;
    }
    if (endDate < startDate) {
      setMessage("结束日期不能早于开始日期。");
      return;
    }
    setBusy(true);
    setResult(null);
    setMessage("正在生成总结。消息读取、AI 分析和长图导出可能需要几分钟…");
    try {
      await saveSettings();
      const generated = await bridge<Result>("generate", {
        chat: chatId,
        start: `${startDate} 00:00:00`,
        end: `${endDate} 23:59:59`,
        export_root: settings.export_root,
      });
      setResult(generated);
      setMessage("报告已生成，PNG 与分析数据已分别归档。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function openPath(path?: string) {
    if (!path) return;
    try {
      await invoke("open_system_path", { path });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <main className="app-shell">
      <aside className="rail">
        <div className="brand-mark">微</div>
        <div className="rail-line" aria-hidden="true" />
        <div className={`rail-node ${wechatState === "ready" ? "done" : "active"}`}><span>1</span><small>连接</small></div>
        <div className={`rail-node ${chatId ? "done" : ""}`}><span>2</span><small>选择</small></div>
        <div className={`rail-node ${result ? "done" : busy ? "active" : ""}`}><span>3</span><small>生成</small></div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">WECHAT · LOCAL INSIGHT</p>
            <h1>微信群聊总结</h1>
          </div>
          <div className={`system-state ${wechatState}`}>
            <span />{wechatState === "ready" ? "数据源已连接" : "等待连接数据源"}
          </div>
        </header>

        <section className="notice" aria-live="polite">
          <strong>{busy ? "分析进行中" : "当前状态"}</strong>
          <span>{message}</span>
        </section>

        <div className="grid">
          <section className="panel source-panel">
            <div className="panel-heading">
              <div><span className="step-tag">01</span><h2>连接微信数据</h2></div>
              <button className="button secondary" onClick={connectWeChat} disabled={wechatState === "testing" || busy}>
                {wechatState === "testing" ? "连接中…" : "测试并读取群聊"}
              </button>
            </div>
            <label>
              <span>WeChatDataAnalysis API</span>
              <input value={settings.wechat_api_url} onChange={(event) => setSettings({ ...settings, wechat_api_url: event.target.value })} />
            </label>
            <div className="chat-picker">
              <label>
                <span>搜索群聊</span>
                <input placeholder="输入群聊名称" value={query} onChange={(event) => setQuery(event.target.value)} disabled={!chats.length} />
              </label>
              <label>
                <span>选择群聊</span>
                <select value={chatId} onChange={(event) => setChatId(event.target.value)} disabled={!filteredChats.length}>
                  {!filteredChats.length && <option value="">连接后显示群聊</option>}
                  {filteredChats.map((chat) => <option key={chat.id} value={chat.id}>{chat.name}</option>)}
                </select>
              </label>
            </div>
            {selectedChat && <p className="selection-note">本次总结：<strong>{selectedChat.name}</strong></p>}
          </section>

          <section className="panel range-panel">
            <div className="panel-heading compact">
              <div><span className="step-tag">02</span><h2>选择统计区间</h2></div>
            </div>
            <div className="date-grid">
              <label><span>开始日期</span><input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
              <label><span>结束日期</span><input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
            </div>
            <div className="quick-dates">
              <button onClick={() => { setStartDate(localDate()); setEndDate(localDate()); }}>今天</button>
              <button onClick={() => { setStartDate(localDate(-1)); setEndDate(localDate(-1)); }}>昨天</button>
              <button onClick={() => { setStartDate(localDate(-6)); setEndDate(localDate()); }}>最近 7 天</button>
            </div>
          </section>

          <section className="panel ai-panel">
            <div className="panel-heading">
              <div><span className="step-tag">03</span><h2>配置 AI 分析</h2></div>
              <button className="button secondary" onClick={testAi} disabled={aiState === "testing" || busy}>
                {aiState === "testing" ? "测试中…" : "测试 API"}
              </button>
            </div>
            <div className="field-grid">
              <label><span>服务类型</span><select value={settings.provider} onChange={(event) => setSettings({ ...settings, provider: event.target.value as Settings["provider"] })}><option value="deepseek">DeepSeek</option><option value="openai-compatible">OpenAI Compatible</option></select></label>
              <label><span>模型</span><input value={settings.model} onChange={(event) => setSettings({ ...settings, model: event.target.value })} /></label>
              <label className="wide"><span>API URL</span><input value={settings.api_url} onChange={(event) => setSettings({ ...settings, api_url: event.target.value })} /></label>
              <label className="wide"><span>API Key {settings.api_key_configured && !apiKey ? <em>本机已保存</em> : null}</span><input type="password" autoComplete="off" placeholder={settings.api_key_configured ? "留空则继续使用已保存的 Key" : "输入 API Key"} value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
            </div>
            <p className="privacy-copy">使用云端 AI 时，生成总结所需的聊天文本会发送给你配置的服务商。Key 仅保存在本机软件数据目录。</p>
          </section>

          <section className="panel output-panel">
            <div className="panel-heading compact">
              <div><span className="step-tag">04</span><h2>选择报告目录</h2></div>
            </div>
            <label><span>独立报告根目录</span><div className="path-control"><input readOnly value={settings.export_root} /><button className="button secondary" onClick={chooseExportRoot}>选择目录</button></div></label>
            <div className="archive-preview">
              <span>自动归档</span>
              <code>群聊 / 导出图 / 年 / 月</code>
              <code>群聊 / 报告数据 / 日期报告数据</code>
            </div>
          </section>
        </div>

        <section className={`action-dock ${result ? "has-result" : ""}`}>
          <div>
            <strong>{selectedChat?.name || "尚未选择群聊"}</strong>
            <span>{startDate === endDate ? startDate : `${startDate} 至 ${endDate}`} · PNG 300 DPI</span>
          </div>
          <button className="button primary" onClick={generate} disabled={busy || !chatId}>{busy ? "正在生成…" : "生成群聊总结"}</button>
        </section>

        {result && (
          <section className="result-panel">
            <div className="result-copy"><span className="result-check">✓</span><div><h2>报告生成完成</h2><p>导出图和报告数据已分别保存，旧版本不会被覆盖。</p></div></div>
            <div className="result-actions">
              <button className="button primary small" onClick={() => openPath(result.png_path)}>打开图片</button>
              <button className="button secondary" onClick={() => openPath(result.chat_dir || result.data_dir)}>打开报告所在目录</button>
              <button className="button ghost" onClick={() => openPath(result.data_dir)}>查看报告数据</button>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

export default App;
