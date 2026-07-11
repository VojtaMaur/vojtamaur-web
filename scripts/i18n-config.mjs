export const i18nConfig = {
  sourceLang: "CS",
  targetLang: "EN-US",
  cacheDir: "translations/en",

  // Only these rendered regions are sent to DeepL.
  // Put this once around rendered article/post content, not in every MDX file.
  translateSelector: '[data-i18n="translate"]',

  // Protected inside translated regions.
  protectSelector: [
    "pre",
    "code",
    "script",
    "style",
    "svg",
    "canvas",
    "iframe",
    ".notranslate",
    '[translate="no"]',
    '[data-i18n="protect"]'
  ].join(","),

  // Do not translate alt/thumbnailAlt. Captions are normal HTML text and are
  // translated when they are inside a translated region.
  translateAttributes: [],

  // Guardrail below DeepL's 128 KiB request-body limit.
  // If a page hits this, split the article manually or implement H2-level chunking.
  maxFragmentBytes: 80_000,

  deepl: {
    tagHandling: "html",
    tagHandlingVersion: "v2",
    splitSentences: "nonewlines",
    preserveFormatting: true,
    // Deliberately conservative. DeepL returns 429 when too many requests arrive
    // in a short period, so translation calls are paced and retried with backoff.
    minRequestIntervalMs: 1200,
    retryAttempts: 8,
    retryBaseDelayMs: 2000,
    retryMaxDelayMs: 60000,
    // Leave undefined for EN-US. Some DeepL target languages reject formality.
    formality: undefined
  },

  // The TSV file is the canonical glossary source. Its SHA-256 hash is used
  // automatically as the glossary/cache revision, so no manual v1/v2 bump.
  glossary: {
    enabled: true,
    name: "vojtamaur.cz CS-EN",
    sourceFile: "translations/glossary-cs-en.tsv",
    stateFile: "translations/glossary-cs-en.state.json"
  },

  hashSchemaVersion: 2,
  selectorPolicyRevision: 2
};
