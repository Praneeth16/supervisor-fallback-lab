import { Switch, Label } from "@databricks/appkit-ui/react";
import { NavLink, Route, Routes, Navigate } from "react-router-dom";
import { api } from "./api";
import { useLoad } from "./hooks";
import { useTheme } from "./theme";
import { StateBlock } from "./ui";
import AskPage from "./pages/Ask";
import BenchmarkPage, { BenchmarkDetailPage } from "./pages/Benchmark";
import GovernancePage from "./pages/Governance";
import ReplicatePage from "./pages/Replicate";

const LINKS = [
  { to: "/ask", label: "Ask" },
  { to: "/benchmark", label: "Benchmark" },
  { to: "/governance", label: "Governance" },
  { to: "/replicate", label: "Replicate" },
];

function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="theme-switch">
      <Switch
        id="theme-switch"
        checked={theme === "dark"}
        onCheckedChange={(checked: boolean) => setTheme(checked ? "dark" : "light")}
      />
      <Label htmlFor="theme-switch">Dark theme</Label>
    </div>
  );
}

export default function App() {
  const config = useLoad(() => api.config(), []);
  const brand = config.state.status === "ready" ? config.state.data.brand : "Hoshi Stream";

  return (
    <div className="app">
      <header className="site-header">
        <div className="brand">
          <p className="brand-name">{brand}</p>
          <h1>Supervisor fallback evaluation lab</h1>
        </div>
        <nav aria-label="Main">
          <ul className="nav-list">
            {LINKS.map((link) => (
              <li key={link.to}>
                <NavLink to={link.to} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
                  {link.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <ThemeSwitch />
      </header>
      <main id="main" className="page">
        <StateBlock state={config.state} empty="The configuration is empty." onRetry={config.reload}>
          {() => (
            <Routes>
              <Route path="/" element={<Navigate to="/ask" replace />} />
              <Route path="/ask" element={<AskPage />} />
              <Route path="/benchmark" element={<BenchmarkPage />} />
              <Route path="/benchmark/:runLabel/:questionId" element={<BenchmarkDetailPage />} />
              <Route path="/governance" element={<GovernancePage />} />
              <Route path="/replicate" element={<ReplicatePage />} />
              <Route path="*" element={<p className="empty-note">This page does not exist.</p>} />
            </Routes>
          )}
        </StateBlock>
      </main>
    </div>
  );
}
