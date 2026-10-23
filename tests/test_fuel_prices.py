from __future__ import annotations

import io

import openpyxl

from offroad_scraper.fuel_prices import FuelPriceProvider


def _xlsx(rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_returns_eur_per_litre() -> None:
    raw = _xlsx(
        [
            ["in EUR", "Euro-super 95", "Gas oil automobile", "Heating gas oil"],
            [None, "1000 l", "1000 l", "1000 l"],
            ["Poland", 1600, 1790.46, 1500],
            ["Germany", 1800, 2266.0, 1600],
            ["Italy", 1900, 2244.44, 1700],
        ]
    )
    prices = FuelPriceProvider._parse(raw)
    assert prices == {"Poland": 1.79, "Germany": 2.27, "Italy": 2.24}


def test_parse_skips_average_rows() -> None:
    raw = _xlsx(
        [
            ["in EUR", "Euro-super 95", "Gas oil automobile"],
            [None, "1000 l", "1000 l"],
            ["Poland", 1600, 1790.46],
            ["CE/EC/EG EUR27_2020 (IV)", None, None],
            ["Moyenne pondérée", 1700, 2138.67],
            ["Weighted average", 1700, 2138.67],
            ["Gewichteter Durchschnitt", 1700, 2138.67],
        ]
    )
    prices = FuelPriceProvider._parse(raw)
    assert prices == {"Poland": 1.79}
