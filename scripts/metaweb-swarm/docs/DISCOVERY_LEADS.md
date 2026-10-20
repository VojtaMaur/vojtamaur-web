# Rozpracované směry a jejich předávání — 0.6.2

Poslední deposit trial 20261012-125951-8d056c25 přečetl dokumentaci Dropley,
ale nezapsal žádný IDEA. Objevená služba nemusí mít hotový upload protokol,
ověřenou podporu EPUB ani přidělený účet. Nová vrstva LEAD uchovává tuto práci
ještě před kvalifikací, aniž by povolovala realizaci.

## Průchod

1. `screen_carrier` pro povolený směr vrací skutečné `lead_id`. Známý nebo
   zakázaný směr nevytváří lead. `NO_MATCH_FOUND` není důkaz novosti.
2. `read_document` automaticky připojí request ID, URL, SHA256 zdroje a přečtený
   rozsah. Výpis odkazu nebo samotný HTTP GET není tento read receipt.
3. Discovery zapíše `record_discovery_lead(lead_id, summary, open_questions,
   next_action)`. Před dokončením role musí zaznamenat zjištění u přečtených
   nekvalifikovaných směrů. Když narazí na limit nebo se přeruší, hostem zachycené
   receipts již zůstávají uložené.
4. Auditor dostane doložené neúplné leads i bez IDEA. Sám přečte relevantní
   dokumenty a zapíše `record_lead_review`: NEEDS_EVIDENCE, SETUP_REQUIRED,
   NOT_SUITABLE nebo QUALIFY. NOT_SUITABLE vyžaduje doslovný negativní podklad
   v jeho nezměněném zdroji; existence citace ještě nepotvrzuje správnost výkladu.
   Nedoložené odmítnutí se uloží jako NEEDS_EVIDENCE. Chybějící účet je setup,
   nikoli zamítnutí mechanismu. Po uloženém aktuálním posouzení je audit hotový.
5. QUALIFY je doporučení k další práci, **nikoli PASS**. Potřebný vlastní úkol
   discovery se předá jednou, pouze v rámci zbývajících kol. Setup se automaticky
   neopakuje. Nové podklady zneplatní staré posouzení a mohou znovu otevřít audit,
   pokud má ještě povolená kola.
6. Teprve `check_deposit_target` vytvoří skutečné QUAL ID. Přijatá kvalifikace
   projde existující IDEA admission/dedupe a propojí původní LEAD s přijatým IDEA.
   Kvalifikace, nezávislý PASS, credentials, approvals, scope a všechny rozpočty
   zůstávají povinné pro skutečné provedení podle konfigurace.

`list_discovery_state` vrací aktuální skutečná LEAD ID a vlastní přípustná QUAL
ID. Smyšlené nebo cizí/nepřípustné QUAL ID při `record_deposit_flow` vrací DEFERRED,
seznam skutečného stavu a konkrétní opravný krok. Nevytvoří protokol, kvalifikaci
ani upload. Při chybě screeningu dokumentu zůstává opravný krok v příštím promptu;
nevzniká automatický wildcard ani povolení jiné služby.

## Výstupy a pokračování

- `SWARM_REPORT.md`: počet rozpracovaných směrů a tabulka služby, stavu, zjištění
  a konkrétního dalšího kroku; celé podklady a provenance jsou dále v témže souboru.
- `discovery_leads.jsonl`: samostatné neúplné směry; nenafukují `ideas.jsonl`.
- `manifest.json`, SQLite checkpoint a audit: kompletní leads, příspěvky jednotlivých
  agentů, cílové kvalifikace a historie předběžného posouzení.
- Při resume se stav zachová. Nezměněné hotové posouzení se neopakuje a reporter
  se může aktualizovat při nových podkladech v rámci svých existujících kol.

Nový běh v CMD z `G:\vojtamaur-web\scripts\metaweb-swarm`:

```cmd
run-deposit-trial.cmd
```

Pokračování konkrétního běhu (nahraď cestu svým runem):

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\RUN_ID" --backend openai --extend-rounds 2
```

Instalace nemění již dokončené historické runy ani jejich rozpočty. Historické
vyprávění se zpětně nepřevádí na nové ověřené receipts; nové načtení dokumentu
ve screenovaném směru může použít nezměněný vlastní cache záznam. Pro další fresh
run stačí stejný projektový spouštěč. OPENAI_API_KEY musí být nastaven v tomto CMD.

## Meze a ověření

LEAD seskupuje průzkum služby podle normalizovaného názvu a uchovává jednotlivé
screen IDs a autory. Není novou sémantickou deduplikací mechanismů; odlišné mechanismy
nad stejnou službou dál posuzuje IDEA admission. Tvrzení v summary/questions/next_action
jsou neověřená agentní data, nikoli oprávnění. SETUP_REQUIRED může být dobrý směr
čekající na účet; NEEDS_EVIDENCE potřebuje konkrétní další podklad.

Regrese ověřují checkpoint, scheduler discovery → uložený lead → nezávislé triage
→ report, zotavení ze smyšleného ID přes skutečné SDK, zastavení Prototypera bez
kvalifikace/PASS a obnovení jen při nových podkladech. Používají místní HTTP fixture
a řízené modelové odpovědi, nikoli placené API nebo veřejný deposit. Živý levný model
je samostatné následné ověření; offline průchod nedokazuje jeho úspěšnost.

Nástroje mají strict schema a strukturované výstupy podle
[OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling).
