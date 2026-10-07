# Režimy roje a oprávnění

Pracovní dokument frameworku; nic z něj se zatím nevkládá do dokumentace webu.
Instalace a příkazy: [README](../README.md). Docker: [DOCKER_SETUP](DOCKER_SETUP.md).

## Tři nezávislé volby

| Nastavení | Význam | Výchozí hodnota |
|---|---|---|
| `run_mode` | `supervised`: výzkum může skončit reportem, realizace čeká na rozhodnutí; `autonomous`: agenti mohou sami přejít k prototypům a testům | `supervised` |
| `external_scope` | `sandbox-only`: bez vnějších zápisů; `external`: dovoleny pouze explicitní zdroje v `external_resources` | `sandbox-only` |
| `approval_required` | Schválení konkrétní vnější akce před provedením | `true` |

| Kombinace | Chování |
|---|---|
| supervised + sandbox-only | Autonomní výzkum, report a zachované kandidáty; realizace až po lidském rozhodnutí |
| autonomous + sandbox-only | Výzkum, kritika, prototyp a test v soukromé kopii; bez uploadu/depositu |
| autonomous + external + approval=true | Prototyp a test samostatně, konkrétní deposit se připraví ke schválení |
| autonomous + external + approval=false | Deposit přes povolený connector bez další skryté schvalovací brzdy; všechny ostatní meze platí |

Neuskutečněný dobrý nápad není `REJECTED`. Rozlišuje se výzkumný stav kandidáta,
stav realizace a stav konkrétní akce. `BLOCKED` znamená skutečnou překážku,
`LIMIT_REACHED` vyčerpanou mez, `REJECTED` doložené zamítnutí nebo vlastníkovo
odmítnutí směru. Úspěšné ukončení výzkumu samo neznamená hotovou archivní vrstvu.

## Provádění a evidence

Záměr je discover → verify → critique → prototype → test → deposit → read-back →
evidence → pokračování. Kód kontroluje návaznost: známý kandidát, přípustný platební
model, zaznamenaná kritika `PASS`, skutečné úspěšné provedení testu a vázané bajty.
`record_test` dokládá exit-zero sandbox experimentu a hash artefaktu. Samo neprokazuje,
že test opravdu měří obnovitelnost nebo že kritika je správná; to musí být vidět
v testu a jeho tvrzeních.

Dosud jsou implementovány pouze nulově placené connectory:

- `local_directory`: nový soubor v explicitní složce mimo produkci a run, následné
  SHA256 čtení; odlišné existující bajty se nepřepisují.
- `http_put`: explicitní HTTPS endpoint, podmíněný PUT a následné GET/SHA256.
  Endpoint musí skutečně respektovat `If-None-Match: *`; klient odmítá redirecty.
  HTTP na loopbacku lze výslovně povolit pro test. Credential je vyhrazená hostitelská
  proměnná prostředí, nikoli API klíč OpenAI nebo hodnota v agentním promptu.

Vytváření účtů, platby, specifická API archivních služeb, zprávy a obecné nasazování
produkčního kódu zatím nemají executor. Vypnutí approval tyto schopnosti nevytváří.
Závislost na průběžném předplatném zůstává odmítnutým kandidátem; jednorázová cena
může být přípustný návrh, ale současné connectory žádnou platbu neprovedou.

Před vnějším pokusem se do SQLite zapíše rezervace. Po pádu je nejistá akce
`UNKNOWN`/`RESERVED`, nikoli automaticky úspěšná ani potichu znovu provedená.
Výsledná evidence obsahuje přesné místo, velikost, SHA256 a způsob nezávislého čtení.
Pause/resume zachovává ledger, checkpointy i auditní řetězec.

Vnější connector běží jako pevný, zkontrolovaný hostitelský worker v samostatném
procesu. Nespouští agentem dodaný kód. Dostává pouze konkrétní parametry a vyhrazený
credential, má omezený JSON vstup/výstup a parent jej při časovém limitu ukončí
a vyčká na konec. Tento procesový deadline platí i pro endpoint, který pomalu
posílá HTTP hlavičky a nedosáhne běžného socket idle timeoutu. Po takovém přerušení
mohl upload již proběhnout: ledger zachová nejistý výsledek a vyžaduje kontrolu cíle.

## Tvrdé meze a jejich rozsah

Tokeny, aktivní čas, kroky, počet externích pokusů, velikost přenesených dat a zdroje
jsou kontrolované hostem. Při nastaveném dolarovém rozpočtu musí operátor uvést
konzervativní jednotkové cenové stropy: rezervace před placeným požadavkem brání
zahájení požadavku, jehož odhad by se nevešel. Nejde o nezávislé měření faktury;
skutečné účtování poskytovatele závisí na správných cenách a případných dalších poplatcích.

Docker dostává pouze soukromou kopii, bez credentialů a Docker socketu. Runtime
má `--network none`; nástroje se připraví v image nebo instalují z připravených
offline balíčků. CPU, RAM, PID a timeout mají meze. **Tvrdá disková kvóta writable
hostitelského bind mountu není implementována.** Limit importu a kontrola velikosti
artefaktu jí nenahrazují. Chybějící Docker nikdy nevede ke spouštění agentního kódu
na hostu. Živé ověření konkrétní instalace je samostatný krok.

## Exporty a paměť generací

`exports` jsou vlastníkova připravená veřejná data: ZIP, EPUB, PDF, TXT a manifesty.
Při init se zachytí samostatně do `input_exports` s limity a hashy. Kontejnery ZIP/
EPUB se při importu nerozbalují; upload pořád podléhá výše uvedeným oprávněním.
Agenti mají upřednostňovat zálohu hotových buildů/exportů před změnami zdrojů a git push.

`context/PRIOR_RUNS.md` a odvozený `RUN_MEMORY.json` zachycují několik krátkých poznámek
z předchozích zastavených běhů. Jde o nedůvěryhodné výzkumné záznamy, nikoli seznam
implementovaných vrstev. Zamítnutí, blokery a testované/neotestované artefakty jsou
oddělené. SQLite každého původního runu zůstává autoritou; odvozený index lze vytvořit znovu.
