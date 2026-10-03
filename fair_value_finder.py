"""
Fair Value Finder v2 - NSE stock fundamentals, fair value, buy/sell verdict and future price scenarios.
Data: Yahoo Finance via yfinance.

Run as a web app:   streamlit run fair_value_finder.py
Run in terminal:    python fair_value_finder.py TCS SBIN --mos 20

Install once:  pip install yfinance streamlit pandas
Educational tool, not investment advice.
"""
from __future__ import annotations

import math
import statistics
import sys

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _num(v):
    try:
        v = float(v)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def cagr(values, years=5):
    """values oldest -> newest; uses the last (years+1) points."""
    s = [v for v in (_num(x) for x in (values or [])) if v is not None]
    if len(s) < 2:
        return None
    pts = s[-(years + 1):]
    a, b, n = pts[0], pts[-1], len(pts) - 1
    if a <= 0 or b <= 0 or n < 1:
        return None
    return ((b / a) ** (1 / n) - 1) * 100


def is_lender(sector: str, industry: str) -> bool:
    t = f"{sector or ''} {industry or ''}".lower()
    return any(k in t for k in ("financ", "bank", "insur", "nbfc", "lend", "credit"))


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


# ----------------------------------------------------------------------------
# Valuation + quality engine
# ----------------------------------------------------------------------------

def analyse(d: dict, discount=12.0, terminal=5.0, mos=15.0, overrides=None) -> dict:
    """d keys: price, eps, bvps, shares, fcf, roe, roa, net_margin, de, current_ratio,
    sector, industry, hist_pe (list), hist{revenue, eps, net_income, fcf} (oldest->newest).
    overrides: optional dict with eps, bvps, roe, growth (any may be None)."""
    o = overrides or {}
    price = _num(d.get("price"))
    eps = _num(o.get("eps")) or _num(d.get("eps"))
    bvps = _num(o.get("bvps")) or _num(d.get("bvps"))
    roe = _num(o.get("roe")) if _num(o.get("roe")) is not None else _num(d.get("roe"))
    shares, fcf = _num(d.get("shares")), _num(d.get("fcf"))
    fcfps = fcf / shares if (fcf is not None and shares) else None
    H = d.get("hist") or {}
    rev_c = cagr(H.get("revenue"))
    eps_c = cagr(H.get("eps"))
    ni_c = cagr(H.get("net_income"))
    lender = d.get("lender")
    if lender is None:
        lender = is_lender(d.get("sector"), d.get("industry"))

    # Growth used for valuation: manual override, else EPS growth, else profit growth, else revenue growth
    g_used = _num(o.get("growth"))
    g_src = "your override"
    if g_used is None:
        for val, src in ((eps_c, "EPS growth"), (ni_c, "profit growth"), (rev_c, "revenue growth")):
            if val is not None:
                g_used, g_src = val, src
                break
    if g_used is None:
        g_used, g_src = 10.0, "default (no history)"

    hist_pes = [p for p in (_num(x) for x in (d.get("hist_pe") or [])) if p is not None and 0 < p < 150]
    hist_pe = _median(hist_pes)

    methods = []
    # 1. Historical P/E: what the market has usually paid for this company's earnings
    if eps and eps > 0 and hist_pe:
        pe1 = clip(hist_pe, 6, 60)
        methods.append(("Historical P/E", eps * pe1,
                        f"EPS Rs{eps:.2f} x its own median P/E {pe1:.1f} over the last {len(hist_pes)} years"))
    else:
        methods.append(("Historical P/E", None, "Skipped: needs positive EPS and past P/E data"))

    # 2. Growth-adjusted P/E (fair P/E ~ growth, kept between 10 and 35)
    if eps and eps > 0:
        fair_pe = clip(g_used, 10, 35)
        methods.append(("Growth-adjusted P/E", eps * fair_pe,
                        f"EPS Rs{eps:.2f} x fair P/E {fair_pe:.1f} ({g_src} {g_used:.1f}%, capped 10-35)"))
    else:
        methods.append(("Growth-adjusted P/E", None, "Skipped: EPS is zero or negative"))

    # 3. Graham number (conservative; tends to undervalue high-ROE businesses)
    if eps and eps > 0 and bvps and bvps > 0:
        methods.append(("Graham number", math.sqrt(22.5 * eps * bvps),
                        f"sqrt(22.5 x EPS Rs{eps:.2f} x book value/share Rs{bvps:.2f})"))
    else:
        methods.append(("Graham number", None, "Skipped: needs positive EPS and book value"))

    # 4a. Banks/NBFCs: justified P/B = ROE / cost of equity
    # 4b. Others: two-stage DCF on free cash flow
    if lender:
        if roe and roe > 0 and bvps and bvps > 0:
            jpb = clip(roe / discount, 0.3, 5)
            methods.append(("Justified P/B (banks)", bvps * jpb,
                            f"Book value/share Rs{bvps:.2f} x justified P/B {jpb:.2f} (ROE {roe:.1f}% / cost of equity {discount}%)"))
        else:
            methods.append(("Justified P/B (banks)", None, "Skipped: needs positive ROE and book value"))
    elif fcfps and fcfps > 0 and discount > terminal:
        g1 = clip(rev_c if rev_c is not None else 8, 0, 20) / 100
        r, tg = discount / 100, terminal / 100
        cf, pv = fcfps, 0.0
        for y in range(1, 11):
            g = g1 if y <= 5 else g1 + (tg - g1) * (y - 5) / 5
            cf *= 1 + g
            pv += cf / (1 + r) ** y
        pv += cf * (1 + tg) / (r - tg) / (1 + r) ** 10
        methods.append(("Cash-flow DCF", pv,
                        f"FCF/share Rs{fcfps:.2f} grows {g1*100:.1f}% for 5 yrs, fades to {terminal}% by yr 10, discounted at {discount}%"))
    else:
        why = "free cash flow is negative" if (fcfps is not None and fcfps <= 0) else "FCF missing or discount <= terminal growth"
        methods.append(("Cash-flow DCF", None, f"Skipped: {why}"))

    vals = [v for _, v, _ in methods if v is not None and v > 0]
    fair = statistics.median(vals) if vals else None
    buy_below = fair * (1 - mos / 100) if fair else None

    # Quality checks (different set for lenders)
    ni = [x for x in (_num(v) for v in (H.get("net_income") or [])) if x is not None][-5:]
    fc = [x for x in (_num(v) for v in (H.get("fcf") or [])) if x is not None][-5:]
    ni_all = all(x > 0 for x in ni) if ni else None
    pb = price / bvps if (price and bvps and bvps > 0) else None
    if lender:
        roa = _num(d.get("roa"))
        jpb_val = (roe / discount) if (roe and roe > 0) else None
        checks = [
            ("Return on equity", roe, "%", lambda x: x >= 12, ">= 12%"),
            ("Return on assets", roa, "%", lambda x: x >= 1.0, ">= 1%"),
            ("Net profit margin", _num(d.get("net_margin")), "%", lambda x: x >= 15, ">= 15%"),
            ("Revenue growth (CAGR)", rev_c, "%", lambda x: x >= 10, ">= 10% a year"),
            ("EPS growth (CAGR)", eps_c, "%", lambda x: x >= 10, ">= 10% a year"),
            ("Profitable every year", ni_all, "bool", lambda x: x is True, "No loss years"),
            ("P/B vs justified P/B", (pb / jpb_val) if (pb and jpb_val) else None, "x",
             lambda x: x <= 1.0, "<= 1.0x (not overpaying for book)"),
        ]
    else:
        fcf_conv = (sum(fc) / sum(ni) * 100) if (fc and ni and sum(ni) > 0) else None
        checks = [
            ("Return on equity", roe, "%", lambda x: x >= 15, ">= 15%"),
            ("Net profit margin", _num(d.get("net_margin")), "%", lambda x: x >= 10, ">= 10%"),
            ("Revenue growth (CAGR)", rev_c, "%", lambda x: x >= 10, ">= 10% a year"),
            ("EPS growth (CAGR)", eps_c, "%", lambda x: x >= 10, ">= 10% a year"),
            ("Profitable every year", ni_all, "bool", lambda x: x is True, "No loss years"),
            ("Debt / Equity", _num(d.get("de")), "x", lambda x: x <= 0.5, "<= 0.5"),
            ("Current ratio", _num(d.get("current_ratio")), "x", lambda x: x >= 1.2, ">= 1.2"),
            ("FCF / net profit", fcf_conv, "%", lambda x: x >= 80, ">= 80%"),
        ]
    rows = []
    for name, v, fmt, test, rule in checks:
        ok = None if v is None else bool(test(v))
        rows.append({"check": name, "value": v, "fmt": fmt, "rule": rule, "ok": ok})
    scored = [r for r in rows if r["ok"] is not None]
    quality = round(sum(r["ok"] for r in scored) / len(scored) * 100) if scored else None
    missing = len(rows) - len(scored)

    # Verdict
    if not price:
        verdict, tone, reason = "No price", "warn", "Price data missing."
    elif quality is not None and quality < 50:
        verdict, tone = "AVOID", "bad"
        reason = f"Fundamentals weak ({quality}% of checks pass). A low price alone is not a reason to buy."
    elif not fair:
        verdict, tone, reason = "CAN'T VALUE", "warn", "No valuation method applies (losses or missing data)."
    elif price <= buy_below:
        verdict, tone = "BUY ZONE", "good"
        reason = f"Price is {(1 - price / fair) * 100:.0f}% below fair value, inside your {mos:.0f}% margin of safety."
    elif price <= fair:
        verdict, tone = "NEAR FAIR VALUE", "warn"
        reason = f"Below fair value but not by {mos:.0f}%. Wait for Rs{buy_below:,.0f} or lower."
    else:
        verdict, tone = "ABOVE FAIR VALUE - NO BUY", "bad"
        reason = f"Price is {(price / fair - 1) * 100:.0f}% above fair value. If you hold, consider booking profit."
    if missing >= 3 and quality is not None:
        reason += f" Note: {missing} checks had no data, so the quality score is less reliable."

    return dict(price=price, eps=eps, bvps=bvps, roe=roe, fcfps=fcfps, rev_c=rev_c, eps_c=eps_c, lender=lender,
                g_used=g_used, g_src=g_src, hist_pe=hist_pe, n_hist_pe=len(hist_pes),
                methods=methods, fair=fair, buy_below=buy_below, checks=rows, quality=quality,
                verdict=verdict, tone=tone, reason=reason)


