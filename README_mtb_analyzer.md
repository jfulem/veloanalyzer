# MTB Start List Analyzer

Nástroj pro analýzu startovních listin MTB závodů.  
Automaticky doplní UCI ranking jezdců a umí porovnat kvalitu dvou závodů.

---

## Instalace

```bash
pip install requests beautifulsoup4 rich thefuzz python-Levenshtein
```

---

## Použití

### 1. Analýza jednoho závodu

```bash
# Základní použití
python mtb_analyzer.py --url "https://www.sportzeitnehmung.at/en/component/eventbooking/34-ktm-kamptal-trophy-c/registrants-list.html" --category "Men Juniors"

# Runtix formát (bez UCI čísel — matching dle jmen)
python mtb_analyzer.py --url "https://runtix.com/sts/10040/3104/19m/-/-" --category "Junior"

# S exportem do CSV
python mtb_analyzer.py --url "..." --category "Men Juniors" --export vysledky.csv

# Elite kategorie (UCI ranking ME = Men Elite)
python mtb_analyzer.py --url "..." --category "Elite" --uci-category ME
```

### 2. Porovnání dvou závodů

```bash
python mtb_analyzer.py \
  --compare \
  "https://www.sportzeitnehmung.at/.../registrants-list.html" \
  "https://runtix.com/sts/10040/3104/19m/-/-" \
  --category "Junior" \
  --uci-category MJ
```

### 3. Aktualizace UCI rankingu

UCI ranking se cachuje do složky `.mtb_cache/` a automaticky se obnovuje po 7 dnech.  
Ruční obnova:

```bash
python mtb_analyzer.py --refresh-cache --uci-category MJ
```

---

## Přehled parametrů

| Parametr | Popis | Výchozí |
|----------|-------|---------|
| `--url URL` | URL startovní listiny | — |
| `--compare URL1 URL2` | Porovnej dva závody | — |
| `--category TEXT` | Filtr kategorie (část názvu) | vše |
| `--uci-category` | UCI kategorie rankingu | `MJ` |
| `--refresh-cache` | Vynuť stažení nového rankingu | ne |
| `--export soubor.csv` | Exportuj do CSV | — |
| `--no-lookup` | Přeskoč UCI lookup | ne |

### UCI kategorie (`--uci-category`):
- `MJ` — Men Juniors (U19)
- `WJ` — Women Juniors (U19)
- `ME` — Men Elite
- `WE` — Women Elite

---

## Podporované weby

| Web | UCI číslo | Poznámka |
|-----|-----------|----------|
| sportzeitnehmung.at | ✅ Ano | Přímé matchování |
| runtix.com | ❌ Ne | Fuzzy matching dle jména |
| Ostatní | ❌ Závisí | Generický parser |

---

## Jak funguje matching bez UCI čísla

Pokud startovní listina neobsahuje UCI ID (např. runtix.com), skript porovná
jméno jezdce s UCI rankingem pomocí fuzzy string matching.

- ≥ 90% shoda → spolehlivé, zobrazeno bez upozornění
- 82–89% → zobrazena shoda v závorce, např. `Adam Horák (87%)`
- < 82% → jezdec označen jako bez rankingu

---

## Výstup - Skóre kvality závodu

Při porovnávání závodů se počítá **skóre kvality**:

```
Skóre = (body TOP10 jezdců × 3) + (počet TOP50 × 10) + (počet TOP100 × 5) + (počet TOP200 × 2) + počet ranked
```

Čím vyšší skóre, tím silnější startovní pole.

---

## Příklad výstupu

```
┌─────────────────────────────────────────────────────────┐
│  34. KTM Kamptal Trophy — XCO Men Juniors               │
│  UCI kategorie: MJ | Celkem: 44 jezdců                  │
├────┬──────────────────────┬──────┬─────────┬──────────┤
│  # │ Jméno                │ Země │ UCI rank│ UCI body │
├────┼──────────────────────┼──────┼─────────┼──────────┤
│  1 │ Michael Ortner       │ 🇦🇹 AUT │    31  │   168    │
│  2 │ Michal Šichta        │ 🇸🇰 SVK │    62  │   108    │
│  3 │ Milan Podgornik      │ 🇭🇺 HUN │    83  │    90    │
│ ...│                      │      │         │          │
```

---

## Soubory cache

Cache se ukládá do složky `.mtb_cache/` vedle skriptu:
- `.mtb_cache/ranking_MJ_2026.json`
- `.mtb_cache/ranking_ME_2026.json`
- atd.

Soubory lze smazat pro vynucení obnovy.
