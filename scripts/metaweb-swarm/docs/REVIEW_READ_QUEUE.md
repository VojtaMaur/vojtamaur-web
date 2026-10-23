# Fronta povinných čtení auditu (0.8.4)

## Příčina

Výběr nástroje byl řízen frameworkem, ale cestu a rozsah stále určoval model.
Auditor tak mohl opakovat již přečtený soubor, zatímco jiná zachycená část zdroje
zůstala nepřečtená. Vyčerpání 12 modelových tahů nebylo výsledkem nové sondy.

## Chování

Pouze SDK nástroj `read_test_artifact` při povinném čtení obslouží další chybějící
rozsah z přiděleného testu. Výstup `path`, `offset`, `end` a `source_lines` vždy
popisuje skutečně přečtenou evidenci. `dispatch_binding` a událost
`prototype_review_read_bound` zachovají požadované i obsloužené parametry.
Po vyprázdnění fronty zůstává volné čtení podle parametrů. Přímé ToolAPI čtení
se nemění. Hash kontroly, oddělení autor/auditor a povinná behaviorální sonda
zůstávají stejné. Žádné čtení není označeno za hotové bez vrácení jeho obsahu;
binární hash kontrola neznamená dekódování nebo prokázání mechanismu.

Kontextový klíč 0.8.3 zůstává, aby resume nezahodil dokončená čtení. Aktualizace
nemění checkpoint ani limity. Limit role lze při resume rozšířit o jedno kolo;
globální token/runtime limity stále platí. Nezakládat nový discovery běh jen kvůli
tomuto opravenému auditu.

## Ověření

38 testů prošlo (`test_review_read_queue`, `test_audit_environment`,
`test_local_contract`, `test_prototype_review`), včetně SDK s opakovanými požadavky
na stejný soubor. V kopii skutečného checkpointu se poslední opakovaný požadavek
přesměroval na nepřečtený `prototype/rss_pointer.py`. Jedno čtení dokončilo frontu,
po host facts byly dostupné `run_review_probe` a `install_packages`.
To ověřuje navigaci, ne nový úspěšný modelový audit nebo nový funkční prototyp.
[Replay evidence](validation/REVIEW_READ_QUEUE_LIVE_PROOF.json).
