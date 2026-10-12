# Kvalifikace konkrétního deposit cíle

Aktuální interface 0.5.1: agent volá check_deposit_target s pojmenovanými poli přímo, bez vnořeného plan_json. Povinné minimum je provider, export_path a documentation_urls. Ostatní pole: upload_url, method (POST/PUT/PATCH), authentication, credential_id, required_external_actions, novelty_class, baseline_evidence_ids, baseline_behavior, proposed_change, validation_plan. SDK vystavuje typovaný JSON schema a enumerace; host sestaví původní interní plan a provede stejné limity/policy/audit checks.

upload_url může být prázdná, když ještě není známý skutečný write endpoint. authentication může být UNKNOWN, pokud nebyla ověřena ze skutečné API dokumentace. Host uloží neadmisibilní QUAL receipt se stavem TARGET_DETAILS_REQUIRED nebo AUTHENTICATION_UNVERIFIED a konkrétním dalším krokem. Chybějící endpoint nebo credentials se nemají nahradit smyšleným URL/ANONYMOUS. Veřejné stahování nedokazuje možnost anonymního uploadu. Stav UNKNOWN autentizace není síťový stav UNKNOWN mutace; ten dál zakazuje automatické opakování.

KNOWN_CARRIER bez odpovídajících BASE IDs vyžaduje doplnění baseline comparison, ne automatické přijetí. UNASSESSED stejně vyžaduje posouzení. ACCOUNT_SETUP_REQUIRED může zachovat doložený účetní setup lead u konkrétního jinak způsobilého targetu. Zakázaný write cíl má přednost před account setup i neznámou autentizací.

Konkrétní zakázané hosty a subdomény (forges i produkce) focused prompt přebírá přímo ze stejného seznamu HTTP executor policy. Dedicated credentials je neodemykají. Read-only dokumentace z těchto hostů obecně není zakázaná; discovery assignment je však nemá vyšetřovat jako upload carrier.

Přijetí IDEA ani PASS nepotvrzuje trvalost nebo sémantickou pravdivost podmínek. Stále je nutný nezávislý Evidence Auditor, jeho vlastní doc-read receipts, přesně stejný kvalifikovaný target/export/grant a lidské schválení při zapnutém approval. Sdílený auditní read tento audit nenahrazuje. Viz [sdílené artefakty](SHARED_AUDIT.md).

## Historie původního no-network gate (0.4.9)

# Kontrola proveditelnosti před IDEA (0.4.9)

Cílený deposit trial používá `require_deposit_qualification: true`. Ostatní profily mají false a zůstávají kompatibilní se starými checkpointy. Nejde o provider connector ani seznam podporovaných služeb. Objevitel zjistí neznámé API a zavolá `check_deposit_target` s konkrétním plánem. Host nic neposílá; používá stejné URL/metodové zákazy jako HTTP executor, skutečný export inventory, explicitní granty, runtime přítomnost dedikovaného tokenu a limity. Zkontroluje též pozorované zdrojové URL a BASE receipts.

## Přesné rozlišení

- POLICY_FORBIDDEN: zápis do chráněných forge/produkce nebo git receive-pack. Ani token či human approval to nezpřístupní.
- ACCOUNT_SETUP_REQUIRED: jinak doložený plán nemá přidělený dostupný token pro přesný cílový host. Uchová se jako BLOCKED kandidát, nikoli zamítnutá myšlenka.
- RESOURCE_LIMIT: požadovaná velikost/počet externích kroků neodpovídá rozpočtu. Approval limity nezvyšuje.
- BASELINE_COMPARISON_REQUIRED: cílový host/provider je zmiňován v ARCHIVE.txt nebo nebyla posouzena novost. Zmínka sama neprokazuje realizaci; vyžaduje konkrétní srovnání. Nepředstíráme sémantické rozhodnutí v kódu.
- ALREADY_KNOWN_BASELINE: agent výslovně označil známý carrier a doložil odpovídající skutečné BASE IDs. To není další nový kandidát tohoto trialu.
- PRIMARY_SOURCES_REQUIRED: plán nemá nejméně dvě vlastní pozorované dokumentační/terms URL.
- READY_FOR_AUDIT: technické předpoklady prošly; neznamená ověřenou pravdivost podmínek, novost ani trvalé uchování. Auditor čte stejné plánované zdroje nezávisle a posoudí konkrétní změnu/retenci/cenu/eligibilitu.

