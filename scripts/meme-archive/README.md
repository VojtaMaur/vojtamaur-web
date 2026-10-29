# Meme archive

Samostatný ručně spouštěný export existujícího webu. Čte `dist/ALL_POSTS.txt`,
`dist/ALL_POSTS.json` a lokální rastrové obrázky v `public/images/`, včetně obrázků,
které nejsou přiřazené k článkům. Nespouští build, překlady ani síťové služby.
Buildy a `export-all.bat` tento nástroj nespouštějí.

## Instalace a použití

Python 3.11+ a Node.js 18+ (Node už používá web). Závislosti exportu jsou oddělené
od npm balíčků webu; žádný kompilátor není potřeba. Doporučená izolovaná instalace
na Windows z kořene repozitáře:

```powershell
python -m venv exports/.meme-venv
exports/.meme-venv/Scripts/python -m pip install -r scripts/meme-archive/requirements.txt -r scripts/meme-archive/requirements-decode.txt
exports/.meme-venv/Scripts/python scripts/meme-archive/generate.py --verify-qr
```

Na Linuxu/macOS má virtuální prostředí spustitelný soubor `bin/python`.
Bez ověřování při generování stačí `requirements.txt`. Pro dekódování z obrázků
stačí `requirements-decode.txt`; Segno dekodér nepotřebuje. Dekódování surových
`.ma` paketů používá jen standardní knihovnu Pythonu a Node. Při běhu se nic
nestahuje. Vestavěné `raptorq.wasm` (asi 200 KiB) obsahuje skutečný RaptorQ,
nikoli vlastní náhradu algoritmu. Instalace balíčku `raptorq` přes pip není nutná.

```powershell
python scripts/meme-archive/generate.py --count 20
python scripts/meme-archive/generate.py --language EN --count 20
python scripts/meme-archive/generate.py --language CS --count 20
python scripts/meme-archive/generate.py --language EN+CS --count 20
python scripts/meme-archive/generate.py --continuous --interval 0.25
python scripts/meme-archive/generate.py --seed moje-edice --verify-qr
python scripts/meme-archive/generate.py --resume exports/vojtamaur-web-export-meme-archive-TIMESTAMP --count 100
python scripts/meme-archive/decode.py exports/vojtamaur-web-export-meme-archive-TIMESTAMP/memes --output exports/ALL_POSTS.recovered.txt
python -m unittest discover -s scripts/meme-archive -p "test_*.py"
```

`TIMESTAMP` nahraď skutečným názvem edice. Dostupné jsou také npm příkazy
`export:meme`, `decode:meme` a `test:meme`, používající `python` z aktuálního
prostředí. Při použití izolovaného prostředí výše lze volat přímo jeho Python.

## Výchozí hodnoty

* Jazyk popisků a patičky: **EN**. `--language EN`, `--language CS` nebo
  `--language EN+CS` (také `--lang`, velikost písmen nerozhoduje) vybírá
  jazyk podle `inLanguage` článků; TXT fallback čte `LANGUAGE` z hlaviček.
  Anglický HTML katalog vynechává bloky označené jako nepřeložené
  (`translate="no"`, `notranslate`, `data-i18n="protect"`) a bloky s jiným `lang`.
  EN+CS dovoluje nezávislý výběr úryvků z obou jazyků a má dvojjazyčnou patičku.
  Pokud vybraný jazyk ve vstupním katalogu chybí, export skončí s jasnou chybou.
  Jazyk popisků nemění QR archiv: vždy obsahuje celý původní `ALL_POSTS.txt`.
* 512 bytů RaptorQ symbolu + 41 bytů obálky v jednom QR, byte mode, ECC M.
* PNG 1080 px široké, fotografie 810 px vysoká, samostatná bílá patička.
  QR verze 18 má 89 modulů, čtyřmodulový tichý okraj a 4 px/modul, celkem
  388 × 388 px. Výška výchozího memu je 1230 px.
  Vlevo dole je stručné vysvětlení fountain kódu a obnovy textového archivu
  z dostatečného množství memů stejné edice. Při malé šířce se celý text
  přesune pod QR; výška patičky se podle potřeby zvětší, text se neořezává.
  Patička ukazuje skutečné minimum `K = ceil(F/T)` různých memů podle velikosti
  komprimovaného přenášeného objektu a QR symbolu a praktický odhad `K + 2×Z`
  (dva opravné symboly navíc na blok). Pro aktuální archiv při 512 B/symbol
  vychází „~259+ různých memů (minimum 257)“. Nejde o počet právě vygenerovaných
  obrázků ani o pevně zadané číslo. U více bloků je nutné mít dost fragmentů
  každého bloku; duplicity se nepočítají a odhad není zárukou pro libovolný výběr.
* Počet memů: součet `ceil(1.15 × K_b) + 8` přes zdrojové bloky. Pro běžný
  archiv o přibližně 131 kB jde o 304 memů. Jde o rezervu; úspěch po ztrátách
  závisí na dostupných symbolech každého bloku, nikoli jen na celkovém počtu.
* Nezávislý výběr obrázku, horního textu a dolního textu. Horní, dolní nebo oba
  texty mají stejnou pravděpodobnost. Úryvky mají nejvýše 120 znaků.
* `kurt-godel-rat.jpg` má relativní váhu 1.25, ostatní obrázky 1. U 836 obrázků
  se jeho pravděpodobnost zvýší z asi 0.120 % na 0.149 % na jeden výběr.
* Náhodný seed založí novou edici. `--seed` umožňuje opakovat tutéž edici.

