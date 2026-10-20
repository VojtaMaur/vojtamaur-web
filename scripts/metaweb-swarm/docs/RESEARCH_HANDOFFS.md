# Obecný výzkum: předání skutečných kandidátů (0.6.9)

`run-http.cmd` spouští nový skutečný výzkumný běh s Dockerem a obecným HTTP.
Nejde o smoke test ani o úzce zadaný deposit trial. Ve stejném CMD s nastaveným
`OPENAI_API_KEY` a běžícím Docker Desktop:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-http.cmd
```

Vytvoří nový run; starý run 20261013-094554-739e32e0 se automaticky nepřepíše
ani nepokračuje. Nastavení je v `config.http.json`. Tier modely zůstávají
`gpt-5.4-mini`; globální limity zůstávají 40 kol, 3 miliony tokenů a hodina.
Externí akce nadále vyžadují schválení. `research_handoffs` nemění credentials,
oprávnění, externí limity ani Docker izolaci. Sandbox profil
`config.research.json` používá stejný způsob předání práce.

## Co se předává

- `list_current_ideas` vrací skutečná ID aktuálního běhu. `get_research_task`
  vrací roli odpovídající zadání a původní tvrzení/evidenci; koordinátor dostává
  roster a coverage, nikoli prázdný auditní úkol.
- Auditor dostane jeden `RESEARCH_IDEA` packet. Nepotřebuje upload qualification
  pro posouzení formátu nebo lokální hypotézy. Musí uložit vlastní critique
  přiděleného ID/revize; další kandidát patří dalšímu omezenému kolu. PASS vyžaduje
  vlastní přečtení citovaných primárních zdrojů. Chybějící důkaz není REJECT.
- Prototyper dostane existující aktuální IDEA. `register_idea_artifacts` připojí
  vlastní existující script/specimen paths, host je validuje a hashuje a zachová
  ostatní autory. `submit_idea` může revidovat přidělené ID; nemůže vytvořit
  jiné nebo vymyšlené. Lokální test hypotézy nevyžaduje předchozí PASS.
- Jeho `run_experiment` vyžaduje přidělené IDEA ID. Import balíčku nebo
  `print('prototype pending')` bez `record_test` neuzavírá implementaci.
  Pro `record_test` musí být skutečné artefakty zachycené s úspěšným experimentem.
  Registruj existující script před prvním během; po vytvoření specimen připoj
  také ten a spusť propojený test znovu. Host ověřuje vazbu, bytes a exit code;
  správnost tvrzení a sílu assertions musí stále posoudit reviewer/člověk.
- `record_research_blocker` ukládá konkrétní překážku lokálního úkolu. Zachová
  hypotézu; nevydává zamítnutí mechanismu. Nezměněná překážka se automaticky
  neopakuje; nové podklady nebo operator note umožní pokračování.
- Reportér načte současný `get_research_task`: aktuální IDEA, critiques,
  experiments, tests, balíčky, approvals a HTTP/external receipts. Historické
  nápady nejsou současnými kandidáty. `SWARM_REPORT.md` stále vytváří host z
  ledgeru, nikoli pouze z agentního vyprávění.

Nové skutečné zadání může znovu otevřít dokončený audit/prototyp/report, ale pouze
v rámci původního počtu kol a globálních limitů. Výsledek LIMIT_REACHED tak dál
znamená nehotovou práci. Dokončení lokálního testu neznamená externí uložení;
report musí uvést pouze skutečné deposit/read-back receipts. Žádné accounty,
provider-specific integrace ani browser fallback tato změna nepřidává.

## Pokračování

Vlož skutečnou cestu vypsanou launcherem:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\SKUTECNE_ID_BEHU" --backend openai
```

Resume načte uloženou konfiguraci a checkpoint svého runu. Úprava profilu platí
pro nový run, nikoli automaticky pro starý. Rozšíření limitů je výslovný operator
krok; framework je sám nezvyšuje. Supervised umožňuje výzkum ukončit bez
realizace a bez zamítnutí dobrých nerealizovaných nápadů.

## Příčina opravy

Běh 20261013-094554-739e32e0 měl dvě skutečné IDEA, ale globálně nabízený
`get_review_task` obsluhoval pouze focused deposit režim. Auditor proto dostal
NONE. Prototyper otestoval CBOR mimo tyto IDEA a zkusil neexistující IDEA-0003;
reportér doporučil starý Google Drive lead. Nový opt-in kontrakt pro obecný
výzkum odděluje lokální hypotézy od deposit qualification, váže zadání na
aktuální ID a ověřuje dokončení pomocí uložených záznamů.

Regrese používají skutečné SDK schema/tool dispatch se simulovaným providerem,
lokální HTTP dokumenty a simulovaný Docker receipt. Tyto testy neprokazují
účinnost QR/microdata mechanismů ani skutečný nový deposit. Docker/PyPI
infrastruktura už byla ověřena v předchozích skutečných smoke bězích.
