import cs from "./cs";
import en from "./en";

export function getDictionary(lang = "cs") {
  return lang === "en" ? en : cs;
}