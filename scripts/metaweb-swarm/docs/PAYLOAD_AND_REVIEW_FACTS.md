# Skutečný vstup a nezávislé hodnocení testu (0.6.17)

Nový běžný výzkum ve Windows CMD ve složce projektu:

```cmd
run-http.cmd
```

Docker musí běžet a CMD musí mít nastavený `OPENAI_API_KEY`. Image není potřeba
přestavovat. Modely, limity a externí oprávnění/schvalování se aktualizací nemění.
Instalace nespouští placený běh a nepřepisuje historické výsledky.

## Vstup je obsah, nikoli popis obsahu

LOCAL role dostane před první implementací `prepare_prototype_input`. Nástroj
vybere jeden skutečný zachycený EPUB/PDF/TXT/ZIP, zkontroluje hash a zkopíruje
jej pouze z izolovaného `input_exports` do jejího workspace. Upřednostňuje
Metaweb payload a související export, pak menší velikost. Neprohledává znovu
produkční web, nerozbaluje archiv a nespouští kód na Windows hostu.

Návrat obsahuje skutečnou cestu, velikost, hash a upozornění na binární formát.
Opakované volání může použít již ověřenou kopii. Pro konkrétní jiný formát
zůstávají dostupné `list_exports` a `materialize_export`.

`.manifest.json` je descriptor, nikoli exportovaný obsah webu. Plán
FULL_MECHANISM s takovým vstupem vrátí `PAYLOAD_EXPORT_REQUIRED`. Užitečné
zpracování samotných metadat lze poctivě testovat jako SUBCOMPONENT s uvedenými
omezeními. EPUB se čte jako bajty/ZIP v Dockeru, nikoli pomocí JSON parseru.
Shoda původních a obnovených bajtů stále neprokazuje správný decoder, soulad
se standardem ani dlouhodobou nezávislou archivaci.

## Opravné odkazy musejí existovat

Nový plán používá prázdné `revision_test_id` a `repair_experiment_id`.
Oprava používá přesné vlastní aktuální REVISE TEST-ID, případně skutečné
failed EXPERIMENT-ID s diagnózou. Musí odpovídat stejnému agentovi, kandidátovi
a aktuální výzkumné revizi. Hash research_revision není TEST-ID.
Neplatný odkaz vrátí `INVALID_REPAIR_REFERENCE` před změnou uloženého plánu;
neplatné historické drafty se automaticky neopravují ani znovu neprovádějí.
Původní historické receipts zůstávají auditními záznamy.

## Fakta před verdiktem

Po vlastním čtení zmrazeného zdroje a výstupů musí SDK reviewer zavolat
`get_prototype_review_facts`. Obdrží IDEA/TEST vazbu, aktuálnost claimu,
klasifikaci vstupu a skutečné matching output paths/hash/byte lengths.
Tato fakta neoznačují kopii původního souboru za decoder ani související ID
za automatický důkaz sémantické relevance kódu.

Verdikt používá také strukturovaná pole:

- `observed_recovery`: MATCHES_INPUT / DIFFERS_FROM_INPUT /
  NO_RECOVERED_OUTPUT / NOT_EVALUATED.
- `review_basis`: LOCAL_DEFECT / IRRELEVANT_TEST / EXTERNAL_GAP_ONLY /
  UNSPECIFIED.

Po načtení faktů musí reviewer existující shodu bajtů výslovně uznat a uvést
odpovídající `recovered_path`. Přesto může dát REVISE kvůli konkrétní vadě,
neověřené konformitě nebo nesouvisejícím operacím. Faktický rozpor vrací
`REVIEW_RECOVERY_FACT_CONFLICT`. Pro REVISE musí uvést konkrétní basis;
absence veřejného uploadu sama vrací `LOCAL_COMPONENT_ASSESSMENT_REQUIRED`.
Užitečná lokální operace může získat SUBCOMPONENT bez externí publikace,
pokud projde nezměněným kontraktem vlastních čtení a skutečných pozitivních/
negativních testů. Host automaticky nevybírá vědecký verdikt.

Tři opakované nekonzistentní pokusy uzavřou posouzení jako
`MODEL_REVIEW_UNRESOLVED`: eviduje se technický problém nezávislého posouzení,
nikoli chyba implementace či REJECTED hypotéza. Prototyper nemá opravovat kód
podle takového rozporu. Další kandidáti mohou pokračovat v existujícím budgetu.
Ani historický descriptor-only FULL plán nemůže získat nové FULL potvrzení
uchování webového obsahu. Staré přímé API callers bez nové faktické attestation zůstávají kompatibilní;
živý SDK tok již načtení faktů vynucuje.

Reporterův přehled výslovně uvádí typ vstupu, počet shodných výstupů a případné
neuzavřené posouzení. Plné záznamy zůstávají dostupné stránkováním.

## Ověření

Read-only replay běhu `20261020-061731-7b04b59a` rozpoznal, že BagIt-like/CBOR
test skutečně obnovil 28 865 bajtů **descriptoru** se shodným hashem. Odmítl
opačné strukturované tvrzení a přijal omezené SUBCOMPONENT hodnocení po
ověření původních testovacích případů; necertifikoval BagIt interoperabilitu,
uchování webového obsahu ani veřejnou custody. Jiný krok zkopíroval skutečný
Metaweb EPUB (1 294 314 bajtů) a ověřil jeho hash. Phantom TEST-ID byl odmítnut.
Původní běh zůstal hashově beze změn.

SDK odpovědi a úsudky v replay dodal místní pevný model, nikoli placený agent.
To ověřuje řídicí kód, ne samostatnou výzkumnou kvalitu cheap modelu.
Přenosné výsledky jsou v `docs/validation/PAYLOAD_FACTS_PROOF.json`.
Žádná placená API volání nebo veřejné uploady při vývoji.

Implementace navazuje na [OpenAI Docs: validace SDK](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals),
ale používá lokální validaci a API instalovaného SDK 0.23.1 bez změny závislostí.
