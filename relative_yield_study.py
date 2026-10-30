"""相對殖利率版：買進門檻改成「該股自己過去 N 年殖利率的中位數」，續抱門檻改成「中位數 − k × 標準差」。
中位數／標準差用滾動視窗、只用當天以前的資料（無前視）。對照正式版（固定 5% / 4.75%）。
用法：python relative_yield_study.py"""
import numpy as np, pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

WINDOWS = {"3年": 750, "5年": 1250}
_stats = {}

def stats(window):
    if window not in _stats:
        med, sd = {}, {}
        for sid, d in rs.G["sub"].items():
            y = pd.Series(d["yield"])
            r = y.rolling(window, min_periods=250)
            med[sid] = r.median().values; sd[sid] = r.std().values
        _stats[window] = (med, sd)
    return _stats[window]

_orig_apply = po.apply
def apply2(cfg):
    _orig_apply(cfg)
    rel = cfg.get("rel")
    if not rel:
        return
    window, buy_k, hold_k, floor = rel
    med, sd = stats(window)
    sig = rs.G["sig"]["任一"]
    for sid, d in rs.G["sub"].items():
        thr_buy = med[sid] + buy_k * sd[sid]
        thr_buy = np.fmax(thr_buy, floor) if floor else thr_buy
        y = np.nan_to_num(d["yield"], nan=-1)
        d["buy"] = sig[sid] & ~np.isnan(thr_buy) & (y >= thr_buy)
        d["hy_rel"] = med[sid] - hold_k * sd[sid]
    po._applied["buy"] = None   # 買點陣列已被改寫，讓下一個固定門檻的設定重新計算
po.apply = apply2
_orig_to_kw = po.to_kw
def to_kw2(cfg):
    kw = _orig_to_kw({k: v for k, v in cfg.items() if k != "rel"})
    if cfg.get("rel"):
        kw["hold_yield"] = "hy_rel"
    return kw
po.to_kw = to_kw2

def main():
    po.setup(); G = rs.G; dates = G["dates"]
    C = {"正式版（固定 5% / 4.75%）": {}}
    for wn, w in WINDOWS.items():
        C[f"{wn}中位數買／中位數−0.08σ續抱"] = {"rel": (w, 0.0, 0.08, None)}
        C[f"{wn}中位數買／中位數−0.5σ續抱"] = {"rel": (w, 0.0, 0.5, None)}
        C[f"{wn}中位數買／中位數−1σ續抱"] = {"rel": (w, 0.0, 1.0, None)}
        C[f"{wn}中位數＋0.5σ買／中位數−0.08σ續抱"] = {"rel": (w, 0.5, 0.08, None)}
        C[f"{wn}中位數買(至少4%)／中位數−0.08σ續抱"] = {"rel": (w, 0.0, 0.08, 4.0)}
        C[f"{wn}中位數買(至少5%)／中位數−0.08σ續抱"] = {"rel": (w, 0.0, 0.08, 5.0)}
    names = []
    for n, x in C.items():
        po.CONFIGS[n] = {**dr.FINAL, "hold_yield": 4.75, **x}; names.append(n)
    m = po.evaluate(names, "relyield")
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    print("【穩健度】"); print(m.loc[names][po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    out = []
    for n in names:
        po.apply(po.CONFIGS[n]); kw = po.to_kw(po.CONFIGS[n])
        tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, **kw)
        cl = tr[tr["出場"].notna()]
        nbuy = sum(int(d["buy"].sum()) for d in G["sub"].values())
        out.append(dict(版本=n, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4), IRR=round(irr([CAPITAL], [dates[1]], eq.iloc[-1] * CAPITAL, dates[-1]), 1),
                        最大回撤=round(100 * (eq / eq.cummax() - 1).min(), 1), 筆數=len(tr), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1),
                        平均持有日=int(cl["持有日"].mean()) if len(cl) else 0, 全池買訊日數=nbuy, 期末現金pct=round(100 * eq.attrs["cash"] / eq.iloc[-1], 1)))
    M = pd.DataFrame(out); M.to_csv(RESULTS / "relative_yield_money.csv", index=False, encoding="utf-8-sig")
    print("\n【500 萬 2017 起不追加】"); print(M.to_string(index=False))
    # 門檻長什麼樣：幾檔代表股的 3 年中位數與標準差（最後一天）
    med, sd = stats(750); p = len(dates) - 1
    ex = pd.DataFrame([dict(代號=s, 目前殖利率=round(G["sub"][s]["yield"][p], 2), 三年中位=round(med[s][p], 2), 三年標準差=round(sd[s][p], 2),
                            續抱門檻_0p08σ=round(med[s][p] - 0.08 * sd[s][p], 2)) for s in ("2382", "2357", "2454", "2303", "3702", "2385", "2376")])
    print("\n【門檻示例（資料最後一天）】"); print(ex.to_string(index=False))

if __name__ == "__main__":
    main()
