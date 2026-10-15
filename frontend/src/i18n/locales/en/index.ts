import common from "./common";
import backend from "./backend";
import overview from "./overview";
import tenders from "./tenders";
import tenderDetail from "./tenderDetail";
import distributions from "./distributions";
import network from "./network";
import workspace from "./workspace";
import method from "./method";
import kpis from "./kpis";
import raci from "./raci";

/**
 * English is the source locale: its shape is the contract every other locale
 * is typed against (`typeof en`). Namespaces are flat-merged, so keys read
 * "nav.overview", "common.retry", "overview.title", "backend.feature.lots", …
 */
const en = {
  ...common,
  backend,
  overview,
  tenders,
  tenderDetail,
  distributions,
  network,
  workspace,
  method,
  kpis,
  raci,
};

export default en;
export type Catalog = typeof en;
