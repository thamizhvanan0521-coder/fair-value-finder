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
# Words on screen, in English and Tamil. tr(key) picks the visitor's language.
# ----------------------------------------------------------------------------

TEXT = {
    # verdicts (stamp) and their tone
    "v_deep": ("DEEP VALUE", "மலிவு விலை"),
    "v_near": ("NEAR FAIR VALUE", "நியாய மதிப்புக்கு அருகில்"),
    "v_above": ("ABOVE FAIR VALUE", "நியாய மதிப்புக்கு மேல்"),
    "v_weak": ("WEAK BUSINESS", "பலவீனமான நிறுவனம்"),
    "v_cant": ("CAN'T VALUE", "மதிப்பிட முடியவில்லை"),
    "v_noprice": ("NO PRICE", "விலை இல்லை"),
    # verdict explanations
    "r_noprice": ("Price data is missing for this stock.", "இந்தப் பங்கின் விலைத் தரவு கிடைக்கவில்லை."),
    "r_weak": ("The fundamentals are weak: only {q}% of the quality checks pass. A low price alone does not make a stock good value.",
               "நிறுவனத்தின் அடிப்படைகள் பலவீனமாக உள்ளன: தரச் சோதனைகளில் {q}% மட்டுமே தேறுகின்றன. விலை குறைவாக இருப்பது மட்டுமே நல்ல மதிப்பு ஆகாது."),
    "r_cant": ("None of the valuation methods can be used, because of losses or missing data.",
               "நஷ்டம் அல்லது தரவு இல்லாததால், எந்த மதிப்பீட்டு முறையையும் பயன்படுத்த முடியவில்லை."),
    "r_deep": ("The price is {d}% below fair value, inside your {m}% margin of safety.",
               "விலை நியாய மதிப்பை விட {d}% குறைவாக உள்ளது; இது உங்கள் {m}% பாதுகாப்பு வரம்புக்குள் உள்ளது."),
    "r_near": ("The price is below fair value, but not by your full {m}% margin of safety. Your margin-of-safety price is ₹{bb}.",
               "விலை நியாய மதிப்பை விடக் குறைவு, ஆனால் உங்கள் முழு {m}% பாதுகாப்பு வரம்பு அளவுக்கு இல்லை. உங்கள் பாதுகாப்பு விலை ₹{bb}."),
    "r_above": ("The price is {d}% above fair value.", "விலை நியாய மதிப்பை விட {d}% அதிகமாக உள்ளது."),
    "r_missing": (" {n} checks had no data, so treat the quality score with care.",
                  " {n} சோதனைகளுக்குத் தரவு இல்லை, எனவே தர மதிப்பெண்ணைக் கவனமாகப் பாருங்கள்."),
    # header
    "tagline": ("Type any NSE stock to see what it is really worth, how strong the business is, and whether today's price is a bargain.",
                "எந்த NSE பங்கையும் தட்டச்சு செய்யுங்கள். அதன் உண்மையான மதிப்பு என்ன, நிறுவனம் எவ்வளவு வலுவானது, இன்றைய விலை மலிவானதா என்பதைப் பாருங்கள்."),
    "contact_line": ("Learn stock market trading and options buying",
                     "பங்குச் சந்தை வர்த்தகம் மற்றும் ஆப்ஷன் வாங்குதலைக் கற்றுக்கொள்ளுங்கள்"),
    "contact_call": ("Call or WhatsApp {p}.", "அழைக்கவும் அல்லது WhatsApp செய்யவும்: {p}."),
    "btn_call": ("Call now", "இப்போதே அழைக்கவும்"),
    "btn_wa": ("WhatsApp", "WhatsApp"),
    "wa_msg": ("Hi, I would like to learn trading and options buying.",
               "வணக்கம், நான் வர்த்தகம் மற்றும் ஆப்ஷன் வாங்குதலைக் கற்றுக்கொள்ள விரும்புகிறேன்."),
    # sidebar
    "settings": ("Settings", "அமைப்புகள்"),
    "mos": ("Margin of safety (%)", "பாதுகாப்பு வரம்பு (%)"),
    "disc": ("Discount rate / cost of equity (%)", "தள்ளுபடி விகிதம் / பங்கு மூலதனச் செலவு (%)"),
    "term": ("Long-term growth rate (%)", "நீண்டகால வளர்ச்சி விகிதம் (%)"),
    "method_note": ("Fair value is the middle value of four methods: historical P/E, growth-adjusted P/E, the Graham number "
                    "and a cash-flow DCF (justified P/B for banks).",
                    "நியாய மதிப்பு என்பது நான்கு முறைகளின் நடு மதிப்பு: வரலாற்று P/E, வளர்ச்சி சார்ந்த P/E, கிரஹாம் எண், "
                    "பணப்புழக்க DCF (வங்கிகளுக்கு நியாயமான P/B)."),
    "ov_title": ("Correct Yahoo's numbers (optional, single stock only)", "Yahoo எண்களைத் திருத்துங்கள் (விருப்பம், ஒரு பங்குக்கு மட்டும்)"),
    "ov_note": ("Leave a box at 0 to use Yahoo's value. If Yahoo's figure is wrong or blank, copy the correct one from Screener.in.",
                "Yahoo மதிப்பைப் பயன்படுத்த பெட்டியை 0-வில் விடுங்கள். Yahoo எண் தவறாக அல்லது காலியாக இருந்தால், "
                "Screener.in-இல் இருந்து சரியான எண்ணை எடுத்துப் போடுங்கள்."),
    "ov_eps": ("EPS, last 12 months (₹)", "EPS, கடந்த 12 மாதங்கள் (₹)"),
    "ov_bv": ("Book value per share (₹)", "ஒரு பங்கின் புத்தக மதிப்பு (₹)"),
    "ov_roe": ("Return on equity (%)", "பங்கு மூலதன வருமானம் - ROE (%)"),
    "ov_g": ("Growth rate for valuation (%), e.g. Screener's 5-year profit growth",
             "மதிப்பீட்டுக்கான வளர்ச்சி விகிதம் (%), எ.கா. Screener-இன் 5 ஆண்டு லாப வளர்ச்சி"),
    # tabs
    "tab_single": ("Single stock", "ஒரு பங்கு"),
    "tab_compare": ("Compare", "ஒப்பிடு"),
    "tab_scan": ("NIFTY 50 scanner", "NIFTY 50 ஸ்கேனர்"),
    # single stock
    "sym_label": ("NSE symbol", "NSE குறியீடு"),
    "sym_ph": ("e.g. TCS, SBIN, TATASTEEL, HDFCBANK", "எ.கா. TCS, SBIN, TATASTEEL, HDFCBANK"),
    "analyse": ("Analyse", "பகுப்பாய்வு"),
    "type_hint": ("Type an NSE symbol, such as TCS or SBIN, and press Analyse.",
                  "TCS அல்லது SBIN போன்ற NSE குறியீட்டைத் தட்டச்சு செய்து, பகுப்பாய்வு அழுத்துங்கள்."),
    "fetching": ("Fetching {s} from Yahoo Finance…", "Yahoo Finance-இல் இருந்து {s} பெறப்படுகிறது…"),
    "load_err": ("Could not load {s}: {e} If Yahoo is busy, wait a minute and try again.",
                 "{s}-ஐ ஏற்ற முடியவில்லை: {e} Yahoo பிஸியாக இருந்தால், ஒரு நிமிடம் கழித்து மீண்டும் முயலுங்கள்."),
    "using_ov": ("Your corrected numbers from the sidebar are being used.", "பக்கப்பட்டியில் நீங்கள் திருத்திய எண்கள் பயன்படுத்தப்படுகின்றன."),
    "valued_bank": ("valued as a bank/NBFC", "வங்கி/NBFC ஆக மதிப்பிடப்பட்டது"),
    "quality_x": ("Quality {q}%", "தரம் {q}%"),
    "h_gauge": ("Price vs fair value", "விலை vs நியாய மதிப்பு"),
    "g_vs": (" vs fair", " vs நியாய மதிப்பு"),
    "gauge_note": ("Green is the deep value zone, amber is below fair value, and red is above fair value. The dark tick marks fair value.",
                   "பச்சை: மலிவு விலை மண்டலம், மஞ்சள்: நியாய மதிப்புக்குக் கீழ், சிவப்பு: நியாய மதிப்புக்கு மேல். அடர் கோடு நியாய மதிப்பைக் காட்டுகிறது."),
    "no_fair_meter": ("This stock has no fair value, so the meter is hidden.", "இந்தப் பங்குக்கு நியாய மதிப்பு இல்லை, எனவே மீட்டர் காட்டப்படவில்லை."),
    "h_card": ("Report card", "மதிப்பெண் அட்டை"),
    "card_note": ("Each score compares the company with a simple benchmark, not with other companies. "
                  "Categories without data are left out of the overall grade.",
                  "ஒவ்வொரு மதிப்பெண்ணும் நிறுவனத்தை ஒரு எளிய அளவுகோலுடன் ஒப்பிடுகிறது, மற்ற நிறுவனங்களுடன் அல்ல. "
                  "தரவு இல்லாத பிரிவுகள் மொத்த மதிப்பெண்ணில் சேர்க்கப்படவில்லை."),
    "no_data": ("no data", "தரவு இல்லை"),
    "cat_Valuation": ("Valuation", "மதிப்பீடு"),
    "cat_Growth": ("Growth", "வளர்ச்சி"),
    "cat_Profitability": ("Profitability", "லாபத்தன்மை"),
    "cat_Financial health": ("Financial health", "நிதி ஆரோக்கியம்"),
    "cat_Consistency": ("Consistency", "நிலைத்தன்மை"),
    "h_share": ("Share this result", "இந்த முடிவைப் பகிருங்கள்"),
    "share_note": ("Download a ready-made picture for WhatsApp, Instagram or your status. It shows the verdict, the price meter and the report card.",
                   "WhatsApp, Instagram அல்லது ஸ்டேட்டஸுக்கு ஒரு தயார் படத்தைப் பதிவிறக்குங்கள். அதில் முடிவு, விலை மீட்டர், மதிப்பெண் அட்டை இருக்கும்."),
    "btn_download": ("Download picture", "படத்தைப் பதிவிறக்கு"),
    "preview": ("Preview the picture", "படத்தை முன்னோட்டம் பாருங்கள்"),
    "share_err": ("The share picture could not be made: {e}", "பகிர்வுப் படத்தை உருவாக்க முடியவில்லை: {e}"),
    "m_price": ("Price", "விலை"),
    "m_fair": ("Fair value", "நியாய மதிப்பு"),
    "m_safety": ("Margin-of-safety price", "பாதுகாப்பு விலை"),
    "m_upside": ("Upside to fair value", "நியாய மதிப்பு வரை உயர்வு"),
    "m_52": ("52-week low / high", "52 வார குறைவு / உயர்வு"),
    "m_from_high": ("{x}% from high", "உச்சத்தில் இருந்து {x}%"),
    "t_details": ("Verdict details", "முடிவு விவரங்கள்"),
    "t_chart": ("Price chart", "விலை வரைபடம்"),
    "t_future": ("Future price", "எதிர்கால விலை"),
    "t_fin": ("Financials", "நிதி விவரங்கள்"),
    "h_checks": ("Quality checks", "தரச் சோதனைகள்"),
    "for_banks": (" (for banks)", " (வங்கிகளுக்கு)"),
    "col_check": ("Check", "சோதனை"),
    "col_value": ("Value", "மதிப்பு"),
    "col_good": ("Good if", "நல்லது எனில்"),
    "col_result": ("Result", "முடிவு"),
    "pass": ("Pass", "தேறியது"),
    "fail": ("Fail", "தோல்வி"),
    "yes": ("Yes", "ஆம்"),
    "no": ("No", "இல்லை"),
    "h_methods": ("Fair value methods", "நியாய மதிப்பு முறைகள்"),
    "methods_note": ("Fair value is the middle value of the methods that can be used.",
                     "பயன்படுத்தக்கூடிய முறைகளின் நடு மதிப்பே நியாய மதிப்பு. முறை விவரங்கள் ஆங்கிலத்தில் உள்ளன."),
    "roe_calc_note": ("Yahoo had no ROE for this company, so it was calculated as EPS ÷ book value per share.",
                      "இந்த நிறுவனத்துக்கு Yahoo-வில் ROE இல்லை, எனவே EPS ÷ ஒரு பங்கின் புத்தக மதிப்பு என்று கணக்கிடப்பட்டது."),
    "period": ("Period", "காலம்"),
    "p6": ("6 months", "6 மாதங்கள்"),
    "p12": ("1 year", "1 ஆண்டு"),
    "p36": ("3 years", "3 ஆண்டுகள்"),
    "p60": ("5 years", "5 ஆண்டுகள்"),
    "chart_note": ("The dashed line is today's fair value, the shaded green band is the deep value zone, and the dotted line is the "
                   "200-day average price. Candles inside the green band were bargains by today's estimate.",
                   "கோடிட்ட கோடு இன்றைய நியாய மதிப்பு, பச்சை நிழல் பகுதி மலிவு விலை மண்டலம், புள்ளிக் கோடு 200 நாள் சராசரி விலை. "
                   "பச்சைப் பகுதிக்குள் உள்ள மெழுகுவர்த்திகள் இன்றைய கணிப்பின்படி மலிவானவை."),
    "no_hist": ("Price history is not available for this stock.", "இந்தப் பங்கின் விலை வரலாறு கிடைக்கவில்லை."),
    "lbl_fair": ("Fair value ₹{x}", "நியாய மதிப்பு ₹{x}"),
    "lbl_zone": ("Deep value zone", "மலிவு விலை மண்டலம்"),
    "lbl_dma": ("200-day average", "200 நாள் சராசரி"),
    "h_future": ("If the company keeps growing by about {g}% a year", "நிறுவனம் ஆண்டுக்கு சுமார் {g}% வளர்ந்தால்"),
    "future_note": ("Growth source: {src}. The base case keeps today's P/E. The bear case uses half the growth and a 20% lower P/E. "
                    "The bull case uses 1.5× the growth and a higher P/E (15% higher, or halfway back to its usual P/E if that is higher).",
                    "வளர்ச்சி ஆதாரம்: {src}. அடிப்படை நிலை இன்றைய P/E-ஐ அப்படியே வைக்கிறது. கரடி நிலை பாதி வளர்ச்சியும் 20% குறைந்த P/E-யும் "
                    "எடுத்துக்கொள்கிறது. காளை நிலை 1.5 மடங்கு வளர்ச்சியும் அதிக P/E-யும் (15% அதிகம், அல்லது வழக்கமான P/E-க்குப் பாதி வழி, "
                    "எது அதிகமோ அது) எடுத்துக்கொள்கிறது."),
    "col_in": ("In", "காலம்"),
    "yr1": ("{n} year", "{n} ஆண்டு"),
    "yrs": ("{n} years", "{n} ஆண்டுகள்"),
    "bear": ("Bear", "கரடி"),
    "base": ("Base", "அடிப்படை"),
    "bull": ("Bull", "காளை"),
    "base_ret": ("Base return per year", "அடிப்படை ஆண்டு வருமானம்"),
    "no_project": ("Future prices need positive earnings, so they are not shown for this stock.",
                   "எதிர்கால விலைக்கு நேர்மறை வருவாய் தேவை, எனவே இந்தப் பங்குக்குக் காட்டப்படவில்லை."),
    "h_analysts": ("What analysts expect (from reports collected by Yahoo)", "ஆய்வாளர்கள் எதிர்பார்ப்பது (Yahoo சேகரித்த அறிக்கைகளில் இருந்து)"),
    "a_low": ("Low target", "குறைந்த இலக்கு"),
    "a_avg": ("Average target", "சராசரி இலக்கு"),
    "a_high": ("High target", "அதிக இலக்கு"),
    "a_n": ("Analysts", "ஆய்வாளர்கள்"),
    "a_note": ("Analyst targets are usually 12-month targets. They are not used to calculate fair value.",
               "ஆய்வாளர் இலக்குகள் பொதுவாக 12 மாத இலக்குகள். நியாய மதிப்பைக் கணக்கிட இவை பயன்படுத்தப்படவில்லை."),
    "a_none": ("No analyst targets are available for this stock.", "இந்தப் பங்குக்கு ஆய்வாளர் இலக்குகள் இல்லை."),
    "proj_note": ("These projections assume past growth continues. Real results can be very different.",
                  "இந்தக் கணிப்புகள் கடந்த கால வளர்ச்சி தொடரும் என்று கருதுகின்றன. உண்மையான முடிவுகள் மிகவும் வேறுபடலாம்."),
    "h_fin": ("Revenue and net profit (₹ crore)", "வருவாய் மற்றும் நிகர லாபம் (₹ கோடி)"),
    "rev": ("Revenue", "வருவாய்"),
    "np": ("Net profit", "நிகர லாபம்"),
    "fin_note": ("Yahoo provides {n} years of annual data, so growth rates are based on {k} years.",
                 "Yahoo {n} ஆண்டுகளின் ஆண்டுத் தரவைத் தருகிறது, எனவே வளர்ச்சி விகிதங்கள் {k} ஆண்டுகளை அடிப்படையாகக் கொண்டவை."),
    "k_mcap": ("Market cap", "சந்தை மதிப்பு"),
    "k_pe": ("P/E (now / usual)", "P/E (இப்போது / வழக்கமான)"),
    "k_pb": ("P/B", "P/B"),
    "k_roe": ("ROE", "ROE"),
    "k_div": ("Dividend yield", "டிவிடெண்ட் வருவாய்"),
    "k_margin": ("Net margin", "நிகர லாப விகிதம்"),
    "k_de": ("Debt / Equity", "கடன் / பங்கு மூலதனம்"),
    "k_roa": ("ROA", "ROA"),
    "bank_warn": ("For banks and NBFCs, also check gross and net NPA, net interest margin, CASA ratio and capital adequacy on the "
                  "company's investor relations page.",
                  "வங்கிகள் மற்றும் NBFC-களுக்கு, மொத்த மற்றும் நிகர NPA, நிகர வட்டி விகிதம், CASA விகிதம், மூலதனப் போதுமை ஆகியவற்றையும் "
                  "நிறுவனத்தின் முதலீட்டாளர் பக்கத்தில் சரிபாருங்கள்."),
    "footer": ("This is an educational tool, not investment advice. Promoter holding, pledges and governance are not covered here, "
               "so check NSE before you buy. Yahoo data can be delayed or incomplete for smaller companies.",
               "இது ஒரு கல்விக் கருவி, முதலீட்டு ஆலோசனை அல்ல. விளம்பரதாரர் பங்கு, அடமானம், நிர்வாகம் ஆகியவை இங்கு இல்லை, எனவே வாங்கும் முன் "
               "NSE-இல் சரிபாருங்கள். சிறிய நிறுவனங்களுக்கு Yahoo தரவு தாமதமாகவோ முழுமையற்றதாகவோ இருக்கலாம்."),
    # home page: today's top five
    "h_top5": ("Today's 5 biggest discounts in NIFTY 50", "இன்று NIFTY 50-இல் மிகப்பெரிய 5 தள்ளுபடிகள்"),
    "top5_note": ("Healthy NIFTY 50 companies trading furthest below fair value. This is a list to research, not a recommendation.",
                  "நியாய மதிப்பை விட மிகக் குறைவாக வர்த்தகமாகும் ஆரோக்கியமான NIFTY 50 நிறுவனங்கள். இது ஆய்வுக்கான பட்டியல், பரிந்துரை அல்ல."),
    "btn_top5": ("Show today's list", "இன்றைய பட்டியலைக் காட்டு"),
    "top5_wait": ("Checking all 50 stocks takes one to three minutes the first time. After that, everyone sees the list instantly for an hour.",
                  "முதல் முறை 50 பங்குகளையும் சரிபார்க்க ஒன்று முதல் மூன்று நிமிடங்கள் ஆகும். அதன் பிறகு ஒரு மணி நேரம் அனைவருக்கும் உடனே தெரியும்."),
    "open_x": ("Open {s}", "{s} திற"),
    "below_fair": ("{d}% below fair value", "நியாய மதிப்பை விட {d}% குறைவு"),
    "above_fair": ("{d}% above fair value", "நியாய மதிப்பை விட {d}% அதிகம்"),
    "top5_none": ("No healthy NIFTY 50 company is below fair value right now.", "இப்போது எந்த ஆரோக்கியமான NIFTY 50 நிறுவனமும் நியாய மதிப்புக்குக் கீழ் இல்லை."),
    # scanner
    "h_scan": ("Which NIFTY 50 stocks are trading below fair value?", "எந்த NIFTY 50 பங்குகள் நியாய மதிப்புக்குக் கீழ் வர்த்தகமாகின்றன?"),
    "scan_note": ("This runs every NIFTY 50 stock through the same checks as the single-stock page, using your settings. The first scan "
                  "takes one to three minutes. Results are saved for an hour, so later scans are quick.",
                  "ஒவ்வொரு NIFTY 50 பங்கையும், உங்கள் அமைப்புகளுடன், ஒரு பங்கு பக்கத்தில் உள்ள அதே சோதனைகள் மூலம் சரிபார்க்கிறது. முதல் ஸ்கேன் "
                  "ஒன்று முதல் மூன்று நிமிடங்கள் ஆகும். முடிவுகள் ஒரு மணி நேரம் சேமிக்கப்படும், அதனால் அடுத்த ஸ்கேன்கள் விரைவாக இருக்கும்."),
    "btn_scan": ("Run NIFTY 50 scan", "NIFTY 50 ஸ்கேன் செய்"),
    "scan_press": ("Press \"Run NIFTY 50 scan\" to check all 50 stocks.", "50 பங்குகளையும் சரிபார்க்க \"NIFTY 50 ஸ்கேன் செய்\" அழுத்துங்கள்."),
    "scan_start": ("Starting the scan…", "ஸ்கேன் தொடங்குகிறது…"),
    "scan_progress": ("Checking {s} ({i}/{n})", "{s} சரிபார்க்கப்படுகிறது ({i}/{n})"),
    "scan_none": ("Yahoo did not return data for any stock. It may be limiting requests, so wait a few minutes and press the button again.",
                  "Yahoo எந்தப் பங்குக்கும் தரவு தரவில்லை. அது கோரிக்கைகளைக் கட்டுப்படுத்தலாம், எனவே சில நிமிடங்கள் கழித்து மீண்டும் அழுத்துங்கள்."),
    "c_deep": ("Deep value", "மலிவு விலை"),
    "c_near": ("Near fair value", "நியாய மதிப்புக்கு அருகில்"),
    "c_above": ("Above fair value", "நியாய மதிப்புக்கு மேல்"),
    "c_weak": ("Weak business", "பலவீனமான நிறுவனம்"),
    "h_heat": ("Heatmap: price vs fair value", "வெப்ப வரைபடம்: விலை vs நியாய மதிப்பு"),
    "heat_note": ("Box size shows market cap. Green boxes trade below fair value and red boxes above it. Pale boxes trade near fair value "
                  "or have no fair value.",
                  "பெட்டியின் அளவு சந்தை மதிப்பைக் காட்டுகிறது. பச்சைப் பெட்டிகள் நியாய மதிப்புக்குக் கீழும், சிவப்புப் பெட்டிகள் மேலும் உள்ளன. "
                  "வெளிர் பெட்டிகள் நியாய மதிப்புக்கு அருகில் உள்ளன அல்லது நியாய மதிப்பு இல்லாதவை."),
    "no_fair_short": ("no fair value", "நியாய மதிப்பு இல்லை"),
    "show": ("Show", "காட்டு"),
    "col_symbol": ("Symbol", "குறியீடு"),
    "col_company": ("Company", "நிறுவனம்"),
    "col_verdict": ("Verdict", "முடிவு"),
    "col_upside": ("Upside %", "உயர்வு %"),
    "col_quality": ("Quality %", "தரம் %"),
    "col_52": ("From 52-week high %", "52 வார உச்சத்தில் இருந்து %"),
    "col_sector": ("Sector", "துறை"),
    "scan_sort": ("Deep-value stocks are listed first, then sorted by upside to fair value. For full details of any stock, type its "
                  "symbol in the \"Single stock\" tab.",
                  "மலிவு விலைப் பங்குகள் முதலில், பிறகு நியாய மதிப்பு வரையிலான உயர்வின்படி வரிசைப்படுத்தப்பட்டுள்ளன. எந்தப் பங்கின் முழு "
                  "விவரத்துக்கும், \"ஒரு பங்கு\" தாவலில் அதன் குறியீட்டைத் தட்டச்சு செய்யுங்கள்."),
    "scan_failed": ("Yahoo did not return data for {n} stock(s): {lst}. Press \"Run NIFTY 50 scan\" again in a minute to retry them.",
                    "{n} பங்குகளுக்கு Yahoo தரவு தரவில்லை: {lst}. ஒரு நிமிடம் கழித்து மீண்டும் \"NIFTY 50 ஸ்கேன் செய்\" அழுத்துங்கள்."),
    "scan_disclaim": ("A deep-value verdict is a starting point for your own research. It is not a recommendation.",
                      "மலிவு விலை என்ற முடிவு உங்கள் சொந்த ஆய்வுக்கான தொடக்கம் மட்டுமே. இது பரிந்துரை அல்ல."),
    # compare
    "h_compare": ("Compare two stocks", "இரண்டு பங்குகளை ஒப்பிடுங்கள்"),
    "cmp_a": ("First stock", "முதல் பங்கு"),
    "cmp_b": ("Second stock", "இரண்டாம் பங்கு"),
    "cmp_hint": ("Type two NSE symbols, such as HDFCBANK and ICICIBANK, to see them side by side.",
                 "HDFCBANK, ICICIBANK போன்ற இரண்டு NSE குறியீடுகளைத் தட்டச்சு செய்து அருகருகே பாருங்கள்."),
    "cmp_note": ("The stronger figure in each row is shown in green.", "ஒவ்வொரு வரிசையிலும் சிறந்த எண் பச்சையில் காட்டப்பட்டுள்ளது."),
    "cmp_metric": ("Measure", "அளவீடு"),
    "cmp_rev_g": ("Revenue growth (CAGR)", "வருவாய் வளர்ச்சி (CAGR)"),
    # share picture
    "card_safety": ("Safety price", "பாதுகாப்பு விலை"),
    "card_cheap": ("Cheap", "மலிவு"),
    "card_costly": ("Costly", "அதிக விலை"),
    "card_nofair": ("Fair value not available", "நியாய மதிப்பு கிடைக்கவில்லை"),
    "card_contact": ("Learn stock market trading and options buying. Call {p}", "பங்குச் சந்தை & ஆப்ஷன் வர்த்தகம் கற்க அழைக்கவும்: {p}"),
    "card_site": ("Check any NSE stock for free at {u}", "எந்த NSE பங்கையும் இலவசமாகப் பாருங்கள்: {u}"),
    "card_disc": ("For learning only. This is not investment advice.", "கற்றலுக்கு மட்டுமே. இது முதலீட்டு ஆலோசனை அல்ல."),
}

