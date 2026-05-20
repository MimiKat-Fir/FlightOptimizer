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
import airportsdata
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
from rich.table import Table


app = typer.Typer(help="Scan flight/date matrices using Fli.")
console = Console()
AIRPORTS_BY_IATA = airportsdata.load("IATA")


DESTINATION_EXTRAS_EUR = {
    "HGH": 0,
    "PVG": 15,
    "SHA": 12,
    "NKG": 30,
    "PEK": 55,
    "PKX": 55,
}

HOME_TRANSFER_EUR = {
    "VLC": 0,
    "MAD": 40,
    "BCN": 40,
}


@dataclass(frozen=True)
class FlightOption:
    origin: str
    destination: str
    date: str
    price: float
    currency: str
    duration_hours: float
    stops: int
    airline_summary: str


@dataclass(frozen=True)
class SearchRow:
    origin: str
    destination: str
    return_origin: str
    depart_date: str
    return_date: str
    outbound_price: float
    return_price: float
    flight_total: float
    currency: str
    route_shape: str
    duration_hours: float
    stops: int
    airline_summary: str
    destination_transfer_eur: float
    origin_transfer_eur: float
    return_transfer_eur: float
    hotel_penalty_eur: float
    penalty_total_eur: float
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


def validate_airport_codes(codes: Iterable[str]) -> None:
    invalid = [code for code in codes if code not in AIRPORTS_BY_IATA]
    if invalid:
        code_list = ", ".join(invalid)
        console.print(f"[red]{code_list} airport does not exist, review the configuration and try again.[/red]")
        raise typer.Exit(code=1)


def fli_executable() -> Path:
    script_dir = Path(__file__).resolve().parent
    env_dir = Path(sys.executable).resolve().parent
    for env_candidate in (
        env_dir / "fli.exe",
        env_dir / "Scripts" / "fli.exe",
        env_dir.parent / "Scripts" / "fli.exe",
    ):
        if env_candidate.exists():
            return env_candidate
    candidate = script_dir / ".venv" / "Scripts" / "fli.exe"
    if candidate.exists():
        return candidate
    return Path("fli")


def cache_path(origin: str, destination: str, depart: str, stops: str, trip: str) -> Path:
    key = f"{trip}-{origin}-{destination}-{depart}-{stops}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return Path("data/cache") / f"{key}-{digest}.json"


