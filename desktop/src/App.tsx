import { useState } from "react";

import GeneratePage from "./pages/GeneratePage";
import HistoryPage from "./pages/HistoryPage";

type AppPage = "generate" | "history";

const appIcon = new URL("../src-tauri/icons/icon.png", import.meta.url).href;

export default function App() {
  const [page, setPage] = useState<AppPage>("generate");

  return <main className="app-shell">
    <aside className="rail" aria-label="主导航">
      <div className="brand-mark"><img src={appIcon} alt="群聊拾遗" /></div>
      <nav className="app-nav">
        <button className={page === "generate" ? "active" : ""} aria-current={page === "generate" ? "page" : undefined} onClick={() => setPage("generate")}><span>生</span><small>生成总结</small></button>
        <button className={page === "history" ? "active" : ""} aria-current={page === "history" ? "page" : undefined} onClick={() => setPage("history")}><span>历</span><small>历史中心</small></button>
      </nav>
      <p className="rail-foot">本地历史</p>
    </aside>
    <div className="page-host">
      <div className="page-slot" hidden={page !== "generate"}><GeneratePage /></div>
      <div className="page-slot" hidden={page !== "history"}><HistoryPage active={page === "history"} /></div>
    </div>
  </main>;
}
