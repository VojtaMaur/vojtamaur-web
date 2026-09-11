/** Public descriptions of the vm: terms used by export-site-json.mjs v1.0.0. */
export const namespace = "https://vojtamaur.cz/ns/";
export const exportVersion = "1.0.0";

export const groups = [
  { id: "export", title: "Export jako celek" },
  { id: "article", title: "Články" },
  { id: "media", title: "Média a odkazy" },
] as const;

type Term = {
  name: string;
  group: typeof groups[number]["id"];
  scope: string;
  type: string;
  description: string;
  example: unknown;
  notes?: string[];
};

export const terms: Term[] = [
  {
    name: "exportVersion", group: "export", scope: "Kořenový objekt Collection", type: "řetězec",
    description: "Verze formátu a implementace JSON-LD exportéru. Pomáhá určit, jak číst tento soubor.",
    example: "1.0.0",
    notes: ["Není to verze JSON-LD, webu ani jednotlivého článku."],
  },
  {
    name: "generatedAt", group: "export", scope: "Kořenový objekt Collection", type: "řetězec s časem v ISO 8601, UTC",
    description: "Okamžik vytvoření JSON exportu, zaznamenaný exportérem.",
    example: "2026-09-11T09:00:00.000Z",
    notes: ["Není to datum vydání ani změny článků. Kontext exportu ponechává hodnotu jako řetězec, nepřiřazuje jí datový typ xsd:dateTime."],
  },
  {
    name: "sourceIndexPath", group: "export", scope: "Kořenový objekt Collection", type: "řetězec: cesta",
    description: "Cesta ke vstupnímu ALL_POSTS.txt, obvykle relativní vůči kořeni projektu. Index určuje výběr článků a jejich zdrojová metadata.",
    example: "dist/ALL_POSTS.txt",
    notes: ["Používá lomítka /. Při volbě buildu mimo projekt může obsahovat ..; u buildu na jiném Windows disku bude absolutní. Není to veřejná URL."],
  },
  {
    name: "sourceIndexSha256", group: "export", scope: "Kořenový objekt Collection", type: "řetězec: 64 malých hexadecimálních znaků",
    description: "SHA-256 přesných bajtů vstupního ALL_POSTS.txt, včetně případného BOM a původních konců řádků.",
    example: "a".repeat(64),
    notes: ["Ukázkový hash je ilustrativní. Hodnota se týká vstupního indexu, nikoli výsledného JSON souboru."],
  },
  {
    name: "sourceGeneratedAt", group: "export", scope: "Kořenový objekt Collection", type: "řetězec",
    description: "Hodnota řádku Generated: ze vstupního ALL_POSTS.txt. Pokud tento řádek chybí, export obsahuje prázdný řetězec.",
    example: "2026-09-10T08:42:49.334Z",
    notes: ["Popisuje vznik textového indexu. Exportér ji nepřepočítává ani nezaručuje shodu se stářím všech souborů buildu."],
  },
  {
    name: "articleCount", group: "export", scope: "Kořenový objekt Collection", type: "celé číslo",
    description: "Počet záznamů v hasPart. Každá jazyková verze článku se počítá samostatně.",
    example: 164,
    notes: ["Například 82 článků s českou i anglickou verzí dává 164 záznamů. Počet se mění s obsahem buildu."],
  },
  {
    name: "notes", group: "export", scope: "Kořenový objekt Collection", type: "pole řetězců",
    description: "Poznámky exportéru k rozsahu exportu a interpretaci textu, médií, dat, jazyků, pořadí a kontrolních součtů.",
    example: ["Article order is recorded explicitly as vm:position because JSON-LD arrays do not imply RDF ordering."],
  },
  {
    name: "declaredBuildSha256", group: "export", scope: "Kořenový objekt Collection; nepovinné pole", type: "řetězec: 64 malých hexadecimálních znaků",
    description: "Hash deklarovaný souborem BUILD_SHA256.txt ve vybraném buildu. V tomto projektu má identifikovat soubor SHA256SUMS.txt.",
    example: "b".repeat(64),
    notes: ["Pole chybí, pokud BUILD_SHA256.txt není přítomen. Exportér údaj pouze přečte; neověřuje manifest, shodu všech souborů ani OpenPGP podpis. Ukázkový hash je ilustrativní."],
  },
  {
    name: "slug", group: "article", scope: "Objekt BlogPosting v hasPart", type: "řetězec",
    description: "Identifikátor článku převzatý z pole SLUG v indexu. Česká a anglická verze používají stejný slug.",
    example: "metawebovy-clanek",
    notes: ["Neobsahuje jazykový prefix en/. Spolu s inLanguage identifikuje konkrétní jazykovou verzi."],
  },
  {
    name: "position", group: "article", scope: "Objekt BlogPosting v hasPart", type: "kladné celé číslo od 1",
    description: "Pořadí jazykové verze článku ve vstupním indexu a ve výsledném hasPart.",
    example: 1,
    notes: ["Slouží k obnovení pořadí i po zpracování jako RDF, kde běžné JSON-LD pole samo o sobě pořadí nezaručuje. Není to trvalé ID článku."],
  },
  {
    name: "sourcePath", group: "article", scope: "Objekt BlogPosting v hasPart", type: "řetězec: cesta zaznamenaná v indexu",
    description: "Původní hodnota SOURCE z ALL_POSTS.txt, obvykle cesta ke zdrojovému MDX souboru vztažená ke kořeni projektu.",
    example: "src/content/posts/metawebovy-clanek.mdx",
    notes: ["Exportér aktuální MDX nečte ani nehashuje. Cesta tedy nepotvrzuje, že současný zdrojový soubor odpovídá vybranému buildu."],
  },
  {
    name: "builtHtmlPath", group: "article", scope: "Objekt BlogPosting v hasPart", type: "řetězec: relativní cesta",
    description: "Cesta ke skutečně načtenému HTML souboru vztažená ke kořeni vybraného buildu, s lomítky /.",
    example: "en/metawebovy-clanek/index.html",
    notes: ["U plochého USB buildu může mít tvar en/metawebovy-clanek.html. Na rozdíl od sourcePath a sourceIndexPath se nevztahuje ke kořeni projektu."],
  },
  {
    name: "builtHtmlSha256", group: "article", scope: "Objekt BlogPosting v hasPart", type: "řetězec: 64 malých hexadecimálních znaků",
    description: "SHA-256 přesných bajtů celého HTML souboru, ze kterého byl tento záznam vytvořen.",
    example: "c".repeat(64),
    notes: ["Nehashuje pouze articleBody ani vm:articleHtml. Ukázkový hash je ilustrativní."],
  },
  {
    name: "sourceMetadata", group: "article", scope: "Objekt BlogPosting v hasPart", type: "objekt JSON; v JSON-LD literál @json",
    description: "Všechna původní metadata z hlavičky záznamu v ALL_POSTS.txt, zachovaná jako slovník řetězců.",
    example: { TITLE: "Metawebový článek", SLUG: "metawebovy-clanek", URL: "https://vojtamaur.cz/en/metawebovy-clanek/", LANGUAGE: "en", SECTION: "volna-tvorba", DATE: "2026-04-01", SOURCE: "src/content/posts/metawebovy-clanek.mdx", BUILT_HTML: "dist/en/metawebovy-clanek/index.html" },
    notes: ["TITLE může zůstat česky i u anglického záznamu. Pole headline oproti tomu pochází z vykresleného nadpisu. Vnitřní klíče tohoto JSON literálu se nerozvíjejí do pojmů Schema.org ani vm:."],
  },
  {
    name: "renderedMetadata", group: "article", scope: "Objekt BlogPosting v hasPart", type: "pole řetězců; může být prázdné",
    description: "Texty prvků .post-meta uvnitř článku po sjednocení bílých znaků, v pořadí nalezeném v HTML.",
    example: ["duben 2026"],
    notes: ["Podle sekce mohou obsahovat datum, místo výstavy nebo další údaje. Jde o čitelné popisky, nikoli o nově strukturované datum nebo místo."],
  },
  {
    name: "articleHtml", group: "article", scope: "Objekt BlogPosting v hasPart", type: "řetězec s HTML",
    description: "Vnitřní HTML prvního článku vybraného pomocí main article, serializované po načtení knihovnou Cheerio. Zahrnuje nadpis, viditelná metadata i obsah článku.",
    example: '<div class="post-header"><h1>Ukázka</h1></div><div class="post-body"><p>Text článku.</p></div>',
    notes: ["Není to samostatná stránka ani přesná bajtová kopie vstupního souboru. Relativní odkazy se vztahují k vm:builtHtmlPath v daném buildu. HTML není sanitizované; při jeho dalším zobrazování je nutné zacházet s ním jako s obsahem původní stránky."],
  },
  {
    name: "robots", group: "article", scope: "Objekt BlogPosting v hasPart", type: "řetězec",
    description: "Obsahy atributu content u značek meta s name=robots v načteném HTML, spojené čárkou. Pokud nejsou přítomné, hodnota je prázdná.",
    example: "index,follow,max-image-preview:large",
    notes: ["Zachycuje značky v HTML; nezahrnuje HTTP hlavičku X-Robots-Tag ani pravidla robots.txt."],
  },
  {
    name: "languageStatus", group: "article", scope: "Objekt BlogPosting v hasPart", type: "řetězec: original, english-route nebo incomplete-czech-fallback",
    description: "Stav odvozený z jazyka v indexu a ze značky robots podle konvence tohoto webu.",
    example: "english-route",
    notes: ["original: záznam má LANGUAGE=cs. incomplete-czech-fallback: záznam má LANGUAGE=en a robots obsahuje slovo noindex. english-route: ostatní záznamy s LANGUAGE=en.", "Není to nezávislé ověření úplnosti ani kvality překladu. Anglická verze může obsahovat český ALT text, citace či nepřeložené pasáže."],
  },
  {
    name: "links", group: "article", scope: "Objekt BlogPosting v hasPart", type: "pole objektů vm:Link; může být prázdné",
    description: "Odkazy nalezené v prvcích a[href] uvnitř článku, v pořadí HTML. Opakované odkazy se zachovávají.",
    example: [{ "@type": "vm:Link", url: "https://vojtamaur.cz/koncepty/", name: "Koncepty", "vm:originalHref": "/koncepty/" }],
    notes: ["Zahrnuje pouze URL, které exportér dokáže rozvinout do podporovaných schémat http, https, mailto, tel, gemini nebo gopher. Nejde o všechny možné síťové odkazy uvnitř HTML, skriptů a médií."],
  },
  {
    name: "element", group: "media", scope: "Objekty v associatedMedia a image", type: "řetězec: img, iframe, video, audio, object nebo embed",
    description: "Název původního HTML prvku, ze kterého vznikl záznam média.",
    example: "iframe",
    notes: ["Není to MIME typ. Druh média popisuje standardní @type, například ImageObject nebo VideoObject."],
  },
  {
    name: "originalSource", group: "media", scope: "Objekty v associatedMedia a image", type: "řetězec",
    description: "Zdroj média před převodem na absolutní URL: první neprázdná hodnota atributu src, atributu data nebo src prvního vnořeného source[src], v tomto pořadí.",
    example: "/images/ukazka.jpg",
    notes: ["Hodnota pochází z HTML parseru, takže entity již mohou být dekódované. Výsledná absolutní adresa je v contentUrl, u iframe v embedUrl."],
  },
  {
    name: "altText", group: "media", scope: "Objekt ImageObject vytvořený z img", type: "řetězec; může být prázdný",
    description: "Hodnota atributu alt obrázku. Chybějící i prázdný atribut se exportují jako prázdný řetězec.",
    example: "Pohled na instalaci v galerii",
    notes: ["ALT se nepřekládá automaticky a může být česky i v anglickém záznamu. Viditelný figcaption se ukládá odděleně do standardního pole caption."],
  },
  {
    name: "originalHref", group: "media", scope: "Objekt vm:Link", type: "řetězec",
    description: "Původní atribut href odkazu načtený HTML parserem, před převodem na absolutní veřejnou URL.",
    example: "/koncepty/",
    notes: ["Výsledná adresa je ve standardním poli url. Původní hodnota může být relativní cesta, fragment i absolutní URL."],
  },
  {
    name: "Link", group: "media", scope: "Hodnota @type u položky vm:links", type: "vlastní třída; instance je objekt JSON",
    description: "Jeden výskyt odkazu v článku. Popisuje samotný odkaz, nikoli typ cílového dokumentu nebo osoby.",
    example: { "@type": "vm:Link", url: "https://vojtamaur.cz/koncepty/", name: "Koncepty", "vm:originalHref": "/koncepty/" },
    notes: ["url je rozvinutá adresa. name je text odkazu se sjednocenými bílými znaky a může být prázdný, například u obrázkového odkazu. vm:originalHref zachovává původní atribut."],
  },
];
