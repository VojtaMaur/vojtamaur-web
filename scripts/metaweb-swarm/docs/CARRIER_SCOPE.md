# Nové služby, nikoli přejmenované existující kopie — 0.6.1

Run `20261012-120434-827d6ccf` nevyzkoušel realizátor: 14 modelových odpovědí,
204 614 tokenů, 3 započítané searches, 5 HTTP pokusů, žádná kvalifikace/IDEA/FLOW
ani approval/upload. Odhad podle operátorových cenových stropů byl $0,19555425,
nejde o údaj z billing účtu.

Zenodo i Figshare jsou skutečné registrované položky zachyceného ARCHIVE.txt,
se samostatnými DOI. Vyplnění tří polí improvement u běžného EPUB uploadu
otevřelo zkoumání Zenoda a jeho screening následně otevřel i dokumentaci Figshare.
Discovery navíc zaměnilo bezplatnost za anonymní upload. Žádný další účet
nebyl použit a žádný export odeslán.

## Oprava

`config.deposit-trial.json` má `allow_known_carrier_improvements: false`.
V tomto úkolu je každá registrovaná služba mimo výběr i s vyplněnými improvement
poli. Kontrola platí při screeningu i kvalifikaci, a nelze ji obejít označením
`POTENTIALLY_NEW` nebo `IMPROVEMENT`. Název a původní registrované URL/řádky/hashes
zůstávají v receipt. Rozpoznávají se také jednoznačné DNS brand/domain aliasy,
například `Figshare v2 API` na `docs.figshare.com`; neslučují se automaticky
odlišné produkty jako Cloudflare Pages a R2.

Obecný `config.json`/výzkumný profil má tento přepínač true. Ten umožňuje
**posoudit** skutečný rozdíl ve výzkumu, nikoli certifikovat jeho novost nebo
autorizovat upload. Chceš-li zkoumat vylepšení starých vrstev, patří to do tohoto
širšího zadání, ne do testu nové nezávislé služby.

Screening se nyní váže na aktuálního skutečného poskytovatele a přesný origin
`scheme://host[:port]`. Další dokumenty/paging/redirect na stejném originu znovu
screenovat nemusíš. Jiný docs/API origin musí mít vlastní screening pod stejným
skutečným provider názvem. Přechod na jinou službu vyžaduje její nový screen.
Před upload kvalifikací musí být vlastní screens pro origin endpointu i všech
primárních docs/podmínek. Žádné wildcardy nebo automatické přiřazení příbuzných
firemních domén. Source obsah zůstává untrusted a přesný protokol kontroluje auditor.

`CARRIER_DOCUMENT_ORIGIN_NOT_SCREENED` se vrací před HTTP i při práci s cache.
Konzole vypíše stručné odložení, stejné opakování se nevypisuje znovu. Auditor
může nezávisle číst své zdroje; tento routing je pro discovery, nenahrazuje review.
Scope neuděluje credentials ani oprávnění k externím změnám.

FREE znamená absenci platební závislosti pro danou variantu. Upload může vyžadovat
vlastní swarm účet/token. Nový doložený kandidát s chybějícím grantem se kvalifikuje
`ACCOUNT_REQUIRED` a zachová jako `BLOCKED/ACCOUNT_SETUP_REQUIRED`, nikoli REJECTED.
Veřejné čtení uloženého exportu se posuzuje odděleně od autentizace při zápisu.
Role nyní tuto hranici výslovně rozlišují. Prototyper má aktuální instrukce
k novému datovému vícekrokovému plánu; nepředstírá, že tři writes stojí jednu akci.

Staré focused deposit checkpointy bez přepínače mají přísnou výchozí interpretaci
„nový carrier“. Historický IMPROVEMENT_REVIEW není platným otevřením dokumentace
v přísném režimu. Původní běh ani jeho historii instalace nepřepisuje.

## Další spuštění

V CMD v `G:\vojtamaur-web\scripts\metaweb-swarm`, se stejným nastaveným API klíčem:

~~~cmd
run-deposit-trial.cmd
~~~

Je to **nový placený výzkumný běh**, nikoli resume starého runu nebo infrastruktury
smoke. Modely/peněžní/token/runtime/action/HTTP limity a approvals zůstaly stejné.
Tato oprava ověřuje směrování a zachování kandidátů; nezaručuje, že model najde
novou vhodnou službu. Limit 1 externí akce dál blokuje reálný tříkrokový deposit.
Ten se případně uloží jako plán s přesnými chybějícími grants/resources.

Lokální regresní scénář přehrává Zenodo pseudo-improvement → Figshare docs bez
jediného HTTP requestu. Samostatně ověřuje scope po restartu, cache/redirect,
nový FREE account-based BLOCKED kandidát, kvalifikační bypass a nainstalovaný SDK
s kontrolovaným modelem. Žádná placená inference ani veřejný upload.
