import type en from "../en";
import researchEvidence from "./researchEvidence";
import product from "./product";
import completion from "./completion";
import common from "./common";
import analysis from "./analysis";
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

const ru: typeof en = {
  ...common,
  analysis,
  completion,
  product,
  researchEvidence,
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

export default ru;