Zakázané či neúplné plány nedostanou IDEA ID; zůstávají v deposit_qualifications, reportu, manifestu a auditu. Novou IDEA může založit pouze discovery role s vlastním přípustným QUAL receipt. Auditor/Prototyper pouze revidují existující IDs; nemohou doplnit chybějící discovery vlastním vymyšleným kandidátem.

## Plán pro obecný nástroj

Všechny klíče jsou povinné. URL a službu vybírá agent z aktuálních primárních dokumentů, example.org níže není přednastavená služba:

```json
{
  "upload_url": "https://api.example.org/upload",
  "method": "POST",
  "authentication": "ANONYMOUS",
  "credential_id": "",
  "export_path": "soubor_z_list_exports.epub",
  "required_external_actions": 1,
  "documentation_urls": ["https://example.org/api", "https://example.org/terms"],
  "provider": "Concrete service name",
  "novelty_class": "POTENTIALLY_NEW",
  "baseline_evidence_ids": [],
  "baseline_behavior": "",
  "proposed_change": "",
  "validation_plan": ""
}
```

Authentication je ANONYMOUS / DEDICATED_CREDENTIAL / ACCOUNT_REQUIRED; jde o doložené tvrzení agenta, nikoli automatickou detekci cizího API. `required_external_actions` zahrnuje upload, authenticated GET a všechny další privileged kroky. SDK argument je `interní plan`, tedy JSON string této struktury. `submit_idea` dostane přesné `qualification_id` vrácené nástrojem a stejného providera. IMPROVEMENT vyžaduje skutečné odpovídající baseline IDs a konkrétní baseline_behavior/proposed_change/validation_plan; audit stále posuzuje, zda změna není jen přejmenování známé služby.

Host uloží plán, původ, export hash/velikost, výsledek a důvody. V konzoli krátce vypíše host a stav. Opakování nezměněného plánu se stejným výsledkem nevyrábí další receipt. Kontrola neposuzuje budoucí DNS dostupnost ani úplný multipart overhead; skutečný transport a approval znovu kontrolují finální požadavek a tvrdé limity.

## Audit, approval a pokračování

PASS musí přijít od nezávislého Evidence Auditor, který pozoroval přesné plánované docs/terms URL a sám stáhl úspěšné, nezkrácené GET odpovědi a přečetl jejich nezměněné bytes přes read_file. Search odkazy samotné nestačí. Záznam dokládá přečtený rozsah, ne porozumění nebo nutně celý dokument. PASS je navázán na konkrétní QUAL ID. Změna cíle, exportu, autentizace nebo plánu vyžaduje novou kvalifikaci a nový audit; starý PASS neplatí. Upload musí mít přesnou kvalifikovanou URL/metodu/grant a jediný soubor s původním export hashem/velikostí. Pak dál platí původní hash-bound human approval. Bez approval_required nevzniká žádné druhé lidské schválení; explicitní technické kvalifikační/auditní předpoklady zůstávají.

Pokud discovery nevytvořilo žádný přijatý kandidát, host přeskočí placené volání auditora a realizátora. Pokud nezávislý audit neschválí proveditelný plán, realizátor rovněž nedostane placené volání. Reporter a deterministický report přesto shrnou výsledky. BLOCKED zde znamená konkrétní nesplněný předpoklad, ne důkaz že mechanismus obecně neexistuje.

Pro další pokus stačí v projektu `run-deposit-trial.cmd` (nový run). Původní limity/modely se nemění. Samostatné účty/tokeny jsme automaticky nevytvořili ani nepřidělili. Přidělení popisuje [DEPOSIT_TRIAL.md](DEPOSIT_TRIAL.md). Přihlašování přes browser, e-mail/CAPTCHA nebo automatický onboarding nového tokenu zatím nemají executor.
