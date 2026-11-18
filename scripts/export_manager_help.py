"""Optional Czech descriptions; discovery and argument forms do not depend on this file.

Checked against the project's documentation and exporter sources on 2026-11-18.
Unknown/new exporters remain usable without adding an entry here.
"""

DOCUMENTATION_URL = "https://vojtamaur.cz/documentation/"

# Labels/fallbacks only. The interface can merge discovered section values from
# ALL_POSTS.json's articleSection or the current posts' frontmatter section.
SECTION_CHOICES = [
    ("volna-tvorba", "Volná tvorba"),
    ("vystavy", "Výstavy"),
    ("cestovani", "Cestování"),
]
SECTION_LABELS = dict(SECTION_CHOICES)

# These exporters set their section default after parsing; source-level argparse
# inspection alone therefore cannot see it. Other section exporters select all.
SECTION_DEFAULTS = {
    "export-site-mom-like.py": ["volna-tvorba"],
    "export-site-booklet.py": ["volna-tvorba"],
}
DEFAULT_SECTIONS = {
    "filter-all-posts.py": ["all"],
    "export-site-pdf.py": ["all"],
    "export-site-pdf-ultra.py": ["all"],
    "export-site-epub.py": ["all"],
    "export-site-sstv.py": ["all"],
    "export-site-markdown.py": ["all"],
    **SECTION_DEFAULTS,
}

