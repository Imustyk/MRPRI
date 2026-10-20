import type en from "../en/backend";

const ro: typeof en = {
  flag: {
    single_bidder: "Un singur ofertant",
    short_window: "Termen scurt de depunere",
    accelerated: "Procedură accelerată",
    no_award: "Niciun contract publicat după licitație",
    split_lots: "Contract împărțit pe multe loturi",
    several_suppliers: "Mai mulți furnizori pe același contract",
    cancelled: "Anulată",
    amended: "Modificată după publicare",
    no_bid_data: "Datele ofertelor nu sunt publicate",
    long_window: "Termen lung de depunere",
  },
  feature: {
    award_total: "Total contract (MDL)",
    first_award: "Valoarea primului contract (MDL)",
    estimated: "Valoare estimată (MDL)",
    award_estimate_ratio: "Contract / estimare",
    value_vs_cpv: "Valoare față de mediana CPV",
    distinct_bidders: "Ofertanți distincți",
    bid_records: "Înregistrări de oferte (per lot)",
    lots: "Loturi",
    awards: "Contracte",
    bidding_window: "Termen de depunere (zile)",
    single_bidder_01: "Un singur ofertant (0/1)",
    short_deadline_01: "Termen scurt (0/1)",
    winner_share: "Cota câștigătorului din contractele cumpărătorului",
    repeat_pair: "Ponderea perechilor repetate",
    anomaly_percentile: "Centila anomaliilor",
    iforest_score: "Scor Isolation Forest",
    lof_score: "Scor LOF",
    svm_score: "Scor One-Class SVM",
    mad_z: "Scor z MAD",
  },
  group: {
    financial: "financiar",
    competition: "concurență",
    procedural: "procedural",
    behavioural: "comportamental",
    model: "model",
  },
  category: {
    risk_band: "Nivel de risc",
    procedure_type: "Tip de procedură",
    procurement_method: "Metodă de achiziție",
    status: "Stare",
    locality: "Localitatea cumpărătorului",
    cpv: "Cod CPV",
    procurer: "Cumpărător",
    supplier: "Furnizor",
  },
  date: {
    published: "Publicat",
    listed: "În listat",
    tender_start: "Începutul licitației",
    deadline: "Termen limită",
    award_date: "Data contractului",
  },
  detector: {
    mad: "Linie de bază scor z MAD",
    iforest: "Isolation Forest",
    lof: "Local Outlier Factor",
    ocsvm: "One-Class SVM",
  },
  family: {
    robust: "statistică univariată robustă",
    ensemble: "ansamblu de arbori",
    neighbourhood: "densitate de vecinătate",
    kernel: "densitate de nucleu",
  },
  band: {
    unscored: "nu există ieșire de la detectoare pentru această înregistrare (nu e curată)",
    low: "niciun model nu a semnalat înregistrarea",
    medium: "1 model a semnalat-o",
    high: "2 modele au semnalat-o",
    critical: "3 sau mai multe modele au semnalat-o (consens)",
  },
  meta: {
    source: "mtender-ocds (date reale de achiziții publice)",
    metrics_reason:
      "achizițiile reale nu au etichete reale de anomaliile, deci precision/recall/F1 nu sunt calculabile pe acest corpus; verificările controlează verdictele, pragurile, numărătorile și căile către artefacte",
    metrics_reason_short: "achizițiile reale nu au etichete ground truth pentru anomalii",
    unavailable_cpv: "MTender publică doar coduri CPV; nu se servește dicționar cod->etichetă",
    unavailable_bids: "bids.details este publicat doar pentru o mică minoritate a achizițiilor",
    unavailable_bid_prices: "derivat din prețurile ofertelor, care lipsesc în mare măsură",
    unavailable_lot_ratio: "necesită atât prețurile ofertelor, cât și valoarea estimată per lot",
    unavailable_direct: "nu există indicator de atribuire directă în pachetul OCDS",
    unavailable_negotiated: "nu există indicator de procedură negociată în pachetul OCDS",
    unavailable_aggregate: "nu se poate derivă dintr-o singură sumă agregată a contractului",
    unavailable_threshold: "proximitatea pragului necesită limita per procedură, care nu se publică",
    unavailable_dates: "datele de înregistrare a părților nu sunt în pachet",
    unavailable_bid_records: "bids.details este per lot, deci numără înregistrări de oferte, nu ofertanți",
    unavailable_truth: "etichetă reală (ground truth), doar date sintetice",
    unknown: "(necunoscut)",
  },
  kpi: {
    verdict_stored: "Verdict salvat pentru fiecare rând evaluat",
    flagged_share: "Ponderea semnalatelor în banda de contaminare ({{name}})",
    flag_reproduces: "Steagul reproduces pragul declarat {{name}}",
    scores_agree: "Scorurile sunt de acord cu verdictul",
    path_resolves: "Calea modelului declarat duce la artefact",
    corpus_output: "Corpusul conține ieșiri de la detectoare",
    counts_equal: "n_models_flagging este egal cu numărul de verdicte setate",
    consensus: "consens == (n_models_flagging >= {{min}})",
    percentile_bounds: "Centila anomaliilor rămâne în 0-100",
    run_repro: "Ponderea semnalatelor live se potrivește cu rularea înregistrată",
  },
  annot: {
    observation: "observație",
    single_bidder: "un singur ofertant",
    repeat: "relație repetată",
    value: "anomalie de valoare",
    docs: "lacună de documentație",
    followup: "de urmărit",
    cleared: "respins",
  },
  ext: {
    aap_label: "Lista de interdicții AAP pentru furnizori (etichetă proxy)",
    ansc_label: "Procedură contestată (documente de plângeri ANSC; etichetă proxy)",
    aap_caveat:
      "Etichetă proxy: proceduri ale furnizorilor sancționați, nu adevăr fundamental. Eticheta este condusă de mărime și concurență (baseline pe un singur caracter n_bidders ~0,80); ansamblul de 4 voturi la ~0,49 este la nivelul aleatorului — raportat ca atare.",
    ansc_caveat:
      "Plângerile sunt un marker de procedură contestată, nu o încălcare confirmată: deciziile ANSC nu au fost accesibile pentru acest corpus, deci nu se pot distinge apelurile confirmate de cele respinse.",
    ansc_verdict: "IC 95% include 0,5 — pe această etichetă semnalul este indistinguibil de aleator",
  },
  eval: {
    noise_note:
      "Experiment cu zgomot de intrare (o măsurătoare, nu un ciclu de acceptare): rangurile scorurilor sunt stabile pentru intrări exacte și aproape exacte, dar pozițiile se schimbă sub zgomot contrafactual — revizuiți liste top-K, nu ranguri exacte.",
    drift_note:
      "Deriva distribuției scorurilor între perioada de calibrare (2018–2021) și perioada de test (2022–2024): granița voturilor necesită recalibrare periodică.",
    disclaimer: "Indicatori de risc potențial, nu dovezi ale corupției.",
  },
  bias: {
    admissible: "admis",
    admissible_explained: "admis (diferența explicată prin factori legitimi)",
    violation: "încălcare",
    warning: "avertizare",
  },
  xai: {
    verdict_disagree: "inconsecvente",
    disclaimer:
      "Indicator de risc potențial, nu dovadă de corupție. O analiză a metodelor de explicare, nu o evaluare a procedurii.",
    note_shap_only:
      "Valorile SHAP de aici sunt calculate doar pentru Isolation Forest; LOF, One-Class SVM și MAD nu au atribuiri per înregistrare.",
    note_disagree:
      "SHAP și LIME nu sunt de acord asupra acestui model (vezi xai_consistency.verdict); tratați atribuirile ca interne modelului, nu cauze.",
  },
  model: {
    production_label:
      "v0 producție: scor z MAD robust + IsolationForest + LOF + One-Class SVM (consens din 4 voturi)",
  },
  explain: {
    disclaimer:
      "Un scor de anomalie este un indicator de risc potențial, nu o dovadă de corupție sau încălcare. Este necesară verificarea de către o autoritate competentă.",
    not_causal:
      "Explicările sunt motive interne ale modelului pentru un scor neobișnuit; nu sunt dovadă cauzală a vreunei fapte.",
    shap_lime_disagree:
      "SHAP și LIME nu sunt de acord asupra acestui model (verdict măsurat: „{{verdict}}”); tratați atribuirile individuale cu prudență.",
    per_row_only:
      "Atribuiri per înregistrare există doar pentru Isolation Forest; LOF, One-Class SVM și MAD au verdicte, dar fără atribuiri per înregistrare.",
    top200:
      "Rangurile sub top-200 sunt sensibile la zgomot (audit de zgomot de intrare); revizuiți liste de cazuri, nu poziții exacte.",
    not_imputed:
      "Câmpurile pe care MTender nu le publică sunt afișate ca indisponibile, niciodată imputate.",
    never_scored:
      "Această înregistrare nu a fost niciodată evaluată de rularea de detecție — nu a fost examinată, iar „neevaluat” nu înseamnă curat.",
    not_present: "Nu apare în această înregistrare: {{fields}}",
    ref_global: "Explicabilitate globală (importanță prin permutare, SHAP, SHAP vs LIME)",
    ref_perm: "Importanță prin permutare (toate cele 22 de caracteristici)",
    ref_shap: "Importanță SHAP (doar Isolation Forest)",
    ref_xai: "Măsurarea concordanței SHAP vs LIME",
    ref_noise: "Sensibilitatea rangurilor la zgomotul de intrare",
    ref_card: "Fișă de model (MTA-0004)",
  },
  err: {
    run_pipeline: "Rulați mai întâi pipeline-ul",
    tender_not_found: "Licitația nu a fost găsită",
    source_invalid: "sursa trebuie să fie 'synthetic' sau 'ocds'",
    case_not_found: "Cazul nu a fost găsit",
    annotation_not_found: "Nota nu a fost găsită",
    watchlist_not_found: "Lista de monitorizare nu a fost găsită",
    item_not_found: "Elementul nu a fost găsit",
    view_not_found: "Vizualizarea nu a fost găsită",
    confirm_reset: "Trimiteți confirm=true pentru a șterge toate rândurile din spațiul de lucru",
    method_invalid: "metoda trebuie să fie pearson, spearman sau kendall",
    scale_invalid: "scara trebuie să fie auto, linear, log sau quantile",
    grain_invalid: "granularitatea trebuie să fie day, week, month, quarter sau year",
  },
};

export default ro;
