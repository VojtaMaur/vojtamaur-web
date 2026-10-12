# Veřejný HTTP smoke test (0.4.2)

V původním CMD, kde už je nastavený `OPENAI_API_KEY`:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-http-public-smoke.cmd
```

Založí **nový běh** se dvěma rolemi a `gpt-5.4-mini`.
Není potřeba Docker. Klíč se zadává stejně jako předtím; launcher jej zachová.

## Co agent udělá

Načte a přečte [API dokumentaci](https://tmpfiles.org/api) a
[podmínky](https://tmpfiles.org/tos). Sám sestaví multipart upload malého
hostem připraveného TXT, zpracuje odpověď, případnou informační stránku
a skutečný odkaz na stažení. Přes obecný `http_request` stáhne bajty
a zavolá `verify_http_copy`.

Framework nemá connector tmpfiles.org, implementaci jeho endpointu,
parser jeho upload response ani pravidlo přepisující jeho download URL.
Profil jen přiděluje HTTPS origin a adresy dokumentace/podmínek.
Stejný profil lze použít pro jinou vhodnou službu po úpravě
`http_smoke_service` v konfiguraci. Rozhraní služby zjišťuje model.

`multipart_files` je pole objektů s `field`, `path`, volitelně `filename`
a `content_type`; `multipart_fields` je objekt textových hodnot.
Název file fieldu a endpoint musí agent zjistit z dokumentace.
Multipart boundary vytváří transport; Content-Type agent nemusí nastavovat.

## Úzký rozsah tohoto testu

- Jen HTTPS origin `https://tmpfiles.org`; žádné jiné služby ani lokální porty.
- Jediný POST pokus, i když skončí chybou. Nejistý výsledek se automaticky neopakuje.
- Upload může obsahovat pouze připravený syntetický soubor
  `context/HTTP_SMOKE_INPUT.txt` se správným hashem. Přidaná form metadata
  smějí být jen krátké číselné řetězce (například expiry).
- Žádné exporty webu, účty, credentials, Git změny, balíčky ani experimenty.
- Approval je pro tento již autorizovaný neškodný test vypnuté.
  Obecný výzkumný `run-http.cmd` má nadále approval defaultně zapnuté.
- Stropy: 5 globálních kol, Prototyper 3 a Reporter 1, 500 000 tokenů,
  1 200 s, 12 HTTP požadavků, 64 KiB na tělo, 1 MiB souhrnně, timeout 30 s.
  USD strop není nastaven; volání modelu jsou placená.

Tmpfiles.org je **dočasné úložiště**, nikoli preservation mechanism.
Jeho API uvádí výchozí expiraci 3 600 s. [Zdroj](https://tmpfiles.org/api).
Služba automaticky soubor odstraní; tento test neslibuje dlouhodobou zálohu.
Vzorek neobsahuje web, osobní údaje, tajemství ani credentials.

## Jak poznáš úspěch

Konzole musí vypsat:

```text
HTTP public smoke: PASS, docs/terms read + upload + download + matching SHA256
COMPLETED: ...
```

V `manifest.json` bude `http_smoke.public_network=true`,
`http_smoke.passed=true` a host receipt s ID dokumentace, podmínek,
uploadu, downloadu, veřejným místem stažení a SHA256.
`preservation_deposit=false`; kandidátů i ověřených preservation depositů je 0.
Report používá označení veřejného HTTPS integračního testu.
HTTP 200 samo nestačí; HTML download stránka také nestačí.

Pokud služba odpoví chybou, CAPTCHA, rate limitem nebo nejistým výsledkem,
správný výsledek je konkrétní BLOCKED/LIMIT_REACHED se zachovaným auditem.
Model ji nemá obcházet, přepínat na jiné služby ani upload opakovat.
`pause` / `resume` zachovává stejné vstupní bajty, limity a pokusy; služba
běží veřejně nezávisle na swarmu a objekt může mezitím expirovat.
Pak tento run nemůže tvrdit úspěšný read-back.

## Ověření implementace

Dne 2026-10-08 proběhl skutečný jednorázový multipart upload 115 bajtů na
veřejné tmpfiles.org přes generický transport. API GET a ToS GET vrátily 200,
upload 200, následovala veřejná informační stránka a samostatný download 200.
Stažené bajty měly stejný SHA256. Bez účtu, API klíče či placené inference;
šlo o hostem řízené ověření přenosu, nikoli o živý agentní run.
Evidence: [HTTP_PUBLIC_PREFLIGHT.json](validation/HTTP_PUBLIC_PREFLIGHT.json).
Dočasná URL může později přestat fungovat, audit zůstává.

Regresní testy používají skutečné Agents SDK se scripted providerem a
simulovanými HTTPS odpověďmi, včetně jiných názvů parametrů a tvaru odpovědí,
aby se neověřoval jen jeden provider. Prokazují omezení scope/payloadu,
čtení dokumentace, jediný pokus a práci s HTML download odkazem.
Nevolají internet ani placené modely:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe -m unittest tests.test_http_public_smoke -v
```

Živý levný model ověří až výše uvedený projektový launcher.
Lokální test `run-http-smoke.cmd` a PyPI/Docker test `run-smoke.cmd` zůstávají zachovány.

## Diagnostika od 0.4.3
Selhání DNS/spojení/TLS před odesláním HTTP požadavku je FAILED s konkrétní sanitizovanou příčinou, nikoli nejistý upload. UNKNOWN zůstává pro nejasný efekt odeslaného požadavku nebo nekategorizovanou chybu. Run 20261008-075301-f0c7fcfa selhal už na dvou GET; nic nenahrál. Přesná příčina nebyla starou verzí uchována a při následné kontrole oba GET fungovaly. Nový běh spustíš stejným projektovým launcherem; pokud síť opět selže, audit již uchová konkrétní diagnostiku.

## Kontext testu od 0.4.4
Test je osobní a nekomerční. Agent musí číst kvalifikátory v podmínkách přesně: zákaz komerční automatizace se nemá rozšířit na veškerou automatizaci. Výslovný zákaz veškeré automatizace či tohoto nekomerčního použití stále znamená BLOCKED. Reporter dostává důvod zastavení a shrnutí ostatních rolí.

## Úspěšný živý veřejný test — 2026-10-08
Run `20261008-084548-bd404437` s gpt-5.4-mini dokončil čtení API/ToS, vlastní multipart POST, inspekci HTML informační stránky, samostatný download a host SHA256 receipt. Skutečné vstupní a stažené bajty se shodují (115 B); 5 HTTP požadavků, 2 agentní kola, 14 modelových požadavků, 105 380 tokenů, 140 ověřených auditních událostí. Oba agenti COMPLETED; žádné kandidáty ani preservation deposit nevytváří. Prokázána obecná veřejná HTTP práce živého levného modelu bez connectoru či účtu. Dočasná služba a malý syntetický vstup neprokazují dlouhodobé uchování, velké exporty ani schopnost samostatně vybrat neznámou službu.