def project(r: dict, years=(1, 3, 5)) -> list:
    """Future price scenarios from current growth. Returns rows of dicts."""
    eps, price, g = r.get("eps"), r.get("price"), r.get("g_used")
    if not eps or eps <= 0 or not price or g is None:
        return []
    now_pe = clip(price / eps, 6, 60)
    hist_pe = r.get("hist_pe")
    # Base keeps today's P/E (no re-rating). Bull moves halfway back to the usual P/E if that is higher.
    bull_pe = now_pe * 1.15
    if hist_pe and hist_pe > now_pe:
        bull_pe = max(bull_pe, now_pe + (clip(hist_pe, 6, 60) - now_pe) * 0.5)
    g = clip(g, -10, 30)
    scen = {
        "Bear": (g * 0.5, now_pe * 0.8),
        "Base": (g, now_pe),
        "Bull": (min(g * 1.5, 40), bull_pe),
    }
    out = []
    for n in years:
        row = {"years": n}
        for name, (gg, pe) in scen.items():
            p = eps * (1 + gg / 100) ** n * pe
            row[name] = p
            row[name + " CAGR"] = ((p / price) ** (1 / n) - 1) * 100 if p > 0 else None
        out.append(row)
    return out


def _scale(x, bad, good):
    """Map x linearly so that `bad` -> 0 and `good` -> 100 (works when good < bad too)."""
    if x is None:
        return None
    return clip((x - bad) / (good - bad) * 100, 0, 100)


def grade(score):
    if score is None:
        return "-"
    return "A" if score >= 80 else "B" if score >= 65 else "C" if score >= 50 else "D" if score >= 35 else "F"


def report_card(r: dict, d: dict) -> dict:
    """Five 0-100 category scores + overall, each with a letter grade.
    Categories with no data are left out of the overall (never counted as zero)."""
    def avg(*xs):
        xs = [x for x in xs if x is not None]
        return sum(xs) / len(xs) if xs else None

    price, fair = r.get("price"), r.get("fair")
    upside = (fair / price - 1) * 100 if (price and fair) else None
    lender = r.get("lender")
    checks = {c["check"]: c["value"] for c in r.get("checks", [])}
    profitable = checks.get("Profitable every year")

    valuation = _scale(upside, -40, 40)                         # 40% above fair -> 0, 40% below -> 100
    growth = avg(_scale(r.get("rev_c"), 0, 20), _scale(r.get("eps_c"), 0, 25))
    if lender:
        profit = avg(_scale(r.get("roe"), 5, 20), _scale(d.get("net_margin"), 5, 30))
        health = avg(_scale(d.get("roa"), 0.3, 2.0),
                     None if profitable is None else (100 if profitable else 0))
    else:
        profit = avg(_scale(r.get("roe"), 5, 25), _scale(d.get("net_margin"), 0, 20))
        health = avg(_scale(d.get("de"), 1.5, 0.0), _scale(d.get("current_ratio"), 0.8, 2.0))
    fcf_conv = checks.get("FCF / net profit")
    consistency = avg(None if profitable is None else (100 if profitable else 0),
                      _scale(fcf_conv, 30, 100) if not lender else None)

    cats = [("Valuation", valuation), ("Growth", growth), ("Profitability", profit),
            ("Financial health", health), ("Consistency", consistency)]
    overall = avg(*(s for _, s in cats))
    return {
        "categories": [{"name": n, "score": None if s is None else round(s), "grade": grade(s)} for n, s in cats],
        "overall": None if overall is None else round(overall),
        "overall_grade": grade(overall),
    }


# ----------------------------------------------------------------------------
# Data from Yahoo Finance
# ----------------------------------------------------------------------------

def to_yahoo(symbol: str) -> str:
    s = symbol.strip().upper().replace("NSE:", "").replace(" ", "")
    if s.startswith("BSE:"):
        return s[4:] + ".BO"
    return s if s.endswith((".NS", ".BO")) else s + ".NS"


def _row_series(df, *names):
    """Return a pandas Series (index = period end date, oldest->newest) or None."""
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            ser = df.loc[n]
            ser = ser[ser.notna()].sort_index()
            return ser if len(ser) else None
    return None


def _vals(ser):
    return [float(x) for x in ser.values] if ser is not None else []


