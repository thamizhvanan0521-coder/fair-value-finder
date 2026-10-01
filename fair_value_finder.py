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
    if ph is not None and not ph.empty:
        c = ph["Close"].dropna()
        idx = c.index.tz_localize(None) if getattr(c.index, "tz", None) is not None else c.index
        price_series = list(zip([str(x)[:10] for x in idx], [float(v) for v in c.values]))

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
# Streamlit web app
# ----------------------------------------------------------------------------

def app():
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="Fair Value Finder", layout="wide")
    st.title("Fair Value Finder")
    st.caption("NSE fundamentals from Yahoo Finance | fair value four ways | buy / near fair / no-buy verdict | future price scenarios")

    with st.sidebar:
        st.header("Settings")
        mos = st.slider("Margin of safety %", 0, 40, 15)
        discount = st.slider("Discount rate / cost of equity %", 8.0, 18.0, 12.0, 0.5)
        terminal = st.slider("Terminal growth %", 2.0, 7.0, 5.0, 0.5)
        st.caption("Fair value = median of historical P/E, growth P/E, Graham number, and DCF "
                   "(or justified P/B for banks).")
        with st.expander("Correct Yahoo's numbers (optional)"):
            st.caption("Leave at 0 to use Yahoo's value. Copy the right figure from Screener.in if Yahoo is wrong or blank.")
            ov_eps = st.number_input("EPS (TTM) Rs", min_value=0.0, value=0.0, step=0.5)
            ov_bv = st.number_input("Book value / share Rs", min_value=0.0, value=0.0, step=1.0)
            ov_roe = st.number_input("ROE %", min_value=0.0, value=0.0, step=0.5)
            ov_g = st.number_input("Growth for valuation % (e.g. Screener 5-yr profit growth)", min_value=0.0, value=0.0, step=0.5)
    overrides = {"eps": ov_eps or None, "bvps": ov_bv or None, "roe": ov_roe or None, "growth": ov_g or None}

    c1, c2 = st.columns([4, 1])
    sym = c1.text_input("NSE symbol", value="", placeholder="e.g. TCS, SBIN, TATASTEEL, HDFCBANK")
    c2.write("")
    c2.button("Analyse", width="stretch", type="primary")
    if not sym:
        st.info("Type an NSE symbol and press Analyse.")
        return

    @st.cache_data(ttl=900, show_spinner=False)
    def cached_fetch(s):
        return fetch(s)

    with st.spinner(f"Fetching {to_yahoo(sym)} from Yahoo Finance..."):
        try:
            d = cached_fetch(sym)
        except Exception as e:
            st.error(f"Couldn't load {sym}: {e}. If Yahoo is busy, wait a minute and try again.")
            return
    r = analyse(d, discount, terminal, mos, overrides)
    if any(overrides.values()):
        st.info("Using your corrected numbers from the sidebar.")

    st.subheader(f"{d['name']}  |  {d['symbol']}")
    st.caption(f"{d['sector']} | {d['industry']}" + (" | valued as a bank/NBFC" if r["lender"] else ""))
    color = {"good": "green", "warn": "orange", "bad": "red"}[r["tone"]]
    st.markdown(f"### :{color}[{r['verdict']}]  \nQuality score **{r['quality']}%** | {r['reason']}")

    m = st.columns(5)
    m[0].metric("Price", rs(r["price"]))
    m[1].metric("Fair value", rs(r["fair"]))
    m[2].metric("Buy below", rs(r["buy_below"]))
    up = (r["fair"] / r["price"] - 1) * 100 if r["fair"] and r["price"] else None
    m[3].metric("Upside to fair", pct(up, True))
    if d.get("hi52") and d.get("lo52") and r["price"]:
        m[4].metric("52-week range", f"{rs(d['lo52'])} - {rs(d['hi52'])}",
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
        if prices:
            span = st.radio("Period", ["1 year", "5 years"], horizontal=True, index=0)
            pts = prices[-252:] if span == "1 year" else prices
            df = pd.DataFrame(pts, columns=["Date", "Price"]).set_index("Date")
            if r["fair"]:
                df["Fair value"] = r["fair"]
                df["Buy below"] = r["buy_below"]
            st.line_chart(df)
            st.caption("Flat lines show today's fair value and buy-below price. When the price line is under "
                       "'Buy below', the stock was in the buy zone by today's estimate.")
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