HELP = {
    "filter-all-posts.py": {
        "title": "TXT s filtry", "group": "Text",
        "summary": "Vybere články podle jazyka, sekce a data a uloží je jako čitelný nebo kompaktní text.",
        "tips": [
            "Čte již vytvořený archiv v dist/. Po změně článků nejprve obnov webový build.",
            "Kompaktní formát ponechá média jako textové odkazy. Volba jazyka a sekce omezuje celý výstup.",
            "Automatické názvy mají čas exportu; vlastní --output se použije přesně, jak jej zadáš.",
        ],
        "docs_anchor": "manual-filtered-and-compact-exports", "output": "exports/",
    },
    "export-site-markdown.py": {
        "title": "Markdown", "group": "Text",
        "summary": "Čitelný archiv článků v Markdownu, s filtry jazyka, sekce a data.",
        "tips": [
            "Čte plný obsah z dist/ALL_POSTS.json. Neprovádí nový build ani překlad.",
            "Média jsou odkazy; obrázky a další binární soubory se do Markdownu nepřibalují.",
            "Chceš-li aktuální obsah, nejprve vytvoř standardní webový build.",
        ],
        "docs_anchor": "9613-manual-markdown-article-export", "output": "exports/",
    },
    "export-site-morse.py": {
        "title": "Morseova abeceda", "group": "Text",
        "summary": "Převede kompaktní obsah článků do textové Morseovy abecedy.",
        "tips": [
            "Výchozí jazyk both vytvoří jeden společný český a anglický soubor.",
            "Používá existující dist/ALL_POSTS.json a nepotřebuje nové Python balíčky.",
            "Normalizace do Morseovy abecedy je ztrátová; ponech také původní TXT nebo JSON.",
        ],
        "docs_anchor": "9611-morse-code-text-export", "output": "exports/",
    },
    "export-site-pdf.py": {
        "title": "PDF webu", "group": "PDF",
        "summary": "Vizuální archiv hotových webových článků s obsahem, záložkami a manifestem.",
        "tips": [
            "Použij hotový standardní webový build; dist/ po USB buildu může mít nesprávné odkazy. Obnovu řídí zvolená webová sestava manageru.",
            "Výchozí volby vytvoří jeden úplný společný český a anglický PDF archiv.",
            "JPG/PNG galerie vyžaduje právě úplné dvojjazyčné kombinované PDF a jeho manifest: bez filtrů sekce, --separate a --no-manifest.",
            "Kvalita archive ponechá původní PDF. Ostatní předvolby a volitelné PDF/A vyžadují Ghostscript.",
        ],
        "docs_anchor": "963-manual-pdf-export", "output": "exports/",
    },
    "export-site-pdf-ultra.py": {
        "title": "Ultra kompaktní PDF", "group": "PDF",
        "summary": "Hustý čtyřsloupcový archiv s malými obrázkovými náhledy a klikacími odkazy.",
        "tips": [
            "Vychází z dist/ALL_POSTS.json a místních médií hotového webového buildu.",
            "Není to snímek vzhledu webu: výchozí sazba používá čtyři sloupce a písmo 4 pt.",
            "--full-dullgpt-log ponechá celý dlouhý ukázkový výstup článku DullGPT; ostatní programy a bloky kódu jsou úplné i bez této volby.",
            "Metaweb PDF přikládá českou Ultra edici se stejným časem exportu.",
        ],
        "docs_anchor": "964-ultra-compact-pdf-export", "output": "exports/",
    },
    "export-site-mom-like.py": {
        "title": "MoM: textové PDF", "group": "PDF",
        "summary": "Velmi úsporné textové PDF inspirované Memory of Mankind.",
        "tips": [
            "Používá existující JSON archiv. Média zůstávají jako kompaktní textové odkazy.",
            "Výchozí výběr je čeština a Volná tvorba. Před spuštěním můžeš změnit jazyk i zaškrtnout více sekcí.",
            "--full-dullgpt-log ponechá celý dlouhý ukázkový výstup DullGPT.",
        ],
        "docs_anchor": "9612-mom-like-text-only-pdf-export", "output": "exports/",
    },
    "export-site-booklet.py": {
        "title": "A5 brožura k tisku", "group": "PDF",
        "summary": "Textová A5 četba a správně vyřazené A4 archy pro skládání a sešití.",
        "tips": [
            "Výchozí výběr je čeština a Volná tvorba. --section all zahrne všechny sekce.",
            "Tiskni A4 na šířku, skutečná velikost 100 %, oboustranně s otočením na krátké hraně. Další režim brožury v tiskárně vypni.",
            "--print-test vytvoří dvoulistý test pořadí. Jednotlivé tiskové soubory skládej zvlášť a seřaď podle názvu.",
            "--max-sheets určuje listy na jednu složku; hodnota 0 vytvoří jednu složku pro celý archiv.",
        ],
        "docs_anchor": "9617-a5-booklet-export", "output": "exports/",
    },
    "export-metaweb-pdf.py": {
        "title": "Metaweb PDF", "group": "PDF",
        "summary": "Dvojjazyčný Metawebový článek včetně obrazové přílohy, Ultra PDF, dokumentace a archivních podkladů.",
        "tips": [
            "Potřebuje dokončený standardní webový build; chybný USB build nejprve nahraď webovým.",
            "Pokud chybí české Ultra PDF ze stejné edice, vytvoří je automaticky s rozlišením obrázků 400 DPI.",
            "Pro navazující JPG/PNG galerii ponech zapnutý manifest a běžné automatické názvy PDF.",
            "Volitelné PDF/A a kompresní předvolby vytvářejí odvozené soubory; zkontroluj stav externí validace v manifestu.",
        ],
        "docs_anchor": "965-metaweb-archival-pdf-export", "output": "exports/",
    },
    "export-site-epub.py": {
        "title": "EPUB webu", "group": "EPUB",
        "summary": "Přizpůsobivá elektronická kniha z článků hotového webového buildu.",
        "tips": [
            "Výběr both vytvoří českou i anglickou edici. Ověř jazyk a sekce v nastavení.",
            "Kompaktní kvalita obrázků zmenší výslednou knihu; režim GIF určuje zachování animací.",
            "Nové články a opravy se projeví až po obnovení standardního webového buildu.",
        ],
        "docs_anchor": "966-manual-epub-exports", "output": "exports/",
    },
    "export-metaweb-epub.py": {
        "title": "Metaweb EPUB", "group": "EPUB",
        "summary": "Jedna dvojjazyčná Metaweb kniha s obrazovou přílohou, mapou archivu a dokumentací.",
        "tips": [
            "Čte hotový webový build; build ani aktualizaci překladů samo nespouští.",
            "Kvalita compact a zachování GIF odpovídají úspornému profilu hromadného exportu.",
            "Manifest používá příponu .epub.manifest.json, aby nekolidoval s Metaweb PDF.",
        ],
        "docs_anchor": "966-manual-epub-exports", "output": "exports/",
    },
    "export-site-images.py": {
        "title": "Galerie JPG / PNG z PDF", "group": "Obrázky",
        "summary": "Převede stránky úplného PDF do očíslované obrázkové galerie se zachováním pořadí a příloh.",
        "tips": [
            "Doporučené pořadí: aktuální webový build → nové PDF → JPG/PNG. Samotný převod obrázků PDF neobnovuje.",
            "Rozsah all používá úplné společné české a anglické PDF webu; metaweb používá celé Metaweb PDF včetně příloh.",
            "Při použití existujícího PDF se bez přesného vstupu vybere nejnovější časovaný název. Vlastní --pdf vyžaduje odpovídající manifest.",
            "JPG je menší, PNG bezeztrátové. Kvalita se týká JPG. --pages 1,6-8 vytvoří pouze náhled vybraných stránek.",
            "Potřebuje Ghostscript nebo Poppler (pdftoppm). Kód 3 znamená chybějící volitelný nástroj; kód 1 chybu dat nebo převodu.",
            "--verify ověřuje již hotovou galerii bez původního PDF. Není to nový export.",
        ],
        "docs_anchor": "9615-gallery-page-images-from-archival-pdfs", "output": "exports/vojtamaur-web-export-images-…/",
    },
    "export-site-sstv.py": {
        "title": "SSTV obrázky PNG", "group": "Obrázky",
        "summary": "Očíslované stránky článků v nativním rozlišení vybraného rádiového režimu SSTV.",
        "tips": [
            "Tento export vychází přímo z hotového HTML a médií v dist/, nikoli z PDF.",
            "Výchozí PD120 má 640 × 496 px a český obsah. PD290 používá 800 × 616 px.",
            "--max-pages omezuje celý export na náhledový počet snímků, nikoli počet článků.",
            "Generuje pouze PNG. Převod na WAV je samostatný ruční postup v dokumentaci.",
            "Po opravě chybějících obrázků obnov webový build, jinak se znovu použije starý obsah dist/.",
        ],
        "docs_anchor": "968-manual-sstv-png-export", "output": "exports/sstv/",
    },
    "export-compact-build.py": {
        "title": "Kompaktní ZIP: USB / web", "group": "Sestavení webu",
        "summary": "Vytvoří a ověří webové a offline USB archivy v limitech 40 MB a 100 MB.",
        "tips": [
            "Výchozí target both a limit all vytvoří všechny čtyři kombinace.",
            "Vytváří vlastní buildy v dočasných složkách pod exports/. Nepotřebuje předem obnovit dist/.",
            "Vyžaduje Ghostscript a Pillow s podporou AVIF i WebP. Používá existující překladovou cache.",
            "USB ZIP po rozbalení otevři přes index.html; webový ZIP patří na statický HTTP server.",
        ],
        "docs_anchor": "9618-compact-usb-and-web-zip-exports", "output": "exports/",
    },
    "export-site-json.mjs": {
        "title": "JSON-LD archiv článků", "group": "Data",
        "summary": "Strukturovaný úplný text článků a jejich vykreslené HTML z existujícího buildu.",
        "tips": [
            "Běžný webový build jej vytváří automaticky jako dist/ALL_POSTS.json.",
            "--dry-run ověří vstupy bez zápisu. --output exports/ALL_POSTS.json uloží samostatný snímek.",
            "Opětovný zápis přímo do již podepsaného dist/ změní jeho kontrolní součty. Pro zachování hotového buildu použij snímek v exports/.",
            "Články se berou z hotového HTML, nikoli z aktuálních zdrojových MDX souborů.",
        ],
        "docs_anchor": "969-json-ld-article-export-and-vocabulary", "output": "dist/ALL_POSTS.json nebo vlastní snímek v exports/",
    },
    "export-site-rosetta.mjs": {
        "title": "Rosetta: jazykové překlady", "group": "Text",
        "summary": "Vícejazyčný textový archiv přes Google Gemini Batch API se zachováním rozpracovaných výsledků.",
        "tips": [
            "Příkaz prepare / --dry-run připraví data bez API požadavků. run a submit mohou spotřebovat placené API kredity.",
            "Čte české články z dist/ALL_POSTS.json nebo přesného --input; anglický překlad webu zde nepřebírá.",
            "API klíč čte z prostředí GEMINI_API_KEY nebo GOOGLE_API_KEY. Klíč nepatří do dodatečných argumentů.",
            "Při změně vstupního snímku nebo modelu použij jiný výstupní adresář. Zachovej rosetta.json pro navazování bez opakování překladů.",
            "Po nejistém odeslání dávky nejprve ověř její existenci; neopakuj placené odeslání naslepo.",
        ],
        "docs_anchor": "9610-rosetta-multilingual-text-export", "output": "exports/rosetta/",
    },
    "export-wayback-snapshots.py": {
        "title": "Wayback archivace", "group": "Síťové nástroje",
        "summary": "Odešle veřejné adresy ze sitemap do Internet Archive; podporuje náhled výběru.",
        "tips": [
            "--dry-run ukáže výběr bez požadavků na archivaci. Ostrý běh odesílá veřejné URL službě Internet Archive.",
            "Výběr stránek a souborů se řídí --pages-only, --with-files nebo --types.",
            "Tento postup je oddělený od export-all.bat a vytváření webového buildu.",
        ],
        "docs_anchor": "1531-manual-wayback-snapshots-from-the-live-sitemap", "output": "exports/vojtamaur-web-wayback-….txt",
    },
    "generate.py": {
        "title": "Meme archiv s QR", "group": "Obrázky",
        "summary": "Meme obrázky nesoucí obnovitelné QR fragmenty úplného textového archivu.",
        "tips": [
            "Platí pro scripts/meme-archive/generate.py. Je to samostatný export mimo export-all.bat.",
            "Výchozí jazyk popisků je en; text archivu vychází z přesných bajtů dist/ALL_POSTS.txt.",
            "--count omezí počet obrázků; --continuous pokračuje do zastavení. --resume navazuje na existující nezměněnou edici.",
            "Jeden QR nestačí k obnově archivu: je potřeba dostatek fragmentů jedné edice.",
        ],
        "docs_anchor": "9616-meme-archive-random-images-with-reconstructable-qr-fragments", "output": "exports/",
    },
    "generate-gemini-capsule.mjs": {
        "title": "Gemini / Gopher", "group": "Sestavení webu",
        "summary": "Textová webová edice ve formátu Gemtext s Gopher menu z hotového webového buildu.",
        "tips": [
            "Vyžaduje standardní webové dist/, nikoli výstup po USB buildu.",
            "Při opakovaném spuštění nahrazuje celou výstupní složku dist-gemini/ a vrací ji do nepodepsaného stavu.",
            "Tento Gemini je publikační protokol; nesouvisí s překladovým API Rosetta.",
        ],
        "docs_anchor": "967-gemini-capsule-and-gopher-map-generation", "output": "dist-gemini/",
    },
    "generate-all-posts.mjs": {
        "title": "Obnova indexu webu", "group": "Příprava webu",
        "summary": "Z hotového HTML znovu vytvoří ALL_POSTS.txt, JSON-LD a textovou záchrannou stránku 404.",
        "tips": [
            "Běžný webový build tento krok provádí automaticky po anglickém postprocessingu.",
            "Samostatné spuštění mění soubory v dist/. Kontrolní součty a podpis takového buildu je potřeba obnovit.",
        ],
        "docs_anchor": "96-plain-text-export-of-all-posts", "output": "dist/",
    },
    "generate-source-bundle.mjs": {
        "title": "Zdrojový ZIP k rekonstrukci", "group": "Data",
        "summary": "Zabalí zdroj webu, manifest médií a nástroj k jejich obnovení do rekonstruovatelného archivu.",
        "tips": [
            "Běžný webový i USB build jej vytváří automaticky. ZIP obsahuje zdroj, rekonstrukční pokyny a kontrolní součty médií.",
            "Velká média se obnovují podle manifestu; nepovažuj ZIP za úplnou samostatnou kopii všech souborů webu.",
            "Vedle source/vojtamaur-web-source.zip se vytváří také JPEG/ZIP nosič v images/kurt-godel-rat.jpg.",
            "Samostatné spuštění přepíše příslušné soubory ve vybraném buildu. Poté obnov jeho integritu a případný podpis.",
            "Vlastní argument může určit cílový build jako první hodnotu, např. dist-arweave. Výchozí je dist.",
        ],
        "docs_anchor": "962-reconstructable-source-package", "output": "dist/source/vojtamaur-web-source.zip",
    },
    "generate-link-graph.mjs": {
        "title": "Graf odkazů: GraphML / SVG / JSON", "group": "Data",
        "summary": "Vytvoří graf propojení stránek hotového webu a jeho interaktivní stránku.",
        "tips": [
            "Běžný webový i USB build jej vytváří automaticky z hotového místního HTML; internet neprohledává.",
            "Výstup obsahuje interaktivní stránku, vektorový SVG, GraphML a JSON se stejnými uzly a hranami.",
            "Samostatná obnova mění soubory v buildu. Poté obnov jeho integritu a případný podpis.",
            "Jde o volitelný generátor: může skončit úspěšným návratovým kódem i při upozornění, že graf nevznikl. Zkontroluj log a výsledné soubory.",
            "Vlastní argument může určit jinou složku buildu jako první hodnotu; výchozí je dist.",
        ],
        "docs_anchor": "9614-build-time-website-link-graph", "output": "dist/link-graph/",
    },
}

