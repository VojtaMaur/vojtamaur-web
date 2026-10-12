# Jeden skutečný export: výzkum → schválení → uložení

Z CMD v `G:\vojtamaur-web\scripts\metaweb-swarm` spusť:

```cmd
run-deposit-trial.cmd
```

Vytváří vždy NOVÝ izolovaný běh. OPENAI_API_KEY musí být v tomto CMD nastavený. Docker není potřeba: používají se existující nezměněné exporty, ne spouštění agentního kódu. Čtyři role používají gpt-5.4-mini. Limit je 20 kol, 1 500 000 tokenů a 40 minut aktivní práce (čekání mezi spuštěními se nepočítá). Lokální odhadový strop API je $5; není to kontrola skutečného zůstatku účtu. Rezervace před požadavkem může zastavit běh i před vyčerpáním stropu. Ceny standardního API ověřené 2026-10-08: $0.75 / milion input tokenů, $4.50 output, $0.01 za search plus jeho input tokeny. Cache se konzervativně účtuje jako běžný input. [Model](https://developers.openai.com/api/docs/models/gpt-5.4-mini), [ceny](https://developers.openai.com/api/docs/pricing). Při změně modelu aktualizuj jeho model_prices; bez ceny konfigurace placený běh odmítne.

Profil `config.deposit-trial.json` obsahuje zadání v operator_objective. Profil vybírá explicitně skutečný soubor `vojtamaur-web-export-metaweb-2026-10-05_13-46-46-779622.epub` (1 294 314 B) přes export_filenames. Zbytek exports se nezachytává. Limit souboru je 2 MiB; změna/zmizení vybraného souboru způsobí jasnou chybu, ne tichou náhradu. Při nových exportech uprav tento seznam v profilu. Null obnoví obecný intake všech exportů s jeho limity. Jde o doloženou kopii tohoto konkrétního exportu, nikoli nutně celého webu. Jedna externí měnící akce, maximálně 3 MiB včetně obalu, 60 HTTP požadavků. Samostatné účty roje a explicitní API credentials jsou povolené; osobní přihlášení/credentials počítače nejsou dostupné. Pro tento pokus jen doložené bezplatné použití. Neznámá služba musí mít vhodné podmínky a smysluplnou retenci. Nález vhodné služby není zaručen.

## Když čeká na schválení

Zkopíruj cestu runu z výpisu. Každý příkaz vlož SAMOSTATNĚ:

```cmd
set "LIVE_RUN=G:\metaweb-swarm-runs\CESTA_Z_VYPISU"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py approvals "%LIVE_RUN%"
```

V reportu a artefaktu UPLOAD_PLAN.md zkontroluj soubor/rozsah obsahu, URL služby, podmínky, retenci, cenu a hash. Schvaluješ konkrétní HTTP požadavek a jeho bytes; změna vyžaduje nové schválení. Approval ID použij z výpisu, příklad:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py decide "%LIVE_RUN%" APPROVAL-0001 --decision approve --note "Schvaluji tento konkretni bezplatny upload"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "%LIVE_RUN%" --backend openai
```

`decide` samo nic neposílá; pouze `resume` pokračuje v TOMTÉŽ běhu. Nepouštěj znovu run-deposit-trial.cmd pro pokračování. Schválení nezvyšuje globální čas/tokeny/kola/USD. Pokud limit zabrání pokračování, nejprve zkontroluj status; nezvyšuj naslepo. BLOCKED při čekání na approval je očekávaný checkpoint. Zamítnutí konkrétní akce nemusí znamenat špatný výzkumný nápad; report lze ponechat bez uploadu.

Úspěch vyžaduje upload + samostatný download skutečných původních bytes + hostem ověřený SHA256 receipt. Zkontroluj SWARM_REPORT.md a manifest.json; audit:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py verify "%LIVE_RUN%"
```

Report se aktualizuje i po resume bez dalšího reporter kola. HTTP UNKNOWN není povolení k opakování uploadu. Dočasná transportní služba není archivní úspěch. Žádné změny produkčního webu/repozitářů ani automatický git push.


2026-10-08 / 0.4.7: první cílený trial bez uploadu; opraven crash smíšených HTTP/search source záznamů a konflikt explicitního zadání s obecnými rolemi. Limity beze změn. Viz [review](RUN_REVIEW_20261008_091804.md).


## Samostatné účty a API tokeny (0.4.8)

Účet není důvod k zamítnutí nápadu. Discovery zjistí požadavky; chybějící přístup zachová jako ACCOUNT_SETUP_REQUIRED a zkouší jiného proveditelného kandidáta. Automatická registrace přes e-mail/CAPTCHA/browser ani převzetí nově vydaných tokenů zatím nejsou implementované. Pokud není žádný použitelný grant ani anonymní API, běh může skončit konkrétním požadavkem na zřízení účtu, bez uploadu.

Existující obecný HTTP executor umí použít dedikovaný API token libovolné nově objevené služby. Před NOVÝM během operátor doplní do `config.deposit-trial.json` přidělení (host nahraď skutečným API hostem):

```json
"http_credentials": [{
  "id": "swarm-storage",
  "env": "META_SWARM_CRED_STORAGE",
  "hosts": ["api.example.org"],
  "header": "Authorization",
  "scheme": "Bearer"
}]
```

A ve stejném CMD nastaví token SAMOSTATNÉHO účtu roje:

```cmd
set "META_SWARM_CRED_STORAGE=TOKEN_SAMOSTATNEHO_UCTU_ROJE"
run-deposit-trial.cmd
```

Token se nedává do JSON, repozitáře ani zadání. Zápis do osobních forge účtů/produkce stále nepovolujeme. Grant platí jen pro uvedený HTTPS host; u jiného formátu autentizace viz [HTTP_ACCESS.md](HTTP_ACCESS.md). Ne všechny interaktivní přihlašovací postupy jsou podporované.

list_http_credentials ukazuje také available (zda je dedikovaný token v aktuálním procesu nastaven), nikdy hodnotu.

Profil zatím nechává http_credentials prázdné — skutečný účet ani token jsme nevytvářeli/nepřidělili. Bez grantů mohou agenti hledat anonymně dostupné API nebo doložit potřebný setup. Samotné povolení účtů nevytváří přístup. Úprava profilu po init nezmění již zachycené credentials granty starého runu; spusť nový run.

Auditor nyní dokončí fázi před realizátorem. `require_independent_http_review: true` vyžaduje PASS od jiného agenta v roli Evidence Auditor s nejméně dvěma vlastními pozorovanými source URL. Discovery si PASS udělit nemůže. Ověřování URL je potvrzení aktivity; pravdivost podmínek a vhodnost služby zůstávají odborným úsudkem modelu, ne certifikací. Tato konfigurace je technický review předpoklad, nikoli druhé lidské schválení; lidské approval stále řídí jediný approval_required.

Jeden povolený privileged HTTP request zahrnuje i autentizované GET. Profil proto preferuje veřejné docs/download a vyhrazuje tento request uploadu. Služba vyžadující více autentizovaných kroků má konkrétní resource blocker; před změnou max_external_actions posuď její plán. USD strop je pro API modelu/search, nikoli automatický přehled plateb cizí služby.


## Povinné posouzení před IDEA (0.4.9)

Trial nyní používá check_deposit_target a vynucenou kontrolu proveditelnosti před přijetím nového kandidáta. Zakázaný GitLab/GitHub/Codeberg cíl není chybějící token. Kontrola rozlišuje setup účtu, limity a srovnání baseline; nový IDEA nesmí vytvořit auditor ani realizátor. Upload a audit jsou navázány na konkrétní plán/export. Podrobný popis a limity kontroly: [DEPOSIT_QUALIFICATION.md](DEPOSIT_QUALIFICATION.md). Příkaz pro nový běh zůstává run-deposit-trial.cmd.


2026-10-08 / 0.5.0: krátký společný cíl + role_assignments, task_style=focused. Objevitel nemá nástroje pro opakované lokální/prior vyhledávání. read_document vrací aktuální externí dokumentaci přímo včetně auditní vazby a stránkování. Vlastní úkol lze předat --task / --task-file. Viz [konkrétní návod](FOCUSED_TASKS.md). Další spuštění je skutečný výzkum, ne další smoke.


2026-10-08 / 0.5.1: kvalifikační tool má named fields; nepodložený endpoint/auth se uchovává jako konkrétní gap. Reporter získává read-only HTTP podklady napříč rolemi, zatímco auditor potřebuje vlastní čtení. Zakázané upload cíle jsou konkrétně v task policy. Modely, grants, limity a approval beze změny. Stejný run-deposit-trial.cmd založí nový skutečný výzkumný běh s opraveným předáváním práce.
