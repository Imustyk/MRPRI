import type en from "../en/network";

const network: typeof en = {
  title: "Rețea cumpărător–câștigător",
  kicker: "Strat relațional",
  loading_title: "Rețea cumpărător–câștigător",
  no_graph: "Niciun graf returnat.",
  empty: "Nicio pereche repetată cumpărător–câștigător",
  empty_hint: "O pereche necesită un furnizor care a câștigat mai mult de o procedură de la aceeași autoritate.",
  lede: "Fiecare celulă este o pereche repetată cumpărător–furnizor: rândurile sunt autorități contractante, coloanele sunt furnizori. Umplutura urmărește cea mai mare centilă a anomaliilor înregistrată pentru pereche; treceți cu mouse-ul peste o celulă pentru numărul de contracte și valoare, iar tabelul alături ranghează aceleași perechi. Apăsați pe eticheta unui rând sau a unei coloane pentru a deschide rețeaua locală a părții respective.",

  legend_authority: "autoritate contractantă",
  legend_supplier: "furnizor",
  legend_high: "centilă ≥ 80",
  legend_mid: "50–79",
  legend_low: "< 50 sau neevaluat",
  legend_unscored: "contur punctat = neevaluat",

  matrix_h: "Matricea conexiunilor",
  matrix_note:
    "Rândurile sunt autorități contractante, coloanele sunt furnizori; o celulă este o pereche repetată. Treceți cu mouse-ul peste o celulă pentru contracte, centilă și valoare. Filtrele de mai jos se aplică matricei și tabelului în același timp.",
  matrix_label: "Matricea conexiunilor: {{rows}} autorități pe {{cols}} furnizori, {{n}} perechi",
  cell_label: "{{a}} → {{b}}: {{w}} contracte, centilă {{p}}, {{v}}",

  f_min_awards: "Minim contracte pe pereche",
  f_min_percentile: "Centilă minimă",
  f_min_percentile_hint: "0 păstrează și perechile pe care niciun model nu le-a punctat",
  f_search: "Căutare",
  ph_search: "numele autorității sau al furnizorului…",
  f_top: "Dimensiunea matricei",
  top_opt: "top {{n}} pe fiecare parte",
  filters_empty: "Nicio pereche nu corespunde acestor filtre",
  filters_empty_hint: "Reduceți pragurile sau căutați altfel.",

  coverage:
    "Sunt afișate {{shown}} din {{qualifying}} perechi calificate — uniunea top-{{slice}} după premii și după centile; restul rețelei rămâne în afara acestei felii.",
  coverage_all: "Toate cele {{n}} perechi calificate sunt afișate.",

  table_h: "Perechi de top",
  table_note:
    "Sunt afișate primele {{shown}} din cele {{total}} perechi filtrate; exportul CSV conține toate {{total}}.",
  btn_csv: "Export CSV ({{n}})",
  sel_note: "Perechea selectată este încadrată în matrice.",
  sel_clear: "Elimină selecția",

  drill_h: "Rețea locală",
  drill_open: "Deschide rețeaua locală a: {{name}}",
  drill_canvas: "Rețeaua locală a {{name}} cu {{n}} parteneri",
  drill_note:
    "{{name}} și cei mai bine plasați {{n}} parteneri ai săi, cel mult 30 desenați. Dimensiunea nodului urmărește contractele, culoarea muchiei urmează clasa centilei, iar o muchie punctată nu a fost niciodată punctată.",
  drill_list: "Lista conexiunilor în text",
  drill_empty: "Această parte nu are parteneri în felia încărcată.",

  th_authority: "Autoritate",
  th_supplier: "Furnizor",
  th_awards: "Contracte",
  th_value: "Valoare totală",
  th_max: "Centilă max.",
  kind_buyer: "autoritate contractantă",
  kind_supplier: "furnizor",
};

export default network;
