"""Brand Health Score (0-100).

Four components, each measured for every brand over the same period:

  growth     Revenue growth % vs. the comparison period            weight 0.30
  margin     Margin %                                              weight 0.25
  rating     Average review rating                                 weight 0.25
  position   Market position change, in percentage points          weight 0.20
               real   = change in average market share (6 brands with data)
               proxy  = change in Premium Retailer Share, i.e. the share of
                        revenue sold through Tier-1 retailers (5 brands
                        without market-share data)

Scoring
  Each component is turned into a z-score against the 11 brands, then into a
  0-100 score with the normal CDF (50 = average brand, ~84 = one standard
  deviation better). The position component is standardised *within its own
  source group*: real-share brands against real-share brands, proxy brands
  against proxy brands. The two measures are on different scales, so ranking
  them together would compare unlike things.

  Health = sum(weight x component score).

Why the proxy is Premium Retailer Share and not "revenue share among the 11
brands": the latter was tested against the 6 brands with real share and got
the trend direction wrong for 5 of 6 (the 11 brands are a closed set, so it's
zero-sum). Tier-1 share is a different but genuine signal of distribution
strength, and it is always labelled as a proxy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from .engine import Engine, PeriodLike
from .filters import Filters

WEIGHTS = {"growth": 0.30, "margin": 0.25, "rating": 0.25, "position": 0.20}


def _z(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    return pd.Series(0.0, index=s.index) if not sd or np.isnan(sd) else (s - s.mean()) / sd


def health_scores(engine: Engine, period: PeriodLike = "YTD", mode: str = "yoy", as_of=None,
                  weights: dict | None = None) -> pd.DataFrame:
    w = weights or WEIGHTS
    brands = sorted(engine.m.products["Brand"].unique())
    share_brands = set(engine.m.market_share["Brand"].unique())
    core = set(engine.core_brands())

    rows = []
    for b in brands:
        f = Filters.make(brands=b)
        rev = engine.compare("revenue", f, period, mode, as_of)
        if b in share_brands:
            pos = engine.compare("market_share", f, period, mode, as_of)
            source = "real"
        else:
            pos = engine.compare("tier1_revenue_share", f, period, mode, as_of)
            source = "proxy"
        rows.append({
            "Brand": b,
            "IsCore": b in core,
            "growth": rev["delta_pct"],
            "margin": engine.value("margin_pct", f, period, as_of),
            "rating": engine.value("avg_rating", f, period, as_of),
            "position": pos["delta"],
            "position_level": pos["current"],
            "position_source": source,
        })
    df = pd.DataFrame(rows).set_index("Brand")

    z = pd.DataFrame(index=df.index)
    for c in ("growth", "margin", "rating"):
        z[c] = _z(df[c].astype(float))
    z["position"] = df.groupby("position_source")["position"].transform(lambda s: _z(s.astype(float)))

    for c in WEIGHTS:
        df[f"{c}_score"] = (100 * norm.cdf(z[c].fillna(0))).round(1)
    df["health_score"] = sum(df[f"{c}_score"] * wt for c, wt in w.items()).round(1)
    df["rank"] = df["health_score"].rank(ascending=False, method="min").astype(int)
    p, _ = engine.period(period, as_of)
    c = engine.comparison_period(period, mode, as_of)
    df.attrs.update(period=p.to_dict(), comparison=c.to_dict() if c else None, weights=w)
    return df.sort_values("health_score", ascending=False)
