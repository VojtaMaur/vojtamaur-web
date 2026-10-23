# Dokončování prototypů — 0.7.5

Výzkumné profily s coding_backend=sdk_shell používají jednu frontu dokončování:
implementace → skutečné spuštění/capture → nezávislý audit → případná oprava →
nový audit. Záznam úspěšného spuštění sám neuzavírá lokální úkol.

Čekající capture blokuje nové implementace. REVISE má přednost před dalším
nápadem; posuzuje se poslední capture aktuální revize, nikoli libovolný starší
úspěch. Upozornění na konkrétní nemožnost nebo vyčerpaný limit ponechá práci
uloženou, neudělá z ní REJECTED. SUBCOMPONENT/FULL_MECHANISM přiděluje nezávislý
auditor podle dosavadního evidence kontraktu, nikoli plánovač.

Auditor dostane nové testy před nedokončeným předběžným research packetem.
Plánovač nedovolí spotřebovat poslední dvě kola auditora předběžným výzkumem.
Pro nový prototyp potřebuje alespoň dvě zbývající kola nezávislého auditora a
čtyři globální kola: coding, audit, případný re-audit a report. Oprava po REVISE
vyžaduje jedno zbývající auditní kolo a tři globální kola. To je minimální
rezerva, ne záruka dokončení: samotné čtení/audit může vyžadovat více kol a
tokeny, USD či runtime mohou skončit dříve. Jejich tvrdé kontroly zůstávají.

Není-li rezerva, další coding/discovery se nezahajuje a report uvede uchovanou
práci. PROTOTYPE_AUDIT_ROUNDS_REQUIRED a PROTOTYPE_CLOSURE_STEPS_REQUIRED jsou
technické důvody čekání, nikoli nové human approval. Host nezvyšuje žádný limit.
AWAITING_INDEPENDENT_PROTOTYPE_REVIEW se uvolní po posouzení; ostatní technické
nebo human blokace se automaticky neodstraňují. Pause/resume a původní auditní
receipts se zachovávají. Stará fronta se nejprve doposoudí, nové kopie nepřibývají.

Supervised výzkum bez vybrané implementace auditní rezervu nepotřebuje a smí
skončit jen reportem. Legacy backend a smoke profily si zachovávají původní tok.
SDK coding dostal také explicitní pokyn: povinný neúspěšný check musí vést
k chybě/nenulovému návratovému kódu. Stub místo reálné operace není hotový
mechanismus. Jde o instrukci modelu, nikoli automatický důkaz funkčnosti.

## Ověření a poslední run

10 nových offline kontrol zahrnuje skutečný Engine.run plánovací cyklus
s testovacími implementačními/auditními odpověďmi, čekání, opakovaný REVISE,
uvolnění po SUBCOMPONENT, vyčerpanou auditní kapacitu a supervised režim.
56 souvisejících regresí a 14 scheduling/reporter kontrol prošlo. Žádné API
volání nebo nový live Docker experiment touto opravou nebyly spuštěny.

Read-only replay checkpointu 20261021-074035-94074e37 správně zachoval pět
čekajících testů a zadržel další coding. Hypotetické rozšíření v paměti vybralo
nejprve auditora pro TEST-13a0519645564650. Původní checkpoint nezměněn.

Při ruční kontrole artefaktů lze z JSON chunků IDEA-0003 a IDEA-0004 obnovit
celý EPUB (1 294 314 bajtů, původní SHA256). Není tím prokázána SFC shoda,
oprava chybějících chunků ani ActivityPub publikování/federace. Obě PDF captures
nemají přílohy; opravený PDF i Zenodo report obsahuje false u ověření sidecaru.
IDEA-0005 má 239bajtový VVCSTUB, ne ověřený video nosič. Výsledky zůstávají
neposouzené nebo REVISE; tato oprava je zpětně necertifikuje.

## Spuštění

Nový běžný běh z projektu (Docker spuštěný, OPENAI_API_KEY ve stejném CMD):

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-http.cmd
```

Všechny tiery nadále gpt-5.4-mini, externí zápisy vyžadují approval. Není třeba
opakovat smoke. U posledního runu zůstává vyčerpaných 46 globálních kol a deset
kol auditora; samotné resume mu kapacitu nepřidá. Případné explicitní rozšíření
musí zahrnout auditní i globální rozpočet a respektovat zbývající tokeny/čas.
