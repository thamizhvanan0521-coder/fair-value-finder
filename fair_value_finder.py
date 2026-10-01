"""
Fair Value Finder (Python) - NSE stock fundamentals, fair value and buy/sell verdict.
Data: Yahoo Finance via yfinance (runs from your own internet, no TradingView limit).

Run as a web app (recommended):   streamlit run fair_value_finder.py
Run in the terminal:              python fair_value_finder.py TCS
                                  python fair_value_finder.py TATASTEEL --mos 20

Install once:  pip install yfinance streamlit pandas
Educational tool, not investment advice.
"""
from __future__ import annotations

import math
import statistics
import sys

# ----------------------------------------------------------------------------
# Valuation + quality engine (same logic as the web Fair Value Finder)
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


def analyse(d: dict, discount=12.0, terminal=5.0, mos=15.0) -> dict:
    """d keys: price, eps, bvps, shares, fcf, roe, net_margin, de, current_ratio,
    sector, industry, hist{revenue, eps, net_income, fcf} (lists oldest->newest)."""
    price, eps, bvps = _num(d.get("price")), _num(d.get("eps")), _num(d.get("bvps"))
    shares, fcf = _num(d.get("shares")), _num(d.get("fcf"))
    fcfps = fcf / shares if (fcf is not None and shares) else None
    H = d.get("hist") or {}
    rev_c = cagr(H.get("revenue"))
    eps_c = cagr(H.get("eps"))
    ni_c = cagr(H.get("net_income"))
    lender = d.get("lender")
    if lender is None:
        lender = is_lender(d.get("sector"), d.get("industry"))

    methods = []
    # 1. Growth-adjusted P/E (fair P/E ~ EPS growth, kept between 8 and 30)
    if eps and eps > 0:
        g = eps_c if eps_c is not None else ni_c
        fair_pe = clip(12 if g is None else g, 8, 30)
        gtxt = "unknown, default 12" if g is None else f"{g:.1f}%"
        methods.append(("Growth-adjusted P/E", eps * fair_pe,
                        f"EPS Rs{eps:.2f} x fair P/E {fair_pe:.1f} (EPS growth {gtxt}, capped 8-30)"))
    else:
        methods.append(("Growth-adjusted P/E", None, "Skipped: EPS is zero or negative"))

    # 2. Graham number
    if eps and eps > 0 and bvps and bvps > 0:
        methods.append(("Graham number", math.sqrt(22.5 * eps * bvps),
                        f"sqrt(22.5 x EPS Rs{eps:.2f} x book value/share Rs{bvps:.2f})"))
    else:
        methods.append(("Graham number", None, "Skipped: needs positive EPS and book value"))

    # 3. Two-stage DCF on free cash flow (not for banks/NBFCs)
    if lender:
        methods.append(("Cash-flow DCF", None, "Skipped: free cash flow is not meaningful for banks/NBFCs"))
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

    # Quality checks
    ni = [x for x in (_num(v) for v in (H.get("net_income") or [])) if x is not None][-5:]
    fc = [x for x in (_num(v) for v in (H.get("fcf") or [])) if x is not None][-5:]
    fcf_conv = (sum(fc) / sum(ni) * 100) if (not lender and fc and ni and sum(ni) > 0) else None
    ni_all = all(x > 0 for x in ni) if ni else None
    de, cr = _num(d.get("de")), _num(d.get("current_ratio"))
    checks = [
        ("Return on equity", _num(d.get("roe")), "%", lambda x: x >= 15, ">= 15%"),
        ("Net profit margin", _num(d.get("net_margin")), "%", lambda x: x >= 10, ">= 10%"),
        ("Revenue growth (CAGR)", rev_c, "%", lambda x: x >= 10, ">= 10% a year"),
        ("EPS growth (CAGR)", eps_c, "%", lambda x: x >= 10, ">= 10% a year"),
        ("Profitable every year", ni_all, "bool", lambda x: x is True, "No loss years"),
        ("Debt / Equity", None if lender else de, "x", lambda x: x <= 0.5, "<= 0.5"),
        ("Current ratio", None if lender else cr, "x", lambda x: x >= 1.2, ">= 1.2"),
        ("FCF / net profit", fcf_conv, "%", lambda x: x >= 80, ">= 80%"),
    ]
    rows = []
    for name, v, fmt, test, rule in checks:
        ok = None if v is None else bool(test(v))
        rows.append({"check": name, "value": v, "fmt": fmt, "rule": rule, "ok": ok})
    scored = [r for r in rows if r["ok"] is not None]
    quality = round(sum(r["ok"] for r in scored) / len(scored) * 100) if scored else None

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

    return dict(price=price, eps=eps, bvps=bvps, fcfps=fcfps, rev_c=rev_c, eps_c=eps_c, lender=lender,
                methods=methods, fair=fair, buy_below=buy_below, checks=rows, quality=quality,
                verdict=verdict, tone=tone, reason=reason)


