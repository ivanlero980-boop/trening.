# Automatski testovi — My Training

Testovi otvaraju `index.html` u pravom pregledaču (Chromium, ekran veličine telefona) i prolaze kroz ključne scenarije aplikacije. Svaki test kreće od praznog stanja i koristi sintetičke podatke. U repozitoriju nema ličnih podataka.

Aplikaciju na telefonu ovaj folder ne mijenja: telefon učitava samo `index.html`, `manifest.json` i `sw.js`.

## Pokretanje

```bash
pip install playwright
python -m playwright install chromium
python tests/run_tests.py            # svi testovi
python tests/run_tests.py backup     # samo testovi čije ime sadrži "backup"
```

Ako želiš sistemski Chrome umjesto Playwright Chromium-a, pokreni ovako:
`CHROME_PATH=/putanja/do/chrome python tests/run_tests.py`

Na kraju se ispisuje `N/N testova prošlo`. Ako neki test padne, ispisuje se i razlog. Izlazni kod je 1 ako bilo koji test padne.

## Šta se testira

| Test | Provjerava |
|---|---|
| `new_user_starts_empty` | Nova instalacija: bez ličnih podataka, dobrodošlica, rad bez ciklusa, neutralne poruke |
| `existing_data_keeps_name` | Postojeći podaci zadržavaju ime i ne dobijaju dobrodošlicu |
| `set_confirmation_and_finish` | ✓ odvojen od unosa, predlog ponavljanja, upozorenje za nepotvrđene setove |
| `reduce_plan_removes_unconfirmed` | „Smanji plan“ uklanja i popunjen nepotvrđen set; nema brisanja pojedinačnog seta |
| `myo_rep_counts_as_two` | Myo-rep = 2 seta u volumenu, ne ulazi u rekorde |
| `best_result_and_pr` | Najbolji rezultat i rekord po e1RM |
| `progress_chart_metrics` | Grafik progresije: e1RM / težina / ponavljanja |
| `pdf_export_is_valid` | PDF izvoz pravi ispravan fajl |
| `free_workout_weekly_volume_and_template` | Slobodni trening: sedmični volumen, ne dira plan, čuvanje kao šablon |
| `same_workout_twice_in_program` | Isti trening više puta u programu, zasebni statusi |
| `open_period_and_cycle_end_prompt` | Pitanje po završetku ciklusa, osnovne serije, rad bez ciklusa, datum kraja |
| `program_switch_midweek` | Promjena programa usred sedmice, priznavanje odrađenog |
| `archived_workouts_and_frozen_past_weeks` | Izmjena programa ne mijenja prošle sedmice ni istoriju |
| `program_copy_only_after_save` | Kopija programa nastaje tek posle potvrde |
| `library_import_without_duplicates` | Ponovljen uvoz biblioteke ne pravi duplikate |
| `cycle_analytics` | Napredak u ciklusu, deload isključen, bez prosjeka |
| `backup_roundtrip` | Izvoz i uvoz rezervne kopije vraćaju identično stanje |
| `all_screens_render` | Svi ekrani se otvaraju bez JS grešaka |

## Pravilo

Svaku izmjenu `index.html` provjeriti pokretanjem testova prije objave na `main`. Za novu funkcionalnost dodati test u `run_tests.py` (dekorator `@test`).
