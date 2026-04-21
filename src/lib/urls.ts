const BASE_URL = import.meta.env.BASE_URL || "/";

function clean(path: string) {
  return path.replace(/^\/+/, "");
}

export function isExternalUrl(path: string) {
  return /^(https?:)?\/\//i.test(path) || /^[a-z]+:/i.test(path);
}

export function asset(path: string) {
  if (!path || isExternalUrl(path)) return path;
  const p = clean(path);
  return BASE_URL === "./" ? `./${p}` : `/${p}`;
}

export function page(slug: string) {
  return BASE_URL === "./" ? `./${slug}.html` : `/${slug}/`;
}

export function section(slug: string) {
  return BASE_URL === "./" ? `./${slug}.html` : `/${slug}/`;
}

export function home() {
  return BASE_URL === "./" ? "./index.html" : "/";
}