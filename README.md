# RTCM TCP Debugger

Jednoduchá desktopová Python aplikace pro **debug RTCM3 streamu přes TCP**.

Primárně vznikla jako lehký nástroj pro rychlou kontrolu, zda z TCP streamu opravdu teče platný RTCM3 obsah, jaké typy zpráv přicházejí, kolik jich dorazilo a jak vypadají poslední validní dekódované hodnoty.

Aplikace je vhodná například pro:
- kontrolu RTCM3 streamu z lokálního TCP serveru,
- debug NTRIP / RTK / base station pipeline,
- ověření, že stream skutečně obsahuje očekávané zprávy jako `1005`, `1006`, `1033`, `1077`, `1087`, `1097`, apod.,
- odhalení situací, kdy stream není RTCM3 nebo obsahuje poškozené rámce.

## Co aplikace umí

- připojení na **TCP stream** pomocí `IP + Port`,
- zobrazení počtu přijatých zpráv podle typu RTCM,
- zobrazení poslední validní dekódované zprávy,
- detekci **invalidních RTCM rámců**,
- detekci balastu / dat, která **nejsou RTCM3**,
- výpočet **validity %**,
- **watchdog** nad živostí streamu,
- **MSM detection**,
- lepší výpis zpráv `1005` / `1006`, včetně přepočtu ECEF souřadnic na zeměpisnou polohu base stanice.

## Health / sanity informace

Aplikace navíc zobrazuje praktické souhrny pro rychlý debug:

- `STREAM OK`
- `WAITING FOR DATA`
- `STREAM DEAD`
- stav přítomnosti **base position** (`1005/1006`)
- stav přítomnosti **MSM corrections**
- poslední známou base pozici
- poslední MSM typ a základní metadata

To je užitečné například při debugování, proč rover nebo NTRIP služba hlásí problém typu:
- stream není RTCM3,
- chybí base position,
- chybí correction zprávy,
- data tečou, ale dlouho nepřišla validní RTCM zpráva.

## Screenshot / typické použití

Typický workflow:

1. Spustíš lokální TCP server nebo jiný zdroj RTCM3 streamu.
2. Do aplikace zadáš IP a port.
3. Klikneš na `Connect`.
4. Sleduješ:
   - jaké zprávy chodí,
   - zda roste počet validních rámců,
   - zda nejsou invalidní rámce,
   - zda aplikace vidí `1005/1006` a MSM zprávy.

## Závislosti

Aplikace používá:

- Python 3.10+
- `pyrtcm`
- `tkinter`

### Python balíčky

Instalace přes `requirements_rtcm_debugger.txt`:

```bash
pip install -r requirements_rtcm_debugger.txt
```

Obsah requirements:

```txt
pyrtcm>=1.1.9
```

Poznámka: `pynmeagps` se doinstaluje jako závislost `pyrtcm`.

## macOS poznámka

Na macOS je potřeba, aby Python měl podporu `tkinter`.

Pokud aplikace padá na chybu typu:

```bash
ModuleNotFoundError: No module named '_tkinter'
```

pomůže doinstalovat Tk podporu, například:

```bash
brew install python-tk
```

V tvém prostředí tohle problém vyřešilo.

## Spuštění

### 1. Klon repozitáře

```bash
git clone https://github.com/TVUJ-UCET/TVUJ-REPO.git
cd TVUJ-REPO
```

### 2. Virtuální prostředí

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instalace závislostí

```bash
pip install -r requirements_rtcm_debugger.txt
```

### 4. Spuštění aplikace

```bash
python3 rtcm_debugger.py
```

## Jak aplikace funguje

Aplikace čte TCP stream jako binární data a hledá RTCM3 rámce podle preambule `0xD3`.

Následně:
- vyčte délku rámce,
- zkusí rámec dekódovat přes `pyrtcm`,
- při úspěchu zvýší počitadlo typu zprávy,
- při chybě zvýší počitadlo invalidních rámců,
- při balastu mimo RTCM rámce zvýší počitadlo non-RTCM bytů.

## Zprávy 1005 / 1006

Pokud dorazí `1005` nebo `1006`, aplikace zobrazuje:
- station ID,
- ECEF souřadnice `X / Y / Z`,
- přepočtenou `Latitude / Longitude / Height`.

To je užitečné pro rychlou kontrolu, že base opravdu vysílá správnou pozici.

## MSM detection

Aplikace hlídá MSM zprávy v rozsahu typicky:
- `1074–1077`
- `1084–1087`
- `1094–1097`
- `1104–1107`
- `1114–1117`
- `1124–1127`

Zobrazuje:
- poslední MSM typ,
- station ID,
- počet satelitů,
- počet signálů,
- počet cell entries,
- stáří poslední MSM zprávy.

## Omezení

- aplikace zatím podporuje pouze **TCP vstup**, ne sériový port,
- je zaměřená na **rychlý debug**, ne na kompletní analýzu všech RTCM polí,
- logická validita obsahu není totéž co CRC validita rámce — rámec může být syntakticky validní, ale stále obsahovat nesmyslná data.

## Nápady na další rozvoj

Možná budoucí vylepšení:
- logování do souboru,
- export raw RTCM streamu,
- zvýraznění důležitých typů zpráv (`1005`, `1033`, MSM),
- barevný `OK / WARN / FAIL` panel,
- build do `.app` pro macOS,
- podpora NTRIP klient režimu,
- podpora sériového portu.

## Licence

Doplň si podle sebe, například:

```txt
MIT License
```

## Poděkování

Dekódování RTCM zpráv zajišťuje knihovna `pyrtcm`.