# ----------------------------------------------------------------------------
# Data from Yahoo Finance
# ----------------------------------------------------------------------------

def to_yahoo(symbol: str) -> str:
    s = symbol.strip().upper().replace("NSE:", "").replace(" ", "")
    if s.startswith("BSE:"):
        return s[4:] + ".BO"
    return s if s.endswith((".NS", ".BO")) else s + ".NS"


def _row(df, *names):
    """Return an annual row oldest->newest from a yfinance statement DataFrame."""
    if df is None or getattr(df, "empty", True):
        return []
    for n in names:
        if n in df.index:
            ser = df.loc[n]
            ser = ser[ser.notna()].sort_index()  # columns are dates
            return [float(x) for x in ser.values]
    return []


def fetch(symbol: str) -> dict:
    import yfinance as yf

    ysym = to_yahoo(symbol)
    t = yf.Ticker(ysym)
    info = t.info or {}
    price = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice"))
    if price is None:
        try:
            h = t.history(period="5d")
            price = float(h["Close"].dropna().iloc[-1]) if not h.empty else None
        except Exception:
            price = None
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
    margin = _num(info.get("profitMargins"))
    de = _num(info.get("debtToEquity"))  # Yahoo reports this as a percent (e.g. 45 = 0.45x)

    fcf_hist = _row(cfs, "Free Cash Flow")
    fcf = _num(info.get("freeCashflow")) or (fcf_hist[-1] if fcf_hist else None)

    return dict(
        symbol=ysym,
        name=info.get("longName") or info.get("shortName") or ysym,
        sector=info.get("sector") or "", industry=info.get("industry") or "",
        price=price,
        eps=_num(info.get("trailingEps")),
        bvps=_num(info.get("bookValue")),
        shares=shares, mcap=mcap, fcf=fcf,
        roe=roe * 100 if roe is not None else None,
        net_margin=margin * 100 if margin is not None else None,
        de=de / 100 if de is not None else None,
        current_ratio=_num(info.get("currentRatio")),
        pe=_num(info.get("trailingPE")), pb=_num(info.get("priceToBook")),
        div_yield=_num(info.get("dividendYield")),
        target=_num(info.get("targetMeanPrice")),
        hist=dict(
            years=[str(c)[:4] for c in sorted(inc.columns)] if inc is not None and not inc.empty else [],
            revenue=_row(inc, "Total Revenue", "Operating Revenue"),
            net_income=_row(inc, "Net Income", "Net Income Common Stockholders"),
            eps=_row(inc, "Diluted EPS", "Basic EPS"),
            fcf=fcf_hist,
        ),
    )


# ----------------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------------

def rs(v):
    return "-" if v is None else f"Rs{v:,.2f}" if v < 100 else f"Rs{v:,.0f}"


def crore(v):
    return "-" if v is None else f"Rs{v / 1e7:,.0f} Cr"


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
        print("=" * 64)
        try:
            d = fetch(sym)
        except Exception as e:
            print(f"{sym}: {e}")
            continue
        r = analyse(d, a.discount, a.terminal, a.mos)
        print(f"{d['name']} ({d['symbol']})  {d['sector']} / {d['industry']}")
        print(f"VERDICT : {r['verdict']}   (quality {r['quality']}%)")
        print(f"Price {rs(r['price'])} | Fair value {rs(r['fair'])} | Buy below {rs(r['buy_below'])}")
        print(r["reason"])
        print("-- Fair value methods (fair = median)")
        for n, v, how in r["methods"]:
            print(f"  {n:22s} {rs(v) if v else 'n/a':>12s}   {how}")
        print("-- Quality checks")
        for c in r["checks"]:
            mark = "  -  " if c["ok"] is None else (" PASS" if c["ok"] else " FAIL")
            print(f"  {mark}  {c['check']:24s} {fmt_check(c):>10s}   good: {c['rule']}")
        if r["lender"]:
            print("  Note: bank/NBFC - check NPA, NIM, CASA and capital adequacy separately.")
    print("=" * 64)
    print("Educational tool, not investment advice. Promoter holding/pledge not included - check NSE.")


