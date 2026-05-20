from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import typer
from rich.console import Console
from rich.table import Table


app = typer.Typer(help="Scan flight/date matrices using Fli.")
console = Console()


DESTINATION_EXTRAS_EUR = {
    "HGH": 0,
    "PVG": 15,
    "SHA": 12,
    "NKG": 30,
    "PEK": 55,
    "PKX": 55,
}


@dataclass(frozen=True)
class SearchRow:
    origin: str
    destination: str
    depart_date: str
    return_date: str
    price: float
    currency: str
    duration_hours: float
    stops: int
    airline_summary: str
    transfer_estimate_eur: float
    estimated_total_eur: float


def parse_date_range(value: str) -> list[str]:
    if ":" not in value:
        return [value]
    start_raw, end_raw = value.split(":", 1)
    start = date.fromisoformat(start_raw)
    end = date.fromisoformat(end_raw)
    if end < start:
        raise typer.BadParameter("End date must be after start date.")
    days = (end - start).days
    return [(start + timedelta(days=i)).isoformat() for i in range(days + 1)]


def split_codes(value: str) -> list[str]:
    return [code.strip().upper() for code in value.split(",") if code.strip()]


def fli_executable() -> Path:
    script_dir = Path(__file__).resolve().parent
    env_candidate = Path(sys.executable).resolve().parent / "fli.exe"
    if env_candidate.exists():
        return env_candidate
    candidate = script_dir / ".venv" / "Scripts" / "fli.exe"
    if candidate.exists():
        return candidate
    return Path("fli")


def cache_path(origin: str, destination: str, depart: str, ret: str, stops: str) -> Path:
    key = f"{origin}-{destination}-{depart}-{ret}-{stops}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return Path("data/cache") / f"{key}-{digest}.json"


def run_fli(
    origin: str,
    destination: str,
    depart: str,
    ret: str,
    stops: str,
    timeout_seconds: int,
    use_cache: bool,
) -> dict:
    cache_file = cache_path(origin, destination, depart, ret, stops)
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    command = [
        str(fli_executable()),
        "flights",
        origin,
        destination,
        depart,
        "--return",
        ret,
        "--format",
        "json",
        "--currency",
        "EUR",
        "--stops",
        stops,
        "--all",
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    payload = json.loads(completed.stdout)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def airline_summary(flight: dict) -> str:
    codes: list[str] = []
    for section in ("outbound", "return"):
        for leg in flight.get(section, {}).get("legs", []):
            code = leg.get("airline", {}).get("code")
            if code and code not in codes:
                codes.append(code)
    return "/".join(codes)


def rows_from_payload(
    origin: str,
    destination: str,
    depart: str,
    ret: str,
    payload: dict,
    limit: int,
) -> list[SearchRow]:
    rows: list[SearchRow] = []
    transfer = float(DESTINATION_EXTRAS_EUR.get(destination, 40))
    for flight in payload.get("flights", [])[:limit]:
        price = float(flight.get("price") or 0)
        currency = flight.get("currency") or "EUR"
        if currency != "EUR":
            # Keep first iteration simple. Fli usually returns EUR with --currency EUR.
            transfer_for_total = 0
        else:
            transfer_for_total = transfer
        rows.append(
            SearchRow(
                origin=origin,
                destination=destination,
                depart_date=depart,
                return_date=ret,
                price=price,
                currency=currency,
                duration_hours=round(float(flight.get("duration") or 0) / 60, 1),
                stops=int(flight.get("stops") or 0),
                airline_summary=airline_summary(flight),
                transfer_estimate_eur=transfer_for_total,
                estimated_total_eur=round(price + transfer_for_total, 2),
            )
        )
    return rows


def write_csv(rows: Iterable[SearchRow], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(rows)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SearchRow.__dataclass_fields__))
        writer.writeheader()
        for row in materialized:
            writer.writerow(row.__dict__)


def render_table(rows: list[SearchRow], max_rows: int) -> None:
    table = Table(title="Best Flight Options")
    for column in (
        "rank",
        "route",
        "dates",
        "price",
        "total",
        "duration",
        "stops",
        "airlines",
    ):
        table.add_column(column)

    for idx, row in enumerate(rows[:max_rows], start=1):
        table.add_row(
            str(idx),
            f"{row.origin}-{row.destination}-{row.origin}",
            f"{row.depart_date} / {row.return_date}",
            f"{row.price:.0f} {row.currency}",
            f"{row.estimated_total_eur:.0f} EUR",
            f"{row.duration_hours:.1f}h",
            str(row.stops),
            row.airline_summary,
        )
    console.print(table)


@app.command()
def scan(
    origins: str = typer.Option("MAD,BCN", help="Comma-separated origin IATA codes."),
    destinations: str = typer.Option("PVG,HGH", help="Comma-separated destination IATA codes."),
    depart: str = typer.Option("2026-07-08:2026-07-10", help="Date or range YYYY-MM-DD:YYYY-MM-DD."),
    return_: str = typer.Option(
        "2026-07-30:2026-07-31",
        "--return",
        help="Date or range YYYY-MM-DD:YYYY-MM-DD.",
    ),
    stops: str = typer.Option("2", help="Maximum stops: ANY, 0, 1, 2."),
    limit_per_query: int = typer.Option(2, min=1, max=10, help="Keep N cheapest flights per query."),
    output: Path = typer.Option(Path("data/results.csv"), help="CSV output path."),
    show: int = typer.Option(15, help="Rows to show in terminal."),
    timeout_seconds: int = typer.Option(60, help="Seconds before skipping a slow Fli query."),
    use_cache: bool = typer.Option(True, help="Reuse cached Fli JSON responses."),
) -> None:
    all_rows: list[SearchRow] = []
    origin_codes = split_codes(origins)
    destination_codes = split_codes(destinations)
    depart_dates = parse_date_range(depart)
    return_dates = parse_date_range(return_)
    total_queries = len(origin_codes) * len(destination_codes) * len(depart_dates) * len(return_dates)

    console.print(f"Running {total_queries} Fli queries...")
    for origin in origin_codes:
        for destination in destination_codes:
            for depart_date in depart_dates:
                for return_date in return_dates:
                    try:
                        payload = run_fli(
                            origin,
                            destination,
                            depart_date,
                            return_date,
                            stops,
                            timeout_seconds,
                            use_cache,
                        )
                    except Exception as exc:
                        console.print(f"[yellow]Skipped {origin}-{destination} {depart_date}/{return_date}: {exc}[/yellow]")
                        continue
                    rows = rows_from_payload(
                        origin,
                        destination,
                        depart_date,
                        return_date,
                        payload,
                        limit_per_query,
                    )
                    all_rows.extend(rows)
                    all_rows.sort(key=lambda row: (row.estimated_total_eur, row.duration_hours))
                    write_csv(all_rows, output)

    all_rows.sort(key=lambda row: (row.estimated_total_eur, row.duration_hours))
    write_csv(all_rows, output)
    render_table(all_rows, show)
    console.print(f"Saved {len(all_rows)} rows to [bold]{output}[/bold]")


if __name__ == "__main__":
    app()
