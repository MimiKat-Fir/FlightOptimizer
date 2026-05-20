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
python .\flight_optimizer.py `
  --origins MAD,BCN `
  --destinations PVG,HGH `
  --depart 2026-07-08:2026-07-10 `
  --return 2026-07-30:2026-07-31 `
  --limit-per-query 3
```

Results are written to `data/results.csv`.

## Notes

- Prices can change and must be verified before purchase.
- `PVG`, `SHA`, and `NKG` include a rough transfer estimate to Hangzhou.
- This first version searches normal round trips. Open-jaw/multi-city support is the next logical step.

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