# Build entries have no unique exporter filename; the GUI can look them up by npm name.
BUILD_HELP = {
    "build:web": {
        "title": "Online web", "group": "Sestavení webu",
        "summary": "Klasické sestavení webu pro hosting podle postupu zvoleného v Přípravě webu.",
        "tips": [
            "Vytvoří standardní web do dist/, včetně základních archivních souborů a kontrolních součtů. Nic automaticky nenahrává na hosting.",
            "Postup zvol na kartě Příprava webu: build:web je běžná varianta bez nových překladů a podpisu; výchozí build:web:translate:signed doplní chybějící překlady a podepíše web i Gemini.",
            "Tato položka sestaví web i bez zaškrtnuté společné volby obnovy. Potřebné přístupy platí pouze pro otevřené okno manageru.",
            "Při hromadném výběru proběhne před ostatními exporty a nahradí jejich samostatnou přípravu webu. Sestavy zachovávají ručně zadané pořadí.",
            "Online a USB build sdílejí dist/. Pokud zaškrtneš oba, USB proběhne poslední a nahradí dist/ offline verzí.",
        ],
        "docs_anchor": "93-web-build", "output": "dist/",
    },
    "build:usb:translate:signed": {
        "title": "Offline web (USB)", "group": "Sestavení webu",
        "summary": "Úplná offline verze webu vytvořená podle vybraného postupu sestavení.",
        "tips": [
            "Nahrazuje dist/ a upravuje odkazy pro otevírání index.html přímo z disku, bez webového serveru.",
            "Použije USB variantu postupu vybraného v Přípravě webu. Výchozí volba doplní chybějící anglické překlady přes DeepL a podepíše build; jiná volba může překlad nebo podpis vynechat.",
            "Přístupové údaje potřebné pro vybraný postup zadej v Přípravě webu nebo je předej z prostředí.",
            "Dočasný API klíč a GNUPGHOME platí jen pro otevřené okno manageru; do nastavení a sestav se neukládají.",
            "Před následným PDF, EPUB nebo Gemini exportem obnov standardní web zvolenou webovou sestavou manageru.",
            "Velikost offline webu není omezena; pro ZIP do 40 nebo 100 MB vyber Kompaktní ZIP: USB / web.",
        ],
        "docs_anchor": "95-portable-file-based-build", "output": "dist/",
    },
    "build:usb:translate": {
        "title": "Offline web (USB)", "group": "Sestavení webu",
        "summary": "Úplný offline web s doplněním chybějících anglických překladů.",
        "tips": [
            "Nahrazuje dist/ a upravuje HTML i odkazy pro přímé otevírání souborů z disku.",
            "Chybějící překlady doplní přes DeepL. API klíč můžeš zadat do dočasných údajů v Přípravě webu; tato varianta build nepodepisuje.",
            "Pro následný PDF, EPUB nebo Gemini export nejprve obnov standardní web zvolenou webovou sestavou manageru.",
        ],
        "docs_anchor": "95-portable-file-based-build", "output": "dist/",
    },
    "build:usb": {
        "title": "Offline web (USB)", "group": "Sestavení webu",
        "summary": "Úplný web pro procházení přímo z disku přes index.html, bez limitu kompaktního ZIP exportu.",
        "tips": [
            "Vytváří celý offline web do dist/ a nahrazuje tam předchozí build. Upravuje HTML a odkazy pro file://.",
            "Tento běh neobnovuje překladovou cache; použije existující překlady a může zachovat české fallbacky.",
            "Před následným PDF, EPUB nebo Gemini exportem znovu sestav standardní web pomocí zvolené webové sestavy manageru.",
            "Chceš-li malý ZIP v limitu 40 nebo 100 MB, vyber samostatný Kompaktní ZIP: USB / web.",
        ],
        "docs_anchor": "95-portable-file-based-build", "output": "dist/",
    },
    "build:usb:strict": {
        "title": "Offline web (USB, úplné překlady)", "group": "Sestavení webu",
        "summary": "Úplný offline web s kontrolou dostupnosti již uložených anglických překladů.",
        "tips": [
            "Nahrazuje dist/ offline verzí a upravuje odkazy pro otevírání souborů přímo z disku.",
            "Strict vyžaduje kompletní existující překladovou cache; chybějící překlady nepřekládá a běh skončí chybou.",
            "Pro navazující PDF, EPUB nebo Gemini export obnov standardní web pomocí zvolené webové sestavy manageru.",
            "Výsledný web není omezen na 40 nebo 100 MB; pro tyto limity použij Kompaktní ZIP.",
        ],
        "docs_anchor": "95-portable-file-based-build", "output": "dist/",
    },
    "build:web:strict": {
        "title": "Aktuální web (úplné překlady)", "group": "Sestavení webu",
        "summary": "Znovu sestaví standardní web a jeho základní archivní soubory pro navazující exporty.",
        "tips": [
            "Nahrazuje obsah dist/. Použij po změně článků, médií nebo po předchozím USB buildu.",
            "Vyžaduje existující anglickou překladovou cache; chybějící překlady nedoplňuje přes API.",
            "Součástí jsou TXT, JSON-LD, zdrojový ZIP, graf odkazů a kontrolní součty. Samostatné PDF/EPUB/obrázkové exporty spouštěj potom.",
            "Tato varianta vytváří nepodepsaný build. Podpis se řídí běžným postupem projektu.",
        ],
        "docs_anchor": "93-web-build", "output": "dist/",
    },
    "build:arweave": {
        "title": "Arweave / Permaweb", "group": "Sestavení webu",
        "summary": "Z hotového nebo nově sestaveného webu připraví odvozenou verzi s odkazy pro Arweave.",
        "tips": [
            "Volitelná obnova webu použije zvolený postup v Přípravě webu. Bez obnovy čte stávající standardní dist/, které nesmí pocházet z USB buildu.",
            "Odvozená verze vzniká v dist-arweave/ s vlastními kontrolními součty. Je-li zvolen podepisovaný webový postup, manager podepíše také Arweave verzi.",
            "Výsledné soubory lze následně předat běžnému nástroji pro nahrání na Arweave.",
        ],
        "docs_anchor": "97-arweave--permaweb-build", "output": "dist-arweave/",
    },
    "export:txt": {
        "title": "ALL_POSTS.txt", "group": "Text",
        "summary": "Uloží přesnou kopii hotového ALL_POSTS.txt do nové časované edice v exports/.",
        "tips": [
            "Jde o samostatný textový soubor se stejnými bajty jako v aktuálním dist/ALL_POSTS.txt. Nevytváří nový JSON a nemění podepsaný build.",
            "Chceš-li zahrnout poslední úpravy webu, zapni před exportem obnovu zvolenou standardní webovou sestavou.",
            "Pro výběr konkrétního jazyka, více sekcí nebo kompaktní podobu použij samostatný TXT s filtry.",
            "Kanonický TXT zachovává podobu hotového buildu včetně případných zkrácení dlouhých bloků. Plný strukturovaný obsah najdeš v JSON-LD exportu.",
        ],
        "docs_anchor": "96-plain-text-export-of-all-posts", "output": "exports/ALL_POSTS-….txt",
    },
    "export:json": {
        "title": "ALL_POSTS.json", "group": "Data",
        "summary": "Uloží přesnou kopii hotového ALL_POSTS.json do nové časované edice v exports/.",
        "tips": [
            "Kopíruje aktuální JSON-LD snímek článků včetně úplného textu a HTML. JSON uvnitř hotového buildu nepřepisuje a nemění jeho podpis.",
            "Obnovu zdrojového webu můžeš zapnout před exportem; použije se zvolená standardní webová sestava manageru.",
            "Obrázky a další média zůstávají odkazy. Samotný JSON není samostatná kopie všech souborů webu.",
            "Pro čtení v prostém textu vyber samostatný TXT archiv nebo TXT s filtry.",
        ],
        "docs_anchor": "969-json-ld-article-export-and-vocabulary", "output": "exports/ALL_POSTS-….json",
    },
}

