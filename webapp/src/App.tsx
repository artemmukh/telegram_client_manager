import { useEffect, useState } from "react";
import {
  isTMA,
  miniAppReady,
  mountMiniApp,
  bindMiniAppCssVars,
  mountThemeParams,
  bindThemeParamsCssVars,
  expandViewport,
} from "@telegram-apps/sdk";

type TabId = "appointments" | "booking" | "profile";

const TABS: { id: TabId; label: string }[] = [
  { id: "appointments", label: "Записи" },
  { id: "booking", label: "Записаться" },
  { id: "profile", label: "Профиль" },
];

function resolveInitialTab(view: string | null): TabId {
  return TABS.some((t) => t.id === view) ? (view as TabId) : "appointments";
}

function initTelegram() {
  if (!isTMA()) {
    return; // dev browser — render without Telegram chrome
  }
  mountMiniApp();
  mountThemeParams();
  bindMiniAppCssVars();
  bindThemeParamsCssVars();
  miniAppReady();
  expandViewport();
}

export default function App() {
  const params = new URLSearchParams(window.location.search);
  const deepLinkId = params.get("id");

  const [tab, setTab] = useState<TabId>(() =>
    resolveInitialTab(params.get("view")),
  );

  useEffect(() => {
    try {
      initTelegram();
    } catch (err) {
      console.warn("Telegram SDK init failed, running outside Telegram", err);
    }
  }, []);

  return (
    <div className="app">
      <header className="app__header">Клиника</header>

      {deepLinkId && (
        <div className="app__deeplink">Deep-link id: {deepLinkId}</div>
      )}

      <main className="app__content">
        {tab === "appointments" && (
          <p>Здесь будет список ваших записей (фаза 1).</p>
        )}
        {tab === "booking" && <p>Здесь будет форма записи (фаза 1).</p>}
        {tab === "profile" && <p>Здесь будет профиль (фаза 1).</p>}
      </main>

      <nav className="app__tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={t.id === tab ? "tab tab--active" : "tab"}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </div>
  );
}
