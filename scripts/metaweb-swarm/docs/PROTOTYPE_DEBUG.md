# Selhaný kód → diagnóza → oprava → funkční výsledek (0.6.15)

Nový skutečný běh v CMD ve složce projektu, s API klíčem a běžícím Dockerem:

```cmd
run-http.cmd
```

Prototyper má v nových research/http profilech 8 kol místo 6. Celkových 40 kol,
3M tokenů, hodina, všechny modely, sandbox/network policy a external approvals
zůstávají stejné. Image není třeba rebuildovat. Placený běh se instalací nespouští.

## Co se změnilo

Běh 105648 měl správně dokončené pre-audity, ale recovery card nepoužívala RS
opravu; smazala část JSONu a pak se jej snažila přečíst. Tři pokusy upravovaly
parsování, nikoli chybějící algoritmus. Tato evidence nebyla úspěšný test.

Nový plánovaný lokální experiment s nonzero exit uloží neměnný snapshot
skutečného scriptu, plán, traceback a návratový kód. Není to TEST receipt ani
novelty/mechanism rejection. SDK po návratu nástroje předá řízení, bez dalšího
modelového požadavku a slepého rerun. Známá usage/tool outcome zůstane v auditu.

Auditor dostane PROTOTYPE_FAILURE, povinně přečte celý zdroj pomocí
read_failed_experiment a uloží record_failure_diagnosis. Určí problém
ALGORITHM_MISSING/DEPENDENCY/CODE_BUG/CONTRACT_MISMATCH/ENVIRONMENT/UNKNOWN,
konkrétní kroky a rozhodující kontrolu. REPAIR vrací práci prototyperovi,
DEFER ponechá hypotézu pro další výzkum. Nejde o human approval nebo udělení
externích oprávnění. Prototyper při čekání nespotřebovává placené modelové role;
other eligible kandidáti mohou pokračovat.

Oprava dostane čistý LOCAL_REPAIR kontext, zatímco původní historie zůstane
archivovaná. Prototyper přečte failed script a diagnosis, provede změnu a
aktualizuje record_prototype_plan s repair_experiment_id, repair_notes a
repair_check. Stejný script nebo plán bez vazby na diagnózu nelze jen znovu
spustit. U DEPENDENCY dovolí stejný kód doložená nová instalace balíčku v
sandboxu; u ENVIRONMENT zaznamenané vyřešení operátorem. Knihovny lze
instalovat přes obecný install_packages. Další
skutečná execution rozhodne, zda oprava pomohla. Úspěch stále potřebuje
record_test a nezávislé scope review; diagnóza sama PROTOTYPED neuděluje.

Vše probíhá uvnitř existujících agentů a budgetů. Není přidán provider connector
ani nový placený model. Limity mohou zastavit i opravný cyklus. Neúspěšný script
nebo nemožnost zachytit snapshot jsou technické evidence gaps, nikoli rejection.
Staré zastavené runy bez nových frozen failure receipts se instalací nepřepisují;
nejjednodušší další krok je nový běh.

## Praktický výsledek a reference

Lokální role dostává context/PROTOTYPING_GUIDE.md a relevantní referenční recipe
context/recipes/rs_recovery.py. Recipe patří jen do odpovídajícího mechanismu,
není nový objev. Používá skutečný RSCodec z
[reedsolo 1.7.0](https://pypi.org/project/reedsolo/1.7.0/), CRC32 a SHA256.
Knihovna není povinnou host dependency frameworku; instaluje se do sandboxu.

Codex také vytvořil samostatný použitelný RS payload artefakt z celého zachyceného
Metaweb EPUB o 1 294 314 bajtech. V Dockeru obnovil původní bytes po osmi unknown
byte errors i 24 známých indexed erasures v každém codewordu. Přesný SHA256
je v report.json. Nadměrné poškození a chybná hlavička byly odmítnuty. Erasure
indexy se třídí po blocích, aby decoder neprováděl opakované globální skenování.

Artefakt je uložen mimo produkční web pod
G:/metaweb-swarm-runs/manual-artifacts/rs-recovery-20261014-v0615/README.md.
Obsahuje kód, požadavky, encoded/damaged/erased soubory a recovered.epub.
Jde o otestovanou payload komponentu. Netestuje tisk, optické čtení, neindexované
smazání bytes, autentizaci proti útočníkovi ani nezávislé veřejné uchování.
Header není error-corrected. Kód i modelové diagnózy tohoto ověření připravil
Codex; nešlo o nový samostatný objev nebo placené autonomní LLM posouzení.

Ověření a receipts: [VALIDATION](../VALIDATION.md).