Volby: `--symbol-size 64..1024`, `--ecc M|Q|H`, `--qr-scale` (nejméně 4),
`--width`, `--image-height`, `--max-text-chars 20..240`, `--rat-weight`,
`--font`, `--input`, `--timestamp`, `--project-root`. Větší QR může vyžadovat
větší šířku memu; neplatná geometrie skončí chybou. `--verify-qr` kontroluje
každý hotový PNG z jeho pixelů před zapsáním do deníku.

## Edice, reprodukce a resume

Výstup je nová složka
`exports/vojtamaur-web-export-meme-archive-YYYY-MM-DD_HH-MM-SS-ffffff/`.
Timestamp a `VOJTAMAUR_EXPORT_TIMESTAMP` používají stávající
`scripts/export_naming.py`. Existující složka se nikdy nepřepisuje.

`manifest.json` obsahuje seed, 128bitové ID edice, kryptografické otisky vstupů,
parametry a počty symbolů. `catalog.json` zmrazí texty, pořadí obrázků a jejich
SHA-256; `archive.rq` zmrazí objekt určený pro RaptorQ. Obrázky se do katalogu
nekopírují. Změna vybraného obrázku nebo fontu při resume skončí chybou, nové
články a změny `dist/` už zmrazenou edici neovlivní. `memes.jsonl` uchovává
původ obou textů i obrázku a otisk každého PNG. `state.json` slouží jako přehled,
autoritativní je potvrzený deník.

Stejný seed, vstupní archiv, katalog a nastavení včetně **bytů fontu** vytvoří
stejné ID edice a stejné pakety. Pro naprosto stejné PNG používej i stejné verze
Pythonu, Pillow a Segno; jejich renderování a komprese se mezi verzemi mohou
změnit. Pro opakování po úpravách webu zachovej katalog, původní obrázky, font
a `archive.rq`. Obnova při relokaci fontu přijímá `--font` s identickými byty.

`--resume` pokračuje za posledním potvrzeným memem a `--count N` přidá N memů.
Ctrl+C ukončí generování; nepotvrzený poslední PNG se při resume přegeneruje.
Neúplný poslední řádek deníku se zálohuje a zahodí. Chybějící nebo změněný
potvrzený PNG je chyba, stejně jako souběžné generování do jedné složky.
Ostatní nastavení edice nelze při resume měnit.

Jazyk je součástí neměnných nastavení a ID nové edice. Při resume se nemění
ani neodvozuje z nového výchozího EN. Starší edice 1.0 lze dál obnovit se
stejnou původní patičkou a katalogem; nové jazykové edice používají verzi 1.1.

Pakety se vybírají po blocích round-robin; nejprve systematické zdrojové symboly,
poté nové opravné symboly. `--start-index` dovoluje začít novou složku dál v téže
edici (např. jen opravné symboly). RaptorQ má konečný 24bitový ESI: kontinuální
režim pokračuje až do Ctrl+C, zaplnění disku nebo vyčerpání 16 777 216 symbolů
**na blok**; pak skončí s jasnou chybou a nikdy tiše neopakuje ID.

## Dekódování a archivace

Každá edice přikládá samostatnou složku `decoder/` se zdroji, WASM, závislostmi
a specifikací [FORMAT.md](FORMAT.md). Pro obnovu stačí dostatek obrázků a tyto
nástroje; manifest, deník, pořadí souborů ani původní web nejsou potřeba.
Dekodér čte přímo binární obsah QR, nikoli jeho textovou reprezentaci nebo
metadata PNG. Umí adresáře, jednotlivé PNG/JPEG/WebP a surové `.ma` pakety.

Duplicitní symboly ignoruje, platné různé edice odmítne; `--edition HEX` vybere
jednu edici ze směsi. Poškozené QR zahodí s upozorněním. Soubor vznikne až po
úspěšné rekonstrukci a kontrole gzip CRC a úplného SHA-256 původního TXT;
existující výstup vyžaduje `--force`. Nedostatek symbolů vrací stav 2.
Výchozí limity přenosu a rozbaleného textu jsou 64 MiB a lze je výslovně upravit
volbami `--max-transfer-bytes` a `--max-output-bytes` (vestavěné jádro má limit
přenosu 64 MiB). Kontrolní součty odhalují chyby, nejsou podpisem autora.

Originální PNG zachovej: chatovací aplikace, tisk, rozmazání, ořez a komprese
mohou QR poškodit. Čitelnost přes sdílecí službu ověř z výsledných souborů.
Memy jsou archivní reprezentace díla Vojty Maura, https://vojtamaur.cz/;
pravidla užití obsahu zůstávají uvedená v hlavním README repozitáře.

## RaptorQ a sestavení přenositelného jádra

Jádro používá nezměněné zdroje `cberner/raptorq` 2.0.1 (Apache-2.0,
licence v `RAPTORQ-LICENSE.txt`). Malý vlastní ABI adaptér je v `wasm-adapter/`.
Standard je [RFC 6330](https://www.rfc-editor.org/rfc/rfc6330.html), gzip je
[RFC 1952](https://www.rfc-editor.org/rfc/rfc1952.html). Implementace:
[cberner/raptorq](https://github.com/cberner/raptorq).

Pro vlastní nové sestavení nainstaluj Rust s cílem `wasm32-unknown-unknown`
a spusť `python scripts/meme-archive/wasm-adapter/build.py`. Tento **volitelný**
krok stáhne přesně připnutý archiv zdrojů a ověří jeho SHA-256; běžný export
ani dekodér ho nespouští. Proměnná `MEME_ARCHIVE_CARGO` může určit jiný Cargo.
