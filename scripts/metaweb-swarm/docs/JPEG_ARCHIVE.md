# Samostatný archiv souboru v JPEG APP13

Experimentální formát `metaweb-jpeg-archive-v1` zachová existující JPEG obrazový
stream a před SOS vloží několik APP13 segmentů. Obsah exportu se nekomprimuje
ani nešifruje. Oba příklady používají jen standardní Python, nepotřebují API key.

## Obnova hotového výsledku v CMD

V adresáři `G:\vojtamaur-web\scripts\metaweb-swarm`:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe examples\jpeg_extract_independent.py "G:\metaweb-swarm-runs\manual-jpeg-recovery-20261022-090142-1d20ea49\metaweb-export.jpg" "G:\metaweb-swarm-runs\manual-jpeg-recovery-20261022-090142-1d20ea49\recovered.epub"
```

Lze také zkopírovat pouze JPEG a `jpeg_extract_independent.py` na jiný počítač a
spustit `python jpeg_extract_independent.py metaweb-export.jpg recovered.epub`.
Encoder, původní EPUB ani externí manifest nejsou k obnově potřeba. Název výstupu
určuje operátor; čtečka nepoužívá jméno z nedůvěryhodného manifestu jako cílovou cestu.
Při chybě před kontrolou se žádný nový obnovený soubor nezveřejní; dřívější existující
výstup se ponechá. Platné výstupy se nahrazují atomicky.

## Vytvoření vlastního nosiče

Obecná syntaxe (dosaď vlastní vstupy a výstup mimo produkční strom):

```cmd
python examples\jpeg_archive.py COVER.jpg EXPORT.epub OUTPUT.jpg
python examples\jpeg_extract_independent.py OUTPUT.jpg RECOVERED.epub
```

Encoder čte skutečné soubory. Export musí mít 1..64 000 000 bajtů; vstupní i
výstupní nosič mají stejný velikostní strop. Režie i velikost obrázku proto snižují
maximální skutečně vložitelný export. Původní soubory nelze přepsat týmž výstupem.
Toto jsou limity samostatného příkladu; profilové export/snapshot limity roje zůstávají
samostatné a nezměněné. Encoder kontroluje strukturální frame/scan, plné obrazové
dekódování ověřuje oddělený reader (v dokončeném příkladu Pillow).

## Struktura v1

APP13 tělo začíná `Photoshop 3.0\0`, obsahuje Image Resource Block se signaturou
`8BIM`, experimentálním ID `0xBEEF` a Pascal názvem `Metaweb archive v1`.
Název i data se doplňují na sudý počet bajtů; délky jsou big endian podle
[Adobe Image Resource Blocks](https://www.adobe.com/devnet-apps/photoshop/fileformatashtml/#ImageResourceBlock).
ID a tělo jsou vlastní experiment; **nejde o IPTC ani registrovaný Adobe resource**.

Resource data:

| Bajty | Význam |
|---|---|
| 0..3 | ASCII `MWJ1` |
| 4..7 | uint32 pořadí bloku; 0 = manifest |
| 8..11 | uint32 počet datových chunků N |
| 12.. | JSON manifest (index 0) nebo raw obsah (index 1..N) |

Manifest obsahuje `format`, původní `filename` bez cesty, `bytes`, `sha256`,
`chunks` a `chunk_bytes=60000`. Poslední chunk smí být kratší. Celý export je
konkatenace chunků 1..N; čtečka ověří chybějící i duplicitní indexy, délky a SHA256.
COM přidává čitelnou stopu s názvem formátu a instrukcí k APP13. Není potřebný
k rekonstrukci a nevytváří novou vnější závislost. Čtečka zpracovává hlavičkové
segmenty před prvním SOS; fotografická data neinterpretuje ani nespouští.

## Co bylo a nebylo ověřeno

Celý skutečný EPUB byl obnoven ze samotného obrázku dvěma oddělenými implementacemi
zápisu a čtení; samostatný JPEG decoder plně načetl stejné pixely jako originál.
Nezávislá čtečka odmítla změněný payload, chybějící/duplicitní segment a useknutí.
Čtečka se při obnově neopírá o původní soubor ani zdrojové konstanty encoderu.

**Odstranění APP13 nebo nové uložení obrázku může archiv zničit.** Nosič je určen
pro zachování původních bajtů, nikoli automaticky pro sociální sítě nebo editory,
které metadata zahazují. Nebyl testován Photoshop round-trip, poškození obrazu,
opravný kód, veřejný upload ani dlouhodobá úschova. SHA256 uvnitř nosiče kontroluje
náhodné poškození; útočník může přepsat data i vložený hash. Pro ověření původu
je potřeba nezávislý očekávaný hash nebo podpis. Jde o funkční lokální nosič dat,
nikoli důkaz nového dlouhodobého preservation mechanismu.