def _hist_pe(eps_ser, price_hist):
    """P/E at each fiscal year end: close on/after that date divided by that year's EPS."""
    if eps_ser is None or price_hist is None or price_hist.empty:
        return []
    import pandas as pd
    closes = price_hist["Close"].dropna()
    if closes.empty:
        return []
    idx = closes.index
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    closes = pd.Series(closes.values, index=idx)
    out = []
    for dt, e in eps_ser.items():
        e = _num(e)
        if not e or e <= 0:
            continue
        ts = pd.Timestamp(dt)
        if getattr(ts, "tz", None) is not None:
            ts = ts.tz_localize(None)
        after = closes[closes.index >= ts]
        if after.empty:
            continue
        out.append(float(after.iloc[0]) / e)
    return out


def fetch(symbol: str) -> dict:
    import yfinance as yf

    ysym = to_yahoo(symbol)
    t = yf.Ticker(ysym)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    try:
        ph = t.history(period="5y", auto_adjust=False)
    except Exception:
        ph = None
    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    if price is None and ph is not None and not ph.empty:
        price = float(ph["Close"].dropna().iloc[-1])
    if price is None:
        raise ValueError(f"No data for {ysym}. Check the NSE symbol (e.g. SBIN, TCS, TATASTEEL).")

    try:
        inc = t.income_stmt
    except Exception:
        inc = None
    try:
        cfs = t.cashflow
    except Exception:
        cfs = None

    shares = _num(info.get("sharesOutstanding"))
    mcap = _num(info.get("marketCap"))
    if not shares and mcap:
        shares = mcap / price

    roe = _num(info.get("returnOnEquity"))
    roa = _num(info.get("returnOnAssets"))
    margin = _num(info.get("profitMargins"))
    de = _num(info.get("debtToEquity"))  # Yahoo reports this as a percent (e.g. 45 = 0.45x)

    rev_s = _row_series(inc, "Total Revenue", "Operating Revenue")
    ni_s = _row_series(inc, "Net Income", "Net Income Common Stockholders")
    eps_s = _row_series(inc, "Diluted EPS", "Basic EPS")
    fcf_s = _row_series(cfs, "Free Cash Flow")
    fcf_hist = _vals(fcf_s)
    fcf = _num(info.get("freeCashflow")) or (fcf_hist[-1] if fcf_hist else None)

    # 52-week range from the last year of prices (falls back to Yahoo's own fields)
    hi52 = lo52 = None
    if ph is not None and not ph.empty:
        last = ph.tail(252)
        hi52 = float(last["High"].max())
        lo52 = float(last["Low"].min())
    hi52 = hi52 or _num(info.get("fiftyTwoWeekHigh"))
    lo52 = lo52 or _num(info.get("fiftyTwoWeekLow"))

    price_series = None
    ohlc = []
    if ph is not None and not ph.empty:
        c = ph["Close"].dropna()
        idx = c.index.tz_localize(None) if getattr(c.index, "tz", None) is not None else c.index
        price_series = list(zip([str(x)[:10] for x in idx], [float(v) for v in c.values]))
        k = ph[["Open", "High", "Low", "Close"]].dropna()
        kidx = k.index.tz_localize(None) if getattr(k.index, "tz", None) is not None else k.index
        ohlc = [(str(dt)[:10], float(o), float(h), float(lo), float(cl))
                for dt, (o, h, lo, cl) in zip(kidx, k.values)]

    return dict(
        symbol=ysym,
        name=info.get("longName") or info.get("shortName") or ysym,
        sector=info.get("sector") or "", industry=info.get("industry") or "",
        price=price,
        eps=_num(info.get("trailingEps")),
        bvps=_num(info.get("bookValue")),
        shares=shares, mcap=mcap, fcf=fcf,
        roe=roe * 100 if roe is not None else None,
        roa=roa * 100 if roa is not None else None,
        net_margin=margin * 100 if margin is not None else None,
        de=de / 100 if de is not None else None,
        current_ratio=_num(info.get("currentRatio")),
        pe=_num(info.get("trailingPE")), pb=_num(info.get("priceToBook")),
        div_yield=_num(info.get("dividendYield")),
        hi52=hi52, lo52=lo52,
        target_mean=_num(info.get("targetMeanPrice")),
        target_high=_num(info.get("targetHighPrice")),
        target_low=_num(info.get("targetLowPrice")),
        n_analysts=_num(info.get("numberOfAnalystOpinions")),
        rec=info.get("recommendationKey") or "",
        hist_pe=_hist_pe(eps_s, ph),
        prices=price_series or [],
        ohlc=ohlc,
        hist=dict(
            years=[str(x)[:4] for x in rev_s.index] if rev_s is not None else [],
            revenue=_vals(rev_s),
            net_income=_vals(ni_s),
            eps=_vals(eps_s),
            fcf=fcf_hist,
        ),
    )


# ----------------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------------

def rs(v):
    return "-" if v is None else f"Rs{v:,.2f}" if abs(v) < 100 else f"Rs{v:,.0f}"


def crore(v):
    return "-" if v is None else f"Rs{v / 1e7:,.0f} Cr"


def pct(v, signed=False):
    if v is None:
        return "-"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def fmt_check(r):
    v = r["value"]
    if v is None:
        return "-"
    if r["fmt"] == "%":
        return f"{v:.1f}%"
    if r["fmt"] == "x":
        return f"{v:.2f}x"
    return "Yes" if v else "No"


# ----------------------------------------------------------------------------
# Terminal mode
# ----------------------------------------------------------------------------

def cli(argv):
    import argparse

    p = argparse.ArgumentParser(description="NSE fair value finder")
    p.add_argument("symbol", nargs="+", help="NSE symbols, e.g. TCS SBIN TATASTEEL")
    p.add_argument("--mos", type=float, default=15, help="margin of safety %% (default 15)")
    p.add_argument("--discount", type=float, default=12, help="discount rate %% (default 12)")
    p.add_argument("--terminal", type=float, default=5, help="terminal growth %% (default 5)")
    a = p.parse_args(argv)
    for sym in a.symbol:
        print("=" * 70)
        try:
            d = fetch(sym)
        except Exception as e:
            print(f"{sym}: {e}")
            continue
        r = analyse(d, a.discount, a.terminal, a.mos)
        print(f"{d['name']} ({d['symbol']})  {d['sector']} / {d['industry']}")
        print(f"VERDICT : {r['verdict']}   (quality {r['quality']}%)")
        print(f"Price {rs(r['price'])} | Fair value {rs(r['fair'])} | Buy below {rs(r['buy_below'])}")
        print(f"52-week range {rs(d['lo52'])} - {rs(d['hi52'])}")
        print(r["reason"])
        print("-- Fair value methods (fair = median)")
        for n, v, how in r["methods"]:
            print(f"  {n:24s} {rs(v) if v else 'n/a':>12s}   {how}")
        print("-- Quality checks")
        for c in r["checks"]:
            mark = "  -  " if c["ok"] is None else (" PASS" if c["ok"] else " FAIL")
            print(f"  {mark}  {c['check']:24s} {fmt_check(c):>10s}   good: {c['rule']}")
        rows = project(r)
        if rows:
            print(f"-- Future price (growth {r['g_used']:.1f}% from {r['g_src']})")
            for row in rows:
                print(f"  {row['years']} yr:  bear {rs(row['Bear'])}  base {rs(row['Base'])}  bull {rs(row['Bull'])}")
        if d.get("target_mean"):
            print(f"-- Analyst targets: low {rs(d['target_low'])} mean {rs(d['target_mean'])} high {rs(d['target_high'])}")
    print("=" * 70)
    print("Educational tool, not investment advice. Promoter holding/pledge not included - check NSE.")


