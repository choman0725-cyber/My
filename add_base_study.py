"""加碼金額基準：進場額度（現行）vs 當下總資產÷5 vs 當下部位市值。分別套在定期加碼、以及定期＋跌深加碼。"""
import pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

C = {
    "正式版（額度固定）": {},
    "定期加碼＝當下總資產÷5×20%": {"time_add_base": "assets"},
    "定期加碼＝當下部位市值×20%": {"time_add_base": "position"},
    "定期＋跌深加碼都＝當下總資產÷5×比例": {"time_add_base": "assets", "deep_add_base": "assets"},
    "定期＋跌深加碼都＝當下部位市值×比例": {"time_add_base": "position", "deep_add_base": "position"},
    "定期加碼＝當下部位市值×50%": {"time_add_base": "position", "time_add_amount": 0.50},
    "定期加碼＝當下總資產÷5×10%": {"time_add_base": "assets", "time_add_amount": 0.10},
}

def main():
    po.setup(); G = rs.G; dates = G["dates"]
    names = []
    for n, x in C.items():
        po.CONFIGS[n] = {**dr.FINAL, **x}; names.append(n)
    m = po.evaluate(names, "addbase")
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    print("【穩健度】"); print(m.loc[names][po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, 2027)}
    SCHED = {"不追加": {}, "每年50萬": {y: 500_000 for y in first_day}, "每年100萬": {y: 1_000_000 for y in first_day}}
    out = []
    for n in names:
        po.apply(po.CONFIGS[n]); kw = po.to_kw(po.CONFIGS[n])
        for sname, sched in SCHED.items():
            contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
            ledger = []
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, ledger=ledger, **kw)
            L = pd.DataFrame(ledger); adds = L[L["動作"] == "加碼"]; timeadds = adds[adds["說明"].str.startswith("定期")]
            flows = [CAPITAL] + list(sched.values()); fd = [dates[1]] + [dates[first_day[y]] for y in sched]; final = eq.iloc[-1] * CAPITAL
            rets = eq.pct_change()
            for k in (contrib or {}): rets.loc[dates[k]] = (eq.loc[dates[k]] - contrib[k]) / eq.shift(1).loc[dates[k]] - 1
            nav = (1 + rets.fillna(0)).cumprod(); cl = tr[tr["出場"].notna()]
            out.append(dict(版本=n, 追加=sname, 期末萬=round(final / 1e4), IRR=round(irr(flows, fd, final, dates[-1]), 1), 最大回撤=round(100 * (nav / nav.cummax() - 1).min(), 1),
                            勝率=round(100 * (cl["報酬%"] > 0).mean(), 1), 定期加碼次數=len(timeadds), 定期加碼總額萬=round(timeadds["金額"].sum() * CAPITAL / 1e4),
                            定期加碼平均萬=round(timeadds["金額"].mean() * CAPITAL / 1e4) if len(timeadds) else 0, 跌深加碼總額萬=round((adds["金額"].sum() - timeadds["金額"].sum()) * CAPITAL / 1e4)))
    M = pd.DataFrame(out); M.to_csv(RESULTS / "add_base_money.csv", index=False, encoding="utf-8-sig")
    print("\n【500 萬 2017 起】"); print(M.to_string(index=False))

if __name__ == "__main__":
    main()
