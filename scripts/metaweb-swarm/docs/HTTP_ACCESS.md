# Obecné HTTP ruce pro Metaweb swarm

Verze 0.4.0 přidává obecné HTTP/API požadavky. Agent čte dokumentaci dosud neznámé služby, sestavuje URL, metodu, hlavičky a tělo, uploaduje veřejné exporty a čte odpovědi. Žádná integrace pro konkrétní službu není nutná. Browser/computer-use fallback není implementovaný.

## Spuštění a oprávnění

`run-sandbox.cmd` zůstává sandbox-only: obecné HTTP může veřejně číst, ale externí zápisy nepovolí. `run-smoke.cmd` má HTTP disabled a nadále ověřuje Docker/PyPI.

Nový `run-http.cmd` vytvoří fresh run podle `config.http.json`: autonomous, external, obecné HTTP enabled a approval required. Zachovává levné modely a původní modelové/tokenové/časové limity. Nemá přidělené credentials.

Z CMD ve `scripts\metaweb-swarm`:

```cmd
run-http.cmd
```

Opravdu vypnuté approval, bez dalšího schvalování neznámých domén:

```cmd
run-http.cmd --approval disabled
```

Supervised výzkum s realizací až po výběru konkrétní IDEA:

```cmd
run-http.cmd --mode supervised
```

HTTP požadavky s credentials potřebují external scope. Veřejné GET/HEAD/OPTIONS fungují i v sandbox-only. Jde o klasifikaci podle HTTP metody; nevhodně navržená cizí služba může mít side effects i na GET, což obecný executor neumí poznat. Ostatní metody potřebují `http_access: enabled`, external scope a v supervised režimu vybranou IDEA. Approval se řídí jediným `approval_required`. Neexistuje seznam podporovaných poskytovatelů ani approval pro novou doménu navíc.

Pending approval lze prohlédnout přes `swarm.py approvals RUN`; `swarm.py decide RUN APPROVAL-ID --decision approve --note "..."` pouze zapíše rozhodnutí. `swarm.py resume RUN --backend openai` pokračuje v rámci zbývajících rozpočtů. Schválení váže přesnou metodu, URL, hlavičky, tělo/file hashes a credential grant; změněný požadavek ho nepřevezme.

## Nástroje

`http_request(request_json, idea_id, purpose)` přijímá JSON popis:

```json
{
  "method": "POST",
  "url": "https://discovered-service.example/api/objects",
  "headers": {"Content-Type": "application/octet-stream"},
  "query": {},
  "upload_path": "preservation/site.zip",
  "response_path": "http/upload-response.json"
}
```

Doména v příkladu je placeholder. Agent musí objevit skutečnou službu a přečíst dokumentaci. `upload_path` je relativní cesta uvnitř jeho kopie, nikdy hostitelská cesta. Připravené exporty lze zkopírovat přes `list_exports` a `materialize_export`.

Tělo tvoří právě jedna varianta: `body_text`, `body_json` (JSON řetězec nebo JSON objekt), `upload_path` pro raw soubor, nebo `multipart_fields` + `multipart_files`. Multipart soubory mají pole `field`, `path`, `filename`, `content_type`. Metody: GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE. Read metody nesmějí mít upload/tělo. Odpověď vrací HTTP status, sanitizované hlavičky, počty bajtů, hashe a cestu k uloženému obsahu; HTTP 4xx/5xx je normální odpověď k analýze.

Přesměrování se neprovádí automaticky. Agent může přečíst Location a sestavit nový požadavek, který znovu projde celou kontrolou. Soubory z internetu se nikdy automaticky nespouštějí. Pro test kódu dál slouží Docker bez sítě.

`verify_http_copy(upload_request_id, download_request_id, source_path)` porovná přesné bajty skutečně uploadovaného souboru se samostatným úspěšným GET provedeným až po uploadu. Oba požadavky patří stejnému agentovi. Teprve tato hostem ověřená receipt může potvrdit uložení kandidáta. Samotné HTTP 200/201, vytvořený účet nebo JSON zpráva `success` nepovyšují IDEA na COMPLETED. Receipt nepotvrzuje dlouhodobou trvanlivost, správnost poskytovatele ani veřejnou dostupnost bez přihlášení.

## Credentials a ochrana účtů autora

Výchozí `http_credentials` je prázdné. Framework nečte Git Credential Manager, GitHub/GitLab/Codeberg přihlášení, SSH klíče, browser session, cookies, `.netrc`, credential helpers ani běžné proměnné `GITHUB_TOKEN`, `GITLAB_TOKEN` či `OPENAI_API_KEY` pro HTTP autorizaci. Proxy z prostředí se nepoužívají. Docker tyto přístupy také nemá.

Přidělení credentials musí udělat operátor výslovně, ideálně pro samostatný účet roje. Příklad nastavení:

```json
"http_credentials": [
  {
    "id": "swarm-storage",
    "env": "META_SWARM_CRED_STORAGE",
    "hosts": ["api.discovered-service.example"],
    "header": "Authorization",
    "scheme": "Bearer"
  }
]
```

Hodnota je pouze v dedikované runtime proměnné; nepatří do configu, repozitáře ani promptu. Host injectuje hlavičku až při přenosu na přesně přidělený HTTPS host. Agent vybírá `credential_id`; `list_http_credentials` ukazuje pouze ID a scope, ne hodnotu. Nesmí sám zadat Authorization/Cookie/proxy authentication hlavičky. Explicitní hodnoty a běžná token/password pole z odpovědí se redigují před uložením. Raw/stored hashes se mohou lišit, pokud sanitizace změnila obsah. Není to všeobecný detektor všech možných tajných údajů cizích služeb.

