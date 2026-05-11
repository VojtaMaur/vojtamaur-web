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
    // Leave undefined for EN-US. Some DeepL target languages reject formality.
    formality: undefined
  },

  hashSchemaVersion: 2,
  selectorPolicyRevision: 2,
  glossaryRevision: "none"
};
