# 0.8.2 — skutečný obsah a samostatná obnova

Podnětem je běh `20261022-090142-1d20ea49`: už nezamrzl na review citacích,
správně rozlišil dva HELPERS a sloučil ORCID návrhy. Schválený JPEG SUBCOMPONENT
však používal konstantu `external-bundle-v1`, neměl obrazová data a četl kontrolní
manifest mimo obrázek. Tento historický run ani jeho verdikty instalace nemění.

## Změny frameworku

1. **Negativní test neposuzuje regex nad větou.** Formulace „a corrupted copy
   does not validate as the original“ je platná. Záznam plánu nyní kontroluje
   datový tvar, existující soubory, původ vstupu a ostatní skutečné limity; důkaz
   negativního chování vyžaduje provedení a audit kódu. Samotné přijetí plánu
   nezakládá coverage. Tím se odstraňuje falešná blokace ORCID z tohoto runu.
2. **Společné evidence_requirements** dostává coder před prací a auditor ve
   zmrazené lokální smlouvě. Vyžadují skutečné bajty exportu nebo přesně označený
   skutečný fragment/metadata, nativní výstupní formát, nezávislého konzumenta,
   bootstrap metadata uvnitř nosiče a skutečný negativní případ. Toy string
   není záloha webu. Užší metadata/fragment práce je stále možná s pravdivým scope.
   Jde o obecné zadání, nikoli connector k providerovi nebo další speciální JPEG
   schvalovací formulář. Nativní RSS kontrola z předchozí verze zůstává.
3. **run_review_probe(..., specimen_paths=[...])** vytvoří čistou kopii obsahující
   pouze vybrané zachycené výstupy. Neobsahuje původní export, driver, helper kód,
   nezvolený sidecar ani `.packages` autora. Auditor vloží vlastní nezávislou
   čtečku do Python `code`. Přesné cesty musejí patřit deklarovaným, hashově
   ověřeným výstupům; vstup/zdroj nelze přidat jako specimen. Změna vybraného
   důkazního souboru sondu zneplatní. Auditor může vytvářet nové pozměněné kopie.
4. Prázdné `specimen_paths` ponechává předchozí režim zkoušení autorových funkcí.
   U **nových smluv s nezávislými sondami** FULL_MECHANISM navíc vyžaduje úspěšnou
   output-only sondu; tento režim sám neuděluje žádný verdikt. SUBCOMPONENT se
   nadále hodnotí podle relevantní skutečné operace a jejích mezí. Host syntax,
   hash a izolace nejsou obecný sémantický rozhodovač správnosti modelového kódu.
5. Review může po požadavku na portable recovery skutečně zvolit novou sondu
   v existujícím rozpočtu. Limity tří sond/test, timeout, bajtové kvóty, pause/
   resume a kontrola cleanup zůstávají. Žádný budget ani oprávnění se nenavyšuje.
   Runtime verze v reportu odpovídá importovanému frameworku místo staré konstanty.

Nový protokol při změně úkolu obnoví modelový coding/review kontext. Existující
checkpointy se neodblokovávají ani nepřeznačují automaticky. Oprava nemůže zpětně
prokázat, že starý schválený artefakt byl nativně čitelný nebo nesl skutečný obsah.

## Dokončený JPEG prototyp

Původní směr dokončil Codex přímo bez dalšího modelového runu. Ve standardních
JPEG APP13 segmentech nese **celý skutečný EPUB o 1 388 309 bajtech**. Nosič je
platný obrázek 691 × 519 px; nový soubor má 1 419 098 bajtů. Nezávislé obrazové
dekódování přes Pillow 12.3.0 potvrdilo stejné RGB pixely před i po vložení.

Vložený a obnovený EPUB má SHA256:

```text
1f296bb3da9dc1f48dce3ddd2289cde36766226154f1e6f5eb4e1eded2832bac
```

Obnova proběhla přes **skutečný nový specimen-only nástroj v Dockeru bez sítě**:
jediný staged důkazní soubor byl JPEG, čtečka používala pouze standardní Python.
V sandboxu nebyl originál, encoder ani sidecar. Negativní případy změnily payload,
odstranily/duplikovaly chunk a usekly soubor; čtečka je odmítla. Prostá kopie
zachovala export. Odstranění metadat předvídatelně zničilo archiv a bylo výslovně
zaznamenáno jako omezení, nikoli úspěšný test odolnosti.

Jde o **lidsky dokončený prototyp**, nikoli dodatečný autonomní úspěch starého roje.
Originální checkpoint zůstal hashově shodný; placená API volání a externí akce: 0.
Detaily v `validation/PORTABLE_RECOVERY_LIVE_PROOF.json`.

Soubory:

- `examples/jpeg_archive.py`: stdlib encoder skutečného souboru do skutečného JPEG;
- `examples/jpeg_extract_independent.py`: samostatná čtečka bez importů encoderu;
- [formát, příkazy a omezení](JPEG_ARCHIVE.md).

Hotový JPEG, nezávislá čtečka, návod a proof se ukládají mimo produkční strom do:

```text
G:\metaweb-swarm-runs\manual-jpeg-recovery-20261022-090142-1d20ea49\
```

Modely zůstávají gpt-5.4-mini. Nový celý výzkumný běh zatím není potřeba k prokázání
tohoto výsledku: JPEG lze z existujícího artefaktu rovnou obnovit bez API. Příští
modelový běh teprve ověří, zda roj obecné zadání a nový nástroj využije samostatně.

Přístup vychází z kontroly pozorovatelných výsledků doporučené v
[OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices),
nikoli z odměňování pouhého tvrzení „test prošel“.
