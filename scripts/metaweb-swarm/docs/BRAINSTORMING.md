# Výchozí výzkum a brainstorming (0.9.0, 2026-11-03)

## Strategické rozhodnutí

Další vývoj plně autonomní realizace je dočasně odložený. Prioritou je užitečný
výzkum/brainstorming; realizace dobrých objevů proběhne zvlášť s lidským dohledem
a pomocí ChatGPT Work. Autor se může k autonomii vrátit podle vývoje komerčních
agentních systémů. Toto není tvrzení o termínu či dostupnosti konkrétního produktu.
Veřejná dokumentace vojtamaur.cz se touto změnou neupravuje.

## Technická změna

`task_style=brainstorming` používá existující research handoffs pro aktuální
IDEA, nezávislou kritiku a závěrečný report. Nemá Prototypera, realizační frontu
ani povinné uzavírání prototypů. Všechny seed i emergentní role dostávají pouze
výzkumné nástroje. Web search a `read_document` zůstávají; neexistuje modelový
HTTP upload, shell, instalace knihoven nebo psaní kódu. Přímý realizační gate
vrací `BRAINSTORMING_RESEARCH_ONLY` i po případné operator select volbě.

Validace odmítá kombinovat tento profil s Dockerem, PyPI, autonomous mode,
externími resources/credentials nebo povolenými externími akcemi. Pro experiment
je potřeba zvolit plný profil, nikoli částečně povolit execution v brainstormingu.
To je explicitní význam tohoto workflow, ne druhá skrytá approval plného režimu.

SDK dostává skutečně omezený seznam nástrojů a zvláštní výzkumné instrukce;
nejde jen o prosbu v promptu při zachování realizačních tools. Princip dostupnosti
nástrojů odpovídá [OpenAI Docs](https://developers.openai.com/api/docs/guides/tools).
API a verze SDK se touto změnou nemigrují.

## Data a výstup

Projekt a autoritativní kontext se dále zachytí do odděleného runu. `exports/`
se ve výchozím profilu nekopírují, takže velký ZIP neblokuje výzkum a nečerpá
intake limit; mechanismy mohou navrhovat jejich pozdější využití. Produkční strom
zůstává pouze pro čtení. Baseline, run-local dedupe, původ příspěvků, emergentní
role, checkpointy, pause/resume a limity zůstávají.

Reporter musí pokrýt aktuální IDEA, důkazy/nejistoty, priority a nejmenší další
krok s člověkem. Nula experimentů nebo depositů je normální. Výzkum dokončený
reportem neproměňuje nerealizované kandidáty na REJECTED, PROTOTYPED ani archivně
COMPLETED. Opravdový technický blocker nebo vyčerpaný limit se dál uvádí pravdivě.

## Kompatibilita

CLI `init/start/doctor` bez profilu a `run.cmd` používají `config.research.json`.
`run-http.cmd` nově odkazuje na brainstorming a změnu vypíše. `config.http.json`
se nemění, stejný plný režim je v `run-experimental.cmd`; ostatní cílené testy
zůstávají. `run-sandbox.cmd` používá tentýž realizační profil se sandbox-only.
`config.json` zůstává nízkoúrovňový základ explicitních profilů pro slučování a
kompatibilitu starých testů/integrací, nikoli doporučený spouštěcí profil.

Resume používá konfiguraci uloženou v runu. Aktualizace nevykonává migraci
starých runů, nepřepisuje výsledky a nezahajuje placený výzkum. Modely jsou stále
`gpt-5.4-mini` ve všech třech tierech. [Příkazy](START_HERE.md).

## 0.9.2 — 2026-11-03: rozsah kontextu pro brainstorming

Prompt již neobsahuje celý packet kandidáta s opakovanými submissions/revisions
ani souhrn všech kandidátů. Obsahuje omezenou hlavičku přidělení a náhled
zachyceného kontextu; úplné podklady zůstávají dostupné přes nástroje. Research
a review packets vynechávají pouze historii submissions/revisions, nikoli aktuální
tvrzení, mechanismus nebo evidence. Nový read_research_idea(idea_id,offset,limit)
vrací úplný záznam včetně provenance po stránkách. Bounded report/index nástroje
zůstávají dostupné. CORE/CURRENT_STATE lze dočíst přes read_file.

Prošlo 58 souvisejících testů. Replay checkpointu 20261103-082635-0ef17a77 ověřil
všechny role pod původním limitem 20000 znaků (kritici 8543/8523, reportér 8620),
nezměněné aktuální důkazy/mechanismus a přesné složení úplné provenance z paged
reads. Test s uměle dlouhou historií také prošel. Bez placeného API, bez změny
původního checkpointu nebo cen/modelů. Všechny tiery nadále gpt-5.4-mini.

Pokračuj v existujícím běhu přes resume; není třeba znovu platit discovery.
Tato aktualizace nezvětšuje prompt_chars ani rozpočty a nezahajuje běh sama.

