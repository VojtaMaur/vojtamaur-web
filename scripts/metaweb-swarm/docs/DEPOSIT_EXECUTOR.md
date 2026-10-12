# Obecný vícekrokový realizátor — 0.6.0

Swarm nyní může provést celý dokumentovaný HTTP postup: zarezervovat upload,
použít ID a podepsanou URL z odpovědi, poslat přesné bytes exportu, dokončit
uložení a anonymně stáhnout skutečný výsledek. Kód nemá žádný connector pro
NudgeHost ani jiného poskytovatele. Agent nebo operátor sestaví datový plán
podle dokumentace konkrétní služby. Framework provede jeho obecné HTTP kroky.

## Co následuje prakticky

Není nutné opakovat Docker, veřejný HTTP smoke ani další placený discovery run
jen kvůli ověření infrastruktury. Vícekrokový executor byl ověřen na skutečném
lokálním HTTP serveru a v nainstalovaném Agents SDK s kontrolovaným modelem.

Pro skutečný deposit ještě potřebujeme vhodnou službu, doložit přijetí přesného
formátu exportu, cenu a podmínky. Případný účet/klíč musí patřit swarmu a být
výslovně přidělený konkrétním hostům. Host GitHub/GitLab/Codeberg účty zůstávají
nedostupné a zápisy do těchto repozitářů i produkčního webu zakázané.

Poslední NudgeHost kandidát není hotový deposit ani ověřená volba pro EPUB.
Stávající run se touto aktualizací nespustil, jeho oprávnění a limity se nezměnily.
Tři privilegované operace potřebují alespoň tři povolené externí akce; nastavení
`max_external_actions: 1` se automaticky nezvyšuje. Při tvorbě NOVÉHO profilu
si případnou změnu povolení nastaví operátor. Resume používá konfiguraci
uloženou v runu, nikoli změněný soubor profilu.

## Použití agentem

1. Discovery přečte API/podmínky, kvalifikuje konkrétní export a uloží IDEA.
2. `record_deposit_execution_plan(idea_id, steps)` uloží konkrétní postup.
   Plánování také může dokončit Prototyper; mění se kvalifikace, proto starý PASS
   už neplatí. Autor discovery a provenance kandidáta zůstávají zachované.
   Při `EXECUTABLE_FLOW_REQUIRED` smí Prototyper nejprve doplnit datový plán;
   v této plánovací fázi nedostane HTTP write/execute tools. Provedení následuje
   až po aktuálním nezávislém auditu.
3. Nezávislý Evidence Auditor posoudí aktuální plán a jeho skutečné zdroje.
   Chybějící účet nebo chybějící realizace není vědecké REJECT.
4. Prototyper zavolá `execute_deposit_plan(idea_id)`. Host sám materializuje
   zachycený export, provede kroky a zkontroluje veřejně stažené bytes.
5. `approval_required=true`: před prvním požadavkem se uloží JEDNO schválení
   celého konkrétního postupu, exportu, cílových originů a limitů těl. Na příkladu
   rezervace → PUT → finalizace není nutné čekat na člověka mezi jednotlivými
   kroky během krátké platnosti podepsané URL. `false` přidává nula lidských
   bran; aktuální audit, scope, granty, rozpočet a technická validace stále platí.

Existující jednorázové `http_request` zůstává pro obecné HTTP a staré jednoduché
kvalifikované uploady. Pro kandidáta s executable plánem nemůže přeskočit
jednotlivé kroky kvalifikace: vrátí `EXECUTION_SEQUENCE_REQUIRED`.

## Datový formát

Plán je JSON pole 2–20 kroků. Každý má přesně tato pole (SDK nabízí výchozí
hodnoty; při přímém načtení souboru musí být všechna uvedená):

| Pole | Význam |
| --- | --- |
| `id` | Jedinečné jednoduché jméno kroku, např. `reserve`. |
| `method` | Pevné GET/HEAD/OPTIONS/POST/PUT/PATCH/DELETE. |
| `purpose` | Konkrétní důvod operace, 5–1500 znaků. |
| `url` | Pevná URL nebo vazba na dřívější JSON odpověď. |
| `allowed_origins` | Přesné `https://host[:port]`, bez wildcardů/path. Každý vrácený cíl se znovu kontroluje. |
| `credential_id` | Jen jméno přiděleného grantu, jinak prázdné. Nikdy hodnota klíče. |
| `headers_json` | JSON text s hlavičkami nebo vazba na celý objekt hlaviček. |
| `body_json` | JSON text pro metadata, jinak prázdné. |
| `sends_export` | Právě jeden krok posílá exact-byte export jako tělo. |
| `max_body_bytes` | Pevný horní limit. Pro soubor přesný počet bytes zachyceného exportu. |
| `success_codes` | Očekávané 2xx kódy, například `[201]`. |
| `max_age_seconds` | Maximální stáří použitých odpovědí; 0 bez lokálního časového omezení. Pro krátké signed URL nastav např. 240. |

