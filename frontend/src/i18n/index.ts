import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import en from "./locales/en";
import ru from "./locales/ru";
import ro from "./locales/ro";

export const LANGS = [
  { code: "en", label: "English", short: "EN" },
  { code: "ro", label: "Română", short: "RO" },
  { code: "ru", label: "Русский", short: "RU" },
] as const;

export type LangCode = (typeof LANGS)[number]["code"];

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      ru: { translation: ru },
      ro: { translation: ro },
    },
    fallbackLng: "en",
    supportedLngs: LANGS.map((l) => l.code),
    nonExplicitSupportedLngs: true,
    detection: {
      // Browser language first, but a saved explicit choice always wins.
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "mtender_lang",
      caches: ["localStorage"],
    },
    interpolation: { escapeValue: false },
    returnEmptyString: false,
  });

/** Keeps <html lang>, the tab title and the meta description in step. */
function syncDocument() {
  const lang = i18n.resolvedLanguage ?? "en";
  document.documentElement.lang = lang;
  document.title = i18n.t("brand.doc_title");
  document
    .querySelector('meta[name="description"]')
    ?.setAttribute("content", i18n.t("brand.doc_desc"));
}
i18n.on("languageChanged", syncDocument);
syncDocument();

/**
 * BCP47 tag used by Intl formatters, per active language. Numbers and dates
 * follow the locale; the currency stays MDL everywhere.
 */
export function intlLocale(): string {
  switch (i18n.resolvedLanguage) {
    case "ro":
      return "ro-MD";
    case "ru":
      return "ru-RU";
    default:
      return "en-GB";
  }
}

export default i18n;