# Optional labels for common dynamically discovered form fields.
LABELS = {
    "--lang": "Jazyk", "--language": "Jazyk", "--section": "Sekce",
    "--scope": "Rozsah galerie", "--format": "Formát", "--output": "Výstupní soubor / složka",
    "--output-dir": "Výstupní složka", "--input": "Vstupní soubor", "--pdf": "Vlastní zdrojové PDF",
    "--source-manifest": "Manifest zdrojového PDF", "--project-root": "Kořen projektu", "--dist": "Složka hotového webu", "--content": "Složka zdrojových článků",
    "--timestamp": "Čas edice", "--no-timestamp": "Použít původní názvy bez času (může přepsat starší export)",
    "--dpi": "Rozlišení (DPI)", "--image-dpi": "Rozlišení obrázků (DPI)", "--quality": "Kvalita JPG",
    "--jpeg-quality": "Kvalita JPEG", "--max-edge": "Nejdelší hrana (px)", "--pages": "Náhled: čísla stránek",
    "--max-pages": "Náhled: nejvýše snímků", "--mode": "Režim SSTV", "--paper": "Formát papíru",
    "--margin": "Okraje", "--font-size": "Velikost písma", "--font": "Soubor písma", "--bold-font": "Soubor tučného písma",
    "--batch-size": "Obrázků v jednom seznamu pro nahrání", "--max-file-mb": "Upozornit nad velikost (MiB)",
    "--backend": "Nástroj převodu PDF", "--ghostscript": "Cesta ke Ghostscriptu", "--pdftoppm": "Cesta k Poppleru",
    "--pdf-quality": "Kvalita PDF", "--pdfa": "Vytvořit také PDF/A", "--compress": "Předvolba komprese",
    "--target-size": "Cílová velikost", "--icc-profile": "Barevný profil ICC", "--verapdf": "Cesta k veraPDF",
    "--separate": "Samostatné soubory pro jednotlivé články", "--include-drafts": "Zahrnout koncepty",
    "--allow-missing": "Přeskočit chybějící stránky", "--no-manifest": "Nevytvářet manifest",
    "--build-command": "Příkaz pro obnovení webu", "--site-url": "Veřejná adresa webu", "--media": "Vzhled pro obrazovku / tisk",
    "--timeout-ms": "Časový limit načtení (ms)", "--wait-ms": "Dodatečné čekání (ms)", "--timeout": "Časový limit (s)",
    "--no-footer": "Bez spodního popisku", "--verify": "Ověřit existující galerii", "--image-quality": "Kvalita obrázků",
    "--gif-mode": "Zacházení s animacemi GIF", "--keep-uncompressed": "Zachovat také nekomprimované PDF",
    "--target": "Web / offline USB", "--limit": "Limit", "--dry-run": "Pouze náhled / kontrola",
    "--max-sheets": "Nejvýše A4 listů na složku", "--print-test": "Vytvořit zkušební tisk",
    "--full-dullgpt-log": "Ponechat celý ukázkový výstup DullGPT", "--slug": "Konkrétní článek (slug)",
    "--date-from": "Od data", "--date-to": "Do data", "--from-date": "Od data", "--to-date": "Do data", "--count": "Počet obrázků", "--continuous": "Generovat do zastavení",
    "--resume": "Navázat na složku edice", "--seed": "Semínko náhodného výběru", "--languages": "Cílové jazyky",
    "--model": "Překladový model", "--poll-seconds": "Interval kontroly dávky (s)", "--list-languages": "Vypsat jazyky",
    "--retry-failed": "Znovu odeslat neúspěšné překlady (může stát API kredity)",
    "--pages-only": "Jen webové stránky", "--with-files": "Stránky i soubory", "--types": "Typy souborů",
}

# Each hash was checked against the current public documentation HTML. Expose a
# complete URL so every help button can jump directly to its export's section.
for _entry in [*HELP.values(), *BUILD_HELP.values()]:
    if _entry.get("docs_anchor"):
        _entry["docs_url"] = DOCUMENTATION_URL + "#" + _entry["docs_anchor"]
del _entry
