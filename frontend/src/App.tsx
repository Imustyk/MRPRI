import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LANGS, type LangCode } from "./i18n";
import { Loading, PageHead } from "./ui";

const Overview = lazy(() => import("./pages/Overview"));
const Tenders = lazy(() => import("./pages/Tenders"));
const TenderDetail = lazy(() => import("./pages/TenderDetail"));
const Network = lazy(() => import("./pages/Network"));
const Distributions = lazy(() => import("./pages/Distributions"));
const Workspace = lazy(() => import("./pages/Workspace"));
const Method = lazy(() => import("./pages/Method"));
const Kpis = lazy(() => import("./pages/Kpis"));
const Raci = lazy(() => import("./pages/Raci"));

const NAV_ICONS: Record<string, string> = {
  "/": "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  "/tenders": "M8 3h8l4 4v14H4V3h4 M8 11h8 M8 16h6",
  "/distributions": "M4 20V10 M10 20V4 M16 20v-8 M22 20H2",
  "/network": "M9 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0 M21 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0 M9 19a3 3 0 1 1-6 0 3 3 0 0 1 6 0 M9 6l6 4 M9 18l6-4",
  "/workspace": "M3 6h7l2 2h9v12H3z",
  "/method": "M12 5C8 2 4 3 2 4v16c4-2 7-1 10 1 3-2 6-3 10-1V4c-2-1-6-2-10 1v16",
  "/kpis": "M4 20V4 M4 20h17 M7 15l5-5 4 2 5-7",
  "/raci": "M3 4h18v16H3z M3 9h18 M9 4v16 M15 9v11",
};

function NavIcon({ path }: { path: string }) {
  return <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={NAV_ICONS[path]} /></svg>;
}

function GlobalSearch() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  return (
    <form className="global-search" role="search" onSubmit={(event) => {
      event.preventDefault();
      const params = new URLSearchParams();
      if (query.trim()) params.set("q", query.trim());
      navigate(`/tenders${params.size ? `?${params}` : ""}`);
    }}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg>
      <label className="visually-hidden" htmlFor="global-search">{t("nav.search")}</label>
      <input id="global-search" type="search" value={query} placeholder={t("nav.search_placeholder")} onChange={(event) => setQuery(event.target.value)} />
      <button type="submit" aria-label={t("nav.search")}><span aria-hidden="true">↵</span></button>
    </form>
  );
}

/** Language switcher: short codes, current one marked as pressed. */
function LangSwitch() {
  const { t, i18n } = useTranslation();
  return (
    <div className="lang-switch" role="group" aria-label={t("lang.label")}>
      {LANGS.map((l) => (
        <button
          key={l.code}
          type="button"
          lang={l.code}
          className={i18n.resolvedLanguage === l.code ? "active" : ""}
          aria-pressed={i18n.resolvedLanguage === l.code}
          title={l.label}
          onClick={() => i18n.changeLanguage(l.code as LangCode)}
        >
          {l.short}
        </button>
      ))}
    </div>
  );
}

function NotFound() {
  const { t } = useTranslation();
  return (
    <div>
      <PageHead kicker="404" title={t("nav.not_found")} lede={t("nav.not_found_hint")} />
      <Link className="action-primary" to="/">{t("nav.overview")}</Link>
    </div>
  );
}

export default function App() {
  const { t } = useTranslation();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const previousPath = useRef(location.pathname);
  useEffect(() => {
    if (previousPath.current === location.pathname) return;
    previousPath.current = location.pathname;
    setMenuOpen(false);
    document.getElementById("main")?.focus();
    window.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuButton.current?.focus();
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen]);
  const NAV: { label: string; items: { to: string; label: string; end?: boolean }[] }[] = [
    {
      label: t("nav.group_analysis"),
      items: [
        { to: "/", end: true, label: t("nav.overview") },
        { to: "/tenders", label: t("nav.procedures") },
        { to: "/distributions", label: t("nav.distributions") },
        { to: "/network", label: t("nav.network") },
        { to: "/workspace", label: t("nav.workspace") },
      ],
    },
    {
      label: t("nav.group_thesis"),
      items: [
        { to: "/method", label: t("nav.methodology") },
        { to: "/kpis", label: t("nav.kpis") },
        { to: "/raci", label: t("nav.raci") },
      ],
    },
  ];
  const currentItem = NAV.flatMap((group) => group.items).find((item) =>
    item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to)
  );
  return (
    <div className="shell">
      <a className="skip" href="#main">
        {t("brand.skip")}
      </a>
      <aside className={`side${menuOpen ? " menu-open" : ""}`}>
        <div className="brand-block">
          <Link className="brand" to="/" aria-label={`${t("brand.name_a")} ${t("brand.name_b")} — ${t("nav.overview")}`}>
            <span className="brand-symbol" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="m4 15 5-5 4 3 7-9 M15 4h5v5 M4 21h16" /></svg></span>
            <span className="brand-wordmark">{t("brand.name_a")} <span>{t("brand.name_b")}</span></span>
          </Link>
          <p>{t("brand.tagline")}</p>
        </div>
        <button className="menu-toggle" type="button" ref={menuButton} aria-expanded={menuOpen} aria-controls="primary-navigation" onClick={() => setMenuOpen(!menuOpen)}>
          <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d={menuOpen ? "M6 6l12 12M6 18L18 6" : "M4 6h16M4 12h16M4 18h16"} /></svg>
          {t(menuOpen ? "nav.close_menu" : "nav.open_menu")}
        </button>
        <nav id="primary-navigation" className="nav" aria-label={t("nav.primary")}>

          {NAV.map((group) => (
            <div key={group.label} className="nav-group">
              <div className="nav-label">{group.label}</div>
              {group.items.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end} onClick={() => { setMenuOpen(false); document.getElementById("main")?.focus(); }}>
                  <NavIcon path={item.to} />
                  <span>{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          {t("brand.foot_1")}
          <br />
          {t("brand.foot_2")}
        </div>
      </aside>
      <div className="content-shell">
        <header className="app-topbar">
          <div className="current-section">{currentItem?.label ?? t("brand.name_a")}</div>
          <GlobalSearch />
          <LangSwitch />
        </header>
      <main className="main" id="main" tabIndex={-1}>
        <Suspense fallback={<Loading />}><Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/tenders" element={<Tenders />} />
          <Route path="/tenders/:id" element={<TenderDetail />} />
          <Route path="/distributions" element={<Distributions />} />
          <Route path="/network" element={<Network />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/method" element={<Method />} />
          <Route path="/kpis" element={<Kpis />} />
          <Route path="/raci" element={<Raci />} />
          <Route path="*" element={<NotFound />} />
        </Routes></Suspense>
      </main>
      </div>
    </div>
  );
}