# ----------------------------------------------------------------------------
# Look and feel: palette, CSS, charts
# ----------------------------------------------------------------------------

INK, PAPER, CARD, LINE, MUTED = "#1B2559", "#F1F3F6", "#FFFFFF", "#D5DAE3", "#5B6478"
TONE = {"good": "#1F7A4D", "warn": "#B26B00", "bad": "#B42318"}
GRADE_COLOR = {"A": "#1F7A4D", "B": "#3E8E5E", "C": "#B26B00", "D": "#C2410C", "F": "#B42318", "-": MUTED}
FONT = "Source Sans 3, Segoe UI, sans-serif"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=Source+Sans+3:wght@400;600&display=swap');
html, body, [class*="st-"], .stMarkdown, p, li, label {{ font-family: {FONT}; }}
h1, h2, h3, h4, .fvf-name, .fvf-brand {{ font-family: 'Bricolage Grotesque', {FONT}; color: {INK}; letter-spacing: -0.01em; }}
.block-container {{ padding-top: 2rem; max-width: 1180px; }}
.fvf-brand {{ font-size: 2.1rem; font-weight: 700; line-height: 1.1; margin: 0; }}
.fvf-tag {{ color: {MUTED}; margin: .25rem 0 1rem; font-size: 1rem; }}
.fvf-hero {{ display: flex; gap: 1.5rem; align-items: center; justify-content: space-between; flex-wrap: wrap;
            background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; padding: 1.4rem 1.6rem; margin: .5rem 0 1rem; }}
