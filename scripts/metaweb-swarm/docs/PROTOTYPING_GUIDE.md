# Jak dotáhnout prototyp

Tento playbook nemění žádná oprávnění nebo limity. Použij jen postup relevantní
k přidělenému mechanismu a nezaměňuj příklad za nový objev.

1. Rozděl implementaci na malou skutečnou operaci: encode/decode, API request/
   response, parse/validate. Ověř nepoškozený průchod dřív než poškození.
2. Pro složité algoritmy najdi skutečnou knihovnu a její primární dokumentaci.
   `install_packages` dovoluje obecné PyPI dependencies v izolaci. Neodstraňuj
   funkci, když knihovna chybí; oprav dependency nebo poctivě odlož práci.
3. Decoder čte uložený specimen, nikoli původní input. Potom ověř shodu s
   referencí a proveď přesně definovaný failure/recovery test.
4. Nonzero Docker exit je skutečné selhání. Host uloží zmrazený script a
   předá jej nezávislému auditorovi. Přečti `read_failed_experiment` a diagnosis.
   Oprav příčinu, ne poslední řádek tracebacku ani assertions.
5. Po změně scriptu aktualizuj `record_prototype_plan`: vyplň konkrétní
   `repair_notes` a rozhodující `repair_check`. Žádné TEST/EXPERIMENT ID
   nevymýšlej ani nepředávej; host je dohledá ze současného vlastního úkolu.
   Nezávislý auditor přečte zmrazený kód a zkontroluje, že skutečně testuje
   přidělený mechanismus. Během čekání neprováděj polling.
6. `execute_prototype(argv)` spustí schválený lokální kód a uloží execution
   receipt v jedné operaci. `record_test` ani další běh pro registraci nepotřebuješ.
   Kontrola relevance před spuštěním není potvrzení funkčnosti. Tu posoudí
   auditor až ze skutečných výstupů a executable pozitivních/negativních testů.

Příklad RS payloadu je v `context/recipes/rs_recovery.py`. Používá skutečné
Reed–Solomon kódování z [reedsolo 1.7.0](https://pypi.org/project/reedsolo/1.7.0/)
a samostatný checksum/hash; checksum sám chybějící data neopravuje. Známé
erasures zachovávají pozice ve frame, unknown errors mění bytes na stejných
pozicích. Smazání libovolných bytes bez indexů je problém synchronizace, nikoli
automaticky RS erasure. Příklad neověřuje tisk, optické skenování ani hosting.

Názvy formátů musí odpovídat skutečnosti: CRC32 není zkrácený SHA256 a soubor
`.cbor` není CBOR, když v něm je JSON. Použij skutečný encoder/decoder formátu.


Od 0.6.17 před implementací použij `prepare_prototype_input`: vrátí skutečný
obsah zachyceného exportu. Manifest je jen descriptor; pro FULL_MECHANISM
použij payload a skutečnou inverzní operaci. Metadata-only práce patří do
SUBCOMPONENT. Pro standardní formáty použij dokumentovanou implementaci a
nezávislý validator; vlastní podobný layout neoznačuj jako ověřenou konformitu.
Od 0.6.18 model-facing plánovací tool vůbec nemá pole pro opravná ID.
Low-level interní API je nadále validuje, avšak mapování provádí framework.
