import { useState } from "react";

import AboutPage from "./pages/AboutPage";
import GeneratePage from "./pages/GeneratePage";
import HeatmapPage from "./pages/HeatmapPage";
import HistoryPage from "./pages/HistoryPage";
import type { HistoryNavigationTarget } from "./types/desktop";

type AppPage = "generate" | "history" | "heatmap" | "about";

const appIcon = new URL("../src-tauri/icons/icon.png", import.meta.url).href;

export default function App() {
  const [page, setPage] = useState<AppPage>("generate");
  const [historyTarget, setHistoryTarget] = useState<HistoryNavigationTarget | null>(null);

  function openHistory(target: HistoryNavigationTarget) {
    setHistoryTarget(target);
    setPage("history");
  }

  return <main className="app-shell">
    <aside className="rail" aria-label="主导航">
      <div className="brand-mark"><img src={appIcon} alt="群聊拾遗" /></div>
      <nav className="app-nav">
        <button className={page === "generate" ? "active" : ""} aria-current={page === "generate" ? "page" : undefined} onClick={() => setPage("generate")}><span>生</span><small>生成总结</small></button>
        <button className={page === "history" ? "active" : ""} aria-current={page === "history" ? "page" : undefined} onClick={() => setPage("history")}><span>历</span><small>历史中心</small></button>
        <button className={page === "heatmap" ? "active" : ""} aria-current={page === "heatmap" ? "page" : undefined} onClick={() => setPage("heatmap")}><span>热</span><small>热力图</small></button>
        <button className={page === "about" ? "active" : ""} aria-current={page === "about" ? "page" : undefined} onClick={() => setPage("about")}><span>关</span><small>关于</small></button>
      </nav>
      <p className="rail-foot">本地历史</p>
    </aside>
    <div className="page-host">
      <div className="page-slot" hidden={page !== "generate"}><GeneratePage /></div>
      <div className="page-slot" hidden={page !== "history"}><HistoryPage active={page === "history"} target={historyTarget} /></div>
      <div className="page-slot" hidden={page !== "heatmap"}><HeatmapPage active={page === "heatmap"} onOpenHistory={openHistory} /></div>
      <div className="page-slot" hidden={page !== "about"}><AboutPage /></div>
    </div>
  </main>;
}
