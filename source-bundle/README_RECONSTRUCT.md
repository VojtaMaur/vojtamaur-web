# Rekonstrukce zdrojového balíku vojtamaur-web

Tento ZIP není kompletní statický snapshot webu. Je to malý zdrojový balík bez velkých veřejných assetů.

Balík obsahuje zdrojové soubory projektu, `download-assets.py`, `MEDIA_MANIFEST.json` a `MEDIA_SHA256SUMS.txt`. Velké assety z `public/images/` a `public/files/` nejsou v ZIPu vložené. Skript je stáhne nebo zkopíruje podle manifestu a ověří jejich SHA-256. Složka `public/demos/` je naopak součástí ZIPu, protože demo soubory se na živém webu mohou lišit od zdrojových souborů a nejsou spolehlivý hashově totožný download-target.

## Rychlá rekonstrukce

```bash
python download-assets.py
npm install
npm run build:web:strict
```

Na Windows může být potřeba spustit Python jako:

```bat
py download-assets.py
```

## Lokální kopírování z rozbaleného buildu

Skript se nejdřív pokusí najít assety lokálně. Pokud je zdrojový balík rozbalený například do hotového `dist/`, zkusí soubory zkopírovat z cest jako:

```text
images/...
files/...
```

Teprve když lokální soubor chybí nebo nesedí SHA-256, zkouší síťové fallbacky z manifestu.

## Demos

`public/demos/` se nestahuje jako asset. Je přibalené přímo ve zdrojovém ZIPu. Důvod je jednoduchý: demo HTML může být při buildu nebo při hostingu přepsané, takže živé `/demos/...` nemusí mít stejný SHA-256 jako zdrojový soubor v repozitáři. Manifest proto sleduje jen `public/images/` a `public/files/`.

## Fallback mirrory

Každý soubor má v `MEDIA_MANIFEST.json` explicitní seznam URL. Výchozí pořadí:

```text
https://vojtamaur.cz
https://vojtamaur.neocities.org
https://vojtamaur.github.io/vojtamaur-web
ArDrive / Arweave deployment
```

Manifest nepředpokládá HTML routy typu `/documentation/`. Pracuje jen s assety z `public/images/`, `public/files/` a `public/demos/`.

## Ověření

Pouze ověření lokálních assetů bez kopírování nebo stahování:

```bash
python download-assets.py --verify
```

## Chybné hashe

Výchozí režim je přísný. Soubor s chybným SHA-256 se nepovažuje za platný asset.

Nouzové režimy:

```bash
python download-assets.py --interactive
python download-assets.py --keep-rejected
python download-assets.py --accept-bad-hash
```

`--interactive` se zeptá, jestli má použít soubor i přes chybný hash.

`--keep-rejected` uloží jeden odmítnutý kandidát do `_rejected-assets/` pro kontrolu.

`--accept-bad-hash` je nouzový režim. Výsledek pak není čistá rekonstrukce, ale kontaminovaný klon. Používat jen tehdy, když je cílem zachránit aspoň něco.

## Požadavky

- Python 3.9 nebo novější
- žádné Python závislosti
- Node/npm podle `package.json` projektu