# Quality-check names, rules, method names and growth sources (computed in English by analyse())
TA_TERMS = {
    "Return on equity": "பங்கு மூலதன வருமானம் (ROE)", "Return on assets": "சொத்து வருமானம் (ROA)",
    "Net profit margin": "நிகர லாப விகிதம்", "Revenue growth (CAGR)": "வருவாய் வளர்ச்சி (CAGR)",
    "EPS growth (CAGR)": "EPS வளர்ச்சி (CAGR)", "Profitable every year": "ஒவ்வொரு ஆண்டும் லாபம்",
    "P/B vs justified P/B": "P/B vs நியாயமான P/B", "Debt / Equity": "கடன் / பங்கு மூலதனம்",
    "Current ratio": "நடப்பு விகிதம்", "FCF / net profit": "இலவச பணப்புழக்கம் / நிகர லாபம்",
    "No loss-making years": "நஷ்ட ஆண்டுகள் இல்லை", "0.5 or less": "0.5 அல்லது குறைவு", "1.2 or more": "1.2 அல்லது அதிகம்",
    "1.0x or less (not overpaying for book value)": "1.0x அல்லது குறைவு (புத்தக மதிப்புக்கு அதிகம் கொடுக்கவில்லை)",
    "Historical P/E": "வரலாற்று P/E", "Growth-adjusted P/E": "வளர்ச்சி சார்ந்த P/E", "Graham number": "கிரஹாம் எண்",
    "Justified P/B (banks)": "நியாயமான P/B (வங்கிகள்)", "Cash-flow DCF": "பணப்புழக்க DCF",
    "EPS growth": "EPS வளர்ச்சி", "profit growth": "லாப வளர்ச்சி", "revenue growth": "வருவாய் வளர்ச்சி",
    "your own growth rate": "உங்கள் சொந்த வளர்ச்சி விகிதம்",
    "a default rate, as no history is available": "இயல்பு விகிதம் (வரலாறு இல்லை)",
}

