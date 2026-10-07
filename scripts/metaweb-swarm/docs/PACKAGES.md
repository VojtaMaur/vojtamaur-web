# Knihovny v agentních workspaces

Od verze 0.3.1 může agent požádat o **libovolný pojmenovaný Python package z PyPI**.
Není whitelist balíčků ani schválení každé instalace. Operátor schopnost zapíná
v konfiguraci; instalace běží pouze v Dockeru. Windows Python a produkční web
se tím nemění.

## Spuštění

`config.research.json` má instalace zapnuté. V CMD s nastaveným API klíčem a
běžícím Docker Desktop:

```cmd
cd /d G:\vojtamaur-web\scripts\metaweb-swarm
run-sandbox.cmd
```

Existující image `metaweb-swarm-experiment:local` stačí; kvůli knihovnám jej
nemusíš přestavovat. Spouštěč založí nový autonomous Docker run. Instalace jsou
možné i se `sandbox-only` a `approval_required=true`: stažení závislosti má
vlastní explicitní oprávnění a neotvírá externí deposit. `run-supervised.cmd`
bez Dockeru pouze zkoumá. Se supervised + Docker agent nejprve potřebuje
vybranou realizaci IDEA; instalace respektuje stejné rozhodnutí jako prototyp.

Config pro nové běhy:

```json
"package_installation": "pypi",
"package_install_timeout_seconds": 120,
"max_package_installs_per_agent": 8,
"max_package_bytes": 536870912
```

`disabled` instalace vypne. Limit pokusů platí pro každého agenta napříč koly
a resume; jeden požadavek má 1–32 balíčků. Čas instalace se omezí také zbývajícím
runtime běhu. Celkový runtime zahrnuje instalace; timeout Docker operací a úklid
mohou přidat režii. Velikost wheels a výsledné `.packages` se kontroluje po
fázích. Jde o **kontrolu velikosti, nikoli tvrdou diskovou kvótu během stahování**.

Staré runy mají uložený vlastní config. Bez nového pole zůstávají instalace
vypnuté; změna profilu jim nepřidává oprávnění. Pro novou schopnost založ nový run.

## Co má agent použít

Agent dostane nástroj a krátké instrukce; není potřeba mu ručně zadávat pip:

```text
install_packages(packages=["Pillow", "qrcode[pil]", "cbor2>=5"], idea_id="IDEA-0001")
run_experiment(argv=["python", "prototype.py"], idea_id="IDEA-0001")
```

Podporované jsou jméno, extras a verze/range, například `numpy==2.2.6` nebo
`cbor2>=5,<7`. Dependencies řeší pip. Host nepoužívá shellové příkazy od agenta.
URL, Git repozitáře, lokální cesty, requirements files a pip options nejsou
jména balíčků a nástroj je nepřijímá. `apt`, systémové knihovny a kompilátory
patří do zvlášť připraveného image. Jakékoli jméno je povolené, ale kompatibilita
s Linuxem/Pythonem 3.11 ani přítomnost native build nástrojů není zaručená.
Chybějící package/build tool je `BLOCKED`; timeout/velikost je `LIMIT_REACHED`.

Instalace do agentova `.packages` přetrvá mezi kontejnery, koly a resume.
Experimenty mají nastavený `PYTHONPATH` a cestu ke console scripts. Python
spuštěný s `-I`/`-E` ignoruje `PYTHONPATH`; pro běžné importy jej tak nespouštěj.
Agent má instalovat potřebné závislosti pro skutečný prototyp a test, nikoli
náhodně zkoušet seznamy knihoven. Neúspěšná offline instalace může zanechat
částečné soubory; před pokračováním ověř import a verzi. Pip upgrade může
ponechat starší metadata; rozhodující je ověřený import a funkční test.

## Izolace a audit

1. Online kontejner spustí pevný `pip wheel` proti PyPI a dependencies. Vidí jen
   novou dočasnou build složku. Nevidí kopii webu, exporty, API klíč, produkci
   ani Docker socket. Source builds jsou povolené a mohou spouštět build hooks.
2. Offline kontejner připojí wheelhouse read-only a instaluje pomocí
   `pip install --no-index` do soukromé `.packages` agenta.
3. Experimenty dál používají `--network none`. Instalované knihovny se spouštějí
   pouze uvnitř Dockeru; nejsou součástí patchů vracených do produkce.

Obě fáze zachovávají neprivilegovaného uživatele, read-only root, dropped caps,
no-new-privileges, 512 MiB RAM, 1 CPU, 64 PIDs, watchdog a úklid kontejneru.
Online fáze má Docker bridge: **nemá síťový firewall omezený jen na PyPI**.
Build hooks mohou kontaktovat jiné cíle. Toto oddělení chrání projektová data;
není náhradou za egress firewall nebo izolovanou VM pro nepřátelské balíčky.

Zahájení a výsledek se stručně zobrazí v CMD. Checkpoint/audit zaznamená
požadované packages, agent/IDEA, stav, fáze, Docker receipts, output, SHA256
wheels a zjištěné distribuce/verze. `manifest.json` obsahuje plné
`package_installations`; `SWARM_REPORT.md` stručný přehled.
Normální přerušení vyčká na úklid a uloží výsledek. Pokud celý host runner
havaruje uprostřed instalace a zůstane auditní `RUNNING`, další instalace téhož
agenta se blokuje: před opakováním je nutné zkontrolovat kontejnery/workspace.
Nový běh nemá tento neuzavřený stav. Nic se automaticky neopakuje naslepo.

Použitá pip rozhraní: [pip wheel](https://pip.pypa.io/en/stable/cli/pip_wheel/)
a [pip install](https://pip.pypa.io/en/stable/cli/pip_install/).

## Ověřeno 2026-10-07

Od 0.3.4 pip pracuje na nativním tmpfs v kontejneru a do Windows workspace se
přenášejí bajty s omezenou tolerancí nepodporovaných POSIX mode updates. Skutečný
SDK→PyPI→Docker test na disku G: prošel po opravě chyby chmod v prvním živém
smoke runu. [Příčina a ověření](RUN_REVIEW_20261007_093936.md).

Skutečné stažení/instalace Pillow 12.3.0, qrcode 8.2 a cbor2 6.1.5 v místním
Dockeru prošly. Následující offline experiment vytvořil PNG s QR a ověřil CBOR
round-trip; nový kontejner po znovuotevření workspace knihovny importoval.
Test ověřil nepřítomnost credentials, nedostupnou experimentální síť, úklid
kontejnerů a nezměněný produkční fixture. Nebyla provedena placená API volání.
Receipts jsou v `docs/validation/PIP_DOCKER_*.json` a `PIP_DOCKER.log`.