Zápisy na GitHub, GitLab, Codeberg včetně jejich API subdomén, git receive-pack a produkční `vojtamaur.cz` jsou blokované v kódu i s approval disabled. Veřejné čtení dokumentace/repozitářů je možné. Vlastní účty agentů na těchto forge službách by vyžadovaly budoucí explicitní změnu oprávnění; tato verze je nepovoluje. Ochrana známých domén nerozpoznává všechny možné self-hosted forge instalace; hlavní hranice je nepřidělení osobních credentials a absence síťového git/shell přístupu.

Starší `http_put` deposit resource používá stejný bezpečný HTTP transport a povoluje credentials pouze přes `META_SWARM_CRED_*`. Staré granty na ambientní proměnné jsou odmítnuty.

## Limity, audit a obnovení

`http_access`: disabled / read-only / enabled. Výchozí config má read-only. Nový external profil má enabled a approval required.

Samostatné tvrdé limity: `max_http_requests` (100), `max_http_request_bytes` (16 MiB), `max_http_response_bytes` (16 MiB), `max_http_total_bytes` (128 MiB), `http_timeout_seconds` (30 s). Byte limity počítají těla požadavků a přijatých odpovědí; hlavičky mají vlastní pevné omezení. Před pokusem se rezervuje request plus maximální response/probe. Nejistý pokus rezervaci konzervativně zachová. Externí mutace/credential requests současně spotřebovávají společný `max_external_actions` a `max_external_bytes`, včetně starších depositů. Přenosy mají timeout a podléhají globálnímu aktivnímu času; nový požadavek respektuje pause flag. První verze drží omezené payloady v paměti, není neomezený streaming client.

Běžné ukládání odpovědi do workspace má nyní limit 20 MB na soubor; default HTTP response limit 16 MiB se do něj vejde. Vyšší přenosy vyžadují další implementaci streaming downloadu.

Modelové USD ceilings dál hlídají inference/search podle operátorských sazeb. Libovolná cizí služba může účtovat náklady, které framework nezná: ty nelze garantovaně započítat do modelového USD limitu. Používej účty s vlastními spend caps. Automatické platby nejsou implementované; nepovoluj platební credentials. Kandidát vyžadující měsíční/roční předplatné zůstává nepřípustný.

Každý pokus se persistuje jako RESERVED před síťovou akcí. Přerušení/nejistý výsledek znamená UNKNOWN. Resume ho nesmí automaticky zopakovat; stejná mutace se nerozběhne změnou popisu ani lokální cesty odpovědi. Remote outcome musí operátor před dalším pokusem zkontrolovat; zde není obecný automatický recovery API pro libovolné služby. Úspěšné opakování vrací původní receipt. Čtení lze opakovat v rámci limitů.

Záznamy jsou v audit logu, checkpointu, `manifest.json` a `SWARM_REPORT.md`. Neukládají se credential hodnoty ani raw cookies. Odpovědi jsou nedůvěryhodný zdroj, který nemůže sám změnit policy, rozpočty či oprávnění. TLS se ověřuje; soukromé/lokální/multicast/reserved IP a smíšené veřejné/soukromé DNS odpovědi jsou odmítnuté. Spojení používá ověřenou IP s TLS hostname ověřením, čímž omezuje DNS rebinding.

`http_test_origins` je pouze explicitní operátorské povolení přesného loopback HTTP originu pro lokální testy; default je prázdné. Agent ho nemůže měnit. Produkční veřejný přenos vyžaduje HTTPS.

## Ověření

Regrese testují obecnou službu s dokumentací, uploadem a downloadem, kterou framework zná pouze jako URL. Skutečné HTTP sockety + skutečné SDK se ověřují s řízeným modelem bez placené inference; takový test prokazuje nástroje a policy, nikoli autonomní úsudek živého modelu. Testy zahrnují approval on/off, změněné body, sandbox scope, supervised výběr, byte/request/action limity, nejisté pokusy, restart, zakázané forge zápisy, ambientní credentials/proxies a hash read-back.

Po těchto kontrolách lze zkusit levný live run přes `run-http.cmd`. První external run nech s approval required, aby šel konkrétní požadavek před odesláním prohlédnout. Další nastavení bez approval je skutečně dostupné výše. Browser fallback zde není.

SDK nástroje vycházejí ze stávajícího function-tool rozhraní skutečně otestovaného s lokálním Agents SDK 0.23.1; [oficiální dokumentace agent definitions](https://developers.openai.com/api/docs/guides/agents/define-agents). Verze SDK se touto změnou nenavyšovala. Závěrečná regrese: 291 testů (290 passed, 1 Windows privilege skip); validation/HTTP_FINAL_REGRESSIONS.log.

## Targeted live-model integration validation
Use `run-http-smoke.cmd` for the narrowly scoped local docs/upload/download/hash test before another broad research run. See [HTTP_SMOKE.md](HTTP_SMOKE.md). This fixture is an integration test, not a public preservation destination.

After local smoke succeeds, [public HTTPS smoke](HTTP_PUBLIC_SMOKE.md) provides a single authorized synthetic upload/read-back via general tools. The profile is not a provider connector and does not alter general HTTP permissions or credentials.