.fvf-hero-text {{ flex: 1 1 360px; min-width: 0; }}
.fvf-name {{ font-size: 1.9rem; font-weight: 700; line-height: 1.15; margin: 0; }}
.fvf-sub {{ color: {MUTED}; font-size: .95rem; margin: .3rem 0 .8rem; }}
.fvf-reason {{ font-size: 1.05rem; line-height: 1.5; max-width: 62ch; margin: 0; color: #1A1F36; }}
.fvf-stamp {{ flex: 0 0 auto; transform: rotate(-6deg); border: 4px double var(--c); color: var(--c);
             border-radius: 10px; padding: .55rem 1.1rem; text-align: center; font-family: 'Bricolage Grotesque', {FONT};
             font-weight: 700; font-size: 1.35rem; line-height: 1.15; max-width: 15rem; background: {CARD};
             animation: fvf-stamp .45s cubic-bezier(.2,1.6,.4,1) both; }}
.fvf-stamp small {{ display: block; font-family: {FONT}; font-weight: 600; font-size: .8rem; margin-top: .25rem; opacity: .85; }}
@keyframes fvf-stamp {{ from {{ transform: rotate(-6deg) scale(1.8); opacity: 0; }} to {{ transform: rotate(-6deg) scale(1); opacity: 1; }} }}
@media (prefers-reduced-motion: reduce) {{ .fvf-stamp {{ animation: none; }} }}
.fvf-panel {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; padding: 1rem 1.1rem .4rem; }}
.fvf-panel h4 {{ margin: 0 0 .2rem; font-size: 1.1rem; }}
.fvf-panel p {{ color: {MUTED}; margin: 0; font-size: .9rem; }}
.fvf-grades {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: .5rem; margin: .4rem 0 .6rem; }}
.fvf-grade {{ border: 1px solid {LINE}; border-radius: 10px; padding: .45rem .6rem; display: flex; align-items: center; gap: .55rem; background: {PAPER}; }}
.fvf-grade b {{ font-family: 'Bricolage Grotesque', {FONT}; font-size: 1.5rem; color: var(--c); min-width: 1.2ch; }}
.fvf-grade span {{ font-size: .85rem; color: #1A1F36; line-height: 1.2; }}
.fvf-grade em {{ display: block; font-style: normal; color: {MUTED}; font-size: .78rem; }}
.fvf-contact {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .6rem 1rem;
                background: {INK}; color: #fff; border-radius: 12px; padding: .75rem 1.1rem; margin: 0 0 1rem; }}
.fvf-contact p {{ margin: 0; color: #fff; font-size: 1.02rem; }}
.fvf-contact b {{ font-family: 'Bricolage Grotesque', {FONT}; }}
.fvf-contact .fvf-links {{ display: flex; gap: .5rem; flex-wrap: wrap; }}
.fvf-contact a {{ color: {INK} !important; background: #fff; border-radius: 8px; padding: .4rem .85rem; font-weight: 600;
                 text-decoration: none; white-space: nowrap; }}
.fvf-contact a:focus-visible {{ outline: 3px solid #9FD1B3; outline-offset: 2px; }}
[data-testid="stMetric"] {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; padding: .7rem .9rem; }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; }}
[data-testid="stMetricValue"] {{ font-family: 'Bricolage Grotesque', {FONT}; color: {INK}; }}
@media (max-width: 640px) {{
  .fvf-brand {{ font-size: 1.6rem; }} .fvf-name {{ font-size: 1.45rem; }}
  .fvf-hero {{ padding: 1rem; }} .fvf-stamp {{ font-size: 1.1rem; }}
}}
</style>
"""


def _esc(s):
    import html
    return html.escape(str(s or ""))


def hero_html(d, r):
    c = TONE[r["tone"]]
    sub = " | ".join(x for x in (d["symbol"], d.get("sector"), d.get("industry")) if x)
    if r["lender"]:
        sub += " | valued as a bank/NBFC"
    q = "" if r["quality"] is None else f"<small>Quality {r['quality']}%</small>"
    return (f'<div class="fvf-hero"><div class="fvf-hero-text"><p class="fvf-name">{_esc(d["name"])}</p>'
            f'<p class="fvf-sub">{_esc(sub)}</p><p class="fvf-reason">{_esc(r["reason"])}</p></div>'
            f'<div class="fvf-stamp" style="--c:{c}" role="img" aria-label="Verdict: {_esc(r["verdict"])}">'
            f'{_esc(r["verdict"])}{q}</div></div>')


def contact_html():
    wa = f"https://wa.me/91{CONTACT_PHONE}?text=" + "Hi%2C%20I%20want%20to%20learn%20trading%20and%20option%20buying"
    return (f'<div class="fvf-contact"><p><b>{CONTACT_LINE}.</b> Call or WhatsApp {CONTACT_DISPLAY}</p>'
            f'<div class="fvf-links"><a href="tel:+91{CONTACT_PHONE}">Call</a>'
            f'<a href="{wa}" target="_blank" rel="noopener">WhatsApp</a></div></div>')


def grades_html(card):
    cells = "".join(
        f'<div class="fvf-grade" style="--c:{GRADE_COLOR[g["grade"]]}"><b>{g["grade"]}</b>'
        f'<span>{g["name"]}<em>{"no data" if g["score"] is None else str(g["score"]) + " / 100"}</em></span></div>'
        for g in card["categories"])
    return f'<div class="fvf-grades">{cells}</div>'


def _base_layout(fig, height):
    fig.update_layout(height=height, margin=dict(l=20, r=20, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(family=FONT, color="#1A1F36", size=13))
    return fig


def gauge_fig(r):
    """Speedometer: where today's price sits against buy-below / fair value."""
    import plotly.graph_objects as go
    price, fair, bb = r["price"], r["fair"], r["buy_below"]
    lo = max(0.0, min(fair * 0.5, price * 0.9))
    hi = max(fair * 1.5, price * 1.1)
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta", value=price,
        number=dict(prefix="Rs", valueformat=",.0f", font=dict(size=34, family="Bricolage Grotesque, " + FONT, color=INK)),
        delta=dict(reference=fair, relative=True, valueformat="+.0%", suffix=" vs fair",
                   increasing=dict(color=TONE["bad"]), decreasing=dict(color=TONE["good"])),
        gauge=dict(
            axis=dict(range=[lo, hi], tickprefix="Rs", tickformat=",.0f", tickcolor=MUTED, nticks=6),
            bar=dict(color=INK, thickness=0.22),
            bgcolor=CARD, borderwidth=0,
            steps=[dict(range=[lo, bb], color="#D7EBDF"),
                   dict(range=[bb, fair], color="#F5E6C8"),
                   dict(range=[fair, hi], color="#F4D5D2")],
            threshold=dict(line=dict(color=INK, width=3), thickness=0.85, value=fair),
        ),
    ))
    return _base_layout(fig, 260)


def radar_fig(card):
    import plotly.graph_objects as go
    cats = [c for c in card["categories"] if c["score"] is not None]
    if len(cats) < 3:
        return None
    names = [c["name"] for c in cats] + [cats[0]["name"]]
    vals = [c["score"] for c in cats] + [cats[0]["score"]]
    fig = go.Figure(go.Scatterpolar(r=vals, theta=names, fill="toself", fillcolor="rgba(27,37,89,0.18)",
                                    line=dict(color=INK, width=2), hovertemplate="%{theta}: %{r}/100<extra></extra>"))
    fig.update_layout(polar=dict(bgcolor="rgba(0,0,0,0)",
                                 radialaxis=dict(range=[0, 100], tickvals=[25, 50, 75, 100], showticklabels=False,
                                                 gridcolor=LINE, linecolor=LINE),
                                 angularaxis=dict(gridcolor=LINE, linecolor=LINE)),
                      showlegend=False)
    return _base_layout(fig, 260)


def candle_fig(ohlc, fair=None, buy_below=None, months=12):
    """Candlestick with 200-day average, today's fair value line and shaded buy zone."""
    import pandas as pd
    import plotly.graph_objects as go
    df = pd.DataFrame(ohlc, columns=["Date", "Open", "High", "Low", "Close"])
    df["Date"] = pd.to_datetime(df["Date"])
    df["DMA200"] = df["Close"].rolling(200).mean()           # computed on full history, then sliced
    df = df[df["Date"] >= df["Date"].iloc[-1] - pd.DateOffset(months=months)]
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df["Date"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                 name="Price", increasing=dict(line=dict(color=TONE["good"]), fillcolor=TONE["good"]),
                                 decreasing=dict(line=dict(color=TONE["bad"]), fillcolor=TONE["bad"])))
    fig.add_trace(go.Scatter(x=df["Date"], y=df["DMA200"], name="200-day average", mode="lines",
                             line=dict(color=MUTED, width=1.5, dash="dot")))
    if fair and buy_below:
        floor = min(float(df["Low"].min()), buy_below) * 0.95
        fig.add_hrect(y0=floor, y1=buy_below, fillcolor=TONE["good"], opacity=0.08, line_width=0,
                      annotation_text="Buy zone", annotation_position="bottom left",
                      annotation_font=dict(color=TONE["good"], size=12))
        fig.add_hline(y=fair, line=dict(color=INK, width=2, dash="dash"),
                      annotation_text=f"Fair value Rs{fair:,.0f}", annotation_position="top left",
                      annotation_font=dict(color=INK, size=12))
        fig.add_hline(y=buy_below, line=dict(color=TONE["good"], width=1.5))
    ys = list(df["Low"]) + list(df["High"]) + ([fair, buy_below] if fair else [])
    pad = (max(ys) - min(ys)) * 0.08
    fig.update_layout(
        xaxis=dict(rangeslider=dict(visible=False), rangebreaks=[dict(bounds=["sat", "mon"])], gridcolor=LINE),
        yaxis=dict(range=[min(ys) - pad, max(ys) + pad], tickprefix="Rs", tickformat=",.0f", gridcolor=LINE),
        legend=dict(orientation="h", y=-0.12, x=0), hovermode="x unified",
    )
    return _base_layout(fig, 460)


PLOTLY_CFG = {"displayModeBar": False, "responsive": True}

SITE_URL = "fair-value-finder.streamlit.app"
CONTACT_PHONE = "8610025411"                       # shown on the site and on every share picture
CONTACT_DISPLAY = "86100 25411"
CONTACT_LINE = "Learn stock market trading and option buying"


# ----------------------------------------------------------------------------
# Share card: a 1080x1350 PNG for WhatsApp / Instagram (drawn with Pillow)
# ----------------------------------------------------------------------------

def _font(kind, size, weight=400):
    import os
    from PIL import ImageFont
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "fonts", "BricolageGrotesque.ttf" if kind == "display" else "SourceSans3.ttf")
    try:
        f = ImageFont.truetype(path, size)
        # axes: Bricolage = (opsz, wght, wdth); Source Sans 3 = (wght,)
        f.set_variation_by_axes([min(96, max(12, size)), weight, 100] if kind == "display" else [weight])
        return f
    except Exception:
        return ImageFont.load_default(size)


def _hex(c, a=255):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) + (a,)


def _fit(draw, text, kind, weight, max_w, start, minimum=24):
    size = start
    while size > minimum:
        f = _font(kind, size, weight)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(kind, minimum, weight)


def _wrap(draw, text, font, max_w, max_lines=2):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textlength(lines[-1] + "...", font=font) > max_w and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "..."
    return lines


