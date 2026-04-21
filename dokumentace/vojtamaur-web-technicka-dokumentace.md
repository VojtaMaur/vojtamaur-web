# Technická dokumentace projektu `vojtamaur-web`

## 1. Přehled projektu

`vojtamaur-web` je statický web postavený na Astro. Obsah je spravován jako soubory v repozitáři a při buildu je převáděn do statického výstupu. Projekt nepoužívá CMS ani databázi. Zdrojem pravdy je repozitář se zdrojovým kódem, obsahem a statickými aktivy.

Projekt je rozdělen do těchto hlavních obsahových částí:

- **Volná tvorba**
- **Výstavy**
- **Cestování**
- **Propagační videa**
- **O mně**
- **Kontakt**

Architektura je založena na kombinaci těchto prvků:

- **Astro** jako statický site generator
- **MDX** jako autorský formát pro obsah
- **Content Collections** pro validaci a typování metadat
- **Komponenty** pro opakovaně používané bloky obsahu a layouty
- **Statická aktiva v `public/`** pro obrázky, PDF, demoverze a další soubory

Tento model usnadňuje verzování obsahu, archivaci build výstupů a případnou migraci projektu na jiné prostředí bez závislosti na databázovém runtime.

---

## 2. Struktura projektu

### 2.1 Adresářová struktura

Aktuální struktura projektu je rozdělena na dvě hlavní části:

- `src/` – zdrojové soubory projektu
- `public/` – statická aktiva kopírovaná při buildu beze změn

Poskytnutá struktura:

```text
public/
  demos/
  files/
  images/

src/
  components/
  content/
  content.config.ts
  env.d.ts
  layouts/
  lib/
  pages/
  styles/
```

### 2.2 Význam hlavních adresářů

#### `public/`
Obsahuje statické soubory, které se při buildu pouze zkopírují do výstupu:

- `public/images/` – obrázky článků, thumbnails, další vizuální obsah
- `public/files/` – PDF a další stažitelné nebo embedované soubory
- `public/demos/` – samostatné HTML/JS demoverze a legacy statické stránky

#### `src/content/`
Obsahové soubory projektu. V aktuální konfiguraci se používají především:

- `src/content/posts/` – články
- `src/content/videos/` – metadata k propagačním videím

#### `src/components/`
Znovupoužitelné komponenty pro práci s obsahem a výpisy:

- `ImageFigure.astro`
- `MediaRow.astro`
- `Embed.astro`
- `PostTileGrid.astro`
- `Header.astro`

#### `src/layouts/`
Layouty pro jednotlivé typy stránek:

- `BaseLayout.astro`
- `PostLayout.astro`
- případně specializované layouty jako `TravelLayout.astro` a `ExhibitionLayout.astro`

#### `src/pages/`
Routy aplikace. Zahrnuje homepage, kategoriální stránky a dynamický routing článků.

#### `src/styles/`
Globální a případně další stylové soubory.

#### `src/lib/`
Pomocné utility a pomocná logika používaná napříč projektem.

---

## 3. Klíčové konfigurační soubory

### `astro.config.mjs`

Projekt používá dva build režimy. Konfigurace přepíná chování podle proměnné `BUILD_TARGET`. V běžném webovém buildu používá `trailingSlash: "always"` a `build.format: "directory"`. V přenositelném souborovém buildu používá `trailingSlash: "never"` a `build.format: "file"`.

Tím vznikají dva odlišné typy výstupu:

- **webový build** – vhodný pro běžný hosting
- **přenositelný souborový build** – vhodný například pro offline použití, archivaci nebo přenos na externím médiu

### `package.json`

Základní workflow projektu:

```bash
npm run dev
npm run build:web
npm run preview
npm run build:usb
```

Význam skriptů:

- `npm run dev` – spustí vývojový server Astro
- `npm run build:web` – vytvoří běžný produkční build
- `npm run preview` – lokální náhled buildu
- `npm run build:usb` – vytvoří přenositelný souborový build a spustí dodatečný postprocessing

### `content.config.ts`

Definuje content collections a schémata metadat pomocí Zod validace. Projekt používá kolekce minimálně pro:

- `posts`
- `videos`

---

## 4. Content Collections

### 4.1 Kolekce `posts`

Články jsou ukládány jako `.mdx` soubory a validovány přes schéma v `content.config.ts`.

