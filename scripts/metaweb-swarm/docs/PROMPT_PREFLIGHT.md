# Kontext a účtování host chyb — 0.6.5

Run 20261013-043825-09e42a24 překročil prompt_chars=30000 opakovanými narrative
shrnutími. Recovery z plánovací chyby jej opakovaně otevřelo, i když prompt nešel
sestavit. Čtyři kola Prototypera 3–6 tak skončila bez volání modelu, ale započítala
se do max_steps a round allowance.

Změny:

- Handoff previews jsou nejvýše tři položky po 300 znacích. Úplná vyprávění
  zůstávají v checkpointu, manifestu a context/SWARM_STATE.json.
- Aktuální kvalifikační plány zůstávají celé. Jejich duplikát v IDEA odkazuje na
  stejnou kvalifikaci v témže promptu. Aktivní flow a nejnovější vlastní kvalifikace
  se také zachovají; nesouvisející historické kvalifikace mají stručný index.
- Zkracuje se pouze prose reason critique; verdict, setup blockers, negativní
  source proof a aktuální plan zůstávají. Configuration/execution policy se nezkracuje.
- Prompt preflight proběhne před rezervací kola. Překročení char limitu znamená
  BLOCKED s nulovým model dispatch, bez změny steps/rounds/usage.
- Planning recovery nepřepíná BLOCKED zpět do PENDING, pokud prompt stále nelze
  sestavit. Po skutečné změně vstupů lze preflight vyhodnotit znovu bez placeného API.

Čtyři konkrétní historické host failures lze účetně vrátit pouze po kontrole
auditní sekvence: přesná prompt ValueError, žádný SDK/provider/tool event uvnitř
kola, žádné modelové použití. Původní checkpoint a překrytelné round artefakty
se zálohují v run/audit/host-prompt-failures; nový append-only event zaznamená
které seq/round byly vráceny. Usage, tokeny, USD, active time a config se nemění.
Historie neúspěšných pokusů se nemaže.

Při této opravě nejde o navýšení rozpočtu, grants ani approval. Nový modelový
běh není spouštěn instalací. Pokračování po instalaci/účetní opravě:

```cmd
G:\metaweb-swarm-env\Scripts\python.exe swarm.py resume "G:\metaweb-swarm-runs\20261013-043825-09e42a24" --backend openai
```

Host safeguards nechávají překročení limitu viditelné, pokud ani po zmenšení
redundance aktuální oprávnění/plan nevejdou. Nepovolují zkrácení bezpečnostní
policy ani automatické zvýšení prompt_chars.
