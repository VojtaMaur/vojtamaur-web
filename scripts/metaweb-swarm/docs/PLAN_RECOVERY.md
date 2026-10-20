# Oprava plánů a review před realizací — 0.6.4

Run `20261013-043825-09e42a24` uchoval upload.am jako IDEA-0001, ale Prototyper
po odmítnutí Authorization/framing hlaviček označil opravitelnou chybu zadání
za BLOCKED. V jeho pokusu byly i odkazy na neexistující `reserve`, JSON obal
místo raw exportu a nulový byte ceiling u JSON `{}`. Konkrétní upload protokol
stále musí pocházet ze skutečné dokumentace; host ho za model nevymýšlí.

## Plánování bez credential hodnot

- `record_deposit_execution_plan` ukládá data, neposílá HTTP ani nežádá approval.
- Chybějící grant lze pojmenovat v `credential_id`, například `REQUIRED_CARRIER_KEY`.
  To je pouze požadavek na budoucí dedicated grant, ne token, environment lookup
  ani oprávnění. Přidělené grants se automaticky nerozšiřují na jiné origins.
- Chybějící credential může být doplněna do nového plánu pro kvalifikovaný
  ACCOUNT_REQUIRED/DEDICATED_CREDENTIAL target s dosud prázdným credential_id.
  Endpoint a method musí dál odpovídat původní kvalifikaci. Nová kvalifikace
  vyžaduje nové nezávislé posouzení; původní PASS ji nepovoluje.
- Už přidělený credential_id s nesprávným host scope je odmítnut i při plánování.
- Kvalifikace uloží ACCOUNT_SETUP_REQUIRED a přesný počet akcí. RESOURCE_LIMIT
  nebrání uchování přípustného datového plánu, ale brání realizaci.
- Executor kontroluje skutečnou připravenost kvalifikace i přidělení credential
  před vytvořením flow/approval a znovu před jednotlivými požadavky. Neznámý grant
  v přísné execution validaci nikdy neprojde. Limity, pricing, scope a nezávislý
  PASS zůstávají beze změny.

## Opravitelné chyby

Tool vrací `DEFERRED / PLAN_REVISION_REQUIRED` s existujícím IDEA/QUAL ID,
konkrétním `step_id`, kódem problému a dalším krokem. Rejected argumenty zůstávají
v původní SDK historii; nový host diagnostic ukládá fingerprint a bezpečný popis,
nikoli credential hodnoty nebo celé vadné hlavičky.

| Kód | Oprava |
|---|---|
| HEADERS_INVALID | Bez Authorization, cookies, Host, Content-Length a framing; autentizace přes credential_id. |
| BINDING_SOURCE_REQUIRED | Použít skutečné ID předchozího kroku a dokumentovaný JSON pointer. |
| EXACT_EXPORT_BODY_REQUIRED | sends_export=true, body_json="", max_body_bytes přesně podle retained exportu. |
| BODY_CEILING_REQUIRED | JSON `{}` posílá dva bajty; prázdné tělo je prázdný string. |
| CREDENTIAL_ORIGIN_MISMATCH | Opravit scope požadavku; existující grant se nepředává cizímu hostu. |
| QUALIFIED_FIRST_REQUEST_MISMATCH | Zachovat kvalifikovaný endpoint, method a credential; nehádat nové API. |

Model opravuje stejný kandidát v aktuálním tahu nebo dalším bounded kole. Pokud
po známém diagnosticu tvrdí BLOCKED/COMPLETED, host ponechá opravu jako CONTINUE.
Třetí identický odmítnutý plán zastaví jako PLAN_REPAIR_STALLED; existující kola,
tokeny, USD a runtime stále omezují i různé neúspěšné pokusy. Úspěšné zaznamenání
plánu dokončí pouze planning-only roli a předá account/resource/review překážky.
Není to dokončený deposit. Rozpracovaný/nejistý externí flow nelze přepisovat
touto opravnou cestou.

Starý konkrétní header error lze při resume poznat z párového tool call/output
v checkpointu. Neobnovují se role podle volného vyprávění nebo obecného slova
BLOCKED. Obnova neproběhne při existujícím externím flow, zamítnutém kandidátovi,
nepřípustné kvalifikaci nebo vyčerpaných kolech. Platně uložený plán znovu nevytahuje
starý diagnostic z historie.

## Review před uploadem

`record_critique` pro deposit kvalifikace zaznamenává stage PRE_DEPLOYMENT,
`execution_receipt_required=false` a aktuální hostem zjištěné setup blockers.
Auditor hodnotí primární podklady, platební model, formát, API, custody a konkrétní
bindings. Chybějící účet, flow nebo zdroj mohou zůstat REVISE.

Formulace, která při takovém posouzení vyžaduje budoucí dokončený upload/deposit
nebo public read-back, vede k DEFERRED s konkrétní opravou review; nevzniká
automatický PASS ani nové REJECTED. Jde o úzkou kontrolu nevhodného kritéria,
nikoli sémantické rozhodování o pravdivosti tvrzení. Model má odstranit tento
požadavek a zaznamenat skutečné evidence/setup gaps. Tři identické vadné pokusy
se nepřetáčejí neomezeně. Získaný konkrétní MECHANISM_FAILURE se source proof
zůstává posuzovatelný původním kontraktem.

Skutečná byte-exact verifikace po realizaci dál vzniká až z host execution
receipts. Nová stage nepovoluje HTTP, nenahrazuje audit a neoznačuje netestovaný
upload jako úspěšný. Historické critique texty instalace zpětně nepřepisuje.

## Další CMD

V projektové složce lze pokračovat v témže runu bez dalšího navyšování kol:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261013-043825-09e42a24" --backend openai
```

Prototyper má ve stávajícím rozpočtu nevyužitá kola. Dalším cílem je konkrétní
uchovaný plán a jeho aktuální audit/setup seznam. Účet ani navýšení externích
akcí tato změna nepřiděluje; instalace ponechává původní run i config beze změny.
Souhrnný run může dál být LIMIT_REACHED kvůli dříve vyčerpané discovery roli,
i když planning fáze dokončí svůj úkol. Čti konkrétní IDEA, plán a receipts.

Regrese obsahují skutečný SDK průchod vadné hlavičky → oprava → plán čekající
na chybějící klíč, retry nevhodného review kritéria, checkpoint recovery,
ochranu host scope a nulové uploady/approvals z plánovacích operací. Modelové
odpovědi jsou řízené fixtures; živý levný model je další ověření.