VERDICT_TONE = {"deep": "good", "near": "warn", "above": "bad", "weak": "bad", "cant": "warn", "noprice": "warn"}
VERDICT_ORDER = ["deep", "near", "above", "weak", "cant", "noprice"]


def cur_lang():
    try:
        import streamlit as st
        return st.session_state.get("lang_code", "en")
    except Exception:
        return "en"


def tr(key, lang=None, **kw):
    lang = lang or cur_lang()
    en, ta = TEXT[key]
    s = ta if lang == "ta" else en
    return s.format(**kw) if kw else s


def term(s, lang=None):
    """Translate a fixed English term (check names, rules, method names, growth sources)."""
    lang = lang or cur_lang()
    if lang != "ta" or not s:
        return s
    if s in TA_TERMS:
        return TA_TERMS[s]
    if s.startswith("At least "):
        return "குறைந்தது " + s[len("At least "):].replace(" a year", " ஆண்டுக்கு")
    return s


def verdict_reason(code, args, note_missing, lang=None):
    txt = tr("r_" + code, lang, **{k: v for k, v in args.items() if v is not None})
    if note_missing:
        txt += tr("r_missing", lang, n=args.get("n"))
    return txt


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
    roe_calc = False
    if roe is None and eps and eps > 0 and bvps and bvps > 0:
        roe, roe_calc = eps / bvps * 100, True          # Yahoo often leaves ROE blank; EPS / book is a close estimate
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
    g_src = "your own growth rate"
    if g_used is None:
        for val, src in ((eps_c, "EPS growth"), (ni_c, "profit growth"), (rev_c, "revenue growth")):
            if val is not None:
                g_used, g_src = val, src
                break
    if g_used is None:
        g_used, g_src = 10.0, "a default rate, as no history is available"

    hist_pes = [p for p in (_num(x) for x in (d.get("hist_pe") or [])) if p is not None and 0 < p < 150]
    hist_pe = _median(hist_pes)

    methods = []
    # 1. Historical P/E: what the market has usually paid for this company's earnings
    if eps and eps > 0 and hist_pe:
        pe1 = clip(hist_pe, 6, 60)
        methods.append(("Historical P/E", eps * pe1,
                        f"EPS of ₹{eps:.2f} × the company's own median P/E of {pe1:.1f} over the last {len(hist_pes)} years."))
    else:
        methods.append(("Historical P/E", None, "Not used: this method needs positive EPS and past P/E data."))

    # 2. Growth-adjusted P/E. Fair P/E ~ growth, but never below the P/E that the company's ROE justifies:
    #    justified P/E = payout x (1 + g) / (r - g), with payout = 1 - g / ROE (the profit it does not need to reinvest).
    #    Without this floor, slow-growing, high-ROE, high-dividend companies (FMCG, utilities) look far too expensive.
    if eps and eps > 0:
        pe_growth = clip(g_used, 10, 35)
        jpe = None
        if roe and roe > 0:
            gs = clip(g_used, 0, max(0.0, discount - 4))   # keep r - g >= 4 points; the formula explodes as g nears r
            payout = clip(1 - gs / roe, 0.1, 0.95)
            jpe = payout * (1 + gs / 100) / ((discount - gs) / 100)
        fair_pe = clip(max(pe_growth, jpe or 0), 10, 35)
        if jpe and jpe > pe_growth:
            how = (f"EPS of ₹{eps:.2f} × a fair P/E of {fair_pe:.1f}. Growth alone ({g_src}, {g_used:.1f}%) suggests "
                   f"{pe_growth:.1f}, but a {roe:.0f}% ROE justifies {jpe:.1f}, so the higher figure is used (kept between 10 and 35).")
        else:
            how = f"EPS of ₹{eps:.2f} × a fair P/E of {fair_pe:.1f}, based on {g_src} of {g_used:.1f}% (kept between 10 and 35)."
        methods.append(("Growth-adjusted P/E", eps * fair_pe, how))
    else:
        methods.append(("Growth-adjusted P/E", None, "Not used: EPS is zero or negative."))

    # 3. Graham number (conservative; badly undervalues high-ROE businesses, so it is skipped for them)
    if not lender and roe and roe >= 20:
        methods.append(("Graham number", None, f"Not used: this method undervalues companies with a very high ROE "
                                               f"({roe:.0f}%, above 20%)."))
    elif eps and eps > 0 and bvps and bvps > 0:
        methods.append(("Graham number", math.sqrt(22.5 * eps * bvps),
                        f"Square root of 22.5 × EPS of ₹{eps:.2f} × book value per share of ₹{bvps:.2f}."))
    else:
        methods.append(("Graham number", None, "Not used: this method needs positive EPS and book value."))

    # 4a. Banks/NBFCs: justified P/B = ROE / cost of equity
    # 4b. Others: two-stage DCF on free cash flow
    if lender:
        if roe and roe > 0 and bvps and bvps > 0:
            jpb = clip(roe / discount, 0.3, 5)
            methods.append(("Justified P/B (banks)", bvps * jpb,
                            f"Book value per share of ₹{bvps:.2f} × a justified P/B of {jpb:.2f} (ROE of {roe:.1f}% ÷ cost of equity of {discount}%)."))
        else:
            methods.append(("Justified P/B (banks)", None, "Not used: this method needs positive ROE and book value."))
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
                        f"Free cash flow per share of ₹{fcfps:.2f}, growing {g1*100:.1f}% a year for five years and slowing to {terminal}% by year 10, discounted at {discount}%."))
    else:
        why = ("free cash flow is negative" if (fcfps is not None and fcfps <= 0)
               else "free cash flow is missing, or the discount rate is not above terminal growth")
        methods.append(("Cash-flow DCF", None, f"Not used: {why}."))

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
            ("Return on equity", roe, "%", lambda x: x >= 12, "At least 12%"),
            ("Return on assets", roa, "%", lambda x: x >= 1.0, "At least 1%"),
            ("Net profit margin", _num(d.get("net_margin")), "%", lambda x: x >= 15, "At least 15%"),
            ("Revenue growth (CAGR)", rev_c, "%", lambda x: x >= 10, "At least 10% a year"),
            ("EPS growth (CAGR)", eps_c, "%", lambda x: x >= 10, "At least 10% a year"),
            ("Profitable every year", ni_all, "bool", lambda x: x is True, "No loss-making years"),
            ("P/B vs justified P/B", (pb / jpb_val) if (pb and jpb_val) else None, "x",
             lambda x: x <= 1.0, "1.0x or less (not overpaying for book value)"),
        ]
    else:
        fcf_conv = (sum(fc) / sum(ni) * 100) if (fc and ni and sum(ni) > 0) else None
        checks = [
            ("Return on equity", roe, "%", lambda x: x >= 15, "At least 15%"),
            ("Net profit margin", _num(d.get("net_margin")), "%", lambda x: x >= 10, "At least 10%"),
            ("Revenue growth (CAGR)", rev_c, "%", lambda x: x >= 10, "At least 10% a year"),
            ("EPS growth (CAGR)", eps_c, "%", lambda x: x >= 10, "At least 10% a year"),
            ("Profitable every year", ni_all, "bool", lambda x: x is True, "No loss-making years"),
            ("Debt / Equity", _num(d.get("de")), "x", lambda x: x <= 0.5, "0.5 or less"),
            ("Current ratio", _num(d.get("current_ratio")), "x", lambda x: x >= 1.2, "1.2 or more"),
            ("FCF / net profit", fcf_conv, "%", lambda x: x >= 80, "At least 80%"),
        ]
    rows = []
    for name, v, fmt, test, rule in checks:
        ok = None if v is None else bool(test(v))
        rows.append({"check": name, "value": v, "fmt": fmt, "rule": rule, "ok": ok})
    scored = [r for r in rows if r["ok"] is not None]
    quality = round(sum(r["ok"] for r in scored) / len(scored) * 100) if scored else None
    missing = len(rows) - len(scored)

    # Verdict: a neutral code plus the numbers needed to explain it (wording lives in TEXT, so it can be translated)
    args = dict(q=quality, m=round(mos), n=missing)
    if not price:
        code = "noprice"
    elif quality is not None and quality < 50:
        code = "weak"
    elif not fair:
        code = "cant"
    elif price <= buy_below:
        code = "deep"
        args["d"] = round((1 - price / fair) * 100)
    elif price <= fair:
        code = "near"
        args["bb"] = f"{buy_below:,.0f}"
    else:
        code = "above"
        args["d"] = round((price / fair - 1) * 100)
    tone = VERDICT_TONE[code]
    verdict = tr("v_" + code, "en")
    reason = verdict_reason(code, args, missing >= 3 and quality is not None, "en")

    return dict(code=code, args=args, note_missing=(missing >= 3 and quality is not None), roe_calc=roe_calc,
                price=price, eps=eps, bvps=bvps, roe=roe, fcfps=fcfps, rev_c=rev_c, eps_c=eps_c, lender=lender,
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


def _div_yield(info, price):
    """Dividend yield in %. Uses the rupee dividend / price when available, because Yahoo's own
    dividendYield field has been reported as a fraction in some yfinance versions and a percent in others."""
    rate = _num(info.get("trailingAnnualDividendRate")) or _num(info.get("dividendRate"))
    if rate and price:
        return rate / price * 100
    dy = _num(info.get("dividendYield"))
    if dy is None:
        return None
    # Below 0.1 it is almost surely a fraction (0.1 = 10%); a genuine yield under 0.1% as a percent is negligible anyway.
    return dy * 100 if dy < 0.1 else dy


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
        raise ValueError(f"No data was found for {ysym}. Check the NSE symbol (for example SBIN, TCS or TATASTEEL).")

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
        div_yield=_div_yield(info, price),
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
    return "-" if v is None else f"₹{v:,.2f}" if abs(v) < 100 else f"₹{v:,.0f}"


def crore(v):
    return "-" if v is None else f"₹{v / 1e7:,.0f} Cr"


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
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
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
    print("For learning only. This is not investment advice. Promoter holding and pledges are not included, so check NSE.")


# ----------------------------------------------------------------------------
# Look and feel: palette, CSS, charts
# ----------------------------------------------------------------------------

INK, PAPER, CARD, LINE, MUTED = "#1D3B34", "#FBF9F4", "#FFFFFF", "#E6E1D5", "#5E6B66"
EMERALD, GOLD, GOLD_TEXT, GOLD_SOFT = "#0F7A5C", "#C99A3E", "#8A6420", "#F7EEDA"
# Palette from the owner's chart: Sukran (lagna lord) pearl/ivory base, Budhan (mahadasa) emerald brand,
# Surya (next bhukti) gold accents. Dark navy/black left out on purpose.
TONE = {"good": "#1F7A4D", "warn": "#A86400", "bad": "#B42318"}
GRADE_COLOR = {"A": "#1F7A4D", "B": "#3E8E5E", "C": "#A86400", "D": "#C2410C", "F": "#B42318", "-": MUTED}
FONT = "Source Sans 3, Noto Sans Tamil, Segoe UI, sans-serif"
SHADOW = "0 1px 2px rgba(29,59,52,.05), 0 10px 28px rgba(29,59,52,.06)"

LOGO_SVG = ('<svg class="fvf-logo" viewBox="0 0 32 32" aria-hidden="true" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round"><path d="M16 4v23M5 8h22M10 27h12M5 8 2 17M5 8l3 9M27 8l-3 9M27 8l3 9"/>'
            '<path d="M1.5 17a3.5 3.5 0 0 0 7 0zM23.5 17a3.5 3.5 0 0 0 7 0z" fill="currentColor"/></svg>')

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Source+Sans+3:wght@400;600;700&family=Noto+Sans+Tamil:wght@400;600;700&display=swap');
html, body, [class*="st-"], .stMarkdown, p, li, label {{ font-family: {FONT}; }}
h1, h2, h3, h4, .fvf-name, .fvf-brand {{ font-family: 'Bricolage Grotesque', {FONT}; color: {INK}; letter-spacing: -0.015em; }}
h4 {{ font-weight: 700; }}
.block-container {{ padding-top: 3.2rem; max-width: 1160px; }}

/* Header: navy band with gold logo, tagline and the class contact row */
.fvf-head {{ background: linear-gradient(135deg, #EEF7F2 0%, #FFFDF8 55%, #FBF1DC 100%); border-radius: 20px;
            padding: 1.6rem 1.8rem 1.2rem; margin-bottom: 1.4rem; border: 1px solid rgba(201,154,62,.45); box-shadow: {SHADOW}; }}
.fvf-brandrow {{ display: flex; align-items: center; gap: .7rem; }}
.fvf-logo {{ width: 38px; height: 38px; color: {GOLD}; flex: 0 0 auto; }}
.fvf-head .fvf-brand {{ font-size: 2.15rem; font-weight: 800; line-height: 1.05; margin: 0; color: {EMERALD}; }}
.fvf-tag {{ color: {MUTED}; margin: .65rem 0 1.15rem; font-size: 1.07rem; line-height: 1.5; max-width: 60ch; }}
.fvf-contact {{ display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .7rem 1rem;
               border-top: 1px solid rgba(201,154,62,.35); padding-top: 1rem; }}
.fvf-contact p {{ margin: 0; color: {INK}; font-size: 1rem; }}
.fvf-contact b {{ color: {EMERALD}; font-weight: 700; }}
.fvf-links {{ display: flex; gap: .55rem; flex-wrap: wrap; }}
.fvf-links a {{ border-radius: 999px; padding: .45rem 1.1rem; font-weight: 700; text-decoration: none !important;
               white-space: nowrap; font-size: .95rem; }}
.fvf-links .gold {{ background: {EMERALD}; color: #fff !important; }}
.fvf-links .ghost {{ border: 1.5px solid {GOLD}; color: {GOLD_TEXT} !important; background: #fff; }}
.fvf-links a:focus-visible {{ outline: 3px solid {GOLD}; outline-offset: 2px; }}

/* Hero with the verdict stamp */
.fvf-hero {{ display: flex; gap: 1.5rem; align-items: center; justify-content: space-between; flex-wrap: wrap;
            background: {CARD}; border: 1px solid {LINE}; border-left: 5px solid {GOLD}; border-radius: 16px;
            padding: 1.5rem 1.7rem; margin: .4rem 0 1.1rem; box-shadow: {SHADOW}; }}
.fvf-hero-text {{ flex: 1 1 360px; min-width: 0; }}
.fvf-hero .fvf-name {{ font-size: 2rem; font-weight: 800; line-height: 1.12; margin: 0; }}
.fvf-sub {{ color: {MUTED}; font-size: .95rem; margin: .35rem 0 .85rem; }}
.fvf-reason {{ font-size: 1.06rem; line-height: 1.55; max-width: 62ch; margin: 0; color: #1D3B34; }}
.fvf-stamp {{ flex: 0 1 auto; box-sizing: border-box; transform: rotate(-6deg); border: 4px double var(--c); color: var(--c);
             border-radius: 12px; padding: .6rem 1.15rem; text-align: center; font-family: 'Bricolage Grotesque', {FONT};
             font-weight: 800; font-size: 1.35rem; line-height: 1.15; max-width: 15rem;
             background: color-mix(in srgb, var(--c) 7%, white);
             animation: fvf-stamp .45s cubic-bezier(.2,1.6,.4,1) both; }}
.fvf-stamp small {{ display: block; font-family: {FONT}; font-weight: 600; font-size: .8rem; margin-top: .25rem; opacity: .85; }}
@keyframes fvf-stamp {{ from {{ transform: rotate(-6deg) scale(1.8); opacity: 0; }} to {{ transform: rotate(-6deg) scale(1); opacity: 1; }} }}
@media (prefers-reduced-motion: reduce) {{ .fvf-stamp {{ animation: none; }} }}

/* Panels (Streamlit containers with key="fvf-panel-...") */
[class*="st-key-fvf-panel"] {{ background: {CARD}; border-radius: 16px !important; box-shadow: {SHADOW};
                              border-color: {LINE} !important; }}
.st-key-fvf-panel-share {{ background: {GOLD_SOFT} !important; border-color: rgba(201,154,62,.55) !important; }}
.st-key-fvf-share-btn button {{ background: {EMERALD} !important; border-color: {EMERALD} !important; color: #fff !important;
                               border-radius: 999px !important; font-weight: 700; }}

/* Report card grades */
.fvf-grades {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: .5rem; margin: .4rem 0 .6rem; }}
.fvf-grade {{ border: 1px solid {LINE}; border-radius: 12px; padding: .5rem .65rem; display: flex; align-items: center;
             gap: .55rem; background: #FDFBF6; }}
.fvf-grade b {{ font-family: 'Bricolage Grotesque', {FONT}; font-size: 1.55rem; color: var(--c); min-width: 1.2ch; }}
.fvf-grade span {{ font-size: .86rem; color: #1D3B34; line-height: 1.2; }}
.fvf-grade em {{ display: block; font-style: normal; color: {MUTED}; font-size: .78rem; }}

/* Metrics, tabs, sidebar */
[data-testid="stMetric"] {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; padding: .8rem 1rem;
                           box-shadow: {SHADOW}; }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; }}
[data-testid="stMetricValue"] {{ font-family: 'Bricolage Grotesque', {FONT}; color: {INK}; font-weight: 700; }}
[data-baseweb="tab-highlight"] {{ background-color: {GOLD} !important; }}
[data-baseweb="tab"] p {{ font-weight: 600; }}
[data-testid="stSidebar"] {{ border-right: 1px solid {LINE}; }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{ background: {GOLD_SOFT} !important;
    border: 1px solid rgba(201,154,62,.45); border-radius: 12px; }}
[data-testid="stAlertContentInfo"], [data-testid="stAlertContentInfo"] p, [data-testid="stAlertContentInfo"] svg {{
    color: {GOLD_TEXT} !important; fill: {GOLD_TEXT}; }}
[data-testid="stExpander"] details {{ border-radius: 12px; }}

/* Today's top five */
.fvf-pick {{ background: #FDFBF6; border: 1px solid {LINE}; border-top: 4px solid {EMERALD}; border-radius: 14px;
            padding: .8rem .85rem; margin-bottom: .45rem; min-height: 9.5rem; }}
.fvf-pick-sym {{ font-family: 'Bricolage Grotesque', {FONT}; font-weight: 800; font-size: 1.2rem; color: {INK}; }}
.fvf-pick-name {{ color: {MUTED}; font-size: .8rem; line-height: 1.25; margin: .1rem 0 .45rem;
                 display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
.fvf-pick-up {{ color: {EMERALD}; font-weight: 700; font-size: .98rem; }}
.fvf-pick-px {{ color: {INK}; font-size: .85rem; margin-top: .15rem; }}
.fvf-pick-grade {{ font-size: .8rem; color: {MUTED}; margin-top: .3rem; }}
.fvf-pick-grade b {{ color: var(--c); font-size: 1rem; }}

/* Compare table */
.fvf-cmp-wrap {{ overflow-x: auto; background: {CARD}; border: 1px solid {LINE}; border-radius: 16px; box-shadow: {SHADOW}; }}
.fvf-cmp {{ width: 100%; border-collapse: collapse; font-size: .95rem; }}
.fvf-cmp th, .fvf-cmp td {{ padding: .6rem .9rem; border-bottom: 1px solid {LINE}; text-align: left; vertical-align: middle; }}
.fvf-cmp thead th {{ background: #F3F8F5; font-family: 'Bricolage Grotesque', {FONT}; color: {EMERALD}; font-size: 1.1rem; }}
.fvf-cmp thead th small {{ display: block; font-family: {FONT}; color: {MUTED}; font-size: .78rem; font-weight: 400; }}
.fvf-cmp tbody th {{ color: {MUTED}; font-weight: 600; width: 34%; }}
.fvf-cmp tbody tr:last-child th, .fvf-cmp tbody tr:last-child td {{ border-bottom: 0; }}
.fvf-cmp td.win {{ color: {TONE["good"]}; font-weight: 700; background: #F1F8F4; }}
.fvf-chip {{ display: inline-block; border: 2px solid var(--c); color: var(--c); border-radius: 8px; padding: .1rem .5rem;
            font-weight: 700; font-size: .8rem; }}

@media (max-width: 640px) {{
  .fvf-pick {{ min-height: 0; }}
  .fvf-head {{ padding: 1.2rem 1.1rem 1rem; border-radius: 16px; }}
  .fvf-head .fvf-brand {{ font-size: 1.65rem; }} .fvf-logo {{ width: 30px; height: 30px; }}
  .fvf-hero .fvf-name {{ font-size: 1.5rem; }} .fvf-hero {{ padding: 1.1rem; }}
  .fvf-stamp {{ font-size: 1.05rem; max-width: calc(100% - 1.5rem); margin: .3rem auto 0; padding: .5rem .9rem;
               transform: rotate(-4deg); animation: none; }}
}}
</style>
"""


def _esc(s):
    import html
    return html.escape(str(s or ""))


def hero_html(d, r):
    c = TONE[r["tone"]]
    parts = [d["symbol"], d.get("sector"), d.get("industry")]
    if r["lender"]:
        parts.append(tr("valued_bank"))
    sub = " | ".join(x for x in parts if x)
    verdict = tr("v_" + r["code"])
    reason = verdict_reason(r["code"], r["args"], r["note_missing"])
    q = "" if r["quality"] is None else f"<small>{_esc(tr('quality_x', q=r['quality']))}</small>"
    return (f'<div class="fvf-hero"><div class="fvf-hero-text"><div class="fvf-name">{_esc(d["name"])}</div>'
            f'<p class="fvf-sub">{_esc(sub)}</p><p class="fvf-reason">{_esc(reason)}</p></div>'
            f'<div class="fvf-stamp" style="--c:{c}" role="img" aria-label="{_esc(verdict)}">'
            f'{_esc(verdict)}{q}</div></div>')


def header_html():
    from urllib.parse import quote
    wa = f"https://wa.me/91{CONTACT_PHONE}?text=" + quote(tr("wa_msg"))
    return (f'<div class="fvf-head"><div class="fvf-brandrow">{LOGO_SVG}<div class="fvf-brand">Fair Value Finder</div></div>'
            f'<p class="fvf-tag">{_esc(tr("tagline"))}</p>'
            f'<div class="fvf-contact"><p><b>{_esc(tr("contact_line"))}.</b> {_esc(tr("contact_call", p=CONTACT_DISPLAY))}</p>'
            f'<div class="fvf-links"><a class="gold" href="tel:+91{CONTACT_PHONE}">{_esc(tr("btn_call"))}</a>'
            f'<a class="ghost" href="{wa}" target="_blank" rel="noopener">{_esc(tr("btn_wa"))}</a></div></div></div>')


def grades_html(card):
    cells = "".join(
        f'<div class="fvf-grade" style="--c:{GRADE_COLOR[g["grade"]]}"><b>{g["grade"]}</b>'
        f'<span>{_esc(tr("cat_" + g["name"]))}<em>{tr("no_data") if g["score"] is None else str(g["score"]) + " / 100"}</em></span></div>'
        for g in card["categories"])
    return f'<div class="fvf-grades">{cells}</div>'


def _base_layout(fig, height):
    fig.update_layout(height=height, margin=dict(l=20, r=20, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(family=FONT + ", Noto Sans Tamil", color="#1D3B34", size=13))
    return fig


def gauge_fig(r):
    """Speedometer: where today's price sits against the margin-of-safety price and fair value."""
    import plotly.graph_objects as go
    price, fair, bb = r["price"], r["fair"], r["buy_below"]
    lo = max(0.0, min(fair * 0.5, price * 0.9))
    hi = max(fair * 1.5, price * 1.1)
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta", value=price,
        number=dict(prefix="₹", valueformat=",.0f", font=dict(size=28, family="Bricolage Grotesque, " + FONT, color=INK)),
        delta=dict(reference=fair, relative=True, valueformat="+.0%", suffix=tr("g_vs"),
                   increasing=dict(color=TONE["bad"]), decreasing=dict(color=TONE["good"])),
        gauge=dict(
            axis=dict(range=[lo, hi], tickprefix="₹", tickformat=",.0f", tickcolor=MUTED, nticks=4,
                      tickfont=dict(size=11, color=MUTED)),
            bar=dict(color=INK, thickness=0.22),
            bgcolor=CARD, borderwidth=0,
            steps=[dict(range=[lo, bb], color="#D7EBDF"),
                   dict(range=[bb, fair], color="#F5E6C8"),
                   dict(range=[fair, hi], color="#F4D5D2")],
            threshold=dict(line=dict(color=INK, width=3), thickness=0.85, value=fair),
        ),
    ))
    fig = _base_layout(fig, 250)
    fig.update_layout(margin=dict(l=34, r=34, t=36, b=6))
    return fig


def radar_fig(cards, names=None):
    """Report-card radar. `cards` is one card or a list of cards (compare view overlays two)."""
    import plotly.graph_objects as go
    cards = cards if isinstance(cards, list) else [cards]
    keep = [i for i in range(5) if all(c["categories"][i]["score"] is not None for c in cards)]
    if len(keep) < 3:
        return None
    theta = [tr("cat_" + cards[0]["categories"][i]["name"]) for i in keep]
    theta += theta[:1]
    styles = [(EMERALD, "rgba(15,122,92,0.16)"), (GOLD, "rgba(201,154,62,0.18)")]
    fig = go.Figure()
    for j, c in enumerate(cards):
        vals = [c["categories"][i]["score"] for i in keep]
        line, fill = styles[j % 2]
        fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=theta, fill="toself", fillcolor=fill,
                                      name=(names[j] if names else ""), line=dict(color=line, width=2),
                                      hovertemplate="%{theta}: %{r}/100<extra></extra>"))
    fig.update_layout(polar=dict(bgcolor="rgba(0,0,0,0)",
                                 radialaxis=dict(range=[0, 100], tickvals=[25, 50, 75, 100], showticklabels=False,
                                                 gridcolor=LINE, linecolor=LINE),
                                 angularaxis=dict(gridcolor=LINE, linecolor=LINE, tickfont=dict(size=12))),
                      showlegend=bool(names), legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"))
    fig = _base_layout(fig, 300 if names else 280)
    fig.update_layout(margin=dict(l=70, r=70, t=30, b=40 if names else 30))
    return fig


def candle_fig(ohlc, fair=None, buy_below=None, months=12):
    """Candlestick with 200-day average, today's fair value line and the shaded deep-value zone."""
    import pandas as pd
    import plotly.graph_objects as go
    df = pd.DataFrame(ohlc, columns=["Date", "Open", "High", "Low", "Close"])
    df["Date"] = pd.to_datetime(df["Date"])
    df["DMA200"] = df["Close"].rolling(200).mean()           # computed on full history, then sliced
    df = df[df["Date"] >= df["Date"].iloc[-1] - pd.DateOffset(months=months)]
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df["Date"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
                                 name=tr("m_price"), increasing=dict(line=dict(color=TONE["good"]), fillcolor=TONE["good"]),
                                 decreasing=dict(line=dict(color=TONE["bad"]), fillcolor=TONE["bad"])))
    fig.add_trace(go.Scatter(x=df["Date"], y=df["DMA200"], name=tr("lbl_dma"), mode="lines",
                             line=dict(color=MUTED, width=1.5, dash="dot")))
    if fair and buy_below:
        floor = min(float(df["Low"].min()), buy_below) * 0.95
        fig.add_hrect(y0=floor, y1=buy_below, fillcolor=TONE["good"], opacity=0.08, line_width=0,
                      annotation_text=tr("lbl_zone"), annotation_position="bottom left",
                      annotation_font=dict(color=TONE["good"], size=12))
        fig.add_hline(y=fair, line=dict(color=INK, width=2, dash="dash"),
                      annotation_text=tr("lbl_fair", x=f"{fair:,.0f}"), annotation_position="top left",
                      annotation_font=dict(color=INK, size=12))
        fig.add_hline(y=buy_below, line=dict(color=TONE["good"], width=1.5))
    ys = list(df["Low"]) + list(df["High"]) + ([fair, buy_below] if fair else [])
    pad = (max(ys) - min(ys)) * 0.08
    fig.update_layout(
        xaxis=dict(rangeslider=dict(visible=False), rangebreaks=[dict(bounds=["sat", "mon"])], gridcolor=LINE),
        yaxis=dict(range=[min(ys) - pad, max(ys) + pad], tickprefix="₹", tickformat=",.0f", gridcolor=LINE),
        legend=dict(orientation="h", y=-0.12, x=0), hovermode="x unified",
    )
    return _base_layout(fig, 460)


def heatmap_fig(rows):
    """NIFTY 50 treemap: sector > stock, box size = market cap, colour = % upside to fair value."""
    import plotly.graph_objects as go
    caps = sorted(x["mcap"] for x in rows if x.get("mcap"))
    med_cap = caps[len(caps) // 2] if caps else 1.0
    ids, labels, parents, values, colors, texts, hovers = [], [], [], [], [], [], []
    sectors = sorted({x["sector"] or "Other" for x in rows})
    for sname in sectors:
        members = [x for x in rows if (x["sector"] or "Other") == sname]
        tot = sum(x.get("mcap") or med_cap for x in members)
        ups = [(x["up"], x.get("mcap") or med_cap) for x in members if x["up"] is not None]
        wavg = sum(u * w for u, w in ups) / sum(w for _, w in ups) if ups else 0.0
        ids.append("s:" + sname); labels.append(sname); parents.append(""); values.append(tot)
        colors.append(clip(wavg, -50, 50)); texts.append(""); hovers.append(sname)
    for x in rows:
        up = x["up"]
        upt = tr("no_fair_short") if up is None else (tr("below_fair", d=f"{up:.0f}") if up >= 0
                                                      else tr("above_fair", d=f"{-up:.0f}"))
        ids.append(x["symbol"]); labels.append(x["symbol"]); parents.append("s:" + (x["sector"] or "Other"))
        values.append(x.get("mcap") or med_cap); colors.append(0.0 if up is None else clip(up, -50, 50))
        texts.append(upt); hovers.append(f"{x['name']}<br>{tr('v_' + x['code'])}<br>{upt}")
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
        text=texts, customdata=hovers, texttemplate="<b>%{label}</b><br>%{text}",
        hovertemplate="%{customdata}<extra></extra>",
        marker=dict(colors=colors, cmin=-50, cmax=50, cmid=0, line=dict(color=CARD, width=2),
                    colorscale=[[0, "#C2524A"], [0.4, "#F2D3CD"], [0.5, "#F6F1E6"], [0.6, "#CFE8DA"], [1, "#2E8A63"]]),
        tiling=dict(pad=2), pathbar=dict(visible=False),
    ))
    fig = _base_layout(fig, 560)
    fig.update_layout(margin=dict(l=4, r=4, t=4, b=4))
    return fig


def top5_html(row):
    up = row["up"]
    return (f'<div class="fvf-pick"><div class="fvf-pick-sym">{_esc(row["symbol"])}</div>'
            f'<div class="fvf-pick-name">{_esc(row["name"])}</div>'
            f'<div class="fvf-pick-up">{_esc(tr("below_fair", d=f"{up:.0f}"))}</div>'
            f'<div class="fvf-pick-px">₹{row["price"]:,.0f} → ₹{row["fair"]:,.0f}</div>'
            f'<div class="fvf-pick-grade" style="--c:{GRADE_COLOR[row["grade"]]}">{_esc(tr("h_card"))}: <b>{row["grade"]}</b></div></div>')


def compare_html(items):
    """items: list of two (d, r, card). Returns an HTML table with the stronger figure in each row in green."""
    def num(v, f):
        return "-" if v is None else f(v)
    rows = []

    def add(label, vals, fmt, better=None):
        cells = [num(v, fmt) for v in vals]
        win = None
        if better and all(v is not None for v in vals) and vals[0] != vals[1]:
            win = (0 if vals[0] > vals[1] else 1) if better == "high" else (0 if vals[0] < vals[1] else 1)
        tds = "".join(f'<td class="{"win" if i == win else ""}">{c}</td>' for i, c in enumerate(cells))
        rows.append(f"<tr><th>{_esc(label)}</th>{tds}</tr>")

    ups = [((r["fair"] / r["price"] - 1) * 100) if (r["fair"] and r["price"]) else None for _, r, _ in items]
    verdict_cells = "".join(f'<td><span class="fvf-chip" style="--c:{TONE[r["tone"]]}">{_esc(tr("v_" + r["code"]))}</span></td>'
                            for _, r, _ in items)
    rows.append(f"<tr><th>{_esc(tr('col_verdict'))}</th>{verdict_cells}</tr>")
    add(tr("m_price"), [r["price"] for _, r, _ in items], lambda v: f"₹{v:,.0f}")
    add(tr("m_fair"), [r["fair"] for _, r, _ in items], lambda v: f"₹{v:,.0f}")
    add(tr("m_upside"), ups, lambda v: f"{v:+.1f}%", "high")
    add(tr("h_card"), [c["overall"] for _, _, c in items], lambda v: f"{grade(v)} ({v}/100)", "high")
    for i in range(5):
        add(tr("cat_" + items[0][2]["categories"][i]["name"]), [c["categories"][i]["score"] for _, _, c in items],
            lambda v: f"{grade(v)} ({v})", "high")
    add("P/E", [d.get("pe") for d, _, _ in items], lambda v: f"{v:.1f}", "low")
    add("ROE", [r["roe"] for _, r, _ in items], lambda v: f"{v:.1f}%", "high")
    add(tr("cmp_rev_g"), [r["rev_c"] for _, r, _ in items], lambda v: f"{v:.1f}%", "high")
    add(tr("k_de"), [d.get("de") for d, _, _ in items], lambda v: f"{v:.2f}", "low")
    add(tr("k_div"), [d.get("div_yield") for d, _, _ in items], lambda v: f"{v:.1f}%", "high")
    head = "".join(f"<th>{_esc(d['symbol'].split('.')[0])}<small>{_esc(d['name'])}</small></th>" for d, _, _ in items)
    return (f'<div class="fvf-cmp-wrap"><table class="fvf-cmp"><thead><tr><th>{_esc(tr("cmp_metric"))}</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


PLOTLY_CFG = {"displayModeBar": False, "responsive": True}

SITE_URL = "fair-value-finder.streamlit.app"
CONTACT_PHONE = "8610025411"                       # shown on the site and on every share picture
CONTACT_DISPLAY = "86100 25411"
CONTACT_LINE = "Learn stock market trading and options buying"


# ----------------------------------------------------------------------------
# Share card: a 1080x1350 PNG for WhatsApp / Instagram (drawn with Pillow)
# ----------------------------------------------------------------------------

def _font(kind, size, weight=400):
    import os
    from PIL import ImageFont
    here = os.path.dirname(os.path.abspath(__file__))
    fname = {"display": "BricolageGrotesque.ttf", "tamil": "NotoSansTamil.ttf"}.get(kind, "SourceSans3.ttf")
    path = os.path.join(here, "fonts", fname)
    try:
        f = ImageFont.truetype(path, size)
        # axes: Bricolage = (opsz, wght, wdth); Noto Sans Tamil = (wght, wdth); Source Sans 3 = (wght,)
        if kind == "display":
            f.set_variation_by_axes([min(96, max(12, size)), weight, 100])
        elif kind == "tamil":
            f.set_variation_by_axes([min(900, weight), 100])
        else:
            f.set_variation_by_axes([weight])
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


CARD_THEME = dict(bg="#EFE8D8", card="#FFFDF8", line="#E6DDCA", gold="#B8862F", brand="#0F7A5C", text="#1D3B34",
                  muted="#6B746F", good="#1F7A4D", warn="#A86400", bad="#B42318",
                  arc_good="#8DCBA8", arc_warn="#EBCB82", arc_bad="#E9A69C")


def _scale_mark(dr, cx, cy, s, col):
    """Small balance-scale logo: post, beam and two pans."""
    w = max(2, s // 7)
    dr.line((cx, cy - s, cx, cy + s * 0.8), fill=col, width=w)
    dr.line((cx - s, cy - s * 0.6, cx + s, cy - s * 0.6), fill=col, width=w)
    dr.line((cx - s * 0.5, cy + s * 0.8, cx + s * 0.5, cy + s * 0.8), fill=col, width=w)
    for px in (cx - s, cx + s):
        dr.line((px, cy - s * 0.6, px - s * 0.35, cy + s * 0.15), fill=col, width=max(1, w - 1))
        dr.line((px, cy - s * 0.6, px + s * 0.35, cy + s * 0.15), fill=col, width=max(1, w - 1))
        dr.chord((px - s * 0.42, cy - s * 0.15, px + s * 0.42, cy + s * 0.45), 0, 180, fill=col)


def share_card_png(d: dict, r: dict, card: dict, today: str | None = None, lang: str = "en") -> bytes:
    import datetime
    import io
    import math as m
    from PIL import Image, ImageDraw

    C = CARD_THEME
    ta = lang == "ta"
    TB, TD = ("tamil", "tamil") if ta else ("body", "display")      # fonts for translated words
    W, H, PAD = 1080, 1350, 84
    img = Image.new("RGBA", (W, H), _hex(C["bg"]))
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle((40, 40, W - 40, H - 40), radius=34, fill=_hex(C["card"]), outline=_hex(C["gold"], 170), width=3)
    white, muted, gold = _hex(C["text"]), _hex(C["muted"]), _hex(C["gold"])
    tones = {"good": _hex(C["good"]), "warn": _hex(C["warn"]), "bad": _hex(C["bad"])}
    grade_tone = {"A": "good", "B": "good", "C": "warn", "D": "bad", "F": "bad"}

    # Header: logo mark + brand, date on the right
    if not today:
        try:
            from zoneinfo import ZoneInfo
            today = datetime.datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y")
        except Exception:
            today = datetime.date.today().strftime("%d %b %Y")
    _scale_mark(dr, PAD + 22, 108, 22, gold)
    dr.text((PAD + 64, 88), "Fair Value Finder", font=_font("display", 34, 700), fill=_hex(C["brand"]))
    fd = _font("body", 28, 400)
    dr.text((W - PAD - dr.textlength(today, font=fd), 94), today, font=fd, fill=muted)
    dr.line((PAD, 152, W - PAD, 152), fill=_hex(C["line"]), width=2)

    # Company name (up to two lines) + symbol and sector
    y = 180
    fname = _font("display", 62, 700)
    for line in _wrap(dr, d["name"], fname, W - 2 * PAD):
        dr.text((PAD, y), line, font=fname, fill=white)
        y += 70
    sub = "  |  ".join(x for x in (d["symbol"].replace(".NS", "").replace(".BO", ""), d.get("sector")) if x)
    dr.text((PAD, y + 4), sub, font=_font("body", 30, 600), fill=muted)
    top = y + 60                                       # first free pixel row below the header block

    price, fair, bb = r["price"], r["fair"], r["buy_below"]
    tone = tones[r["tone"]]
    has_gauge = bool(price and fair)

    # Build the stamp first so its height is known before laying out the page
    fs = _font(TD, 42 if ta else 46, 800)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    verdict = "\n".join(_wrap(tmp, tr("v_" + r["code"], lang), fs, 560))
    bbox = tmp.multiline_textbbox((0, 0), verdict, font=fs, align="center", spacing=6)
    sw, sh = int(bbox[2] - bbox[0]) + 76, int(bbox[3] - bbox[1]) + 52
    stamp = Image.new("RGBA", (sw + 20, sh + 20), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rounded_rectangle((10, 10, sw + 10, sh + 10), radius=18, outline=tone, width=7, fill=tone[:3] + (18,))
    sd.rounded_rectangle((22, 22, sw - 2, sh - 2), radius=12, outline=tone, width=3)
    sd.multiline_text(((sw + 20) / 2, (sh + 20) / 2), verdict, font=fs, fill=tone, anchor="mm", align="center", spacing=6)
    stamp = stamp.rotate(6, resample=Image.BICUBIC, expand=True)

    # Vertical budget: label gap + gauge + price block + stamp + stats must fit above the footer
    fy = H - 40 - 182                                  # footer rule (contact band + site + disclaimer)
    R, thick = 250, 44
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
        dr.arc((cx - R - 10, cy - R - 10, cx + R + 10, cy + R + 10), 180, 360, fill=_hex(C["line"]), width=2)
        for a0, a1, col in ((lo, bb, C["arc_good"]), (bb, fair, C["arc_warn"]), (fair, hi, C["arc_bad"])):
            if a1 > a0:
                dr.arc(box, ang(a0), ang(a1), fill=_hex(col), width=thick)
        # fair value tick + label just outside the arc
        t = m.radians(ang(fair))
        dr.line((cx + (R - thick - 12) * m.cos(t), cy + (R - thick - 12) * m.sin(t),
                 cx + (R + 16) * m.cos(t), cy + (R + 16) * m.sin(t)), fill=gold, width=6)
        lx, ly = cx + (R + 30) * m.cos(t), cy + (R + 30) * m.sin(t)
        dr.text((lx, ly), tr("lbl_fair", lang, x=f"{fair:,.0f}"), font=_font(TB, 24 if ta else 26, 600), fill=gold,
                anchor="md" if abs(m.cos(t)) < 0.35 else ("rd" if m.cos(t) < 0 else "ld"))
        # needle with a gold hub
        n = m.radians(ang(price))
        dr.line((cx, cy, cx + (R - thick - 26) * m.cos(n), cy + (R - thick - 26) * m.sin(n)), fill=white, width=10)
        dr.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill=gold)
        dr.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=_hex(C["card"]))
        fz = _font(TB, 24 if ta else 26, 600)
        dr.text((cx - R - 16, cy - 6), tr("card_cheap", lang), font=fz, fill=tones["good"], anchor="rd")
        dr.text((cx + R + 16, cy - 6), tr("card_costly", lang), font=fz, fill=tones["bad"], anchor="ld")
        y = cy + 24
    # price + % vs fair value
    dr.text((cx, y), f"₹{price:,.0f}" if price else "-", font=_font("display", 76, 700), fill=white, anchor="ma")
    if has_gauge:
        diff = (price / fair - 1) * 100
        dtxt = tr("above_fair" if diff > 0 else "below_fair", lang, d=f"{abs(diff):.0f}")
        dcol = tones["bad"] if diff > 0 else tones["good"]
    else:
        dtxt, dcol = tr("card_nofair", lang), muted
    dr.text((cx, y + 92), dtxt, font=_fit(dr, dtxt, TB, 600, W - 2 * PAD, 30 if ta else 34), fill=dcol, anchor="ma")
    y += price_block + 22

    # Verdict stamp
    img.alpha_composite(stamp, (int(cx - stamp.width / 2), int(y)))
    y += stamp.height + 22

    # Stats row: fair value | buy below | report card
    og = card["overall_grade"]
    cols = [(tr("m_fair", lang), "-" if not fair else f"₹{fair:,.0f}", white),
            (tr("card_safety", lang), "-" if not bb else f"₹{bb:,.0f}", tones["good"]),
            (tr("h_card", lang), og + ("" if card["overall"] is None else f"  {card['overall']}/100"),
             tones[grade_tone[og]] if og in grade_tone else muted)]
    cw = (W - 2 * PAD) / 3
    for i, (lab, val, col) in enumerate(cols):
        x = PAD + cw * i + cw / 2
        dr.text((x, y), lab, font=_fit(dr, lab, TB, 400, cw - 16, 26 if ta else 28, 18), fill=muted, anchor="ma")
        dr.text((x, y + 40), val, font=_fit(dr, val, "display", 700, cw - 24, 48), fill=col, anchor="ma")
        if i:
            dr.line((PAD + cw * i, y + 4, PAD + cw * i, y + 92), fill=_hex(C["line"]), width=2)

    # Footer: gold contact band, site link, disclaimer
    dr.line((PAD, fy, W - PAD, fy), fill=_hex(C["line"]), width=2)
    dr.rounded_rectangle((PAD, fy + 20, W - PAD, fy + 92), radius=16, fill=_hex(C["brand"]))
    ctext = tr("card_contact", lang, p=CONTACT_DISPLAY)
    dr.text((W / 2, fy + 56), ctext, font=_fit(dr, ctext, TB, 700, W - 2 * PAD - 40, 32, 18),
            fill=(255, 255, 255, 255), anchor="mm")
    stext = tr("card_site", lang, u=SITE_URL)
    dr.text((W / 2, fy + 106), stext, font=_fit(dr, stext, TB, 600, W - 2 * PAD, 29, 18),
            fill=white, anchor="ma")
    dr.text((W / 2, fy + 146), tr("card_disc", lang), font=_font(TB, 22 if ta else 24, 400),
            fill=muted, anchor="ma")

    out = io.BytesIO()
    img.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


# ----------------------------------------------------------------------------
# Streamlit web app
# ----------------------------------------------------------------------------

NIFTY50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BSE", "BAJAJ-AUTO", "BAJFINANCE",
    "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM",
    "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC", "INFY", "INDIGO",
    "JSWSTEEL", "JIOFIN", "KOTAKBANK", "LT", "M&M", "MARUTI", "MAXHEALTH", "NTPC", "NESTLEIND", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN", "SUNPHARMA", "TCS", "TATACONSUM", "TMPV",
    "TATASTEEL", "TECHM", "TITAN", "TRENT", "ULTRACEMCO",
]
# NIFTY 50 constituents from NSE's official list (nsearchives.nseindia.com ind_nifty50list.csv, Oct 2026)

# Scan results shared by every visitor on this server for an hour, keyed by the valuation settings.
SCAN_CACHE: dict = {}
SCAN_TTL = 3600


def scan_nifty(cached_fetch, discount, terminal, mos, progress=None, force=False):
    """Run all NIFTY 50 stocks through analyse(). Returns (rows, failed, timestamp)."""
    import time
    key = (discount, terminal, mos)
    hit = SCAN_CACHE.get(key)
    if hit and not force and time.time() - hit[2] < SCAN_TTL and not hit[1]:
        return hit
    rows, failed = [], []
    for i, s in enumerate(NIFTY50):
        if progress:
            progress(i, s)
        try:
            d = cached_fetch(s)
        except Exception:
            failed.append(s)
            continue
        r = analyse(d, discount, terminal, mos)
        card = report_card(r, d)
        rows.append(dict(symbol=s, name=d["name"], sector=d.get("sector") or "", code=r["code"], tone=r["tone"],
                         price=r["price"], fair=r["fair"], bb=r["buy_below"], quality=r["quality"],
                         up=((r["fair"] / r["price"] - 1) * 100) if (r["fair"] and r["price"]) else None,
                         from_high=((r["price"] / d["hi52"] - 1) * 100) if (d.get("hi52") and r["price"]) else None,
                         mcap=d.get("mcap"), grade=card["overall_grade"]))
    out = (rows, failed, time.time())
    if rows:
        SCAN_CACHE[key] = out
    return out


def cached_scan(discount, terminal, mos):
    import time
    hit = SCAN_CACHE.get((discount, terminal, mos))
    return hit if (hit and time.time() - hit[2] < SCAN_TTL) else None


def app():
    import time
    import pandas as pd
    import streamlit as st

    st.set_page_config(page_title="Fair Value Finder", page_icon="⚖️", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    # Language switch (top right, visible on phones too, where the sidebar is hidden)
    _, lang_col = st.columns([3, 1.2])
    choice = lang_col.radio("Language / மொழி", ["English", "தமிழ்"], horizontal=True, key="lang_choice",
                            label_visibility="collapsed")
    st.session_state["lang_code"] = "ta" if choice == "தமிழ்" else "en"

    st.markdown(header_html(), unsafe_allow_html=True)

    with st.sidebar:
        st.header(tr("settings"))
        mos = st.slider(tr("mos"), 0, 40, 15)
        discount = st.slider(tr("disc"), 8.0, 18.0, 12.0, 0.5)
        terminal = st.slider(tr("term"), 2.0, 7.0, 5.0, 0.5)
        st.caption(tr("method_note"))
        with st.expander(tr("ov_title")):
            st.caption(tr("ov_note"))
            ov_eps = st.number_input(tr("ov_eps"), min_value=0.0, value=0.0, step=0.5)
            ov_bv = st.number_input(tr("ov_bv"), min_value=0.0, value=0.0, step=1.0)
            ov_roe = st.number_input(tr("ov_roe"), min_value=0.0, value=0.0, step=0.5)
            ov_g = st.number_input(tr("ov_g"), min_value=0.0, value=0.0, step=0.5)
    overrides = {"eps": ov_eps or None, "bvps": ov_bv or None, "roe": ov_roe or None, "growth": ov_g or None}

    @st.cache_data(ttl=3600, show_spinner=False)
    def cached_fetch(s):
        time.sleep(0.3)  # gentle on Yahoo; only runs when the result is not already cached
        return fetch(s)

    tab_single, tab_cmp, tab_scan = st.tabs([tr("tab_single"), tr("tab_compare"), tr("tab_scan")])
    with tab_single:
        single_view(st, pd, cached_fetch, discount, terminal, mos, overrides)
    with tab_cmp:
        compare_view(st, cached_fetch, discount, terminal, mos)
    with tab_scan:
        scanner_view(st, pd, cached_fetch, discount, terminal, mos)


def _open_symbol(sym):
    import streamlit as st
    st.session_state["sym_input"] = sym


def _run_scan_with_bar(st, cached_fetch, discount, terminal, mos, force=False):
    bar = st.progress(0.0, text=tr("scan_start"))
    n = len(NIFTY50)
    res = scan_nifty(cached_fetch, discount, terminal, mos, force=force,
                     progress=lambda i, s: bar.progress(i / n, text=tr("scan_progress", s=s, i=i + 1, n=n)))
    bar.empty()
    return res


def home_top5(st, cached_fetch, discount, terminal, mos):
    with st.container(border=True, key="fvf-panel-top5"):
        st.markdown(f"#### {tr('h_top5')}")
        st.caption(tr("top5_note"))
        res = cached_scan(discount, terminal, mos)
        if res is None:
            st.caption(tr("top5_wait"))
            if not st.button(tr("btn_top5"), key="top5_btn"):
                return
            res = _run_scan_with_bar(st, cached_fetch, discount, terminal, mos)
        rows = [x for x in res[0] if x["code"] in ("deep", "near") and x["up"] is not None]
        rows.sort(key=lambda x: x["up"], reverse=True)
        if not res[0]:
            st.error(tr("scan_none"))
            return
        if not rows:
            st.info(tr("top5_none"))
            return
        cols = st.columns(min(5, len(rows)))
        for col, row in zip(cols, rows[:5]):
            with col:
                st.markdown(top5_html(row), unsafe_allow_html=True)
                st.button(tr("open_x", s=row["symbol"]), key=f"open_{row['symbol']}", on_click=_open_symbol,
                          args=(row["symbol"],), width="stretch")
        st.caption(tr("scan_disclaim"))


def scanner_view(st, pd, cached_fetch, discount, terminal, mos):
    st.markdown(f"#### {tr('h_scan')}")
    st.caption(tr("scan_note"))
    if st.button(tr("btn_scan"), type="primary", key="scan_btn"):
        st.session_state["scan_on"] = True
        st.session_state["scan_force"] = True
    res = cached_scan(discount, terminal, mos)
    if res is None and not st.session_state.get("scan_on"):
        st.info(tr("scan_press"))
        return
    force = st.session_state.pop("scan_force", False)
    if res is None or (force and res[1]):          # nothing cached yet, or retrying stocks that failed last time
        res = _run_scan_with_bar(st, cached_fetch, discount, terminal, mos, force=True)
    rows, failed, _ = res
    if not rows:
        st.error(tr("scan_none"))
        return

    counts = {}
    for x in rows:
        counts[x["code"]] = counts.get(x["code"], 0) + 1
    c = st.columns(4)
    for col, code in zip(c, ("deep", "near", "above", "weak")):
        col.metric(tr("c_" + code), counts.get(code, 0))

    with st.container(border=True, key="fvf-panel-heat"):
        st.markdown(f"#### {tr('h_heat')}")
        st.plotly_chart(heatmap_fig(rows), config=PLOTLY_CFG, width="stretch")
        st.caption(tr("heat_note"))

    present = [v for v in VERDICT_ORDER if v in {x["code"] for x in rows}]
    labels = [tr("v_" + v) for v in present]
    picked = st.multiselect(tr("show"), labels, default=labels)
    show = {present[labels.index(lbl)] for lbl in picked}
    view = [x for x in rows if x["code"] in show]
    view.sort(key=lambda x: (VERDICT_ORDER.index(x["code"]), -(x["up"] if x["up"] is not None else -1e9)))
    df = pd.DataFrame([{
        tr("col_symbol"): x["symbol"], tr("col_company"): x["name"], tr("col_verdict"): tr("v_" + x["code"]),
        tr("m_price"): x["price"], tr("m_fair"): x["fair"], tr("m_safety"): x["bb"], tr("col_upside"): x["up"],
        tr("col_quality"): x["quality"], tr("col_52"): x["from_high"], tr("col_sector"): x["sector"]} for x in view])
    money = st.column_config.NumberColumn(format="₹%.0f")
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        tr("m_price"): money, tr("m_fair"): money, tr("m_safety"): money,
        tr("col_upside"): st.column_config.NumberColumn(format="%+.1f%%"),
        tr("col_quality"): st.column_config.NumberColumn(format="%d%%"),
        tr("col_52"): st.column_config.NumberColumn(format="%+.1f%%"),
    })
    st.caption(tr("scan_sort"))
    if failed:
        st.warning(tr("scan_failed", n=len(failed), lst=", ".join(failed)))
    st.caption(tr("scan_disclaim"))


def compare_view(st, cached_fetch, discount, terminal, mos):
    st.markdown(f"#### {tr('h_compare')}")
    a_col, b_col = st.columns(2)
    a = a_col.text_input(tr("cmp_a"), placeholder="HDFCBANK", key="cmp_a").strip()
    b = b_col.text_input(tr("cmp_b"), placeholder="ICICIBANK", key="cmp_b").strip()
    if not (a and b):
        st.info(tr("cmp_hint"))
        return
    items = []
    for sym in (a, b):
        with st.spinner(tr("fetching", s=to_yahoo(sym))):
            try:
                d = cached_fetch(sym)
            except Exception as e:
                st.error(tr("load_err", s=sym, e=e))
                return
        r = analyse(d, discount, terminal, mos)
        items.append((d, r, report_card(r, d)))
    st.markdown(compare_html(items), unsafe_allow_html=True)
    st.caption(tr("cmp_note"))
    rf = radar_fig([c for _, _, c in items], names=[d["symbol"].split(".")[0] for d, _, _ in items])
    if rf is not None:
        with st.container(border=True, key="fvf-panel-cmp-radar"):
            st.markdown(f"#### {tr('h_card')}")
            st.plotly_chart(rf, config=PLOTLY_CFG, width="stretch")
    st.caption(tr("footer"))


def single_view(st, pd, cached_fetch, discount, terminal, mos, overrides):
    c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
    sym = c1.text_input(tr("sym_label"), placeholder=tr("sym_ph"), key="sym_input").strip()
    c2.button(tr("analyse"), width="stretch", type="primary")
    if not sym:
        st.info(tr("type_hint"))
        home_top5(st, cached_fetch, discount, terminal, mos)
        return

    with st.spinner(tr("fetching", s=to_yahoo(sym))):
        try:
            d = cached_fetch(sym)
        except Exception as e:
            st.error(tr("load_err", s=sym, e=e))
            return
    r = analyse(d, discount, terminal, mos, overrides)
    if any(overrides.values()):
        st.info(tr("using_ov"))

    st.markdown(hero_html(d, r), unsafe_allow_html=True)

    card = report_card(r, d)
    g_col, rc_col = st.columns([1, 1.25], gap="medium")
    with g_col:
        with st.container(border=True, key="fvf-panel-gauge"):
            st.markdown(f"#### {tr('h_gauge')}")
            if r["fair"] and r["price"]:
                st.plotly_chart(gauge_fig(r), config=PLOTLY_CFG, width="stretch")
                st.caption(tr("gauge_note"))
            else:
                st.info(tr("no_fair_meter"))
    with rc_col:
        with st.container(border=True, key="fvf-panel-card"):
            st.markdown(f"#### {tr('h_card')}: **{card['overall_grade']}**"
                        + ("" if card["overall"] is None else f"  ({card['overall']}/100)"))
            st.markdown(grades_html(card), unsafe_allow_html=True)
            rf = radar_fig(card)
            if rf is not None:
                st.plotly_chart(rf, config=PLOTLY_CFG, width="stretch")
            st.caption(tr("card_note"))

    with st.container(border=True, key="fvf-panel-share"):
        s_text, s_btn = st.columns([2.2, 1.2], vertical_alignment="center")
        s_text.markdown(f"#### {tr('h_share')}\n{tr('share_note')}")
        try:
            lang = cur_lang()
            png = share_card_png(d, r, card, lang=lang)
            fname = d["symbol"].split(".")[0].replace("&", "and") + ("-fair-value-ta.png" if lang == "ta" else "-fair-value.png")
            s_btn.download_button(tr("btn_download"), png, file_name=fname, mime="image/png",
                                  type="primary", width="stretch", key="fvf-share-btn")
            with st.expander(tr("preview")):
                st.image(png, width=420)
        except Exception as e:
            s_btn.caption(tr("share_err", e=e))

    m = st.columns(3)
    m[0].metric(tr("m_price"), rs(r["price"]))
    m[1].metric(tr("m_fair"), rs(r["fair"]))
    m[2].metric(tr("m_safety"), rs(r["buy_below"]))
    m2 = st.columns(2)
    up = (r["fair"] / r["price"] - 1) * 100 if r["fair"] and r["price"] else None
    m2[0].metric(tr("m_upside"), pct(up, True))
    if d.get("hi52") and d.get("lo52") and r["price"]:
        m2[1].metric(tr("m_52"), f"₹{d['lo52']:,.0f} / ₹{d['hi52']:,.0f}",
                     tr("m_from_high", x=f"{(r['price'] / d['hi52'] - 1) * 100:.1f}"), delta_color="off")

    tab1, tab2, tab3, tab4 = st.tabs([tr("t_details"), tr("t_chart"), tr("t_future"), tr("t_fin")])

    with tab1:
        left, right = st.columns(2)
        with left:
            st.markdown(f"#### {tr('h_checks')}" + (tr("for_banks") if r["lender"] else ""))

            def val(c):
                v = fmt_check(c)
                return tr("yes") if v == "Yes" else tr("no") if v == "No" else v
            st.dataframe(pd.DataFrame([{
                tr("col_check"): term(c["check"]), tr("col_value"): val(c), tr("col_good"): term(c["rule"]),
                tr("col_result"): tr("no_data") if c["ok"] is None else (tr("pass") if c["ok"] else tr("fail"))}
                for c in r["checks"]]), hide_index=True, width="stretch")
            if r.get("roe_calc"):
                st.caption(tr("roe_calc_note"))
        with right:
            st.markdown(f"#### {tr('h_methods')}")
            for n, v, how in r["methods"]:
                st.markdown(f"**{term(n)}: {rs(v) if v else '-'}**  \n<small>{_esc(how)}</small>", unsafe_allow_html=True)
            st.caption(tr("methods_note"))

    with tab2:
        prices = d.get("prices") or []
        ohlc = d.get("ohlc") or []
        spans = [6, 12, 36, 60]
        if ohlc:
            opts = [tr(f"p{k}") for k in spans]
            span = spans[opts.index(st.radio(tr("period"), opts, horizontal=True, index=1))]
            st.plotly_chart(candle_fig(ohlc, r["fair"], r["buy_below"], span), config=PLOTLY_CFG, width="stretch")
            st.caption(tr("chart_note"))
        elif prices:
            opts = [tr("p12"), tr("p60")]
            span = [12, 60][opts.index(st.radio(tr("period"), opts, horizontal=True, index=0))]
            pts = prices[-252:] if span == 12 else prices
            df = pd.DataFrame(pts, columns=["Date", tr("m_price")]).set_index("Date")
            if r["fair"]:
                df[tr("m_fair")] = r["fair"]
                df[tr("m_safety")] = r["buy_below"]
            st.line_chart(df)
        else:
            st.warning(tr("no_hist"))

    with tab3:
        rows = project(r)
        if rows:
            g_txt = f"{r['g_used']:.1f}"
            st.markdown(f"#### {tr('h_future', g=g_txt)}")
            st.caption(tr("future_note", src=term(r["g_src"])))
            st.dataframe(pd.DataFrame([{
                tr("col_in"): tr("yr1" if row["years"] == 1 else "yrs", n=row["years"]),
                tr("bear"): rs(row["Bear"]), tr("base"): rs(row["Base"]), tr("bull"): rs(row["Bull"]),
                tr("base_ret"): pct(row["Base CAGR"], True)} for row in rows]),
                hide_index=True, width="stretch")
        else:
            st.warning(tr("no_project"))
        st.markdown(f"#### {tr('h_analysts')}")
        if d.get("target_mean"):
            a = st.columns(4)
            a[0].metric(tr("a_low"), rs(d.get("target_low")))
            a[1].metric(tr("a_avg"), rs(d.get("target_mean")),
                        pct((d["target_mean"] / r["price"] - 1) * 100, True) if r["price"] else None)
            a[2].metric(tr("a_high"), rs(d.get("target_high")))
            a[3].metric(tr("a_n"), "-" if not d.get("n_analysts") else f"{int(d['n_analysts'])}",
                        (d.get("rec") or "").replace("_", " ").title() or None, delta_color="off")
            st.caption(tr("a_note"))
        else:
            st.caption(tr("a_none"))
        st.caption(tr("proj_note"))

    with tab4:
        H = d["hist"]
        n = min(len(H["years"]), len(H["revenue"]), len(H["net_income"]))
        if n:
            st.markdown(f"#### {tr('h_fin')}")
            chart = pd.DataFrame({tr("rev"): [v / 1e7 for v in H["revenue"][-n:]],
                                  tr("np"): [v / 1e7 for v in H["net_income"][-n:]]},
                                 index=[f"FY{y[-2:]}" for y in H["years"][-n:]])
            st.bar_chart(chart, stack=False)
            st.caption(tr("fin_note", n=n, k=n - 1))
        k = st.columns(4)
        k[0].metric(tr("k_mcap"), crore(d["mcap"]))
        k[1].metric(tr("k_pe"), ("-" if d["pe"] is None else f"{d['pe']:.1f}")
                    + (f" / {r['hist_pe']:.1f}" if r.get("hist_pe") else ""))
        k[2].metric(tr("k_pb"), "-" if d["pb"] is None else f"{d['pb']:.2f}")
        k[3].metric(tr("k_roe"), pct(r["roe"]))
        k2 = st.columns(4)
        k2[0].metric(tr("k_div"), pct(d.get("div_yield")))
        k2[1].metric(tr("k_margin"), pct(d.get("net_margin")))
        k2[2].metric(tr("k_de"), "-" if d.get("de") is None else f"{d['de']:.2f}")
        k2[3].metric(tr("k_roa"), pct(d.get("roa")))

    if r["lender"]:
        st.warning(tr("bank_warn"))
    st.caption(tr("footer"))


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