def share_card_png(d: dict, r: dict, card: dict, today: str | None = None) -> bytes:
    import datetime
    import io
    import math as m
    from PIL import Image, ImageDraw

    W, H, PAD = 1080, 1350, 84
    img = Image.new("RGBA", (W, H), _hex(PAPER))
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle((44, 44, W - 44, H - 44), radius=36, fill=_hex(CARD), outline=_hex(LINE), width=3)
    ink, muted = _hex(INK), _hex(MUTED)

    # Header: brand + date
    if not today:
        try:
            from zoneinfo import ZoneInfo
            today = datetime.datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y")
        except Exception:
            today = datetime.date.today().strftime("%d %b %Y")
    dr.text((PAD, 86), "Fair Value Finder", font=_font("display", 36, 700), fill=ink)
    fd = _font("body", 30, 400)
    dr.text((W - PAD - dr.textlength(today, font=fd), 92), today, font=fd, fill=muted)
    dr.line((PAD, 152, W - PAD, 152), fill=_hex(LINE), width=2)

    # Company name (up to 2 lines) + symbol / sector
    y = 180
    fname = _font("display", 62, 700)
    for line in _wrap(dr, d["name"], fname, W - 2 * PAD):
        dr.text((PAD, y), line, font=fname, fill=ink)
        y += 70
    sub = " | ".join(x for x in (d["symbol"].replace(".NS", "").replace(".BO", ""), d.get("sector")) if x)
    dr.text((PAD, y + 4), sub, font=_font("body", 32, 600), fill=muted)
    top = y + 60                                       # first free pixel row below the header block

    price, fair, bb = r["price"], r["fair"], r["buy_below"]
    tone = _hex(TONE[r["tone"]])
    has_gauge = bool(price and fair)

    # Build the stamp first so its height is known before laying out the page
    verdict = r["verdict"].replace(" - ", "\n")
    fs = _font("display", 46, 800)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bbox = tmp.multiline_textbbox((0, 0), verdict, font=fs, align="center", spacing=6)
    sw, sh = int(bbox[2] - bbox[0]) + 76, int(bbox[3] - bbox[1]) + 52
    stamp = Image.new("RGBA", (sw + 20, sh + 20), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rounded_rectangle((10, 10, sw + 10, sh + 10), radius=18, outline=tone, width=7, fill=_hex(CARD))
    sd.rounded_rectangle((22, 22, sw - 2, sh - 2), radius=12, outline=tone, width=3)
    sd.multiline_text(((sw + 20) / 2, (sh + 20) / 2), verdict, font=fs, fill=tone, anchor="mm", align="center", spacing=6)
    stamp = stamp.rotate(6, resample=Image.BICUBIC, expand=True)

    # Vertical budget: label gap + gauge + price block + stamp + stats must fit above the footer
    fy = H - 44 - 178                                  # footer rule (contact band + site + disclaimer)
    R, thick = 250, 46
    label_gap, price_block, stats_h, gaps = 64, 150, 104, 3 * 22
    need = lambda R: (label_gap + R if has_gauge else 0) + price_block + stamp.height + stats_h + gaps
    while R > 120 and top + need(R) > fy - 16:
        R -= 10
    spare = max(0, (fy - 16) - (top + need(R)))
    y = top + spare / 2                                # centre the block in whatever room is left
    cx = W // 2

    if has_gauge:
        cy = y + label_gap + R
        lo = max(0.0, min(fair * 0.5, price * 0.9))
        hi = max(fair * 1.5, price * 1.1)
        frac = lambda v: clip((v - lo) / (hi - lo), 0, 1)
        ang = lambda v: 180 + frac(v) * 180          # PIL: 0 deg = 3 o'clock, clockwise; top half = 180..360
        box = (cx - R, cy - R, cx + R, cy + R)
        for a0, a1, col in ((lo, bb, "#9FD1B3"), (bb, fair, "#EBC77F"), (fair, hi, "#E8A49D")):
            if a1 > a0:
                dr.arc(box, ang(a0), ang(a1), fill=_hex(col), width=thick)
        # fair value tick + label just outside the arc
        t = m.radians(ang(fair))
        dr.line((cx + (R - thick - 12) * m.cos(t), cy + (R - thick - 12) * m.sin(t),
                 cx + (R + 12) * m.cos(t), cy + (R + 12) * m.sin(t)), fill=ink, width=6)
        lx, ly = cx + (R + 26) * m.cos(t), cy + (R + 26) * m.sin(t)
        dr.text((lx, ly), f"Fair Rs{fair:,.0f}", font=_font("body", 26, 600), fill=ink,
                anchor="md" if abs(m.cos(t)) < 0.35 else ("rd" if m.cos(t) < 0 else "ld"))
        # needle
        n = m.radians(ang(price))
        dr.line((cx, cy, cx + (R - thick - 26) * m.cos(n), cy + (R - thick - 26) * m.sin(n)), fill=ink, width=11)
        dr.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill=ink)
        fz = _font("body", 26, 600)
        dr.text((cx - R - 14, cy - 6), "Cheap", font=fz, fill=_hex(TONE["good"]), anchor="rd")
        dr.text((cx + R + 14, cy - 6), "Costly", font=fz, fill=_hex(TONE["bad"]), anchor="ld")
        y = cy + 22
    # price + % vs fair value
    dr.text((cx, y), f"Rs{price:,.0f}" if price else "-", font=_font("display", 76, 700), fill=ink, anchor="ma")
    if has_gauge:
        diff = (price / fair - 1) * 100
        dtxt = f"{abs(diff):.0f}% {'above' if diff > 0 else 'below'} fair value"
        dcol = _hex(TONE["bad"] if diff > 0 else TONE["good"])
    else:
        dtxt, dcol = "Fair value not available", muted
    dr.text((cx, y + 92), dtxt, font=_font("body", 34, 600), fill=dcol, anchor="ma")
    y += price_block + 22

    # Verdict stamp
    img.alpha_composite(stamp, (int(cx - stamp.width / 2), int(y)))
    y += stamp.height + 22

    # Stats row: fair value | buy below | report card
    cols = [("Fair value", "-" if not fair else f"Rs{fair:,.0f}", ink),
            ("Buy below", "-" if not bb else f"Rs{bb:,.0f}", _hex(TONE["good"])),
            ("Report card", card["overall_grade"] + ("" if card["overall"] is None else f"  {card['overall']}/100"),
             _hex(GRADE_COLOR[card["overall_grade"]]))]
    cw = (W - 2 * PAD) / 3
    for i, (lab, val, col) in enumerate(cols):
        x = PAD + cw * i + cw / 2
        dr.text((x, y), lab, font=_font("body", 28, 400), fill=muted, anchor="ma")
        dr.text((x, y + 40), val, font=_fit(dr, val, "display", 700, cw - 24, 48), fill=col, anchor="ma")
        if i:
            dr.line((PAD + cw * i, y, PAD + cw * i, y + 96), fill=_hex(LINE), width=2)

    # Footer
    dr.line((PAD, fy, W - PAD, fy), fill=_hex(LINE), width=2)
    band = (PAD, fy + 18, W - PAD, fy + 88)
    dr.rounded_rectangle(band, radius=16, fill=ink)
    dr.text((W / 2, fy + 53), f"{CONTACT_LINE}: call {CONTACT_DISPLAY}",
            font=_fit(dr, f"{CONTACT_LINE}: call {CONTACT_DISPLAY}", "body", 700, W - 2 * PAD - 40, 32),
            fill=_hex(CARD), anchor="mm")
    dr.text((W / 2, fy + 100), f"Check any NSE stock free at {SITE_URL}", font=_font("body", 30, 600), fill=ink, anchor="ma")
    dr.text((W / 2, fy + 140), "For learning only. Not investment advice.", font=_font("body", 24, 400), fill=muted, anchor="ma")

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


# ----------------------------------------------------------------------------
# Streamlit web app
# ----------------------------------------------------------------------------

# NIFTY 50 constituents from NSE's official list (nsearchives.nseindia.com ind_nifty50list.csv, Oct 2026)
NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BSE", "BAJAJ-AUTO", "BAJFINANCE",
    "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM",
    "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC", "INFY", "INDIGO",
    "JSWSTEEL", "JIOFIN", "KOTAKBANK", "LT", "M&M", "MARUTI", "MAXHEALTH", "NTPC", "NESTLEIND", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN", "SUNPHARMA", "TCS", "TATACONSUM", "TMPV",
    "TATASTEEL", "TECHM", "TITAN", "TRENT", "ULTRACEMCO",
]

VERDICT_ORDER = ["BUY ZONE", "NEAR FAIR VALUE", "ABOVE FAIR VALUE - NO BUY", "AVOID", "CAN'T VALUE", "No price"]