Celá URL z odpovědi: `{{reserve:/upload/signedUrl}}`. ID vložené do pevné path:
`https://service.example.org/complete/{{reserve:/id}}`; ID se percent-escapuje.
Authority se neskládá z fragmentů odpovědi. Celá vrácená URL musí mít jeden
z přesných originů uvedených u tohoto kroku. Žádné automatické redirecty.

JSON binding: `{"$response":"reserve","pointer":"/id"}` (RFC6901).
Export metadata: `{"$export":"filename"}`, `bytes` nebo `sha256`.
Pole se nezpracovávají jako programy, expression language, shell ani Python.
Poslední krok musí být anonymní GET bez credentials; hash se porovná s
odeslaným zachyceným exportem po úspěchu všech plánovaných operací.

Podpora této verze: běžné JSON request/response orchestrace a upload přesného
souboru jako HTTP těla. Multipart, parsování HTML/formulářů, cookie session,
automatický signup, browser a dynamické podpisy vlastním kódem se v tomto
datovém realizátoru neprovádějí. Obecný HTTP tool umí vlastní multipart;
před případným rozšířením vícekrokového plánu musí mít i tato cesta auditní vazbu.

## CMD bez dalšího placeného modelového kola

Plán lze uložit ručně ze souboru pro EXISTUJÍCÍ IDEA (nevytváří account/PASS):

~~~cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py deposit-plan "%LIVE_RUN%" IDEA-0001 --plan-file "C:\cesta\deposit-plan.json"
~~~

Vykonat již připravený a nezávisle schválený plán:

~~~cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py deposit-execute "%LIVE_RUN%" IDEA-0001
~~~

Tohle nepotřebuje OpenAI API klíč a nedělá žádné modelové volání. **Může provést
skutečné externí akce** podle scope/grantů/schválení runu. Výzkumný status celého
runu se tím nepřepisuje na COMPLETED; rozhodující je nový stav FLOW a jeho receipts.

Při pending schválení zjisti jeho skutečné ID, rozhodni a zopakuj execution:

~~~cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py approvals "%LIVE_RUN%"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py decide "%LIVE_RUN%" APPROVAL-0001 --decision approve --note "Schvaluji uvedeny presny export, postup a cilove servery"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py deposit-execute "%LIVE_RUN%" IDEA-0001
~~~

`APPROVAL-0001` je ilustrace: použij skutečné zobrazené ID. Pro návrat výzkumných
rolí používej obvyklé `resume ... --backend openai`; již požadovaný nedokončený
FLOW se posune před dalším placeným dispatch. Ruční `deposit-execute` respektuje
PAUSE.flag; neodstraňuje operátorovu pauzu. Normální resume ji odstraňuje.

## Pause, crash, limity a audit

Každý HTTP pokus má FLOW ID a jméno kroku uložené PŘED posláním. Dokončené
operace se při restartu načtou z skutečného HTTP ledgeru, i při pádu před
následujícím FLOW checkpointem. `RESERVED`/`UNKNOWN` write se nikdy neopakuje
slepě. Neúspěšný status/truncation/mismatch zastaví postup a zachová dosavadní
receipt i případný částečný vzdálený objekt. Není automatické mazání/rollback.
Neznámý výsledek potřebuje ověření vzdáleného stavu a výslovnou operátorovu
opravu auditu; tato verze nemá automatickou reconciliation ani restart uploadu.

Před prvním requestem se kontroluje kapacita pro CELÝ zbývající postup. Další
kroky mají rezervované sloty a konzervativní bytes; jiné požadavky je nemohou
spotřebovat během pause. Účtuje se každá mutace i každý credentialed read,
všechny HTTP requesty/response bytes a aktivní čas. Token/USD nejistota nadále
blokuje zápis. Dojde-li k expiraci URL, nenaváže se nová rezervace automaticky.
Změna plánu vyžaduje nové nezávislé posouzení a nové schválení.

`manifest.json` a report obsahují `deposit_executions`, stavy kroků, plan SHA,
HTTP/action IDs a skutečný SHA256 byte receipt. `TIMELINE.md` obsahuje jejich
hashovaný audit. BLOCKED/FAILED provedení neznamená REJECTED mechanismus.

Podepsané URL a JSON bindingy jsou v host-only `private-flow/`, mimo agentní
workspaces a reporty. Windows je šifruje DPAPI pro stejného uživatele; na POSIX
jsou soubory owner-only. Jiný proces se stejným OS uživatelem není touto
aplikační vrstvou izolovaný. Kopie reportu nestačí k resume; DPAPI vault se
obnoví jen na původním hostu/uživateli. Přidělený klíč se nepřenáší na storage
host, pokud pro příslušný krok není zvlášť přidělený grant; finální GET je anonymní.

Lokální testy: `tests/test_deposit_execution.py`, žádná placená inference nebo
veřejný upload. SDK používá typed function tools podle
[oficiálního OpenAI function calling contractu](https://developers.openai.com/api/docs/guides/function-calling).