Povinná metadata:

- `title`
- `slug`
- `section`
- `date`
- `thumbnail`
- `thumbnailAlt`

Volitelná metadata:

- `excerpt`
- `draft`

Sekčně specifická metadata:

#### Pro `section: "vystavy"`
- `dateFrom`
- `dateTo`
- `city`
- `venue`
- `exhibition`

#### Pro `section: "cestovani"`
- `year`
- `media`

### 4.2 Kolekce `videos`

Používá se pro sekci Propagační videa. Obsahuje metadata externích YouTube videí. Typicky:

- `title`
- `url`
- `thumbnail`
- `thumbnailAlt`
- `draft`

---

## 5. Layout logika

### 5.1 `PostLayout.astro`

`PostLayout.astro` obaluje obsah článku do hlavního layoutu a vytváří společný wrapper pro článkové stránky.

### 5.2 Dynamický routing přes `[slug].astro`

Soubor `[slug].astro` je centrální routa pro obsah z kolekce `posts`. Zajišťuje:

- načtení článků přes `getCollection`
- generování statických cest podle `slug`
- render konkrétního obsahu přes `render(post)`

### 5.3 Podmíněné renderování podle sekce

Různé sekce mají odlišné meta bloky:

- **Volná tvorba** – název + formátovaný měsíc a rok
- **Výstavy** – název + datum konání + město + místo + název výstavy
- **Cestování** – název + doplňková metadata typu médium

### 5.4 Formátování datumu

U sekce Volná tvorba se datum zobrazuje jako měsíc a rok, například:

```text
duben 2026
```

Interně se pro řazení stále používá standardní datumové pole `date`.

### 5.5 Řazení

Články se řadí podle `date`. To platí i v případech, kdy se v UI nezobrazuje přesný den, ale pouze měsíc a rok.

---

## 6. Přidávání a správa obsahu

### 6.1 Přidání nového článku

Nový článek se přidává vytvořením nového `.mdx` souboru do:

```text
src/content/posts/
```

Soubor musí obsahovat validní frontmatter podle schématu `posts`.

### 6.2 Povinná a volitelná metadata

#### Společná povinná metadata
- `title`
- `slug`
- `section`
- `date`
- `thumbnail`
- `thumbnailAlt`

#### Společná volitelná metadata
- `excerpt`
- `draft`

#### Metadata pro Výstavy
- `dateFrom`
- `dateTo`
- `city`
- `venue`
- `exhibition`

#### Metadata pro Cestování
- `year`
- `media`

### 6.3 Thumbnails

Každý článek používá:

- `thumbnail` – cesta k náhledu
- `thumbnailAlt` – alternativní text náhledu

Thumbnails jsou používány ve výpisech článků, na homepage i v jednotlivých sekcích.

### 6.4 `draft`

Pole `draft: true` vyřadí článek z veřejného výpisu i z generovaných cest. Slouží pro rozpracovaný nebo dočasně skrytý obsah.

### 6.5 Používané komponenty v obsahu

Obsah článků může kromě běžného Markdownu používat i komponenty:

- `ImageFigure`
- `MediaRow`
- `Embed`

Tyto komponenty je potřeba v MDX souboru explicitně importovat.

### 6.6 Ukázkový frontmatter

#### Volná tvorba

```mdx
---
title: "Název článku"
slug: "nazev-clanku"
section: "volna-tvorba"
date: 2026-04-19
thumbnail: "/images/nazev-clanku-nahled.jpg"
thumbnailAlt: "Náhled článku"
excerpt: ""
draft: false
---
```

#### Výstavy

```mdx
---
title: "Recamánova struktura"
slug: "vystavy-recamanova-struktura"
section: "vystavy"
date: 2024-01-01
thumbnail: "/images/vystavy-recamanova-struktura-nahled.jpg"
thumbnailAlt: "Recamánova struktura"
dateFrom: "1. 1. 2024"
dateTo: "31. 1. 2024"
city: "Jindřichův Hradec"
venue: "Muzeum fotografie a moderních obrazových médií"
exhibition: "Obrazy nad čísly"
draft: false
---
```

#### Cestování

