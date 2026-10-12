# 0.5.5 — rozhodnutí o kandidátovi a dokončení práce role

## Kritika

record_critique má decision_basis:
- SETUP_GAP: chybí účet/credential/resource.
- CAPABILITY_GAP: chybí executor či jiná technická schopnost.
- EVIDENCE_GAP: dosud neověřená fakta, neznámá kompatibilita formátu nebo neprovedený test.
- MECHANISM_FAILURE: konkrétní negativní vlastnost mechanismu.
- UNSPECIFIED: původní tříparametrový contract.

V kvalifikovaných deposit bězích se REJECT bez doloženého MECHANISM_FAILURE ukládá jako REVISE. Audit zachová requested_verdict, verdict_adjustment i původní reason. Nejde o odstranění názoru modelu.

Skutečné REJECT vyžaduje failure_kind, failure_fact doslova citovaný z podkladu a negative_evidence_urls, které nezávislý auditor sám četl přes read_document. Vlastní objevitel si negativní tvrzení necertifikuje. Samotná absence zmínky o EPUB není explicitní zákaz EPUB; chybějící klíč či neprovedený upload není selhání mechanismu. Host ověří přítomnost doslovné citace v nezměněných bajtech vlastního zachyceného dokumentu. Formální pole/receipt neprokazují pravdivost tvrzení ani jeho interpretaci; jejich věcný význam stále potřebuje posouzení.

Takto doložený REJECT může označit kandidáta REJECTED. Pozdější mezera v setupu nesmí přepsat stejné podložené zamítnutí. Nová kvalifikace varianty vyžaduje nové posouzení. PASS má stále původní tvrdé podmínky na aktuální plán, cenu, vlastní zdroje, credential/executor readiness a approval před realizací.

## Dokončený audit

Stav role není verdikt kandidáta. Jestli auditor deklaruje hotovou práci (COMPLETED nebo REJECTED) a pro všechny aktuální přidělené kandidáty existuje jeho critique na aktuální QUAL, host uloží dokončení práce jako COMPLETED. Budoucí account/upload/test se přesune do handoff_leads, bez ztráty textu. Kandidát může zůstat BLOCKED/REVISE.

Bez aktuální critique host nepřijme tvrzení o dokončení: AUDIT_RECEIPT_REQUIRED. Pokud auditor výslovně CONTINUE potřebuje další podklad, tento stav se neukončuje automaticky. Human approval, neznámý budget/outcome a skutečné technické blokace se nemění.

## Krátký úkol na protokol

record_deposit_flow(qualification_id, operation_steps, unknown_reason) upraví jen vlastní existující admissible QUAL objevitele. Není nutné znovu skládat celý deposit plan nebo IDEA:
- známé kroky: uložit skutečně popsané reserve/send/finalize a credentialed reads;
- neznámý protokol: operation_steps=[] a konkrétní unknown_reason;
- host přepočítá akce, znovu kvalifikuje a ponechá stejné IDEA ID;
- nic se nenahrává, negeneruje se credential ani neověřuje preservation.

Ve focused běhu s require_explicit_upload_flow a čekajícím plánem nastaví první SDK request tool_choice na record_deposit_flow. SDK reset_tool_choice po nástroji vrátí běžný režim. V tomto kroku se neprovádí web search; další primární podklady zůstávají dostupné přes read_document. O explicitní nejistotě se lze po dočtení podkladů vrátit k nové kvalifikaci.

Po zachycení známého či neznámého protokolu je tato plánovací práce hotová a setup/execution se předá dál. Jestli model nástroj vůbec nezavolá, FLOW_NOT_RECORDED zastaví tuto úlohu jako BLOCKED; zopakování starého závěru není pokrok. Obecný research režim ani ostatní role se na tento nástroj nenutí.

Oficiální API contract pro forced function/strict schema: https://developers.openai.com/api/docs/guides/function-calling#tool-choice . Ověřeno i na nainstalovaném Agents SDK bez API klíče s kontrolovaným modelem.

## Aktuální NudgeHost

Ukládaný protokol z již zachycených API docs je POST reservation → PUT přes vrácený signed URL → POST completion. Host tedy počítá nejméně 3 externí akce, nikoli 1. Žádná z těchto akcí nebyla provedena. Signed URL v dokumentaci je vzor, nikoli skutečný přístupový odkaz.

Stále chybí vyhrazený credential, dostatečný action limit a vícekrokový kvalifikovaný executor. Podpora přesných EPUB bytes není nezávisle potvrzená. Kandidát zůstává BLOCKED; původní verdict s chybějícím setupem je REVISE. Tato aktualizace nic z toho nepředstírá ani nepovoluje.

Dále není potřeba prodlužovat starý run jen kvůli těmto dvěma účetním/rozhodovacím chybám. Další implementační krok je obecný vícekrokový executor; následné skutečné ověření vyžaduje přidělené zdroje a aktuální nezávislý audit.


## Validace a oprava původního runu

Celá sada: 383 testů OK, jeden Windows symlink test přeskočen. Poté přidáno ověření doslovné source quote a změněných/forged source bytes; finálních 31 cílených regresí OK (včetně 13 review/flow scénářů). Skutečný SDK test potvrzuje forced první tool a reset do auto po capture, zachování action limitu a BLOCKED při pouhé naraci.

Před opravou aktuálního runu vznikla kompletní záloha checkpointu/SQLite/event logu/reportů. Staré modelové výroky nebyly odstraněny. Nová klasifikace a doplnění tří kroků jsou výslovně OPERATOR_WORKFLOW_REPAIR; žádný nový independent model review, inference, upload ani grant nevznikl. Výsledek a zdrojový hash jsou v docs/validation/REVIEW_FLOW_REAL_RUN_CORRECTION.json.
