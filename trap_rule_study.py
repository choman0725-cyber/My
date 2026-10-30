"""新邏輯：額外加碼與「不佔名額」都要先賠到 -30%（相對平均成本）。
  - 套牢定義：收盤低於平均成本 30% 以上；回到 -30% 以內就歸零重算（連續計時）。
  - 額外加碼：連續套牢每滿半年、出現加碼訊號且收盤低於平均成本，才加碼額度 20%。
  - 不佔名額：A 連續套牢滿半年才不佔；B 一跌到 -30% 就不佔；C 永遠佔名額（最多 5 檔）。
與現行正式版（持有>1年或虧>30% 不佔名額；每半年虧損就加碼）對照。"""
import pandas as pd
import daily_run as dr, param_opt as po, portfolio_study as ps, robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL

F = dr.FINAL
C = {
    "現行正式版": {},
    "新A：套牢滿半年才不佔名額＋滿半年才額外加碼": {"trap_days": 182, "time_add_trap": True},
    "新B：-30%立即不佔名額＋套牢滿半年才額外加碼": {"trap_days": 0, "time_add_trap": True},
    "新C：永遠佔名額(最多5檔)＋套牢滿半年才額外加碼": {"stale": False, "time_add_trap": True},
    "新D：只改加碼（名額維持現行）": {"time_add_trap": True},
    "新E：套牢滿半年才不佔名額＋取消額外加碼": {"trap_days": 182, "time_add_days": None},
    "新F：套牢滿半年才不佔名額＋滿半年加碼、之後每季一次": {"trap_days": 182, "time_add_trap": True, "time_add_days": 91},
    "首買價版A：跌破首買價-30%連續滿半年才不佔名額＋才額外加碼": {"trap_days": 182, "time_add_trap": True, "trap_ref": "first"},
    "首買價版B：跌破首買價-30%立即不佔名額＋滿半年才額外加碼": {"trap_days": 0, "time_add_trap": True, "trap_ref": "first"},
    "首買價版D：只改加碼（名額維持現行）": {"time_add_trap": True, "trap_ref": "first"},
}

def main():
    po.setup(); G = rs.G; dates = G["dates"]
    names = []
    for n, x in C.items():
        po.CONFIGS[n] = {**F, **x}; names.append(n)
    m = po.evaluate(names, "traprule")
    pd.set_option("display.width", 320); pd.set_option("display.unicode.east_asian_width", True)
    print("【穩健度】"); print(m.loc[names][po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string())
    first_day = {y: dates.get_indexer([dates[dates.year == y][0]])[0] for y in range(2018, 2027)}
    SCHED = {"不追加": {}, "每年50萬": {y: 500_000 for y in first_day}, "每年100萬": {y: 1_000_000 for y in first_day},
             "分段50/80/100萬": {**{y: 500_000 for y in (2018, 2019, 2020)}, **{y: 800_000 for y in (2021, 2022, 2023)}, **{y: 1_000_000 for y in (2024, 2025, 2026)}}}
    out = []
    for n in names:
        po.apply(po.CONFIGS[n]); kw = po.to_kw(po.CONFIGS[n])
        for sname, sched in SCHED.items():
            contrib = {first_day[y]: a / CAPITAL for y, a in sched.items()} or None
            tr, eq = ps.run(G["sub"], G["member"], dates, capital=CAPITAL, contributions=contrib, **kw)
            flows = [CAPITAL] + list(sched.values()); fd = [dates[1]] + [dates[first_day[y]] for y in sched]; final = eq.iloc[-1] * CAPITAL
            rets = eq.pct_change()
            for k in (contrib or {}): rets.loc[dates[k]] = (eq.loc[dates[k]] - contrib[k]) / eq.shift(1).loc[dates[k]] - 1
            nav = (1 + rets.fillna(0)).cumprod(); cl = tr[tr["出場"].notna()]
            held = tr.groupby("進場").size()
            out.append(dict(版本=n, 追加=sname, 期末萬=round(final / 1e4), IRR=round(irr(flows, fd, final, dates[-1]), 1), 最大回撤=round(100 * (nav / nav.cummax() - 1).min(), 1),
                            筆數=len(tr), 加碼次數=int(tr["加碼"].sum()), 勝率=round(100 * (cl["報酬%"] > 0).mean(), 1), 最多同時持股=int(eq.attrs.get("max_pos", 0)) if "max_pos" in eq.attrs else "",
                            期末持股=len(eq.attrs["positions"]), 期末現金pct=round(100 * eq.attrs["cash"] / eq.iloc[-1], 1)))
    M = pd.DataFrame(out); M.to_csv(RESULTS / "trap_rule_money.csv", index=False, encoding="utf-8-sig")
    print("\n【500 萬 2017 起】"); print(M.drop(columns=["最多同時持股"]).to_string(index=False))

if __name__ == "__main__":
    main()
