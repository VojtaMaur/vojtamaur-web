# Cílený HTTP smoke test (0.4.1)

V CMD v projektu, kde už máš nastavený API klíč:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-http-smoke.cmd
```

Každé spuštění založí **nový běh**, používá OpenAI backend a modelové tiery
z `config.http-smoke.json` (výchozí `gpt-5.4-mini`). Volání modelu jsou placená.
Docker ani instalace balíčků se pro tento test nepoužívají.
Launcher je součást projektu; nepotřebuje soubory chatu ani Codex outputs.

## Co se skutečně testuje

Host připraví krátký neškodný TXT specimen a dočasnou HTTP službu na
`127.0.0.1` s náhodným portem a adresou objektu. Prototyper zná pouze adresu
dokumentace, vstupní soubor a cíl testu. Musí:

1. Přes obecný `http_request` načíst dokumentaci služby.
2. Přečíst její odpověď pomocí `read_file` ještě před uploadem.
3. Z dokumentace sestavit požadavek a skutečně nahrát soubor.
4. Samostatným HTTP GET stáhnout uložený objekt.
5. Přes `verify_http_copy` získat hostem ověřené potvrzení shody SHA256.

Neexistuje connector této služby. Používá se stejný HTTP transport, SDK,
rozpočty a audit jako u běžného běhu. Speciální je testovací služba,
úzce vymezené zadání a hostem kontrolovaná podmínka dokončení.
Reporter má jen čtení a poznámky. Neprovádí další upload.

Úspěch v konzoli: `HTTP smoke: PASS, docs read + upload + download + matching SHA256`,
potom `COMPLETED` po dokončení reportující role.
V `manifest.json` musí být `http_smoke.passed=true` a receipt s ID všech
tří požadavků a hashem skutečných bajtů. Totéž najdeš nahoře v `SWARM_REPORT.md`.
Kandidátů i ověřených preservation depositů má být **0**.
Čisté HTTP 200/201 nebo prohlášení modelu nestačí.

## Rozsah a limity

Test povoluje `autonomous / external / approval_required=false`, ale **všechny
agentní HTTP požadavky jsou omezeny na právě běžící lokální testovací službu**.
Veřejné služby ani další lokální porty nejsou přístupné v tomto profilu.
Služba přijímá pouze přesné připravené testovací bajty, nejvýše 64 KiB.
Nepoužívá účty, cookies, přidělené credentials, veřejné exporty ani produkční zápisy.
API klíč pro placený model dál používá pouze backend.

Profil: Prototyper nejvýše 3 kola, Reporter 1 kolo, globální strop 5 kol
(včetně rezervy na uzavření plánovače), 500 000 tokenů, 1 200 s;
12 HTTP požadavků, 3 externí mutace, 64 KiB na tělo požadavku/odpovědi,
1 MiB souhrnný HTTP budget, timeout 10 s. USD strop není v profilu nastaven;
platí nastavené tokenové a časové limity a účetní omezení poskytovatele.
Obecné výzkumné profily, modely a rozpočty se nemění.

Tento test ověřuje živý model → SDK tools → HTTP → soubor → host receipt.
**Neprokazuje schopnost objevit veřejnou službu, překonat její autentizaci ani
dlouhodobě něco archivovat.** To bude samostatný další test.
`run-http.cmd` zůstává launcherem obecného HTTP výzkumu s approval defaultně zapnutým.
`run-smoke.cmd` nadále testuje PyPI/Docker/CBOR.

## Přerušení a pokračování

Standardní `pause` / `resume` funguje. Zadej skutečnou vypsanou cestu běhu:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py pause "G:\metaweb-swarm-runs\ID_BEHU"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\ID_BEHU" --backend openai
```

Služba se po skončení/pause běhu vypne. Objekt zůstává v adresáři běhu
`http-smoke-service/object.txt`; při resume se služba obnoví a přednostně
použije stejný port. Je-li obsazený, dostane nový port, který agent vidí
v aktuálním zadání; musí znovu přečíst dokumentaci a provést sekvenci na nové
adrese. Původní HTTP záznamy zůstávají v auditu. Nejisté mutace se automaticky
neopakují. Úspěšný read-back dokládá shodu v okamžiku testu, nikoli trvalost.
Technické překážky jsou BLOCKED; chybějící receipt vyžaduje další práci
v dostupných kolech a po jejich vyčerpání LIMIT_REACHED.

## Ověření bez API klíče

```cmd
G:\metaweb-swarm-env\Scripts\python.exe -m unittest tests.test_http_smoke -v
```

Testy používají skutečný HTTP server a skutečné OpenAI Agents SDK s lokálním
scripted model providerem. Nevolají placené inference a neposílají soubory
na veřejný internet. Ověřují úspěšnou sekvenci, nesprávné scope, chybějící
dokumentaci/receipt, odlišné bajty, pause/resume a pravdivost reportu.
Průchod těchto testů nenahrazuje následný běh s živým modelem.

Další krok po PASS: [veřejný HTTP test](HTTP_PUBLIC_SMOKE.md), `run-http-public-smoke.cmd`.
