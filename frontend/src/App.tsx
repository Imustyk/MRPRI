import { NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview";
import Tenders from "./pages/Tenders";
import TenderDetail from "./pages/TenderDetail";
import Network from "./pages/Network";
import Distributions from "./pages/Distributions";
import Workspace from "./pages/Workspace";
import Method from "./pages/Method";

export default function App() {
  return (
    <div className="shell">
      <aside className="side">
        <h1 className="brand">
          MTender <span>Risk</span>
        </h1>
        <p>Anomaly detection for Moldova public procurement</p>
        <nav className="nav">
          <NavLink to="/" end>
            Overview
          </NavLink>
          <NavLink to="/tenders">Procedures</NavLink>
          <NavLink to="/distributions">Distributions</NavLink>
          <NavLink to="/network">Buyer–bidder graph</NavLink>
          <NavLink to="/workspace">Workspace</NavLink>
          <NavLink to="/method">Methodology</NavLink>
        </nav>
        <div className="side-foot">
          Master's application · Law 131/2015 · Isolation Forest + red flags
          <br />
          Scores are risk indicators, not legal findings.
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/tenders" element={<Tenders />} />
          <Route path="/tenders/:id" element={<TenderDetail />} />
          <Route path="/distributions" element={<Distributions />} />
          <Route path="/network" element={<Network />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/method" element={<Method />} />
        </Routes>
      </main>
    </div>
  );
}
