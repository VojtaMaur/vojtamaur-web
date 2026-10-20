# Zadání, execution receipt a pokrytí mechanismu — 0.6.10

Aktuální contract 0.6.13: [EVIDENCE_REVIEW](EVIDENCE_REVIEW.md) přidává vlastní
čtení výstupů, quoted executable positive/negative cases a exact-byte recovered
artifact pro FULL_MECHANISM. Historický postup níže doplň těmito požadavky.

Pro nový skutečný běh ve stávajícím CMD s klíčem a běžícím Dockerem:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-http.cmd
```

Není nutné znovu pouštět smoke testy ani rebuildovat Docker image. Výchozí image
obsahuje Python; nový `get_sandbox_capabilities` změří skutečnou dostupnost
Python/Node/npm uvnitř izolovaného kontejneru. Nejde o spuštění na hostu.
PyPI instalace je nadále obecná; `pip` samo nedodává Node runtime.

## Přechod na nové zadání

Review/local úkol má klíč kind + ID + revision. Při změně klíče se celá původní
modelová historie archivuje do `raw/` a kopie do vlastního `context/`; další
modelové kolo dostane čistou pracovní historii a explicitní ACTIVE HOST TASK.
Workspace, evidence, balíčky, receipts, neznámé externí outcomes a approval
ledger zůstávají. Změna modelového kontextu není reset rozpočtu ani povolení
opakovat externí akce. Pokračování stejného úkolu svou historii zachovává.

## Testovací kontrakt

Prototyper má před provedením testu:

1. Převzít přidělené aktuální IDEA, zjistit dostupný runtime a materializovat
   skutečný zachycený export. Vymyšlený text ani výstup jiného IDEA není retained
   export input.
2. Napsat skutečný script a použít `record_prototype_plan`: ID, testovaná
   vlastnost, cesta k nezměněnému exportu, script, plánované specimen paths,
   pozitivní assertion, negativní assertion, scope a omezení.
3. Připojit existující script pomocí `register_idea_artifacts` a spustit jeho
   přesnou cestu přes `run_experiment`. Změna scriptu vyžaduje nový kontrakt.
   Python odmítne `.mjs` a známý nedostupný runtime se odmítne před spuštěním.
4. Připojit skutečně vytvořené specimen paths a znovu provést propojený script.
   `record_test` ověřuje experiment, input, script a specimen hashes. Stejný
   experiment nevytvoří další duplicitní test receipt.

`FULL_MECHANISM` je tvrzení o úplném pokrytí; `SUBCOMPONENT` musí uvést, co
neověřuje. Kontrakt sám tvrzení nepotvrzuje. Host kontroluje vazby a bytes;
nezávislý auditor posuzuje význam skutečných assertions.

## Nezávislé posouzení po testu

Úspěšné `record_test` v obecném výzkumu ukládá **execution receipt**. Neuděluje
automaticky `PROTOTYPED`. Host uloží neměnné kopie script/specimen do auditu,
deduplikované podle SHA256, s celkovým byte limitem `max_snapshot_bytes`.
Další práce agenta tak nezničí původní podklady pro review.

Auditor dostane `PROTOTYPE_TEST` packet obsahující původní mechanismus, zmrazený
kontrakt a receipt. `read_test_artifact` čte jen artefakty přiděleného testu a
ověřuje jejich hashes. Před pozitivním posouzením musí auditor přečíst celý
skutečný script. `review_prototype_test` zaznamenává:

- `FULL_MECHANISM`: relevantní test celé deklarované vlastnosti; může přidělit
  `PROTOTYPED`. Nelze takto povýšit kontrakt označený `SUBCOMPONENT`.
- `SUBCOMPONENT`: užitečné dílčí pokrytí; celé IDEA zůstává bez certifikace.
- `REVISE`: nerelevantní, nedostatečný nebo chybný test; hypotéza se tím
  nezamítá. Prototyper může opravit test v původním zbývajícím budgetu.

Verdict je **nezávislý agentní úsudek**, nikoli hostem dokázaná vědecká správnost
či dlouhodobá trvalost. Scope review, skutečný upload a ověřený veřejný read-back
jsou odlišné záznamy. QR s hashem není Arweave custody, otevření PNG není QR
dekódování, JSON není CBOR a slepení několika zbylých fragmentů není erasure
recovery. Report rozlišuje execution receipts, čekající reviews a jejich scope.

## Počty kol, staré runy a známé vrstvy

Evidence Auditor má v nových obecných profilech **6 kol místo 2**, pro posouzení
tří návrhů před testy a tří výsledků po testech. Globální 40 kol / 3 miliony
tokenů / hodina i všechny model tiers a externí oprávnění zůstávají stejné.
Další kandidáti mohou skončit LIMIT_REACHED; limity se automaticky nezvyšují.

Při explicitním otevření/resume starého research runu zachová host execution
receipts, ale nepodložené historické PROTOTYPED přehodnotí na INVESTIGATING,
s auditním záznamem o chybějící/stale scope review. Nevymýšlí zpětně plán testu
a nezamítá mechanismus. Archivovaný původní report a raw data zůstávají podklady.
Instalace sama staré runy nespouští; doporučený další krok je fresh `run-http.cmd`.

Podání nového kandidáta nyní také porovnává skutečně pojmenované vrstvy s URL
v `ARCHIVE.txt`. Arweave uvedené v registru není novým carrier discovery.
Materiální improvement může projít s konkrétním rozdílem, validation plánem
a původními BASE IDs. Žádný fuzzy textový match se tím nemění v důkaz existence.

## Diagnóza běhu 20261013-112205-7f99ddd8

Auditorovo druhé kolo shrnulo starý IDEA-0001 místo aktuálního IDEA-0002. Dva
testy ztroskotaly na Node/JS runtime; první navíc obsahoval JSON místo CBOR a
fragmenty bez parity, takže sparse subset nemohl rekonstruovat celý payload.
Jediný zaznamenaný úspěšný test vytvořil QR hash pro OPDS JSON a otevřel PNG.
Neověřil Arweave upload, retrieval ani QR decoding. Jeho historický PROTOTYPED
proto nebyl důkazem implementovaného preservation mechanismu. Žádný externí
deposit se v tomto běhu neprovedl.
## Aktualizace 0.6.12

Pro plánované research experimenty je aktuální postup [FLOW_COMPLETION](FLOW_COMPLETION.md): host zachytí skutečně zapsané plánované výstupy a `record_test` provede jejich registraci pro stejné experiment ID, bez bookkeeping rerun. Nezávislý scope review a immutable snapshots zůstávají. Níže popsaný ruční register/rerun odpovídá staršímu contractu nebo legacy/unplanned workflow.

