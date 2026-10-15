/** Network page strings (English = source). */
const network = {
  title: "Buyer–winner network",
  kicker: "Relational layer",
  loading_title: "Buyer–winner network",
  no_graph: "No graph returned.",
  empty: "No repeated buyer–winner pairs",
  empty_hint: "A pair needs a supplier that won more than one procedure from the same authority.",
  lede: "Each cell is one repeated buyer–supplier pair: rows are contracting authorities, columns are suppliers. The fill follows the highest anomaly percentile recorded for the pair; hover a cell for its award count and value, and the table beside it ranks the same pairs. Click a row or column label to open that party's local network.",

  legend_authority: "contracting authority",
  legend_supplier: "supplier",
  legend_high: "percentile ≥ 80",
  legend_mid: "50–79",
  legend_low: "< 50 or unscored",
  legend_unscored: "dashed border = not scored",

  matrix_h: "Connections matrix",
  matrix_note:
    "Rows are contracting authorities, columns are suppliers; one cell is one repeated pair. Hover a cell for its award count, percentile and value. The filters below apply to the matrix and the table at the same time.",
  matrix_label: "Connections matrix: {{rows}} authorities by {{cols}} suppliers, {{n}} pairs",
  cell_label: "{{a}} → {{b}}: {{w}} awards, percentile {{p}}, {{v}}",

  f_min_awards: "Min awards per pair",
  f_min_percentile: "Min percentile",
  f_min_percentile_hint: "0 keeps pairs no model ever scored",
  f_search: "Search",
  ph_search: "authority or supplier name…",
  f_top: "Matrix size",
  top_opt: "top {{n}} per side",
  filters_empty: "No pairs match these filters",
  filters_empty_hint: "Lower the thresholds or clear the search.",

  coverage:
    "Showing {{shown}} of {{qualifying}} qualifying pairs — the union of the top {{slice}} by awards and by percentile; the rest of the network stays outside this slice.",
  coverage_all: "All {{n}} qualifying pairs are shown.",

  table_h: "Top pairs",
  table_note:
    "Showing the {{shown}} highest-ranked of {{total}} filtered pairs; the CSV export carries all {{total}}.",
  btn_csv: "Export CSV ({{n}})",
  sel_note: "The selected pair is outlined in the matrix.",
  sel_clear: "Clear selection",

  drill_h: "Local network",
  drill_open: "Open the local network of {{name}}",
  drill_canvas: "Local network of {{name}} with {{n}} partners",
  drill_note:
    "{{name}} with its {{n}} most-awarded partners, at most 30 drawn. Node size follows awards, edge colour follows the percentile band, and a dashed edge was never scored.",
  drill_list: "Text list of connections",
  drill_empty: "No partners for this party in the loaded slice.",

  th_authority: "Authority",
  th_supplier: "Supplier",
  th_awards: "Awards",
  th_value: "Total value",
  th_max: "Max percentile",
  kind_buyer: "contracting authority",
  kind_supplier: "supplier",
};

export default network;
