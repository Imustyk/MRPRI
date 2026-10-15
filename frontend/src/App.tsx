import { NavLink, Route, Routes } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { LANGS, type LangCode } from "./i18n";
import Overview from "./pages/Overview";
import Tenders from "./pages/Tenders";
import TenderDetail from "./pages/TenderDetail";
import Network from "./pages/Network";
import Distributions from "./pages/Distributions";
import Workspace from "./pages/Workspace";
import Method from "./pages/Method";
import Kpis from "./pages/Kpis";
import Raci from "./pages/Raci";

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

export default function App() {
  const { t } = useTranslation();
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
  return (
    <div className="shell">
      <a className="skip" href="#main">
        {t("brand.skip")}
      </a>
      <aside className="side">
        <div className="brand-block">
          <h1 className="brand">
            {t("brand.name_a")} <span>{t("brand.name_b")}</span>
          </h1>
          <p>{t("brand.tagline")}</p>
        </div>
        <LangSwitch />
        <nav className="nav" aria-label={t("nav.primary")}>
          {NAV.map((group) => (
            <div key={group.label} className="nav-group">
              <div className="nav-label">{group.label}</div>
              {group.items.map((item) => (
                <NavLink key={item.to} to={item.to} end={item.end}>
                  {item.label}
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
      <main className="main" id="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/tenders" element={<Tenders />} />
          <Route path="/tenders/:id" element={<TenderDetail />} />
          <Route path="/distributions" element={<Distributions />} />
          <Route path="/network" element={<Network />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/method" element={<Method />} />
          <Route path="/kpis" element={<Kpis />} />
          <Route path="/raci" element={<Raci />} />
        </Routes>
      </main>
    </div>
  );
}
