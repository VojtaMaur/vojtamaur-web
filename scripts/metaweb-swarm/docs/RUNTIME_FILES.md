# Společná složka pracovních souborů (0.12.0)

Výchozí rozložení na tomto počítači:

```text
G:\vojtamaur-web\scripts\metaweb-swarm\   kód a projektové profily
G:\vojtamaur-metaweb-swarm-files\
    runs\                   běhy, reporty, RUN_MEMORY.json a pracovní kopie
    env\                    Python prostředí a jeho spouštěče
    docker-data\            původní disky Docker Desktop / WSL
    config.json              původní uživatelský metaweb-swarm-config.json
    gui-settings.json        volitelně uložený API klíč GUI
    NAVOD.txt                stručný místní návod
    migration-backup\       původní prostředí, pracovní značky a záznam přesunu
```

Soubor `config.json` v této pracovní složce je zachovaný uživatelský profil.
Není automaticky zaměněn za projektový `config.research.json`; chceš-li ho použít,
předej `--config G:\vojtamaur-metaweb-swarm-files\config.json`. Profily GUI a modely
zůstávají stejné. Paměť/reporty nejsou dočasná data k vymazání.

V CMD nadále stačí `run-gui.cmd` nebo `run.cmd` ve složce swarmu. Launchery sdílejí
`runtime.cmd`: respektují `SWARM_PYTHON`, pak místní `.venv`, společné `env`, nakonec
Python v PATH. `SWARM_FILES_ROOT` mění společný kořen; `SWARM_RUNS_ROOT` jen běhy.
Bez přepisu je společný kořen sourozenec projektu, také na jiném disku/systému.
GUI používá stejný výchozí kořen. CLI `init/start --runs-root` zůstává explicitní.

Nové příklady:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-gui.cmd
G:\vojtamaur-metaweb-swarm-files\env\Scripts\python.exe swarm.py resume "G:\vojtamaur-metaweb-swarm-files\runs\ID_BEHU" --backend openai
```

## Zachování předchozích běhů

Ověření přesunu 2026-11-03: 59 běžných běhů a 4 validační databáze (63 auditních
řetězců), 553 důkazních souborů beze změny hashů, 409 přesměrovaných pracovních
značek. Tři reprezentativní pracovní kopie byly otevřeny z nové cesty. Včetně
19 značek ze dvou nejstarších běhů s původním prefixem F:. Nové Python prostředí
má totožných 43 distribucí, pip check prošel, původní Docker image úspěšně spustil
krátký kontejner bez sítě nebo připojených souborů. Důkazy jsou v migration-backup.

Přesun probíhá při zastaveném roji i Dockeru. Adresář běhů se přesune na stejném
disku bez přepisování SQLite, auditních událostí, reportů, schválení nebo modelových
historií. Historické absolutní cesty v těchto důkazech zůstávají jako provenance.
Host aktualizuje pouze `.metaweb-workspace.json` značky pracovních kopií, které
obsahují původní absolutní root/snapshot; jejich původní obsah je zálohovaný.
Nové pracovní operace používají skutečný run_dir, nikoli historický snapshot.path.
Nevytváří se junction/symlink na původním místě; kontroly hranic zůstávají zachované.

Python venv se vytváří znovu a přebírá stejný inventář již nainstalovaných knihoven
bez stažení nových verzí. Absolutní cesty konzolových spouštěčů se regenerují.
Původní venv je uložený v migration-backup/env-before-move. U Dockeru se přesouvá
i registrace distribuce docker-desktop příkazem WSL --manage --move a upravuje
wslDefaultDataRoot; samotné přejmenování adresáře by nestačilo.

Otevřené staré CMD může mít vlastní LIVE_RUN nebo SWARM_PYTHON: přepiš je na nové
cesty nebo otevři nové CMD. Po přesunu restartuj GUI; API klíč není potřeba
posílat do chatu ani ukládat do repozitáře. Staré kopírované příkazy z historických
reportů mohou uvádět původní cestu — použij nový kořen runs.
