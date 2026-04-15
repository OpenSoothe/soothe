"""Tabular data inspection and quality validation tools.

Ported from noesium's tabular_data toolkit. langchain has `create_csv_agent`
but no direct equivalent for column inspection or data quality validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
_MAX_SAMPLE_DISPLAY_LENGTH = 50
_HIGH_MISSING_THRESHOLD_PCT = 50


def _load_dataframe(file_path: str) -> Any:
    """Load a tabular file into a pandas DataFrame.

    Supports CSV, TSV, Excel (.xlsx/.xls), JSON, and Parquet.

    Args:
        file_path: Path to the data file.

    Returns:
        pandas DataFrame.

    Raises:
        ValueError: If file is too large or format is unsupported.
        FileNotFoundError: If file does not exist.
    """
    import pandas as pd

    path = Path(file_path)
    if not path.exists():
        msg = f"File not found: {file_path}"
        raise FileNotFoundError(msg)

    if path.stat().st_size > _MAX_FILE_SIZE:
        msg = f"File exceeds {_MAX_FILE_SIZE // (1024 * 1024)}MB limit"
        raise ValueError(msg)

    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        sep = "\t" if suffix == ".tsv" else ","
        for encoding in ("utf-8", "latin1", "cp1252", "iso-8859-1"):
            try:
                return pd.read_csv(path, sep=sep, encoding=encoding)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(path, sep=sep, encoding="utf-8", errors="replace")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        return pd.read_json(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)

    msg = f"Unsupported file format: {suffix}"
    raise ValueError(msg)


class TabularColumnsTool(BaseTool):
    """List columns and basic statistics for a tabular data file."""

    name: str = "get_tabular_columns"
    description: str = (
        "List columns with types, null counts, and sample values for a data file. "
        "Supports CSV, TSV, Excel, JSON, and Parquet. Provide `file_path`."
    )
    max_file_size: int = Field(default=_MAX_FILE_SIZE)

    def _run(self, file_path: str) -> str:
        df = _load_dataframe(file_path)
        lines = [f"Columns ({len(df.columns)}) | Rows: {len(df)}"]
        lines.append("-" * 60)
        for col in df.columns:
            dtype = str(df[col].dtype)
            nulls = int(df[col].isna().sum())
            null_pct = round(nulls / len(df) * 100, 1) if len(df) > 0 else 0
            sample = str(df[col].dropna().iloc[0]) if not df[col].dropna().empty else "N/A"
            if len(sample) > _MAX_SAMPLE_DISPLAY_LENGTH:
                sample = sample[:_MAX_SAMPLE_DISPLAY_LENGTH] + "..."
            lines.append(f"  {col}: {dtype} | nulls: {nulls} ({null_pct}%) | sample: {sample}")
        return "\n".join(lines)

    async def _arun(self, file_path: str) -> str:
        return self._run(file_path)


class TabularSummaryTool(BaseTool):
    """Generate a data summary including shape, types, and statistics."""

    name: str = "get_data_summary"
    description: str = (
        "Generate a summary of a tabular data file: shape, dtypes, missing data, "
        "numeric statistics, and categorical value counts. Provide `file_path`."
    )

    def _run(self, file_path: str) -> str:
        df = _load_dataframe(file_path)
        lines = [
            f"Shape: {df.shape[0]} rows x {df.shape[1]} columns",
            f"Memory: {df.memory_usage(deep=True).sum() / 1024:.1f} KB",
            "",
            "Dtypes:",
        ]
        lines.extend(f"  {dtype}: {count}" for dtype, count in df.dtypes.value_counts().items())

        missing = df.isna().sum()
        if missing.any():
            lines.append("\nMissing data:")
            lines.extend(
                f"  {col}: {missing[col]} ({missing[col] / len(df) * 100:.1f}%)"
                for col in missing[missing > 0].index
            )

        numerics = df.select_dtypes(include="number")
        if not numerics.empty:
            lines.append("\nNumeric summary:")
            lines.append(numerics.describe().to_string())

        return "\n".join(lines)

    async def _arun(self, file_path: str) -> str:
        return self._run(file_path)


class TabularQualityTool(BaseTool):
    """Validate data quality for a tabular data file."""

    name: str = "validate_data_quality"
    description: str = (
        "Run data quality checks on a tabular file: high missing rates, "
        "duplicate rows, single-value columns, and mixed types. Provide `file_path`."
    )

    def _run(self, file_path: str) -> str:
        df = _load_dataframe(file_path)
        issues: list[str] = []

        for col in df.columns:
            null_pct = df[col].isna().sum() / len(df) * 100 if len(df) > 0 else 0
            if null_pct > _HIGH_MISSING_THRESHOLD_PCT:
                issues.append(f"HIGH MISSING: {col} has {null_pct:.1f}% missing values")

        dupes = df.duplicated().sum()
        if dupes > 0:
            issues.append(f"DUPLICATES: {dupes} duplicate rows ({dupes / len(df) * 100:.1f}%)")

        for col in df.columns:
            # Check for constant columns efficiently
            if (df[col] == df[col].iloc[0]).all() if len(df) > 0 else True:
                unique_count = df[col].nunique()
                issues.append(f"SINGLE VALUE: {col} has only {unique_count} unique value(s)")

        if not issues:
            return "No data quality issues found."
        return "Data quality issues:\n" + "\n".join(f"  - {i}" for i in issues)

    async def _arun(self, file_path: str) -> str:
        return self._run(file_path)


def create_tabular_tools() -> list[BaseTool]:
    """Create tabular data inspection tools.

    Returns:
        List of tabular data `BaseTool` instances.
    """
    return [TabularColumnsTool(), TabularSummaryTool(), TabularQualityTool()]
