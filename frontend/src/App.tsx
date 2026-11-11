import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LANGS, type LangCode } from "./i18n";
import { Loading, PageHead } from "./ui";

const Overview = lazy(() => import("./pages/Overview"));
const Tenders = lazy(() => import("./pages/Tenders"));
const TenderDetail = lazy(() => import("./pages/TenderDetail"));
const ResearchAnalysis = lazy(() => import("./pages/ResearchAnalysis"));
const Network = lazy(() => import("./pages/Network"));
const Distributions = lazy(() => import("./pages/Distributions"));
const Workspace = lazy(() => import("./pages/Workspace"));
const Method = lazy(() => import("./pages/Method"));
const Kpis = lazy(() => import("./pages/Kpis"));
const Raci = lazy(() => import("./pages/Raci"));
// Dev-only: isolated-fixture verification page. The `import.meta.env.DEV`
// guard is statically false in a production build, so neither the route nor
// the chunk survives bundling.
const ModelCardFixture = import.meta.env.DEV
  ? lazy(() => import("./pages/ModelCardFixture"))
  : null;
const ICONS: Record<string, string> = {
  "/": "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  "/tenders": "M8 3h8l4 4v14H4V3h4 M8 11h8 M8 16h6",
  "/models": "M3 17l5-8 5 5 7-11 M3 21h18 M19 3h2v3",
  "/indicators": "M12 3 2 21h20L12 3 M12 9v5 M12 17v1",
  "/distributions": "M4 20V10 M10 20V4 M16 20v-8 M22 20H2",
  "/network": "M9 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0 M21 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0 M9 19a3 3 0 1 1-6 0 3 3 0 0 1 6 0 M9 6l6 4 M9 18l6-4",
  "/workspace": "M3 6h7l2 2h9v12H3z",
  "/method": "M12 5C8 2 4 3 2 4v16c4-2 7-1 10 1 3-2 6-3 10-1V4c-2-1-6-2-10 1v16",
  "/kpis": "M4 20V4 M4 20h17 M7 15l5-5 4 2 5-7",
  "/raci": "M3 4h18v16H3z M3 9h18 M9 4v16 M15 9v11",
};
function Icon({ path }: { path: string }) {
  return <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={ICONS[path]} /></svg>;
}
function Brand() {
  const { t } = useTranslation();
  return <Link className="brand" to="/" aria-label={`${t("brand.name_a")} ${t("brand.name_b")} — ${t("nav.overview")}`}><span className="brand-symbol" aria-hidden="true"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="m4 15 5-5 4 3 7-9 M15 4h5v5 M4 21h16" /></svg></span><span className="brand-wordmark">{t("brand.name_a")} <span>{t("brand.name_b")}</span></span></Link>;
}
function GlobalSearch() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  return <form className="global-search" role="search" onSubmit={(event) => {
    event.preventDefault();
    const params = new URLSearchParams();
    if (query.trim()) params.set("q", query.trim());
    navigate(`/tenders${params.size ? `?${params}` : ""}`);
  }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg><label className="visually-hidden" htmlFor="global-search">{t("nav.search")}</label><input id="global-search" type="search" value={query} placeholder={t("nav.search_placeholder")} onChange={(event) => setQuery(event.target.value)} /><button type="submit" aria-label={t("nav.search")}><span aria-hidden="true">↵</span></button></form>;
}
function LangSwitch() {
  const { t, i18n } = useTranslation();
  return <div className="lang-switch" role="group" aria-label={t("lang.label")}>{LANGS.map((language) => <button key={language.code} type="button" lang={language.code} className={i18n.resolvedLanguage === language.code ? "active" : ""} aria-pressed={i18n.resolvedLanguage === language.code} title={language.label} onClick={() => i18n.changeLanguage(language.code as LangCode)}>{language.short}</button>)}</div>;
}
function ThemeSwitch() {
  const { t } = useTranslation();
  const [dark, setDark] = useState(document.documentElement.dataset.theme === "dark");
  return <button className="theme-toggle" type="button" aria-pressed={dark} aria-label={t("analysis.theme_toggle")} title={t(dark ? "analysis.theme_light" : "analysis.theme_dark")} onClick={() => {
    const next = !dark; setDark(next); document.documentElement.dataset.theme = next ? "dark" : "light";
    try { localStorage.setItem("mtender-theme", next ? "dark" : "light"); } catch { /* Appearance works when storage is disabled. */ }
  }}><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">{dark ? <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2" /></> : <path d="M20 15A8 8 0 0 1 9 4a8.5 8.5 0 1 0 11 11Z" />}</svg></button>;
}
function NotFound() {
  const { t } = useTranslation();
  return <div><PageHead kicker="404" title={t("nav.not_found")} lede={t("nav.not_found_hint")} /><Link className="action-primary" to="/">{t("nav.overview")}</Link></div>;
}
export default function App() {
  const { t } = useTranslation();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const drawer = useRef<HTMLElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const previousPath = useRef(location.pathname);
  const closeMenu = () => { setMenuOpen(false); menuButton.current?.focus(); };
  useEffect(() => {
    if (previousPath.current === location.pathname) return;
    previousPath.current = location.pathname; setMenuOpen(false);
    requestAnimationFrame(() => { document.getElementById("main")?.focus(); window.scrollTo(0, 0); });
  }, [location.pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (content.current) content.current.inert = true;
    closeButton.current?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); closeMenu(); }
      if (event.key !== "Tab") return;
      const items = drawer.current?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), [tabindex="0"]');
      if (!items?.length) return;
      const first = items[0], last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    const wide = window.matchMedia("(min-width: 1101px)");
    const resize = () => { if (wide.matches) setMenuOpen(false); };
    document.addEventListener("keydown", keydown); wide.addEventListener("change", resize);
    return () => { document.body.style.overflow = previousOverflow; if (content.current) content.current.inert = false; document.removeEventListener("keydown", keydown); wide.removeEventListener("change", resize); };
  }, [menuOpen]);
  const nav = [
    { label: t("nav.group_analysis"), items: [
      { to: "/", label: t("nav.overview") }, { to: "/tenders", label: t("nav.procedures") },
      { to: "/models", label: t("analysis.models_title") }, { to: "/network", label: t("nav.network") }, { to: "/workspace", label: t("nav.workspace") },
      { to: "/method", label: t("product.how") },
    ] },
    { label: t("analysis.research"), items: [{ to: "/indicators", label: t("analysis.indicators_title") }, { to: "/distributions", label: t("nav.distributions") }, { to: "/kpis", label: t("nav.kpis") }, { to: "/raci", label: t("nav.raci") }] },
  ];
  let selectedProcedure = new URLSearchParams(location.search).get("tender");
  if (!selectedProcedure && location.pathname.startsWith("/tenders/")) {
    try { selectedProcedure = decodeURIComponent(location.pathname.slice("/tenders/".length)); } catch { selectedProcedure = null; }
  }
  const destination = (path: string) => selectedProcedure && ["/models", "/indicators"].includes(path)
    ? `${path}?${new URLSearchParams({ tender: selectedProcedure, returnTo: new URLSearchParams(location.search).get("returnTo") ?? "/tenders" })}` : path;
  const current = nav.flatMap((group) => group.items).find((item) => item.to === "/" ? location.pathname === "/" : location.pathname.startsWith(item.to));
  return <div className="shell product-shell">
    <a className="skip" href="#main">{t("brand.skip")}</a>
    <div className="mobile-app-header"><Brand /><button className="menu-toggle" ref={menuButton} type="button" aria-expanded={menuOpen} aria-controls="app-sidebar" onClick={() => setMenuOpen(true)}><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16" /></svg>{t("nav.open_menu")}</button></div>
    {menuOpen && <button className="drawer-backdrop" onClick={closeMenu} aria-label={t("analysis.close_menu")} tabIndex={-1} />}
    <aside id="app-sidebar" ref={drawer} className={`side${menuOpen ? " menu-open" : ""}`} role={menuOpen ? "dialog" : undefined} aria-modal={menuOpen ? true : undefined} aria-label={menuOpen ? t("nav.primary") : undefined}>
      <div className="brand-block"><Brand /><button ref={closeButton} type="button" className="drawer-close" aria-label={t("analysis.close_menu")} onClick={closeMenu}>×</button><p>{t("brand.tagline")}</p></div>
      <nav id="primary-navigation" className="nav" aria-label={t("nav.primary")}>{nav.map((group) => <div key={group.label} className="nav-group"><div className="nav-label">{group.label}</div>{group.items.map((item) => <NavLink key={item.to} to={destination(item.to)} end={item.to === "/"} onClick={() => { setMenuOpen(false); requestAnimationFrame(() => document.getElementById("main")?.focus()); }}><Icon path={item.to} /><span>{item.label}</span></NavLink>)}</div>)}</nav>
      <div className="side-foot">{t("brand.foot_1")}<p>{t("brand.foot_2")}</p></div>
    </aside>
    <div className="content-shell" ref={content}>
      <header className="app-topbar"><div className="current-section">{current?.label ?? t("brand.name_a")}</div><GlobalSearch /><div className="appearance-controls"><ThemeSwitch /><LangSwitch /></div></header>
      <main className="main" id="main" tabIndex={-1}><Suspense fallback={<Loading />}><Routes>
        <Route path="/" element={<Overview />} /><Route path="/tenders" element={<Tenders />} /><Route path="/tenders/:id" element={<TenderDetail />} />
        <Route path="/models" element={<ResearchAnalysis />} /><Route path="/indicators" element={<ResearchAnalysis mode="indicators" />} />
        <Route path="/distributions" element={<Distributions />} /><Route path="/network" element={<Network />} /><Route path="/workspace" element={<Workspace />} />
        <Route path="/method" element={<Method />} /><Route path="/kpis" element={<Kpis />} /><Route path="/raci" element={<Raci />} />
        {ModelCardFixture && <Route path="/__fixture/model-card" element={<ModelCardFixture />} />}
        <Route path="*" element={<NotFound />} />
      </Routes></Suspense></main>
      <footer className="app-footer">{t("analysis.disclaimer")}</footer>
    </div>
  </div>;
}
