# Pojmenované profily a názvy agentů

V GUI otevři **Výchozí nastavení** nebo **Nový běh**. Vyber v nabídce
**Režim a profil** nejbližší výchozí profil a uprav zadání, tým, modely a limity.
Vyplň **Název vlastního profilu** a klikni na **Uložit jako nový profil**.
Nový profil se hned objeví ve stejné nabídce; uložení nespouští běh ani API.

U vlastního profilu můžeš změnit i název a kliknout na **Uložit změny profilu**.
Pro další variantu napiš jiný název a použij **Uložit jako nový profil**.
Tlačítko **Smazat profil** vyžaduje druhé potvrzující kliknutí. Maže pouze
předvolbu, nikoli dřívější běhy. Tři vestavěné profily zůstávají k dispozici;
jejich vlastní výchozí nastavení lze obnovit původním tlačítkem.

V tabulce týmu je název každého agenta editovatelné pole. Popisek **Role**
pod ním ukazuje jeho původní funkci. Přejmenování zachovává interní roli,
modelový tier, přidělování práce a nezávislé posuzování. Zadání role lze upravit
zvlášť. Vlastní startovní agenti nadále mají editovatelný název i zadání.
Názvy se zobrazují na kartách agentů, v aktivitách a v přehledu agentů reportu.

Profily se ukládají mimo produkční strom do
`G:\vojtamaur-metaweb-swarm-files\defaults\user-<náhodné ID>.json`.
Název je uvnitř souboru, nepoužívá se jako cesta. Profil uchovává kopii
editovatelných parametrů; další změny výchozího týmu či limitů vestavěného
profilu ji nepřepisují. Provozní oprávnění stále určuje původní vestavěný režim.
API klíč není součástí profilu.

CLI a staré příkazy zůstávají funkční. `run.cmd` dál používá výchozí
brainstorming, nikoli naposledy vybraný vlastní profil v GUI. GUI spouští
pojmenované profily přes stávající CLI s konkrétní zachycenou konfigurací.
Existující běhy při pokračování používají vlastní uložené nastavení a nejsou
změnou ani smazáním předvolby ovlivněné.
