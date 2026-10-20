# Strukturované odkazy a pracovní historie (0.6.7)

## Proč

Run 20261013-043825-09e42a24 použil draft editor, ale v kole 7 smíchal JSON binding s URL šablonou a v kolech 8–10 vrátil neexistující source ID. Guard zastavil třetí stejnou chybu. Ve starší pracovní historii i příkladech nástroje byly chybné řetězce, které malý model opakoval. Žádný validovaný execution plan, approval ani upload nevznikl.

## Strukturovaný nástroj

`bind_deposit_step_response` dostává `idea_id`, aktuální `draft_sha256`, cílové `step_id`, `field` (url / headers_json / body_json), `source_step_id`, `response_pointer` a případně `target_pointer`, `url_prefix`, `url_suffix`.

- Source ID se vybírá ze skutečných předchozích kroků uvedených v `read_deposit_plan_draft.binding_sources`. Pokud existuje vlastní aktuální draft s validními ID, SDK schema omezí source na jeho skutečná ID. Schéma platí pro začátek daného SDK kola; po změně topologie je potřeba nové kolo. Host vždy znovu kontroluje konkrétní pořadí i aktuální hash, takže samotné členství v enum není permission.
- `response_pointer` je samotná RFC6901 cesta doložená dokumentací. Host sestaví binding syntax, nenavrhuje žádný endpoint, JSON field ani způsob autentizace.
- Pro celou vrácenou URL jsou target_pointer/prefix/suffix prázdné. Pro vložení hodnoty do path/query agent dodá literal prefix/suffix a host mezi ně vloží binding; executor hodnotu percent-escapuje. Authority nelze interpolovat. Prefix/suffix nesmí obsahovat další bindings a nadále podléhají origin/credential pravidlům.
- Pro JSON je target_pointer cesta do existujícího literal objektu/pole. Poslední klíč objektu může být agentem explicitně přidán; předci musí existovat. Prázdný target_pointer výslovně nahrazuje celé pole JSON bindingem. Původní ostatní literal data se zachovají. Vadný JSON se nehádá ani automaticky neopravuje; literal strukturu je potřeba nejdřív zapsat editorem. URL prefix/suffix jsou pro JSON prázdné.
- Po změně se validuje celá sekvence a vrací se další konkrétní chyba nebo nová kvalifikace. Změna nezachová platnost starého PASS/approvalu. Setup, přesné grants, hard budgets, chráněné hosty, jeden exact-byte export a veřejný GET zůstávají povinné. Formálně validní pointer sám neprokazuje sémantiku skutečné API odpovědi.

Host příklady s konkrétním vymyšleným source ID v popisu nástroje už nepodsouvá. Obecný datový editor i plný plán zůstávají pro literal údaje a změny topologie.

## Historie

Před další SDK rundou host archivuje celou původní historii, včetně hash v `history_compacted`. Z pracovního kontextu odstraňuje pouze spárované volání/výsledek známých čistě plánovacích nástrojů, pokud výsledek explicitně uvádí DEFERRED / PLAN_REVISION_REQUIRED; odstraňuje také stará spárovaná čtení UNVALIDATED_DRAFT. Tato chybná data a staré draft hashes se nevracejí ani v compaction inventory.

Výběr neodstraňuje úspěšné plány, dokumentační reads, externí operace, UNKNOWN/INTERRUPTED výsledky, nevrácená volání ani nejednoznačné/dvojité call IDs. Obecná stávající size compaction nadále může starší ostatní položky zkrátit či archivovat s pointerem; nový filtr jejich výsledek nevydává za úspěch. Aktuální kvalifikace, permissions, execution checkpoints a současný repair jsou nadále v úplném host task state. SQLite event chain, raw SDK odpovědi a původní historie se nemažou.

## Další běh v CMD

Po instalaci z `G:\vojtamaur-web\scripts\metaweb-swarm`:

```cmd
run-deposit-trial.cmd
```

To vytvoří nový izolovaný běh se stávajícím cheap-modelem a nastavením profilu. Automaticky nereaktivujeme zastavený starý Prototyper ani nenavyšujeme jeho budget. Pro pokračování starého běhu je nutné vědomě řešit jeho BLOCKED / vyčerpanou role allowance; saved draft nezmizí.

Ověření před instalací probíhá offline: strict Agents SDK schema a FakeProvider, lokální docs fixture, replay kopie skutečného runu, regresní testy. Neprokazuje uskutečněný veřejný deposit nebo schopnost živého modelu bez chyby zvládnout celý protokol. Příklady provider-specifických connectorů ani browser fallback se nepřidávají.

Oficiální pravidla strict function calling: https://developers.openai.com/api/docs/guides/function-calling .
