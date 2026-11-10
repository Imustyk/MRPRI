import type en from "../en/analysis";

const analysis: typeof en = {
  "platform": "Spațiu de cercetare a achizițiilor",
  "models_title": "Analiza modelelor",
  "indicators_title": "Indicatori de risc",
  "models_intro": "Examinează deciziile salvate, compară scoruri din aceeași rulare și verifică datele procedurii.",
  "indicators_intro": "Valori, formule și limitele datelor. Regulile sunt separate de rezultatele modelelor.",
  "select_procedure": "Selectează procedura",
  "find_procedure": "Caută o procedură",
  "search_hint": "Titlu, cumpărător, furnizor sau OCID",
  "open_case": "Deschide analiza completă",
  "picker_scope": "Până la 20 rezultate, ordonate după centila existentă. Lista este un selector, nu populația de referință.",
  "no_results": "Nu există rezultate",
  "selected_procedure": "Procedura selectată",
  "model_explanation": "Dovezile modelului",
  "flagged": "Semnalată",
  "not_flagged": "Nesemnalată",
  "unavailable": "Date indisponibile",
  "raw_score": "Scor brut",
  "score_rank": "Centila scorului",
  "rank_definition": "Rang mediu pentru egalități; nu probabilitate",
  "reference_size": "Observații de referință",
  "same_run": "Scoruri disponibile din aceeași rulare",
  "score_distribution": "Distribuția scorului modelului",
  "log_counts": "log10(1 + număr)",
  "hist_scope": "Bază: {{n}} scoruri finite, {{missing}} lipsă; rulare {{run}}.",
  "hist_a11y": "Distribuția {{name}}. Scor selectat: {{value}}. Intervalele exacte sunt în tabel.",
  "procedures": "Număr de proceduri",
  "score_intervals": "Intervale ale scorului brut",
  "selected_interval": "Intervalul procedurii selectate",
  "threshold_interval": "Intervalul pragului confirmat",
  "y_log": "Axa verticală: log10(1 + număr), etichete în numere",
  "y_count": "Axa verticală: număr de proceduri",
  "bin_note": "Marcajele indică intervale, nu poziții geometrice exacte. Scorul și pragul exact sunt afișate numeric.",
  "reference_unavailable": "Referință comparabilă indisponibilă",
  "reference_reason": "Lipsește identificatorul confirmat sau scorurile finite. Nu se substituie altă rulare.",
  "threshold": "Prag confirmat al scorului",
  "source": "Sursă",
  "threshold_mismatch": "Indicatorul salvat diferă de pragul documentat. Decizia nu a fost modificată; verifică sursa.",
  "features_parameters": "Caracteristici, parametri și limite",
  "features": "Caracteristici înregistrate",
  "parameters": "Parametri înregistrați",
  "no_attribution": "Medianele/MAD de antrenare și contribuțiile locale nu sunt furnizate aici. Importanța globală nu explică individual procedura. Contamination/nu nu este prag al scorului brut.",
  "distribution_table": "Verifică intervalele și numerele",
  "selection": "Selecție",
  "run": "Rulare",
  "version": "Versiune declarată",
  "explainability_first": "Înțelege înainte de interpretare",
  "compare_models": "Patru modele. Patru scări diferite.",
  "votes": "Număr salvat de semnalări",
  "relative_rank": "Centila relativă agregată",
  "consensus": "Indicator de consens salvat",
  "yes": "Da",
  "no": "Nu",
  "voting_note": "Nivelul și numărul provin din API. Schema documentată: 0 scăzut, 1 mediu, 2 ridicat, 3–4 critic. Lipsurile rămân necunoscute. Centila nu este probabilitate de corupție sau constatare juridică.",
  "run_unverified": "Identitatea rulării sau rezumatul parametrilor nu este confirmat. Pragurile lipsă nu au fost reconstruite.",
  "scales_note": "Fiecare scor are propria scară. Selectează modelul pentru analiză separată.",
  "model": "Model",
  "verdict": "Decizie salvată",
  "details": "Detalii",
  "inspect": "Examinează modelul",
  "agreement_title": "Cât de des coincid deciziile?",
  "agreement_scope": "Aceeași rulare {{run}}: {{n}} proceduri. Fiecare celulă exclude deciziile lipsă ale perechii.",
  "agreement_definition": "Acord = decizii identice / perechi cu ambele decizii. Include nesemnalările comune; nu este acuratețe externă.",
  "separate_rules": "Caracteristici măsurate · separat de modele",
  "indicators_note": "Valorile provin din ETL curent. Valorile derivate pot conține imputări și nu certifică integralitatea sau disponibilitatea la publicare.",
  "indicator_group": "Grupa indicatorilor",
  "source_missing": "Date sursă lipsă",
  "derived_unverified": "Derivat · intrări incomplete",
  "stored_value": "Valoare ETL salvată",
  "recorded_signal": "Semnal înregistrat",
  "formula_quality": "Calcul și calitatea datelor",
  "formula": "Calcul în ETL existent",
  "inputs": "Câmpuri sursă",
  "etl_value": "Valoare derivată salvată",
  "no_indicator_threshold": "Nu este furnizat un prag separat pentru valoarea continuă. Valoarea singură nu înseamnă încălcare.",
  "additional_rules": "Alte reguli și module specializate",
  "additional_rules_note": "Sunt afișate doar semnalele din flags. Absența nu dovedește un rezultat negativ dacă sursa lipsește.",
  "no_recorded_signals": "Nu sunt semnale înregistrate; integralitatea trebuie verificată.",
  "specialized_unavailable": "Modulele specializate fără rezultate API per procedură sunt referințe metodologice, nu semnale suplimentare calculate aici.",
  "disclaimer": "O anomalie justifică analiză suplimentară, nu dovedește corupție, coluziune sau încălcarea legii.",
  "case_sections": "Secțiuni de analiză",
  "facts": "Datele procedurii",
  "evidence": "Dovezi și proveniență",
  "package_date": "Data pachetului OCDS",
  "bid_data_available": "Date despre oferte publicate",
  "bid_data_missing": "Date despre oferte indisponibile",
  "award_data_available": "Date despre atribuire disponibile",
  "award_data_missing": "Date despre atribuire indisponibile",
  "additional_facts": "Date suplimentare și limite",
  "days": "zile",
  "raw_facts_limit": "Valorile derivate pot folosi valori implicite ETL. Data pachetului nu certifică primul anunț; disponibilitatea istorică nu este confirmată.",
  "loading_models": "Se încarcă rezultatele salvate…",
  "traceability": "Verifică proveniența fiecărei concluzii",
  "run_date": "Data rulării salvate",
  "reference_present": "Fișier disponibil",
  "not_recorded": "Semnal neînregistrat",
  "corpus_frequency": "Frecvență în corpus",
  "explanation_unavailable": "Straturile de explicație nu sunt disponibile. Rezultatele modelelor sunt afișate separat mai sus.",
  "peer_limit": "Referința este populația evaluată în aceeași rulare, nu proceduri similare potrivite. Nu se pretinde comparabilitate cauzală.",
  "theme_light": "Temă deschisă",
  "theme_dark": "Temă întunecată",
  "theme_toggle": "Schimbă tema",
  "research": "Cercetare",
  "close_menu": "Închide navigarea",
  "coverage_decisions": "Decizii disponibile",
  "groups": {
    "all": "Toate",
    "financial": "Financiari",
    "competition": "Concurență",
    "procedural": "Procedurali",
    "behavioural": "Comportamentali"
  },
  "models": {
    "statistical_mad_zscore": {
      "description": "Abatere robustă față de valorile tipice; scorul este abaterea normalizată absolută maximă.",
      "limitation": "Medianele/MAD de antrenare nu sunt salvate. Abaterile pe caracteristici nu sunt reconstruite. Caracteristicile binare și concentrate sunt excluse conform parametrilor salvați."
    },
    "isolation_forest": {
      "description": "Isolation Forest evaluează ușurința izolării observației. Scorul salvat este −score_samples: valori mai mari indică anomalii mai mari.",
      "limitation": "Arborii și contribuțiile locale nu sunt furnizate. Histograma explică poziția, nu cauza deciziei. Contamination nu este prag al scorului."
    },
    "local_outlier_factor": {
      "description": "LOF compară densitatea locală cu vecinătatea antrenată. Valoarea salvată −score_samples crește cu anomalia locală.",
      "limitation": "Identitățile vecinilor, geometria și offset-ul nu sunt salvate în API. Nu sunt desenate vecinătăți fictive sau hărți 2D."
    },
    "one_class_svm": {
      "description": "One-Class SVM estimează o frontieră în spațiul caracteristicilor. Scor = −decision_function; valorile pozitive sunt pe partea anormală a frontierei zero documentate.",
      "limitation": "Pragul este afișat numeric doar când proveniența coincide. O linie 2D arbitrară nu este prezentată drept model multidimensional."
    }
  },
  "indicators": {
    "value_vs_cpv_median": {
      "title": "Valoare / mediana CPV",
      "description": "Valoarea primei atribuiri față de mediana grupei CPV din ETL.",
      "limitation": "Raporturile lipsă devin 1, extremele sunt limitate la 20. Valoare derivată, nu reper de preț original."
    },
    "estimate_to_award_ratio": {
      "title": "Estimare / total atribuit",
      "description": "Estimarea împărțită la totalul atribuirilor; prima atribuire este substituție dacă totalul lipsește.",
      "limitation": "Codul folosește estimare / atribuire, deși eticheta API veche spune invers. Lipsurile devin 1, interval [0,20]."
    },
    "n_bidders": {
      "title": "Participanți distincți",
      "description": "Număr furnizat de ETL, separat de înregistrările ofertelor pe loturi.",
      "limitation": "Zero fără date publicate nu dovedește lipsa concurenței."
    },
    "single_bidder": {
      "title": "Participant unic",
      "description": "Indicator binar salvat: numărul participanților este unu.",
      "limitation": "Lipsa listei nu permite o concluzie negativă privind participantul unic."
    },
    "bid_window_days": {
      "title": "Perioada ofertelor",
      "description": "Diferența în zile întregi dintre sfârșitul și începutul perioadei în ETL.",
      "limitation": "Lipsa devine 30 zile. Amestecul PN/EV și disponibilitatea istorică rămân nerezolvate; nu este dovadă certificată la publicare."
    },
    "short_deadline": {
      "title": "Termen scurt",
      "description": "Regulă salvată: perioada este nenegativă și mai mică de șapte zile.",
      "limitation": "Regula moștenește imputările și limitele provenienței; nu este constatare juridică."
    },
    "buyer_supplier_repeat_share": {
      "title": "Ponderea perechii repetate",
      "description": "Proceduri atribuite perechii cumpărător–câștigător / proceduri atribuite cumpărătorului.",
      "limitation": "Calculat pe cadrul disponibil, nu pe snapshot istoric. Coincide cu winner_share_of_buyer_awards; semnalele nu sunt independente."
    },
    "winner_share_of_buyer_awards": {
      "title": "Ponderea câștigătorului la cumpărător",
      "description": "Aceeași pondere a perechii în procedurile atribuite cumpărătorului.",
      "limitation": "Valorile implicite pot fi zero. Coincide cu ponderea perechii și nu o confirmă independent."
    }
  }
};

export default analysis;
