# OSDP Control Panel: testování čteček přes RS-485

OSDP Control Panel je desktopová aplikace v Pythonu a PyQt6 pro práci s OSDP periferními zařízeními (PD), například čtečkami. Aplikace se připojuje jako Control Panel (CP) přes sériovou linku RS-485 a soustřeďuje běžné kroky při vývoji a uvádění zařízení do provozu do jednoho grafického rozhraní.

## Přehled připojených zařízení

Panel **PD** umí prohledat adresy OSDP od 0 do 126. U nalezených zařízení zobrazuje identifikaci výrobce, model, verzi, sériové číslo a dostupné funkce oznámené zařízením. Stav připojení a průběh komunikace jsou viditelné v okně aplikace i v průběžném protokolu.

Připojení vyžaduje nastavený sériový port, rychlost přenosu a adresu PD. Během prohledávání sběrnice aplikace pozastaví aktivní spojení a po dokončení zobrazí nalezená zařízení.

## Ovládání čtečky

Samostatné záložky připravují příkazy OSDP pro funkce čtečky:

- **LED** – nastavení trvalého stavu LED a volitelného dočasného přepsání s barvou, blikáním a délkou trvání.
- **Buzzer** – nastavení tónu, doby zapnutí a vypnutí a počtu opakování.
- **MFG** – odeslání výrobně specifického příkazu s kódem výrobce a daty.
- **Security** – konfigurace režimu zabezpečeného kanálu a odeslání příkazu `KEYSET`.

Zařízení může také posílat události, které se zobrazují v protokolu spolu se stavem PD a diagnostickými zprávami.

## Architektura a testování

`OsdpManager` propojuje Qt rozhraní s `pyosdp`. Příkazy z uživatelského rozhraní se řadí do fronty a zpracovávají v monitorovacím vlákně, aby běžná komunikace neblokovala okno aplikace. Když knihovna `libosdp` není dostupná, aplikace použije simulační cestu s fiktivními zařízeními a příkazy; tato cesta nekomunikuje po fyzické sběrnici.

## Spuštění

Projekt vyžaduje Python 3.10 nebo novější. Z kořenového adresáře repozitáře vytvořte virtuální prostředí, nainstalujte závislosti a spusťte hlavní modul:

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python main.py
```

Pro práci s hardwarem je potřeba OSDP PD a kompatibilní adaptér RS-485. Nastavení portu, rychlosti, adresy a režimu zabezpečení upravte v dialogu **Settings**.

> **Zabezpečení:** Aplikace ukládá SCBK do `config.json` jako čitelný text. Pro vývoj používejte testovací klíč, nezapisujte produkční klíče do verzovaného konfiguračního souboru a případný zveřejněný klíč vyměňte.

Zdrojový kód: [CodElecCz/osdp-control-panel](https://github.com/CodElecCz/osdp-control-panel).
