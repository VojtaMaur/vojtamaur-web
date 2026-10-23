# Nový kontext musí skutečně znovu přečíst důkazy — 0.7.10

Pokračování 20261022-051417-8cb93cc5, auditor round 3, skončilo po třech stejných
citacích vymyšleného kódu. Verze 0.7.9 správně nevytvořila verdikt a skončila
BLOCKED. Neopravila ale celý vstup modelu: concise_state znovu připojil historický
prototype_reviews s falešnými citacemi a současně zůstala platná metadata own-read
z předchozího kontextu. Po archivaci historie model nedostal skutečný script,
ale host rovnou vynucoval jeho posudek. Je to chyba předávání důkazů, nikoli důvod
vypnout jejich ověřování nebo navýšit budget.

## Oprava

Přehled review obsahuje jen ID, test/idea/agent, review_unresolved a platný verdikt.
Nevkládá znovu modelové code quotes, reason ani jiné staré posudky jako zdrojový
kód. Nevyřešený historický posudek má v přehledu verdict=null. Plná historie je
zachována v checkpointu/auditu a explicitních report detailech.

Při změně modelového task kontextu pro PROTOTYPE_TEST se zneplatní pouze vlastní
read/fact/check metadata a neplatné pokusy pro přidělený test. Audit původních čtení
se nemaže. Následující dispatch vyžaduje read_test_artifact pro celý skutečný
zachycený script a potřebné výstupy, potom host facts, teprve pak review.
Opakovaná příprava stejného kontextu nic znovu nemaže, takže se čtení mohou dokončit.
Protokol fresh-review-0.7.10 vyvolá tento reset i při upgradu existujícího běhu.

Verdikt stále určuje auditor podle skutečného kódu a negativního případu. Změna
neschvaluje aktuální vadný negativní test, neposkytuje nové credentials, oprávnění
ani budget. Backend stále zastaví opakované neplatné posudky bez vymyšleného REVISE.

## Ověření

Regrese nyní kontroluje obsah skutečného Engine.prompt, archivaci staré historie,
zneplatnění starých read metadat, povinné čtení zdroje/výstupu/facts v tomto pořadí,
stabilitu čtení uvnitř stejného kontextu a zachování původní auditní evidence.

Přehrání skutečného checkpointu v oddělené kopii ukázalo první povinné čtení
prototype/test.py a prototype/recovery-seed.json. Nový Engine.prompt neobsahuje
falešný output/recovery_seed.json. Původní doložené REVISE z prvního auditu po
čerstvém čtení prošlo coderovi. Není to nový placený běh ani oprava/certifikace
Open Library prototypu. Viz validation/FRESH_REVIEW_LIVE_PROOF.json.

## Pokračování

Auditor je nyní skutečně BLOCKED, takže potřebuje explicitní unblock operátora:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py unblock "G:\metaweb-swarm-runs\20261022-051417-8cb93cc5" AGENT-006 --note "Opraven kontext auditu; znovu precist skutecny kod a vystupy"
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261022-051417-8cb93cc5" --backend openai
```

Instalace tyto příkazy nespouští. Stávající token/čas/USD/round limity se nenavyšují.
Budoucí správný úsudek modelu nelze zaručit; toto ověření dokládá opravený vstup
a předání, nikoli obecnou schopnost modelu auditovat libovolný kód.
