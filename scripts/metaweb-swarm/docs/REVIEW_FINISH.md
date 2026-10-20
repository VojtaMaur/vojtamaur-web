# Dokončení auditu a test vlastní mechanismu (0.6.14)

Nový běh v CMD, s nastaveným API klíčem a spuštěným Dockerem:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-http.cmd
```

Modely, 40 globálních kol / 3 miliony tokenů / hodina, sandbox a externí approval
zůstávají stejné. Auditor má v nových research/http profilech 10 kol místo 6.
Není třeba rebuild image ani opakování placených smoke testů. Instalace sama
nespouští API ani nemění stav starých runů.

## Povinná činnost, svobodný verdict

Běh 084150 vytvořil tři test receipts. Auditor přečetl jen první test a část
velkého výstupu; napsal slovní endorsement bez `review_prototype_test`. Po
vyčerpání jeho šesti kol zůstaly všechny tři reviews prázdné.

Host nyní před každým modelovým požadavkem pro PROTOTYPE_TEST vypočte další
akci: `read_test_artifact` pro přesný chybějící path/offset/limit, potom
`review_prototype_test`. SDK provider wrapper nastaví `tool_choice` i po
automatickém SDK resetu. Dynamické zadání je v system instructions před
request reservation, aby je zahrnovala existující kontrola budgetu. Nenastavuje
verdict a neuděluje žádná externí práva. Model vybírá FULL/SUBCOMPONENT/REVISE
a host dál ověřuje dosavadní evidence contract. Po uložení verdictu se nucená
volba uvolní. Tokeny, čas, USD, max_turns i pause/resume stále platí.

Scheduler upřednostní čekající zaznamenaný test před dalším experimentem.
Při nedostatku globálních kol chrání známou auditní frontu, ale ponechá poslední
kolo reportérovi. Nově vzniklé či mimořádně velké úlohy nemusí stihnout; žádný
verdikt se z prose nedovozuje a budget se nezvyšuje automaticky.

## Co má lokální prototyp skutečně testovat

Research/http profily zapínají `require_prototype_focus=true`. Auditor v témže
`record_critique` určí `local_test_scope` a `local_test_goal`:

- FULL_MECHANISM: konkrétní celý ověřitelný mechanismus.
- SUBCOMPONENT: užitečná konkrétní část, s omezením případné custody/discovery.
- DEFER: nyní chybí smysluplná testovatelná operace nebo její dokumentace.

DEFER uchová nápad pro výzkum; není REJECTED ani human approval gate. Žádný
účet, HTTP nebo upload permission se tím nemění. Fokus platí pro aktuální
revizi tvrzení; změna mechanismu/evidence vyžaduje nové posouzení. Lokální queue
nepřidělí kandidáta bez aktuálního vybraného testu a dílčí fokus nelze povýšit
na celý mechanismus pouze označením plánu. Staré runy bez tohoto nastavení
zachovávají původní policy; explicitně jej lze vypnout v konfiguraci.

SVG test musí extrahovat data z vytvořeného SVG a výstupy odvozovat z nich.
CBOR z původního inputu není důkaz extrakce. Přesnou raw-byte obnovu dokládá
samostatný dekódovaný výstup; rasterizace/renderer je jiný scope. U Commons
je cesta G:\\... lokální údaj, nikoli veřejný recovery pointer. U neověřeného
repository obecná JSON kopie netestuje jeho deposit nebo download.

Výběr relevance zůstává agentním úsudkem; host nedokazuje sémantiku libovolného
scriptu. Syntax/read/hash guards nejsou zárukou vědecké správnosti. Reporter
dostává oddělené počty pending/FULL/SUBCOMPONENT/REVISE; exit=0 není automaticky
potvrzené functional coverage. Ověření: [VALIDATION](../VALIDATION.md).
