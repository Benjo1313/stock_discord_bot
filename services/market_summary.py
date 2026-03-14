from services.market_data import get_current_price

INDEX_ETFS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "DIA": "Dow Jones",
    "IWM": "Russell 2000",
}

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLC": "Communication",
    "XLY": "Cons. Discretionary",
    "XLP": "Cons. Staples",
    "XLRE": "Real Estate",
    "XLU": "Utilities",
    "XLB": "Materials",
}


def get_market_overview() -> dict:
    indices = {}
    for symbol, name in INDEX_ETFS.items():
        data = get_current_price(symbol)
        if data:
            indices[symbol] = {"name": name, **data}

    sectors = {}
    for symbol, name in SECTOR_ETFS.items():
        data = get_current_price(symbol)
        if data:
            sectors[symbol] = {"name": name, **data}

    return {"indices": indices, "sectors": sectors}