```mdx
---
title: "Itálie - Benátky 2019"
slug: "cestovani-italie-benatky-2019"
section: "cestovani"
date: 2019-01-01
thumbnail: "/images/cestovani-italie-benatky-2019-nahled.jpg"
thumbnailAlt: "Itálie - Benátky 2019"
year: "2019"
media: "Fotografie"
draft: false
---
```

### 6.7 Reprezentativní ukázka obsahu

Jako reprezentativní příklad MDX článku byl poskytnut soubor:

```text
recamanova-posloupnost-zelvi-grafice.mdx
```

Tento soubor je vhodný jako referenční ukázka struktury obsahu, frontmatteru a použití komponent.

---

## 7. Komponenty médií

### 7.1 `ImageFigure.astro`

Komponenta pro samostatné obrázky s podporou těchto parametrů:

- `src`
- `alt`
- `caption`
- `width`
- `align`
- `bordered`
- `link`

Podporované varianty šířky:

- `full`
- `half`
- `one-third`

Podporované zarovnání:

- `left`
- `center`
- `right`

Komponenta může podle konfigurace také otevřít obrázek po kliknutí.

### 7.2 `MediaRow.astro`

Komponenta pro řádkové skládání více položek. Podporuje typy:

- `image`
- `pdf`
- `text`

Použití:

- galerie více obrázků
- kombinace obrázků a PDF
- kombinace vizuálních a textových bloků v jednom gridu

Komponenta podporuje i variantu s rámečkem.

### 7.3 `Embed.astro`

Obecný wrapper pro iframe embed obsah. Používá se například pro:

- YouTube
- Google Maps
- Sketchfab
- lokální HTML demoverze

Podporované parametry:

- `src`
- `ratio`
- `kind`
- `width`
- `align`

### 7.4 Edge cases

#### PDF v `MediaRow`
Při kolapsu gridu může PDF iframe vyžadovat speciální úpravu výšky nebo poměru stran. To bylo řešeno pomocí CSS pro `.media-row__pdf`.

#### Responsive kolaps gridu
Výpisy a media layouty mají více stavů podle šířky. Některé prvky, například tlačítko „zobrazit vše“ nebo PDF embed, vyžadovaly samostatné doladění chování pro 3, 2 a 1 sloupec.

---

## 8. Homepage architektura

Homepage skládá obsah z více částí webu.

### 8.1 Dynamické načítání obsahu
Každá hlavní sekce na homepage zobrazuje posledních 9 položek:

- Volná tvorba
- Výstavy
- Cestování

### 8.2 Tlačítko „zobrazit vše“
Pokud daná sekce obsahuje více položek než je počet zobrazený na homepage, přidá se dlaždice typu „zobrazit vše“.

### 8.3 Propagační videa
Sekce Propagační videa používá podobný vizuální model jako článkové výpisy, ale položky vedou na externí YouTube URL. Výpis je založen na kolekci `videos`.

### 8.4 Navigační nadpisy sekcí
Nadpisy sekcí na homepage jsou klikatelné a slouží jako rychlá navigace do příslušných kategorií nebo na externí playlist.

### 8.5 O mně a Kontakt
Homepage obsahuje i specializované obsahové bloky mimo klasický systém článků:

- blok O mně s textem a Sketchfab iframe
- blok Kontakt s telefonem a e-mailem

---

## 9. Vývoj a běžný workflow

### 9.1 Lokální vývoj

```bash
npm install
npm run dev
```

Astro standardně spouští lokální server na `http://localhost:4321/` a průběžně reaguje na změny v projektu.

### 9.2 Praktická poznámka k dev serveru

V tomto konkrétním projektu se občas stává, že po přidání nového `.mdx` souboru se nový článek v dev režimu neobjeví správně, případně dočasně nahradí jiný článek ve výpisu. Restart vývojového serveru to obvykle okamžitě opraví.

Doporučený troubleshooting krok:

```bash
Ctrl + C
npm run dev
```

### 9.3 Webový build

```bash
npm run build:web
```

Vytvoří standardní build určený pro běžné nasazení na webový hosting.

### 9.4 Náhled buildu

```bash
npm run preview
```

Používá se pro lokální ověření produkčního buildu.

### 9.5 Přenositelný souborový build

```bash
npm run build:usb
```

Tento build je vhodný například pro offline použití, archivaci nebo přenos jako sada souborů.

---

## 10. Přesná logika `build:usb`

