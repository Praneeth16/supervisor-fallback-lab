import {
  ChartBar,
  ChatCircleText,
  List,
  ListChecks,
  Plus,
  Pulse,
  ShieldCheck,
  StarFour,
  ThumbsUp,
  TrendUp,
  Wrench,
} from "@phosphor-icons/react";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api";
import { chatApi, type ConversationInfo, type Me } from "./chatApi";
import { ChatProvider, useChat } from "./chat/state";
import { useLoad } from "./hooks";
import { StateBlock } from "./ui";
import BenchmarkPage, { BenchmarkDetailPage } from "./pages/Benchmark";
import ChatPage from "./pages/Chat";
import DemandPage from "./pages/Demand";
import FeedbackPage from "./pages/Feedback";
import GovernancePage from "./pages/Governance";
import MonitorPage from "./pages/Monitor";
import QuestionsPage from "./pages/Questions";
import ReplicatePage from "./pages/Replicate";

const MONITOR = [
  { to: "/monitor", label: "Activity and traces", icon: <Pulse size={17} />, end: true },
  { to: "/monitor/feedback", label: "Feedback", icon: <ThumbsUp size={17} />, end: false },
  { to: "/monitor/demand", label: "Fallback demand", icon: <TrendUp size={17} />, end: false },
];
const BENCHMARK = [
  { to: "/benchmark/questions", label: "Questions and ground truth", icon: <ListChecks size={17} />, end: false },
  { to: "/benchmark", label: "Results", icon: <ChartBar size={17} />, end: true },
  { to: "/governance", label: "Scope checks", icon: <ShieldCheck size={17} />, end: false },
];

function initials(name: string): string {
  const parts = name.split("@")[0].split(/[.\s_-]+/).filter(Boolean);
  return (parts[0]?.[0] ?? "?").concat(parts[1]?.[0] ?? "").toUpperCase();
}