def app():
    import time
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="Fair Value Finder", page_icon="⚖️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<p class="fvf-brand">Fair Value Finder</p>'
                '<p class="fvf-tag">Type any NSE stock. See what it is really worth, how strong the business is, '
                'and whether today\'s price is a bargain.</p>', unsafe_allow_html=True)
    st.markdown(contact_html(), unsafe_allow_html=True)

    with st.sidebar:
        st.header("Settings")
        mos = st.slider("Margin of safety %", 0, 40, 15)
        discount = st.slider("Discount rate / cost of equity %", 8.0, 18.0, 12.0, 0.5)
        terminal = st.slider("Terminal growth %", 2.0, 7.0, 5.0, 0.5)
        st.caption("Fair value = median of historical P/E, growth P/E, Graham number, and DCF "
                   "(or justified P/B for banks).")
        with st.expander("Correct Yahoo's numbers (optional, single stock only)"):
            st.caption("Leave at 0 to use Yahoo's value. Copy the right figure from Screener.in if Yahoo is wrong or blank.")
            ov_eps = st.number_input("EPS (TTM) Rs", min_value=0.0, value=0.0, step=0.5)
            ov_bv = st.number_input("Book value / share Rs", min_value=0.0, value=0.0, step=1.0)
            ov_roe = st.number_input("ROE %", min_value=0.0, value=0.0, step=0.5)
            ov_g = st.number_input("Growth for valuation % (e.g. Screener 5-yr profit growth)", min_value=0.0, value=0.0, step=0.5)
    overrides = {"eps": ov_eps or None, "bvps": ov_bv or None, "roe": ov_roe or None, "growth": ov_g or None}

    @st.cache_data(ttl=3600, show_spinner=False)
    def cached_fetch(s):
        time.sleep(0.3)  # gentle on Yahoo; only runs when the result is not already cached
        return fetch(s)

    tab_single, tab_scan = st.tabs(["Single stock", "NIFTY 50 scanner"])
    with tab_single:
        single_view(st, pd, cached_fetch, discount, terminal, mos, overrides)
    with tab_scan:
        scanner_view(st, pd, cached_fetch, discount, terminal, mos)


def scanner_view(st, pd, cached_fetch, discount, terminal, mos):
    st.markdown("#### Which NIFTY 50 stocks are in the buy zone right now?")
    st.caption("Runs every NIFTY 50 stock through the same checks as the single-stock page, using your sidebar "
               "settings. The first scan takes 1-3 minutes; results are kept for an hour, so it is quick after that.")
    if st.button("Run NIFTY 50 scan", type="primary"):
        st.session_state["scan_on"] = True
    if not st.session_state.get("scan_on"):
        st.info("Press 'Run NIFTY 50 scan' to check all 50 stocks.")
        return

    rows, failed = [], []
    bar = st.progress(0.0, text="Starting scan...")
    for i, s in enumerate(NIFTY50):
        bar.progress(i / len(NIFTY50), text=f"Checking {s} ({i + 1}/{len(NIFTY50)})")
        try:
            d = cached_fetch(s)
        except Exception:
            failed.append(s)
            continue
        r = analyse(d, discount, terminal, mos)
        up = (r["fair"] / r["price"] - 1) * 100 if r["fair"] and r["price"] else None
        rows.append({
            "Symbol": s,
            "Company": d["name"],
            "Verdict": r["verdict"],
            "Price": r["price"],
            "Fair value": r["fair"],
            "Buy below": r["buy_below"],
            "Upside %": up,
            "Quality %": r["quality"],
            "From 52w high %": ((r["price"] / d["hi52"] - 1) * 100) if (d.get("hi52") and r["price"]) else None,
            "Sector": d["sector"],
        })
    bar.empty()

    if not rows:
        st.error("Yahoo didn't return data for any stock. It may be limiting requests; wait a few minutes and press the button again.")
        return

    df = pd.DataFrame(rows)
    counts = df["Verdict"].value_counts()
    c = st.columns(4)
    c[0].metric("Buy zone", int(counts.get("BUY ZONE", 0)))
    c[1].metric("Near fair value", int(counts.get("NEAR FAIR VALUE", 0)))
    c[2].metric("Above fair value", int(counts.get("ABOVE FAIR VALUE - NO BUY", 0)))
    c[3].metric("Avoid (weak fundamentals)", int(counts.get("AVOID", 0)))

    present = [v for v in VERDICT_ORDER if v in set(df["Verdict"])]
    show = st.multiselect("Show", present, default=present)
    view = df[df["Verdict"].isin(show)].copy()
    view["_o"] = view["Verdict"].map({v: i for i, v in enumerate(VERDICT_ORDER)})
    view = view.sort_values(["_o", "Upside %"], ascending=[True, False]).drop(columns="_o")
    st.dataframe(
        view, hide_index=True, width="stretch",
        column_config={
            "Price": st.column_config.NumberColumn(format="Rs %.0f"),
            "Fair value": st.column_config.NumberColumn(format="Rs %.0f"),
            "Buy below": st.column_config.NumberColumn(format="Rs %.0f"),
            "Upside %": st.column_config.NumberColumn(format="%+.1f%%"),
            "Quality %": st.column_config.NumberColumn(format="%d%%"),
            "From 52w high %": st.column_config.NumberColumn(format="%+.1f%%"),
        },
    )
    st.caption("Sorted: buy zone first, then by upside to fair value. For full details of any stock, "
               "type its symbol in the 'Single stock' tab.")
    if failed:
        st.warning(f"Yahoo didn't return data for {len(failed)} stock(s): {', '.join(failed)}. "
                   "Press 'Run NIFTY 50 scan' again in a minute to retry them.")
    st.caption("A buy-zone verdict is a starting point for your own research, not a recommendation.")


