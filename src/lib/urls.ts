import type { Lang } from "./i18n";

function clean(path: string) {
  return path.replace(/^\/+/, "");
}

export function isExternalUrl(path: string) {
  return /^(https?:)?\/\//i.test(path) || /^[a-z]+:/i.test(path);
}

export function asset(path: string) {
  if (!path || isExternalUrl(path)) return path;
  return `/${clean(path)}`;
}

export function page(slug: string, lang: Lang = "cs") {
  return lang === "en" ? `/en/${slug}/` : `/${slug}/`;
}

export function section(slug: string, lang: Lang = "cs") {
  return lang === "en" ? `/en/${slug}/` : `/${slug}/`;
}

export function home(lang: Lang = "cs") {
  return lang === "en" ? "/en/" : "/";
}
