# Stejný lokální úkol pro implementaci a audit — 0.7.7

Run 20261021-110550-9af1ce61 ověřil opravu spuštění/předávání: osm skutečných
finálních Docker captures a osm nezávislých reviews. Všechna hodnocení byla
REVISE. Celkem 37 kol, 2 365 300 tokenů, 39 development příkazů; žádný upload.
Kód vytvářel vlastní textový pointer a extrahoval OPF z EPUB. DNS funkce jen
vracela text, takže DNS codec/query nebyl otestován. Pozdější review současně
uznávala dílčí lokální pokrok a požadovala veřejný DNS záznam pro SUBCOMPONENT.

## Jeden sdílený cíl

SDK coding worker vybírá konkrétní local_operation: skutečnou lokálně testovatelnou
operaci formátu/nosiče, její pozitivní test, negativní test a omezení. Host při
prvním odevzdání uloží local_contract s ID, revizí IDEA a rozsahem. Stejný objekt
je v coding tasku, zachyceném plánu, review packetu a host facts. Nejde o další
agentní schvalování ani provider connector; nic se nevkládá před každý příkaz.

Opravy stejné revize zachovávají původní operaci, assertions, scope a limitations.
Změna textu ve výsledku neoslabí očekávané chování. Starší výstupy bez nového
local_operation použijí pozitivní assertion jako kompatibilní lokální popis;
nová SDK instrukce výslovně požaduje konkrétní operaci. Legacy receipts bez
local_contract nadále používají dosavadní evidence pravidla.

Příklady lokálního cíle: DNS wire-format encode/query/read-back v lokálním testu,
PDF attachment embed/extract nebo skutečný audio encoder/decoder. Celé veřejné
preservation flow je širší cíl. Přepsání manifestu nebo stub místo skutečné
operace nesplní jen tím, že se označí jako SUBCOMPONENT. Příklady nejsou host
implementace DNS, PDF ani předpřipravené služby; implementaci dál vybírá agent.

## Konzistentní audit a konec nekonečné série

Auditor pro nový contract uvede local_contract_status:
SATISFIED / LOCAL_DEFECT / IRRELEVANT_TEST. Při REVISE přidá required_local_change
a defect_code, doslovný úryvek skutečně zachyceného zdroje. SATISFIED + REVISE
je rozpor k opravě posudku, nikoli pokyn přepisovat funkční kód kvůli chybějícímu
public uploadu. Working/relevant SUBCOMPONENT nevyžaduje veřejnou úschovu.
FULL nadále vyžaduje původní silnější evidence kontroly a obnovená originální data.

Host netvrdí, že textová citace nebo typové pole dokazují věcnou správnost.
Kontroluje identitu cíle, konzistenci hodnocení a původ citovaného kódu; relevance
a skutečné pokrytí zůstávají úsudkem nezávislého auditora. Po třech opakovaných
rozporech se auditor zastaví s LOCAL_CONTRACT_REVIEW_STALLED bez uloženého
verdiktu. Posouzení lze po explicitním unblock auditora dokončit správně;
nevyrobí se fingovaná programová chyba ani neodvolatelné REVISE.

Po úvodním REVISE a třech neúspěšných opravách stejného kontraktu se lokální
úkol uchová s LOCAL_CONTRACT_REPAIR_LIMIT. Kandidát není REJECTED a všechny
artefakty zůstávají. Roj může přejít k dalšímu nápadu v existujícím rozpočtu.
Explicitní unblock s poznámkou dovolí novou sérii, nemaže staré pokusy ani
nezvyšuje tokenové, časové, příkazové či USD limity. Promising/unimplemented
neznamená vědecky zamítnutý. Report nyní uvádí lokální operaci i požadovanou opravu.

## Co se považuje za změnu implementace

Původní opakovaný test TEST-f3d7c5909ddb4efd měl stejný driver jako předchozí
TEST-d4a2971f295f40b1. Nově přidal README.md a 37MB rosetta.json mezi reference,
čímž obešel původní porovnání helperů. Nová kontrola vyžaduje změnu bajtů driveru
nebo dříve zachyceného implementačního helperu. Přidání README/JSON, výstupních
cest, nového nepoužitého helperu či opravných poznámek nestačí. Existující helper
lze opravit bez umělé změny driveru. Samotná změna bajtů není sémantický důkaz
opravy; ten dál posuzuje audit. Stejná odmítnutí podléhají bounded submission
pravidlu z 0.7.6 a nemohou opakovat capture donekonečna.

## Ověření a spuštění

75 cílených kontrol prošlo, včetně 10 nových: stejný kontrakt v obou rolích,
SUBCOMPONENT bez publikování, odmítnutí rozporného posudku, skutečná citace chyby,
uchování po třech opravách a zamezení falešné změny přes reference. Skutečný SDK
tool s fake providerem přenesl nová pole a uzavřel dílčí hodnocení bez uploadu.
Reporter byl po posledním doplnění packetu ověřen ještě samostatně.

Read-only replay hashově ověřených snapshots skutečného duplicitního testu jej
novou kontrolou odmítl. Původní checkpoint nezměněn; žádné API volání ani změna
starých review. Tyto testy nepotvrzují funkčnost DNS kódu z původního runu a nejsou
novým placeným úspěchem levného modelu.

Nový běžný běh z projektu: run-http.cmd (Docker spuštěný, API klíč ve stejném CMD).
Levné modely gpt-5.4-mini, globální rozpočty i externí approval zůstaly stejné.
Není třeba další smoke. Aktualizovaný coding kontext se při resume archivuje
a obnoví pro nový protokol; auditní soubory a rozpočty zůstávají zachované.