def single_view(st, pd, cached_fetch, discount, terminal, mos, overrides):
    c1, c2 = st.columns([4, 1])
    sym = c1.text_input("NSE symbol", value="", placeholder="e.g. TCS, SBIN, TATASTEEL, HDFCBANK")
    c2.write("")
    c2.button("Analyse", width="stretch", type="primary")
    if not sym:
        st.info("Type an NSE symbol and press Analyse.")
        return

    with st.spinner(f"Fetching {to_yahoo(sym)} from Yahoo Finance..."):
        try:
            d = cached_fetch(sym)
        except Exception as e:
            st.error(f"Couldn't load {sym}: {e}. If Yahoo is busy, wait a minute and try again.")
            return
    r = analyse(d, discount, terminal, mos, overrides)
    if any(overrides.values()):
        st.info("Using your corrected numbers from the sidebar.")

    st.markdown(hero_html(d, r), unsafe_allow_html=True)

    card = report_card(r, d)
    g_col, rc_col = st.columns([1, 1.25], gap="medium")
    with g_col:
        with st.container(border=True):
            st.markdown("#### Price vs fair value")
            if r["fair"] and r["price"]:
                st.plotly_chart(gauge_fig(r), config=PLOTLY_CFG, width="stretch")
                st.caption("Green: buy zone (below your margin of safety). Amber: under fair value. "
                           "Red: above fair value. The dark tick is fair value.")
            else:
                st.info("No fair value for this stock, so the meter is hidden.")
    with rc_col:
        with st.container(border=True):
            st.markdown(f"#### Report card: **{card['overall_grade']}**"
                        + ("" if card["overall"] is None else f"  ({card['overall']}/100)"))
            st.markdown(grades_html(card), unsafe_allow_html=True)
            rf = radar_fig(card)
            if rf is not None:
                st.plotly_chart(rf, config=PLOTLY_CFG, width="stretch")
            st.caption("Scores compare this company with simple benchmarks, not with other companies. "
                       "Categories without data are left out of the overall grade.")

    with st.container(border=True):
        s_text, s_btn = st.columns([3, 1.3], vertical_alignment="center")
        s_text.markdown("#### Share this result\nDownload a ready-made picture for WhatsApp, Instagram or "
                        "your status. It shows the verdict, the meter and the report card.")
        try:
            png = share_card_png(d, r, card)
            fname = d["symbol"].split(".")[0].replace("&", "and") + "-fair-value.png"
            s_btn.download_button("Download share picture", png, file_name=fname, mime="image/png",
                                  type="primary", width="stretch")
            with st.expander("Preview the picture"):
                st.image(png, width=420)
        except Exception as e:
            s_btn.caption(f"Share picture unavailable: {e}")

    m = st.columns(5)
    m[0].metric("Price", rs(r["price"]))
    m[1].metric("Fair value", rs(r["fair"]))
    m[2].metric("Buy below", rs(r["buy_below"]))
    up = (r["fair"] / r["price"] - 1) * 100 if r["fair"] and r["price"] else None
    m[3].metric("Upside to fair", pct(up, True))
    if d.get("hi52") and d.get("lo52") and r["price"]:
        m[4].metric("52-week low / high", f"{d['lo52']:,.0f} / {d['hi52']:,.0f}",
                    f"{(r['price'] / d['hi52'] - 1) * 100:.1f}% from high", delta_color="off")

    tab1, tab2, tab3, tab4 = st.tabs(["Verdict details", "Price chart", "Future price", "Financials"])

    with tab1:
        left, right = st.columns(2)
        with left:
            st.markdown("#### Quality checks" + (" (bank set)" if r["lender"] else ""))
            st.dataframe(pd.DataFrame([{
                "Check": c["check"], "Value": fmt_check(c), "Good if": c["rule"],
                "Result": "no data" if c["ok"] is None else ("PASS" if c["ok"] else "FAIL")} for c in r["checks"]]),
                hide_index=True, width="stretch")
        with right:
            st.markdown("#### Fair value methods")
            for n, v, how in r["methods"]:
                st.markdown(f"**{n}: {rs(v) if v else 'n/a'}**  \n<small>{how}</small>", unsafe_allow_html=True)
            st.caption("Fair value is the middle value of the methods that apply.")

    with tab2:
        prices = d.get("prices") or []
        ohlc = d.get("ohlc") or []
        spans = {"6 months": 6, "1 year": 12, "3 years": 36, "5 years": 60}
        if ohlc:
            span = st.radio("Period", list(spans), horizontal=True, index=1)
            st.plotly_chart(candle_fig(ohlc, r["fair"], r["buy_below"], spans[span]),
                            config=PLOTLY_CFG, width="stretch")
            st.caption("Dashed line: today's fair value. Shaded green band: the buy zone. Dotted line: "
                       "200-day average price. Candles inside the green band were bargains by today's estimate.")
        elif prices:
            span = st.radio("Period", ["1 year", "5 years"], horizontal=True, index=0)
            pts = prices[-252:] if span == "1 year" else prices
            df = pd.DataFrame(pts, columns=["Date", "Price"]).set_index("Date")
            if r["fair"]:
                df["Fair value"] = r["fair"]
                df["Buy below"] = r["buy_below"]
            st.line_chart(df)
        else:
            st.warning("Price history not available for this stock.")

    with tab3:
        rows = project(r)
        if rows:
            st.markdown(f"#### If the company keeps growing at about **{r['g_used']:.1f}%** a year")
            st.caption(f"Growth source: {r['g_src']}. Base keeps today's P/E. "
                       "Bear = half the growth and a 20% lower P/E. "
                       "Bull = 1.5x growth and a higher P/E (15% more, or halfway back to its usual P/E if that is higher).")
            st.dataframe(pd.DataFrame([{
                "In": f"{row['years']} year" + ("s" if row["years"] > 1 else ""),
                "Bear": rs(row["Bear"]), "Base": rs(row["Base"]), "Bull": rs(row["Bull"]),
                "Base return / yr": pct(row["Base CAGR"], True)} for row in rows]),
                hide_index=True, width="stretch")
        else:
            st.warning("Can't project: needs positive earnings.")
        st.markdown("#### What analysts expect (from reports Yahoo collects)")
        if d.get("target_mean"):
            a = st.columns(4)
            a[0].metric("Low target", rs(d.get("target_low")))
            a[1].metric("Average target", rs(d.get("target_mean")),
                        pct((d["target_mean"] / r["price"] - 1) * 100, True) if r["price"] else None)
            a[2].metric("High target", rs(d.get("target_high")))
            a[3].metric("Analysts", "-" if not d.get("n_analysts") else f"{int(d['n_analysts'])}",
                        (d.get("rec") or "").replace("_", " ").title() or None, delta_color="off")
            st.caption("Analyst targets are usually 12-month targets. They are not used in the fair value.")
        else:
            st.caption("No analyst targets available for this stock.")
        st.caption("Projections assume past growth continues. Real results can be very different.")

    with tab4:
        H = d["hist"]
        n = min(len(H["years"]), len(H["revenue"]), len(H["net_income"]))
        if n:
            st.markdown("#### Revenue and net profit (Rs crore)")
            chart = pd.DataFrame({"Revenue": [v / 1e7 for v in H["revenue"][-n:]],
                                  "Net profit": [v / 1e7 for v in H["net_income"][-n:]]},
                                 index=[f"FY{y[-2:]}" for y in H["years"][-n:]])
            st.bar_chart(chart, stack=False)
            st.caption(f"Yahoo provides {n} years of annual data, so growth rates use {n - 1} years.")
        k = st.columns(4)
        k[0].metric("Market cap", crore(d["mcap"]))
        k[1].metric("P/E (now / usual)", ("-" if d["pe"] is None else f"{d['pe']:.1f}")
                    + (f" / {r['hist_pe']:.1f}" if r.get("hist_pe") else ""))
        k[2].metric("P/B", "-" if d["pb"] is None else f"{d['pb']:.2f}")
        k[3].metric("ROE", pct(r["roe"]))
        k2 = st.columns(4)
        k2[0].metric("Dividend yield", pct(d.get("div_yield")))
        k2[1].metric("Net margin", pct(d.get("net_margin")))
        k2[2].metric("Debt / Equity", "-" if d.get("de") is None else f"{d['de']:.2f}")
        k2[3].metric("ROA", pct(d.get("roa")))

    if r["lender"]:
        st.warning("Bank/NBFC: also check Gross/Net NPA, NIM, CASA and capital adequacy on the bank's investor page.")
    st.caption("Educational tool, not investment advice. Promoter holding, pledges and governance are not in "
               "this data - check NSE before buying. Yahoo data can lag or have gaps for smaller companies.")


def _running_in_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


if __name__ == "__main__":
    if _running_in_streamlit():
        app()
    elif len(sys.argv) > 1:
        cli(sys.argv[1:])
    else:
        print(__doc__)
