"""Fetch 4-hour OHLCV candles for crypto assets from Alpaca's Crypto API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ALPACA_CRYPTO_DATA_URL = "https://data.alpaca.markets/v1beta3/crypto/us/bars"

# Map friendly names to Alpaca crypto symbols
SYMBOL_MAP = {
    "BTC": "BTC/USD",
    "ETH": "ETH/USD",
    "BTC/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
}


class CryptoDataClient:
    """Fetch historical crypto OHLCV data from Alpaca."""

    def __init__(self, api_key: str, secret_key: str):
        self._api_key = api_key
        self._secret_key = secret_key
        self._session = requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        })

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "4Hour",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """Fetch OHLCV bars for a crypto symbol.

        Parameters
        ----------
        symbol : str
            e.g. "BTC", "ETH", "BTC/USD"
        timeframe : str
            Alpaca timeframe string, default "4Hour"
        start : datetime, optional
            Start time (UTC). Defaults to 90 days ago.
        end : datetime, optional
            End time (UTC). Defaults to now.
        limit : int
            Max bars per request.

        Returns
        -------
        pd.DataFrame
            Columns: [timestamp, open, high, low, close, volume, vwap, trade_count]
        """
        alpaca_symbol = SYMBOL_MAP.get(symbol, symbol)

        if start is None:
            start = datetime.utcnow() - timedelta(days=90)
        if end is None:
            end = datetime.utcnow()

        all_bars = []
        page_token = None

        while True:
            params = {
                "symbols": alpaca_symbol,
                "timeframe": timeframe,
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "limit": limit,
                "sort": "asc",
            }
            if page_token:
                params["page_token"] = page_token

            resp = self._session.get(ALPACA_CRYPTO_DATA_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            bars = data.get("bars", {}).get(alpaca_symbol, [])
            all_bars.extend(bars)

            page_token = data.get("next_page_token")
            if not page_token or not bars:
                break

        if not all_bars:
            logger.warning("No bars returned for %s", alpaca_symbol)
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(all_bars)
        df.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                           "l": "low", "c": "close", "v": "volume",
                           "vw": "vwap", "n": "trade_count"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        logger.info("Fetched %d bars for %s (%s)", len(df), alpaca_symbol, timeframe)
        return df
