"""Convert Pine Script strategies to Python/VectorBT.

Handles common Pine Script constructs and maps them to pandas/numpy equivalents.
For complex scripts that can't be auto-converted, flags them for manual review.
"""

from __future__ import annotations

import logging
import re
import textwrap
from typing import Optional

from whitelight.research.database import StrategyDB

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pine Script → Python mapping tables
# ---------------------------------------------------------------------------

# Pine Script indicator functions → pandas/numpy equivalents
INDICATOR_MAP = {
    "ta.sma": "df['close'].rolling({period}).mean()",
    "ta.ema": "df['close'].ewm(span={period}, adjust=False).mean()",
    "ta.rsi": "_rsi(df['close'], {period})",
    "ta.wma": "df['close'].rolling({period}).apply(lambda x: np.average(x, weights=range(1, len(x)+1)))",
    "ta.stdev": "df['close'].rolling({period}).std()",
    "ta.highest": "df['high'].rolling({period}).max()",
    "ta.lowest": "df['low'].rolling({period}).min()",
    "ta.atr": "_atr(df, {period})",
    "ta.tr": "_true_range(df)",
    "ta.change": "df['close'].diff({period})",
    "ta.mom": "df['close'].diff({period})",
    "ta.roc": "df['close'].pct_change({period}) * 100",
    "ta.vwap": "(df['close'] * df['volume']).cumsum() / df['volume'].cumsum()",
    "ta.bb": "_bollinger_bands(df['close'], {period}, {mult})",
    "ta.macd": "_macd(df['close'], {fast}, {slow}, {signal})",
    "ta.crossover": "(_prev({a}) <= _prev({b})) & ({a} > {b})",
    "ta.crossunder": "(_prev({a}) >= _prev({b})) & ({a} < {b})",
}

# Template for the generated Python strategy function
STRATEGY_TEMPLATE = textwrap.dedent("""\
    import numpy as np
    import pandas as pd

    def _rsi(series, period=14):
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def _atr(df, period=14):
        high, low, close = df['high'], df['low'], df['close']
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def _true_range(df):
        high, low, close = df['high'], df['low'], df['close']
        return pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)

    def _bollinger_bands(series, period=20, mult=2.0):
        mid = series.rolling(period).mean()
        std = series.rolling(period).std()
        upper = mid + mult * std
        lower = mid - mult * std
        return mid, upper, lower

    def _macd(series, fast=12, slow=26, signal=9):
        fast_ema = series.ewm(span=fast, adjust=False).mean()
        slow_ema = series.ewm(span=slow, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def _prev(series):
        return series.shift(1)

    def strategy(df):
        \"\"\"Generated strategy: {name}
        
        Source: {source}
        Converted from Pine Script automatically.
        
        Returns:
            entries (pd.Series[bool]): True on buy signal
            exits (pd.Series[bool]): True on sell signal
        \"\"\"
        df = df.copy()
        
    {logic}
        
        return entries.fillna(False), exits.fillna(False)
""")


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------


