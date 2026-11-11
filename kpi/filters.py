"""Filters shared by every KPI.

A Filters object lists the values to keep for each dimension; an empty field
means "no filter". Each data source only understands some dimensions (reviews
have no retailer, market share has only Brand), so `apply` ignores filters a
source can't use and reports them, letting the UI say "retailer filter does
not apply to ratings" instead of silently showing the wrong number.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

import pandas as pd

# dimension field -> column name in the processed tables
DIMENSIONS = {
    "brands": "Brand",
    "manufacturers": "Manufacturer",
    "products": "ProductID",
    "categories": "Category",
    "subcategories": "SubCategory",
    "retailers": "Retailer",
    "channels": "Channel",
    "tiers": "Tier",
    "regions": "Region",
    "promotions": "Promotion",
}

# which filter dimensions each source supports
SOURCE_DIMENSIONS = {
    "sales": set(DIMENSIONS),
    "reviews": {"brands", "manufacturers", "products", "categories", "subcategories"},
    "inventory": {"brands", "manufacturers", "products", "categories", "subcategories"},
    "market_share": {"brands"},
    "marketing": set(),
    "events": {"manufacturers"},
}


@dataclass(frozen=True)
class Filters:
    brands: tuple = ()
    manufacturers: tuple = ()
    products: tuple = ()
    categories: tuple = ()
    subcategories: tuple = ()
    retailers: tuple = ()
    channels: tuple = ()
    tiers: tuple = ()
    regions: tuple = ()
    promotions: tuple = ()

    @classmethod
    def make(cls, **kw) -> "Filters":
        clean = {}
        for k, v in kw.items():
            if k not in DIMENSIONS:
                raise ValueError(f"Unknown filter {k!r}; use one of {list(DIMENSIONS)}")
            if v is None:
                continue
            clean[k] = (v,) if isinstance(v, str) else tuple(v)
        return cls(**clean)

    def with_(self, **kw) -> "Filters":
        return replace(self, **{k: ((v,) if isinstance(v, str) else tuple(v or ())) for k, v in kw.items()})

    def active(self) -> dict:
        return {k: list(v) for k, v in asdict(self).items() if v}

    def apply(self, df: pd.DataFrame, source: str) -> tuple[pd.DataFrame, list[str]]:
        """Filter df; return it plus the names of filters this source ignored."""
        allowed = SOURCE_DIMENSIONS[source]
        ignored, mask = [], pd.Series(True, index=df.index)
        for name, values in asdict(self).items():
            if not values:
                continue
            if name not in allowed:
                ignored.append(name)
                continue
            col = DIMENSIONS[name] if source != "events" else "Competitor"
            mask &= df[col].isin(values)
        return df[mask], ignored
