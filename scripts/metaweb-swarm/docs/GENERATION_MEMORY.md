# Paměť generací a pokračování

Nový run načte uzavřené sousední generace read-only. Staré SQLite/checkpoint
ledgery nepřepisuje. `PRIOR_RUNS.md` je krátký lidský přehled; strukturální
inventář je v `context/prior-runs.json`, dostupný přes `check_prior_work`.
Zachycuje až 20 běhů v 8000 znacích stručných poznámek, maximálně 64 kandidátů
na běh a 200 dohromady. Starší/nadměrné/nečitelné/aktivní/demo běhy mohou být
vynechány. To se projeví v zachyceném indexu; paměť není úplný archiv všech běhů.

Každý kandidát má referenci `run_id/IDEA-id`, canonical mechanism key, provider,
popis, stav, další krok a odlišení artefaktů/testových tvrzení. Předchozí
výzkum se **nikdy automaticky nestává implementovanou Metaweb baseline**.
Nerealizovaný dobrý kandidát není zamítnutý. Owner rejections a ARCHIVE.txt jsou
samostatné autoritativní podklady.

Od 0.3.3 má `config.research.json` `prior_work_policy=continue`; paměť je jen
kontext a nová deduplikace porovnává pouze aktuální run. Následující potlačování
minulých návrhů je volitelná funkce při explicitním nastavení:

```json
"prior_work_policy": "novelty-first"
```

Discovery má hledat mechanismy odlišné od již probádaných, před web search
volat `check_prior_work(["provider", "format"])`. Host vrátí DEFERRED při
novém nezměněném návrhu odpovídajícím známému canonical key. Výsledek nese
originální reference, nevytváří další IDEA a nezamítá původní výzkum.
Odložení se stručně ukáže v CMD, auditu i reportu.

Orchestrator / Role Architect / Reporter v tomto režimu nevytvářejí nové
discovery kandidáty. Mohou poznamenat coverage gap, delegovat a aktualizovat
existující ID. Prototyper a local specialisté mohou cíleně navázat na chybějící
prototyp/test a nové lokální záznamy automaticky nesou `prior_work_refs`.
V poznámce musí uvést, co přesně řeší a co se změnilo — třeba nyní dostupné
Pillow/cbor2. Staré prototypy nejsou automaticky importované do workspace;
aktuální artefakt a test musí skutečně vytvořit a ověřit.

Pro cílený run pokračující ve starých hypotézách vytvoř vlastní profil:

```cmd
copy config.research.json config.continue.json
```

V něm nastav `"prior_work_policy": "continue"`, zúžené zadání/seed role dle
zamýšlené práce, potom `run-sandbox.cmd --config config.continue.json`.
Continue umožňuje opětovné zařazení kandidáta; původ se stále zaznamená.
Základní profil a staré runy bez pole mají tento kompatibilní default.
Resume pracuje s původním zachyceným configem a pamětí, nikoli novým profilem.

Identita není univerzální sémantický deduplikátor. Host rozpoznává doložené
aliasy ORCID/public-pointer a QR/XMP recovery-card, odděluje embedded archive
a skutečně odlišné scopes, a používá stabilní mechanism keys pro další rodiny.
Neznámé parafráze se automaticky neslučují jen podle podobnosti slov.
Další opakující se případy vyžadují konkrétní diagnózu a regresi; prompt sám
nemůže zaručit, že model žádné discovery search neopakuje.