def run_fli(
    origin: str,
    destination: str,
    depart: str,
    stops: str,
    timeout_seconds: int,
    use_cache: bool,
) -> dict:
    cache_file = cache_path(origin, destination, depart, stops, "oneway")
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    command = [
        str(fli_executable()),
        "flights",
        origin,
        destination,
        depart,
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
    for leg in flight.get("legs", []):
        code = leg.get("airline", {}).get("code")
        if code and code not in codes:
            codes.append(code)
    for section in ("outbound", "return"):
        for leg in flight.get(section, {}).get("legs", []):
            code = leg.get("airline", {}).get("code")
            if code and code not in codes:
                codes.append(code)
    return "/".join(codes)


def flight_options_from_payload(
    origin: str,
    destination: str,
    depart: str,
    payload: dict,
    limit: int,
) -> list[FlightOption]:
    options: list[FlightOption] = []
    for flight in payload.get("flights", [])[:limit]:
        price = float(flight.get("price") or 0)
        if price <= 0:
            continue
        currency = flight.get("currency") or "EUR"
        options.append(
            FlightOption(
                origin=origin,
                destination=destination,
                date=depart,
                price=price,
                currency=currency,
                duration_hours=round(float(flight.get("duration") or 0) / 60, 1),
                stops=int(flight.get("stops") or 0),
                airline_summary=airline_summary(flight),
            )
        )
    return options


def hotel_penalty(depart_date: str, free_arrival_date: str, hotel_per_night: float) -> float:
    departure = date.fromisoformat(depart_date)
    free_arrival = date.fromisoformat(free_arrival_date)
    early_days = max((free_arrival - departure).days, 0)
    return float(early_days * hotel_per_night)


def combine_options(
    outbound: FlightOption,
    inbound: FlightOption,
    free_arrival_date: str,
    hotel_per_night: float,
) -> SearchRow | None:
    if outbound.currency != "EUR" or inbound.currency != "EUR":
        return None
    route_shape = "round_trip_shape" if outbound.origin == inbound.destination else "open_jaw_shape"
    destination_transfer = float(DESTINATION_EXTRAS_EUR.get(outbound.destination, 40))
    origin_transfer = float(HOME_TRANSFER_EUR.get(outbound.origin, 40))
    return_transfer = float(HOME_TRANSFER_EUR.get(inbound.destination, 40))
    hotel = hotel_penalty(outbound.date, free_arrival_date, hotel_per_night)
    flight_total = outbound.price + inbound.price
    penalty_total = destination_transfer + origin_transfer + return_transfer + hotel
    return SearchRow(
        origin=outbound.origin,
        destination=outbound.destination,
        return_origin=inbound.destination,
        depart_date=outbound.date,
        return_date=inbound.date,
        outbound_price=outbound.price,
        return_price=inbound.price,
        flight_total=round(flight_total, 2),
        currency="EUR",
        route_shape=route_shape,
        duration_hours=round(outbound.duration_hours + inbound.duration_hours, 1),
        stops=outbound.stops + inbound.stops,
        airline_summary="/".join(
            dict.fromkeys(
                code
                for summary in (outbound.airline_summary, inbound.airline_summary)
                for code in summary.split("/")
                if code
            )
        ),
        destination_transfer_eur=destination_transfer,
        origin_transfer_eur=origin_transfer,
        return_transfer_eur=return_transfer,
        hotel_penalty_eur=hotel,
        penalty_total_eur=round(penalty_total, 2),
        estimated_total_eur=round(flight_total + penalty_total, 2),
    )


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
            f"{row.origin}-{row.destination}-{row.return_origin}",
            f"{row.depart_date} / {row.return_date}",
            f"{row.flight_total:.0f} {row.currency}",
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
    return_origins: str | None = typer.Option(
        None,
        "--return-origins",
        help="Comma-separated final return airport IATA codes. Defaults to --origins.",
    ),
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
    free_arrival_date: str = typer.Option(
        "2026-07-12",
        help="Date when free accommodation starts. Earlier departures add hotel penalty.",
    ),
    hotel_per_night: float = typer.Option(40.0, help="Cheap hotel penalty per early day."),
) -> None:
    all_rows: list[SearchRow] = []
    origin_codes = split_codes(origins)
    destination_codes = split_codes(destinations)
    return_origin_codes = split_codes(return_origins) if return_origins else origin_codes
    validate_airport_codes(origin_codes + destination_codes + return_origin_codes)
    depart_dates = parse_date_range(depart)
    return_dates = parse_date_range(return_)
    total_queries = (
        len(origin_codes) * len(destination_codes) * len(depart_dates)
        + len(destination_codes) * len(return_origin_codes) * len(return_dates)
    )
    outbound_options: dict[tuple[str, str, str], list[FlightOption]] = {}
    inbound_options: dict[tuple[str, str, str], list[FlightOption]] = {}

    console.print(f"Running {total_queries} Fli queries...")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Starting", total=total_queries)
        for origin in origin_codes:
            for destination in destination_codes:
                for depart_date in depart_dates:
                    label = f"OUT {origin}-{destination} {depart_date}"
                    progress.update(task, description=label)
                    try:
                        payload = run_fli(
                            origin,
                            destination,
                            depart_date,
                            stops,
                            timeout_seconds,
                            use_cache,
                        )
                        outbound_options[(origin, destination, depart_date)] = flight_options_from_payload(
                            origin, destination, depart_date, payload, limit_per_query
                        )
                    except Exception as exc:
                        progress.console.print(f"[yellow]Skipped {label}: {exc}[/yellow]")
                    progress.advance(task)

        for destination in destination_codes:
            for return_origin in return_origin_codes:
                for return_date in return_dates:
                    label = f"RET {destination}-{return_origin} {return_date}"
                    progress.update(task, description=label)
                    try:
                        payload = run_fli(
                            destination,
                            return_origin,
                            return_date,
                            stops,
                            timeout_seconds,
                            use_cache,
                        )
                        inbound_options[(destination, return_origin, return_date)] = flight_options_from_payload(
                            destination, return_origin, return_date, payload, limit_per_query
                        )
                    except Exception as exc:
                        progress.console.print(f"[yellow]Skipped {label}: {exc}[/yellow]")
                    progress.advance(task)

                    all_rows = []
                    for origin in origin_codes:
                        for destination_for_combo in destination_codes:
                            for return_origin_for_combo in return_origin_codes:
                                for depart_date in depart_dates:
                                    for return_date_for_combo in return_dates:
                                        for outbound in outbound_options.get(
                                            (origin, destination_for_combo, depart_date), []
                                        ):
                                            for inbound in inbound_options.get(
                                                (destination_for_combo, return_origin_for_combo, return_date_for_combo), []
                                            ):
                                                row = combine_options(
                                                    outbound,
                                                    inbound,
                                                    free_arrival_date,
                                                    hotel_per_night,
                                                )
                                                if row is not None:
                                                    all_rows.append(row)
                    all_rows.sort(key=lambda row: (row.estimated_total_eur, row.duration_hours))
                    write_csv(all_rows, output)

    all_rows.sort(key=lambda row: (row.estimated_total_eur, row.duration_hours))
    write_csv(all_rows, output)
    render_table(all_rows, show)
    console.print(f"Saved {len(all_rows)} rows to [bold]{output}[/bold]")


if __name__ == "__main__":
    app()