function when(iso: string): string {
  const date = new Date(iso.replace(" ", "T") + (iso.includes("Z") ? "" : "Z"));
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function modeText(chat: ConversationInfo): string {
  if (chat.mode === "compare" || chat.arms.length > 1) return "Both";
  return chat.arms[0] === "genie_one" ? "Genie One" : "Custom agent";
}

function Side({ brand, open, onClose }: { brand: string; open: boolean; onClose: () => void }) {
  const chat = useChat();
  const location = useLocation();
  const me = useLoad<Me>(() => chatApi.me(), []);
  const user = me.state.status === "ready" ? me.state.data : null;
  const onChat = location.pathname === "/" || location.pathname.startsWith("/c/");

  return (
    <>
      {open && <button type="button" className="side-scrim" aria-label="Close the menu" onClick={onClose} />}
      <aside className={open ? "side open" : "side"}>
        <div className="side-top">
          <Link to="/" className="brand" onClick={chat.reset}>
            <span className="brand-mark" aria-hidden="true">
              <StarFour size={17} weight="fill" />
            </span>
            <span className="brand-text">
              <strong>{brand}</strong>
              <span>Data assistant lab</span>
            </span>
          </Link>
          <Link to="/" className="new-chat" onClick={chat.reset}>
            <Plus size={16} weight="bold" />
            New chat
          </Link>
        </div>
        <nav aria-label="Main">
          <ul className="side-nav">
            <li>
              <Link to="/" className={onChat ? "side-link active" : "side-link"} onClick={onChat ? undefined : chat.reset}>
                <ChatCircleText size={17} />
                Chat
              </Link>
            </li>
            {[
              { label: "Monitor", links: MONITOR },
              { label: "Benchmark", links: BENCHMARK },
            ].map((group) => (
              <Fragment key={group.label}>
                <li className="side-label">{group.label}</li>
                {group.links.map((link) => (
                  <li key={link.to}>
                    <NavLink to={link.to} end={link.end} className={({ isActive }) => (isActive ? "side-link active" : "side-link")}>
                      {link.icon}
                      {link.label}
                    </NavLink>
                  </li>
                ))}
              </Fragment>
            ))}
            <li>
              <NavLink to="/replicate" className={({ isActive }) => (isActive ? "side-link active" : "side-link")}>
                <Wrench size={17} />
                How it is built
              </NavLink>
            </li>
            <li className="side-label">Your chats</li>
          </ul>
        </nav>
        <div className="side-chats">
          {chat.listError ? (
            <p className="side-empty">Your chats could not be loaded. {chat.listError}</p>
          ) : chat.list.length === 0 ? (
            <p className="side-empty">Questions you ask are kept here, under your name.</p>
          ) : (
            <ul className="chat-list">
              {chat.list.map((item) => (
                <li key={item.conversation_id}>
                  <NavLink
                    to={`/c/${item.conversation_id}`}
                    className={({ isActive }) => (isActive ? "chat-link active" : "chat-link")}
                    title={item.title}
                  >
                    <span className="chat-link-title">{item.title}</span>
                    <span className="chat-link-meta">
                      {modeText(item)}, {when(item.last_at)}
                    </span>
                  </NavLink>
                </li>
              ))}
            </ul>
          )}
        </div>
        {user && (
          <div className="side-user">
            <span className="avatar" aria-hidden="true">
              {initials(user.name)}
            </span>
            <span className="side-user-text">
              <strong title={user.email}>{user.email}</strong>
              <span>Your chats and ratings</span>
            </span>
          </div>
        )}
      </aside>
    </>
  );
}

function Scroll({ children }: { children: ReactNode }) {
  return <main className="main">{children}</main>;
}

export default function App() {
  const config = useLoad(() => api.config(), []);
  const brand = config.state.status === "ready" ? config.state.data.brand : "Hoshi Stream";
  const [menu, setMenu] = useState(false);
  const location = useLocation();

  useEffect(() => setMenu(false), [location.pathname]);
  useEffect(() => {
    document.title = `${brand} data assistant lab`;
  }, [brand]);

  return (
    <ChatProvider>
      <div className="shell">
        <button type="button" className="menu-button" aria-label="Open the menu" onClick={() => setMenu(true)}>
          <List size={20} />
        </button>
        <Side brand={brand} open={menu} onClose={() => setMenu(false)} />
        <StateBlock state={config.state} empty="The configuration is empty." onRetry={config.reload}>
          {(data) => (
            <Routes>
              <Route path="/" element={<main className="main main-chat"><ChatPage config={data} /></main>} />
              <Route path="/c/:conversationId" element={<main className="main main-chat"><ChatPage config={data} /></main>} />
              <Route path="/ask" element={<Navigate to="/" replace />} />
              <Route path="/benchmark" element={<Scroll><div className="page"><BenchmarkPage /></div></Scroll>} />
              <Route
                path="/benchmark/:runLabel/:questionId"
                element={<Scroll><div className="page"><BenchmarkDetailPage /></div></Scroll>}
              />
              <Route path="/governance" element={<Scroll><div className="page"><GovernancePage /></div></Scroll>} />
              <Route path="/benchmark/questions" element={<Scroll><div className="page"><QuestionsPage /></div></Scroll>} />
              <Route path="/monitor" element={<Scroll><div className="page"><MonitorPage config={data} /></div></Scroll>} />
              <Route path="/monitor/feedback" element={<Scroll><div className="page"><FeedbackPage /></div></Scroll>} />
              <Route path="/monitor/demand" element={<Scroll><div className="page"><DemandPage config={data} /></div></Scroll>} />
              <Route path="/feedback" element={<Navigate to="/monitor/feedback" replace />} />
              <Route path="/demand" element={<Navigate to="/monitor/demand" replace />} />
              <Route path="/replicate" element={<Scroll><div className="page"><ReplicatePage /></div></Scroll>} />
              <Route path="*" element={<Scroll><div className="page"><p className="empty-note">This page does not exist.</p></div></Scroll>} />
            </Routes>
          )}
        </StateBlock>
      </div>
    </ChatProvider>
  );
}
