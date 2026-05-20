# FlightOptimizer

Small terminal tool built on top of Fli / Google Flights data.

Author: Firas Amine Waez / [MimiKat-Fir](https://github.com/MimiKat-Fir)

Initial goal: scan many route/date combinations for the China trip and export a ranked CSV.

## Setup

Use Miniconda/Miniforge, not a standalone Python install.

```powershell
conda create -n flights python=3.12
conda activate flights
pip install -r requirements.txt
conda install -c conda-forge spyder-kernels
```

## Basic scan

```powershell
conda activate flights
python .\flight_optimizer.py --origins MAD,VLC,BCN --destinations PVG,HGH --return-origins MAD,VLC,BCN --depart 2026-07-09:2026-07-12 --return 2026-07-27:2026-07-28 --limit-per-query 1 --output data/china_full_baseline.csv
```

Results are written to the path passed in `--output` (`data/results.csv` by default).

## Notes

- Prices can change and must be verified before purchase.
- `PVG`, `SHA`, and `NKG` include a rough transfer estimate to Hangzhou.
- The scanner queries one-way outbound and one-way return flights, then combines them internally.
- `--return-origins` enables open-jaw shapes such as `MAD -> PVG -> VLC`.
- `MAD` and `BCN` include a rough Valencia train penalty by default; `VLC` is zero.
- Departures before `--free-arrival-date` add a cheap-hotel penalty.

## Spyder

Spyder is useful for editing and debugging `flight_optimizer.py`, but run real scans from a Miniforge Prompt:

```powershell
conda activate flights
cd "C:\Users\firas\OneDrive - UPV\Documentos\My Documents\FlightOptimizer"
python .\flight_optimizer.py --help
```

If Spyder is installed in another environment, set this as the Python interpreter:

```text
C:\Users\firas\miniconda3\envs\flights\python.exe
```

In Spyder: `Tools > Preferences > Python interpreter > Use the following Python interpreter`.

## License

MIT License. Copyright (c) 2026 Firas Amine Waez / MimiKat-Fir.