# ----------------------------------------------------------------------------
# Streamlit web app
# ----------------------------------------------------------------------------

def app():
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="Fair Value Finder", layout="wide")
    st.title("Fair Value Finder")
    st.caption("NSE fundamentals from Yahoo Finance | fair value three ways | buy / near fair / no-buy verdict")

    with st.sidebar:
        st.header("Settings")
        mos = st.slider("Margin of safety %", 0, 40, 15)
        discount = st.slider("Discount rate %", 8.0, 18.0, 12.0, 0.5)
        terminal = st.slider("Terminal growth %", 2.0, 7.0, 5.0, 0.5)
        st.caption("Fair value = median of growth P/E, Graham number and cash-flow DCF.")

    c1, c2 = st.columns([4, 1])
    sym = c1.text_input("NSE symbol", value="", placeholder="e.g. TCS, SBIN, TATASTEEL, HDFCBANK")
    go = c2.button("Analyse", use_container_width=True, type="primary")
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
            st.error(f"Couldn't load {sym}: {e}")
            return
    r = analyse(d, discount, terminal, mos)

    st.subheader(f"{d['name']}  |  {d['symbol']}")
    st.caption(f"{d['sector']} | {d['industry']}" + (" | valued as a lender" if r["lender"] else ""))
    color = {"good": "green", "warn": "orange", "bad": "red"}[r["tone"]]
    st.markdown(f"### :{color}[{r['verdict']}]  \nQuality score **{r['quality']}%** | {r['reason']}")

    m = st.columns(4)
    m[0].metric("Price", rs(r["price"]))
    m[1].metric("Fair value", rs(r["fair"]))
    m[2].metric("Buy below", rs(r["buy_below"]))
    up = (r["fair"] / r["price"] - 1) * 100 if r["fair"] and r["price"] else None
    m[3].metric("Upside to fair", "-" if up is None else f"{up:+.1f}%")

    left, right = st.columns(2)
    with left:
        st.markdown("#### Quality checks")
        st.dataframe(pd.DataFrame([{
            "Check": c["check"], "Value": fmt_check(c), "Good if": c["rule"],
            "Result": "-" if c["ok"] is None else ("PASS" if c["ok"] else "FAIL")} for c in r["checks"]]),
            hide_index=True, use_container_width=True)
    with right:
        st.markdown("#### Fair value methods")
        for n, v, how in r["methods"]:
            st.markdown(f"**{n}: {rs(v) if v else 'n/a'}**  \n<small>{how}</small>", unsafe_allow_html=True)
        if d.get("target"):
            st.caption(f"Analyst mean target (reference only, not used): {rs(d['target'])}")

    H = d["hist"]
    n = min(len(H["years"]), len(H["revenue"]), len(H["net_income"]))
    if n:
        st.markdown("#### Revenue and net profit (Rs crore)")
        chart = pd.DataFrame({"Revenue": [v / 1e7 for v in H["revenue"][-n:]],
                              "Net profit": [v / 1e7 for v in H["net_income"][-n:]]},
                             index=[f"FY{y[-2:]}" for y in H["years"][-n:]])
        st.bar_chart(chart, stack=False)
        st.caption(f"Yahoo provides about {n} years of annual data, so growth rates use {n - 1} years.")

    st.markdown("#### Key numbers")
    k = st.columns(4)
    k[0].metric("Market cap", crore(d["mcap"]))
    k[1].metric("P/E", "-" if d["pe"] is None else f"{d['pe']:.1f}")
    k[2].metric("P/B", "-" if d["pb"] is None else f"{d['pb']:.2f}")
    k[3].metric("ROE", "-" if d["roe"] is None else f"{d['roe']:.1f}%")
    if r["lender"]:
        st.warning("Bank/NBFC: check Gross/Net NPA, NIM, CASA and capital adequacy on the bank's investor page.")
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
