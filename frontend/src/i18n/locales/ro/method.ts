import type en from "../en/method";

const method: typeof en = {
  kicker: "Corelare cu teza",
  title: "Cum este construit detectorul",
  lede: `Panoul este o vizualizare doar în citire peste ETL-ul din <code>/scripts</code>. Fiecare cifră afișată provine din fluxul real MTender OCDS stocat în MongoDB, nu din date generate. Cine poate modifica această metodologie se află în <racilink>matricea RACI</racilink>.`,
  pipeline_h: "Pipeline",
  pipeline: {
    step1: `Parcurgerea întregului istoric public OCID (<code>01a</code>) și preluarea unui pachet OCDS per procedură (<code>01b</code>), păstrând corpul exact al răspunsului într-o arhivă pentru a putea recalcula orice rezultat.`,
    step2: `Normalizare și validare (<code>02</code>): cumpărătorul se rezolvă din <code>parties[].roles</code>, deoarece câmpul de nivel superior <code>buyer</code> nu este niciodată completat; CPV se citește atât din <code>tender.classification</code>, cât și din <code>tender.items[].classification</code>; se acceptă ambele variante de adresă.`,
    step3: `Ingineria indicilor în SQL și pandas (<code>03</code>), cu verificarea încrucișată a definițiilor medianei CPV din MongoDB și pandas.`,
    step4: `Patru detectoare (<code>06</code>): MAD folosește pragul robust-z salvat; Isolation Forest, LOF și One-Class SVM folosesc ipoteza contamination/nu de 5%. Parametrii nu sunt acuratețe măsurată. Indicatorii binari sunt separați. Verificări pe <kpilink>pagina KPI</kpilink>.`,
    step5: `Exportarea instantaneului (<code>04</code>), a tabelelor descriptive (<code>05</code>), a importanței SHAP și permutărilor (<code>07</code>) și a unui dicționar de câmpuri live (<code>08</code>).`,
  },
  band_h: "Cum se stabilește nivelul de risc",
  band_p: `Unei proceduri i se atribuie un nivel în funcție de câte detectoare au semnalat-o: <strong>mediu</strong> = 1, <strong>ridicat</strong> = 2, <strong>critic</strong> = 3 sau mai mult (consens). Clasificarea după acord, nu după un prag de scor, menține nivelele comparabile între modele, ale căror scări de scor brut diferă cu ordine de mărime.`,
  band_note: `Cila afișată lângă fiecare nivel este rangul celei mai extreme detector al înregistrării în acest set de date. Nu este o probabilitate și nu este comparabilă între rulări diferite ale pipeline-ului.`,
  absent_h: "Indicii absenți în mod deliberat",
  absent_p: `MTender nu publică acestea, deci nu sunt calculate și nu sunt afișate niciodată ca zero. O versiune anterioară a panoului le deriva din date generate, ceea ce făcea ca cifre inventate să pară măsurători.`,
  absent_th_field: "Câmp",
  absent_th_why: "De ce nu este disponibil",
  high_h: "Ce înseamnă un nivel ridicat",
  high_p: `Sistemul identifică <em>indicatori de risc</em> statistici și procedurali. Acordul este diagnostic intern, nu dovadă independentă a calității. Evaluarea externă necesită etichete verificate, unități independente și caracteristici disponibile istoric. Un nivel ridicat justifică verificarea, nu este constatare juridică.`,
  high_p2: `Valorile contractelor se însumează pe toate loturile atribuite înainte de comparare cu estimarea, deoarece <code>estimated_value</code> acoperă întreaga procedură, iar o procedură poate fi atribuită pe sute de loturi.`,
};

export default method;
