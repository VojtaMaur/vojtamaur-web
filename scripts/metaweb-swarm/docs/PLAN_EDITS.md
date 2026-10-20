# Opravy datových plánů po jednotlivých krocích (0.6.6)

Nevalidní návrh už nemusí model přepisovat celý. Host vrací konkrétní krok, kód chyby a u chybných bindings seznam chybějících i dostupných předchozích ID. JSON syntax a velikost literal body mají samostatnou diagnostiku. Endpointy, JSON pointers ani autentizaci host nevymýšlí; musí vycházet z dokumentace.

## Nástroje pro agenta

1. `record_deposit_execution_plan(idea_id, steps)` zůstává pro první návrh nebo změnu pořadí/počtu kroků. Odmítnutý bounded návrh uloží host do soukromého draftu.
2. `read_deposit_plan_draft(idea_id, step_id="")` vrátí ID kroků, issue a `draft_sha256`; s konkrétním ID vrátí redigovaná pole kroku. Draft je výslovně UNVALIDATED_DRAFT.
3. `edit_deposit_plan_step(idea_id, draft_sha256, step_id, changes_json)` změní jen vyjmenovaná pole kroku. Například JSON objekt s jediným polem `url` opraví binding source, ale správný pointer musí dodat agent podle docs. ID nelze přejmenovat tímto nástrojem. Zbytek sekvence zůstane totožný.
4. Po každé změně se znovu validuje CELÝ plán. Další chyba vrací nový draft hash. Zastaralý hash odmítne editaci. Úspěch vytvoří novou kvalifikaci a vyžaduje její nezávislý audit, setup a případný approval.

Draft je vlastní danému agentovi a aktuální kvalifikaci. Po vzniku FLOW, změně kvalifikace nebo uzavření kandidáta se nesmí editovat. Žádný draft neposkytuje upload permission, PASS ani doklad testu. Missing dedicated credential lze pojmenovat v plánování; skutečná realizace stále potřebuje přesný grant a všechny resource/approval gates.

## Omezení opakování

Host počítá stejný kód chyby ve stejném místě daného kandidáta/kvalifikace, nikoli hash celého návrhu. Změna purpose, body nebo ID kroku proto sama počet opakování nenuluje. Po třech výskytech je role BLOCKED / PLAN_REPAIR_STALLED. Návrat stejné chyby po jiné chybě si předchozí počet pamatuje. Opravy různých skutečných problémů mají vlastní počty.

Dvě kola bez dalšího pokusu o opravu při nevyřešené chybě také zastaví roli. Čtení draftu či dokumentace není oprava. Guard platí i po SDK turn yield. BLOCKED je technická překážka; kandidát není vědecky REJECTED. Automatické prerequisite recovery tento stav znovu neotevře. Uložený draft a diagnostika zůstávají k revizi.

## Soukromí, checkpoint a audit

Celý nevalidní draft je v host-only private-flow vaultu: Windows DPAPI, na POSIX owner-only files (není ochrana před jiným procesem stejného uživatele). Checkpoint/report obsahují pouze metadata, issue a hash, nikoli původní headers/body. Čtení jednotlivého kroku rediguje explicitní přidělené secret hodnoty a běžná auth pole; nevalidní JSON se do view nevrací. Audit editace ukládá ID, hash a názvy měněných polí. Draft se nikam neposílá automaticky.

Starší checkpoint při resume obnoví draft pouze z vlastních bounded raw/history tool calls, jejichž argumenty přesně odpovídají uloženému fingerprintu posledního odmítnutí. Nemění účtování, konfiguraci, kvalifikaci, permissions ani historický audit. Pokud odpovídající data chybí, agent musí dodat celý plán znovu.

## Pokračování v CMD

Z adresáře `G:\vojtamaur-web\scripts\metaweb-swarm`:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261013-043825-09e42a24" --backend openai --extend-steps 6
```

Tento běh už skutečně spotřeboval globálních 20 kol. Šest dalších kol je explicitní omezená kapacita na opravu/audit/report; tokeny, USD, runtime, per-role round allowance a externí oprávnění se tím nezvyšují. Poslední čtyři modelová kola se nevracejí do budgetu. Příkaz pokračuje ve stávajícím běhu. Nový samostatný pokus: `run-deposit-trial.cmd`.

Získání syntakticky validního plánu neznamená, že služba funguje nebo že byl EPUB uložen. Tento run stále nemá dedicated credentials a má limit jedné externí akce; vícekrokový upload může vyžadovat samostatné rozhodnutí operátora o setupu/limitech.

SDK tool schemas používají strict function calling; pravidla schématu a skutečná bezpečnostní politika jsou různé vrstvy. Oficiální zdroj: https://developers.openai.com/api/docs/guides/function-calling . Offline testy používají nainstalovaný Agents SDK a FakeProvider, bez placených modelů.
