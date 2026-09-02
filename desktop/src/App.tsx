import { CalendarDays, CircleHelp, FileText, History, Info, Settings } from "lucide-react";
import { useState } from "react";

import GuideDialog from "./components/GuideDialog";
import AboutPage from "./pages/AboutPage";
import GeneratePage from "./pages/GeneratePage";
import HeatmapPage from "./pages/HeatmapPage";
import HistoryPage from "./pages/HistoryPage";
import SettingsPage from "./pages/SettingsPage";
import type { HistoryNavigationTarget } from "./types/desktop";

type AppPage = "generate" | "history" | "heatmap" | "settings" | "about";

const appIcon = new URL("../src-tauri/icons/icon.png", import.meta.url).href;

export default function App() {
  const [page, setPage] = useState<AppPage>("generate");
  const [historyTarget, setHistoryTarget] = useState<HistoryNavigationTarget | null>(null);
  const [guideOpen, setGuideOpen] = useState(() => localStorage.getItem("quick-guide-dismissed") !== "1");

  function navigate(nextPage: AppPage) {
    setPage(nextPage);
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }

  function openHistory(target: HistoryNavigationTarget) {
    setHistoryTarget(target);
    navigate("history");
  }

  function closeGuide() {
    localStorage.setItem("quick-guide-dismissed", "1");
    setGuideOpen(false);
  }

  return <main className="app-shell">
    <aside className="rail" aria-label="主导航">
      <div className="brand-mark"><img src={appIcon} alt="群聊拾遗" /></div>
      <nav className="app-nav">
        <button className={page === "generate" ? "active" : ""} aria-current={page === "generate" ? "page" : undefined} onClick={() => navigate("generate")}><span><FileText size={18} aria-hidden="true" /></span><small>生成总结</small></button>
        <button className={page === "history" ? "active" : ""} aria-current={page === "history" ? "page" : undefined} onClick={() => navigate("history")}><span><History size={18} aria-hidden="true" /></span><small>历史中心</small></button>
        <button className={page === "heatmap" ? "active" : ""} aria-current={page === "heatmap" ? "page" : undefined} onClick={() => navigate("heatmap")}><span><CalendarDays size={18} aria-hidden="true" /></span><small>热力图</small></button>
        <button className={page === "settings" ? "active" : ""} aria-current={page === "settings" ? "page" : undefined} onClick={() => navigate("settings")}><span><Settings size={18} aria-hidden="true" /></span><small>设置</small></button>
        <button className={page === "about" ? "active" : ""} aria-current={page === "about" ? "page" : undefined} onClick={() => navigate("about")}><span><Info size={18} aria-hidden="true" /></span><small>关于</small></button>
      </nav>
      <button className="rail-help" onClick={() => setGuideOpen(true)} title="打开使用指南"><CircleHelp size={18} aria-hidden="true" /><small>指南</small></button>
    </aside>
    <div className="page-host">
      <div className="page-slot" hidden={page !== "generate"}><GeneratePage active={page === "generate"} onOpenSettings={() => navigate("settings")} /></div>
      <div className="page-slot" hidden={page !== "history"}><HistoryPage active={page === "history"} target={historyTarget} /></div>
      <div className="page-slot" hidden={page !== "heatmap"}><HeatmapPage active={page === "heatmap"} onOpenHistory={openHistory} /></div>
      <div className="page-slot" hidden={page !== "settings"}><SettingsPage active={page === "settings"} /></div>
      <div className="page-slot" hidden={page !== "about"}><AboutPage /></div>
    </div>
    {guideOpen && <GuideDialog onClose={closeGuide} onOpenSettings={() => { closeGuide(); navigate("settings"); }} />}
  </main>;
}