class PineConverter:
    """Convert Pine Script to Python strategy functions."""

    def convert(self, pine_script: str, name: str = "unnamed", source: str = "") -> Optional[str]:
        """Attempt to convert Pine Script to a Python strategy function.

        Returns Python code string, or None if conversion fails.
        """
        if not pine_script or len(pine_script) < 50:
            return None

        try:
            # Extract key components from Pine Script
            inputs = self._extract_inputs(pine_script)
            indicators = self._extract_indicators(pine_script)
            conditions = self._extract_conditions(pine_script)

            if not conditions.get("entry") and not conditions.get("exit"):
                logger.warning("No entry/exit conditions found in %s", name)
                return None

            # Build Python logic
            logic_lines = []

            # Add indicator calculations
            for var_name, calc in indicators.items():
                logic_lines.append(f"    {var_name} = {calc}")

            logic_lines.append("")
            logic_lines.append("    # Entry/exit signals")

            # Add entry condition
            if conditions.get("entry"):
                logic_lines.append(f"    entries = {conditions['entry']}")
            else:
                logic_lines.append("    entries = pd.Series(False, index=df.index)")

            # Add exit condition
            if conditions.get("exit"):
                logic_lines.append(f"    exits = {conditions['exit']}")
            else:
                logic_lines.append("    exits = pd.Series(False, index=df.index)")

            logic = "\n".join(logic_lines)

            code = STRATEGY_TEMPLATE.format(
                name=name,
                source=source,
                logic=logic,
            )

            # Validate the generated code compiles
            compile(code, "<strategy>", "exec")

            return code

        except Exception as e:
            logger.error("Conversion failed for %s: %s", name, e)
            return None

    def _extract_inputs(self, pine: str) -> dict:
        """Extract input() declarations and their default values."""
        inputs = {}
        for match in re.finditer(
            r'(\w+)\s*=\s*input(?:\.(?:int|float|bool|string))?\s*\(\s*(?:defval\s*=\s*)?([^,\)]+)',
            pine,
        ):
            var_name = match.group(1)
            default = match.group(2).strip()
            inputs[var_name] = default
        return inputs

    def _extract_indicators(self, pine: str) -> dict:
        """Extract indicator calculations and convert to Python."""
        indicators = {}

        # SMA: ta.sma(close, length)
        for match in re.finditer(r'(\w+)\s*=\s*ta\.sma\s*\(\s*(\w+)\s*,\s*(\w+|\d+)\s*\)', pine):
            var, src, period = match.groups()
            period = self._resolve_value(period)
            indicators[var] = f"df['close'].rolling({period}).mean()"

        # EMA: ta.ema(close, length)
        for match in re.finditer(r'(\w+)\s*=\s*ta\.ema\s*\(\s*(\w+)\s*,\s*(\w+|\d+)\s*\)', pine):
            var, src, period = match.groups()
            period = self._resolve_value(period)
            indicators[var] = f"df['close'].ewm(span={period}, adjust=False).mean()"

        # RSI: ta.rsi(close, length)
        for match in re.finditer(r'(\w+)\s*=\s*ta\.rsi\s*\(\s*(\w+)\s*,\s*(\w+|\d+)\s*\)', pine):
            var, src, period = match.groups()
            period = self._resolve_value(period)
            indicators[var] = f"_rsi(df['close'], {period})"

        # MACD
        for match in re.finditer(
            r'\[(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\]\s*=\s*ta\.macd\s*\(\s*(\w+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)',
            pine,
        ):
            macd_var, sig_var, hist_var, src, fast, slow, signal = match.groups()
            indicators[f"{macd_var}, {sig_var}, {hist_var}"] = f"_macd(df['close'], {fast}, {slow}, {signal})"

        # ATR
        for match in re.finditer(r'(\w+)\s*=\s*ta\.atr\s*\(\s*(\w+|\d+)\s*\)', pine):
            var, period = match.groups()
            period = self._resolve_value(period)
            indicators[var] = f"_atr(df, {period})"

        # Bollinger Bands
        for match in re.finditer(
            r'\[(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\]\s*=\s*ta\.bb\s*\(\s*(\w+)\s*,\s*(\d+)\s*,\s*(\d+\.?\d*)\s*\)',
            pine,
        ):
            mid, upper, lower, src, period, mult = match.groups()
            indicators[f"{mid}, {upper}, {lower}"] = f"_bollinger_bands(df['close'], {period}, {mult})"

        # Highest/Lowest
        for match in re.finditer(r'(\w+)\s*=\s*ta\.highest\s*\(\s*(\w+)\s*,\s*(\w+|\d+)\s*\)', pine):
            var, src, period = match.groups()
            period = self._resolve_value(period)
            col = "high" if "high" in src.lower() else "close"
            indicators[var] = f"df['{col}'].rolling({period}).max()"

        for match in re.finditer(r'(\w+)\s*=\s*ta\.lowest\s*\(\s*(\w+)\s*,\s*(\w+|\d+)\s*\)', pine):
            var, src, period = match.groups()
            period = self._resolve_value(period)
            col = "low" if "low" in src.lower() else "close"
            indicators[var] = f"df['{col}'].rolling({period}).min()"

        # Simple variable assignments (close, open, etc.)
        for match in re.finditer(r'(\w+)\s*=\s*(close|open|high|low|volume)\b', pine):
            var, col = match.groups()
            if var not in indicators:
                indicators[var] = f"df['{col}']"

        return indicators

    def _extract_conditions(self, pine: str) -> dict:
        """Extract strategy entry/exit conditions."""
        conditions = {}

        # strategy.entry("Long", ..., when=condition) or strategy.entry("Long", ...) with preceding if
        entry_patterns = [
            # if condition \n strategy.entry
            r'if\s+(.+?)\s*\n\s*strategy\.entry\s*\(\s*["\'](?:Long|Buy)',
            # strategy.entry(..., when=condition)
            r'strategy\.entry\s*\([^)]*when\s*=\s*(.+?)\s*\)',
            # longCondition = ... \n if longCondition \n strategy.entry
            r'(\w+Condition\w*)\s*(?:=\s*true)?\s*\n\s*(?:if\s+\1\s*\n\s*)?strategy\.entry',
        ]

        for pattern in entry_patterns:
            match = re.search(pattern, pine, re.IGNORECASE)
            if match:
                cond = match.group(1).strip()
                conditions["entry"] = self._convert_condition(cond, pine)
                break

        # Look for the condition variable definition
        if "entry" not in conditions:
            for match in re.finditer(r'(long\w*|buy\w*|enter\w*)\s*=\s*(.+)', pine, re.IGNORECASE):
                var_name, cond = match.groups()
                if "strategy" not in cond and len(cond) < 200:
                    conditions["entry"] = self._convert_condition(cond.strip(), pine)
                    break

        # Exit conditions
        exit_patterns = [
            r'if\s+(.+?)\s*\n\s*strategy\.close',
            r'strategy\.close\s*\([^)]*when\s*=\s*(.+?)\s*\)',
            r'strategy\.exit\s*\([^)]*when\s*=\s*(.+?)\s*\)',
        ]

        for pattern in exit_patterns:
            match = re.search(pattern, pine, re.IGNORECASE)
            if match:
                cond = match.group(1).strip()
                conditions["exit"] = self._convert_condition(cond, pine)
                break

        if "exit" not in conditions:
            for match in re.finditer(r'(short\w*|sell\w*|exit\w*)\s*=\s*(.+)', pine, re.IGNORECASE):
                var_name, cond = match.groups()
                if "strategy" not in cond and len(cond) < 200:
                    conditions["exit"] = self._convert_condition(cond.strip(), pine)
                    break

        return conditions

    def _convert_condition(self, pine_cond: str, full_script: str) -> str:
        """Convert a Pine Script condition expression to Python."""
        py = pine_cond

        # ta.crossover(a, b) → (_prev(a) <= _prev(b)) & (a > b)
        py = re.sub(
            r'ta\.crossover\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)',
            r'(_prev(\1) <= _prev(\2)) & (\1 > \2)',
            py,
        )
        py = re.sub(
            r'ta\.crossunder\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)',
            r'(_prev(\1) >= _prev(\2)) & (\1 < \2)',
            py,
        )

        # Replace Pine operators with Python/pandas
        py = py.replace(" and ", " & ")
        py = py.replace(" or ", " | ")
        py = py.replace("not ", "~")
        py = py.replace("true", "True")
        py = py.replace("false", "False")

        # Replace close/open/high/low/volume references
        py = re.sub(r'\bclose\b', "df['close']", py)
        py = re.sub(r'\bopen\b', "df['open']", py)
        py = re.sub(r'\bhigh\b', "df['high']", py)
        py = re.sub(r'\blow\b', "df['low']", py)
        py = re.sub(r'\bvolume\b', "df['volume']", py)

        # Replace comparison operators
        py = py.replace(">", ">").replace("<", "<")

        return py

    def _resolve_value(self, val: str) -> str:
        """Try to resolve a Pine Script variable to a literal value."""
        try:
            int(val)
            return val
        except ValueError:
            return val  # Keep as variable reference


def convert_strategy(
    db: StrategyDB,
    strategy_id: int,
    pine_script: str,
    name: str = "",
    source_url: str = "",
) -> Optional[str]:
    """Convert a Pine Script strategy to Python and store in DB.

    Returns the Python code, or None if conversion failed.
    """
    converter = PineConverter()
    python_code = converter.convert(pine_script, name=name, source=source_url)

    if python_code:
        db.update_python_code(strategy_id, python_code)
        logger.info("Converted strategy #%d to Python (%d chars)", strategy_id, len(python_code))
    else:
        db.update_status(strategy_id, "failed", "Pine Script conversion failed")
        logger.warning("Failed to convert strategy #%d", strategy_id)

    return python_code