Skript `build:usb` je definován jako:

```text
set "BUILD_TARGET=usb" && astro build && node scripts/usb-rewrite.mjs
```

Z toho vyplývají tři kroky:

1. nastaví se `BUILD_TARGET=usb`
2. spustí se standardní Astro build v režimu definovaném v `astro.config.mjs`
3. spustí se postprocessing skript `scripts/usb-rewrite.mjs`

### 10.1 Co dělá `astro.config.mjs` v tomto režimu

Při `BUILD_TARGET=usb` se používá:

- `trailingSlash: "never"`
- `build.format: "file"`

To znamená, že interní routy jsou generovány jako soubory typu:

```text
slug.html
```

namísto adresářového tvaru:

```text
slug/index.html
```

### 10.2 Co dělá `scripts/usb-rewrite.mjs`

Skript:

1. projde všechny `.html` soubory v adresáři `dist`
2. načte jejich obsah
3. přepíše vybrané root-based cesty na relativní cesty
4. soubory znovu uloží

Konkrétní přepisy:

- `/_astro/` → `./_astro/`
- `/images/` → `./images/`
- `/files/` → `./files/`
- `/demos/` → `./demos/`
- homepage `/` → `./index.html`
- interní odkazy ve tvaru `/slug/` → `./slug.html`

Smyslem tohoto kroku je upravit HTML tak, aby výstup fungoval i mimo klasický webserver s root-relative URL.

---

## 11. Deploy

### 11.1 Struktura `dist`
Adresář `dist/` obsahuje hotový build určený k publikaci.

### 11.2 Nasazení běžného webového buildu
Pro produkční web se na hosting nahrává obsah odpovídající standardnímu webovému buildu.

### 11.3 `.htaccess`
Pro statický Astro web je vhodná minimalistická konfigurace. Typické WordPress rewrite pravidlo do `index.php` není pro tento typ projektu relevantní.

### 11.4 Přenositelný build
Přenositelný build lze používat jako souborový snapshot nebo offline kopii. Není však identický s běžným webovým hostováním a některé externí služby se mohou chovat odlišně.

---

## 12. Známé problémy a jejich řešení

### 12.1 YouTube embed v lokálním nebo souborovém režimu
YouTube iframe může v lokálním nebo souborovém režimu selhávat s chybou 153. V takovém případě se doporučuje počítat s fallbackem na otevření videa přes externí odkaz.

### 12.2 Sketchfab warnings v konzoli
Sketchfab iframe může v konzoli generovat warnings typu:

- permissions policy violation
- deviceorientation blocked
- accelerometer is not allowed

Pokud je viewer funkční, nejde o chybu projektu, ale o omezení nebo chování třetí strany.

### 12.3 Rozbití CSS nebo assetů při špatném base modelu
Pokud build používá root-relative cesty v prostředí, kde není k dispozici klasický serverový root, mohou se rozbít styly, obrázky a interní odkazy. Proto je přenositelný souborový build doplněn o postprocessing `usb-rewrite.mjs`.

### 12.4 Dev server a nové články
Pokud po přidání nového `.mdx` souboru nesedí výpis nebo routy, doporučený první krok je restartovat dev server.

---

## 13. Budoucí rozšíření

Možné další směry rozvoje projektu:

- další doladění responzivity
- oddělení konfigurace pro více prostředí
- další formalizace build targetů
- případný přechod na jiný hosting bez změny autorského workflow
- rozšíření dokumentace o obsahové workflow pro dalšího editora

---

## 14. Shrnutí

Projekt je navržen jako souborově orientovaný statický web. Obsah je verzován přímo v repozitáři a výsledná publikovaná podoba vzniká build procesem. Tento model usnadňuje archivaci, obnovu a migraci projektu bez závislosti na databázovém runtime.

Z hlediska údržby jsou důležité zejména tyto body:

- obsah je spravován jako `.mdx` soubory
- metadata jsou validována přes content collections
- speciální obsah je zapouzdřen do několika opakovaně použitelných komponent
- projekt podporuje standardní webový build i přenositelný souborový build
- při práci s novým obsahem je vhodné počítat s občasnou potřebou restartu dev serveru

Tato dokumentace popisuje aktuální architekturu a provozní model projektu v podobě vhodné pro další údržbu, předání nebo budoucí migraci.
