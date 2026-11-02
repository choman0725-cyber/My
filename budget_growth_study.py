"""額度隨資產成長、伺機補足（2026-11-01 使用者選的選項）。額度＝可投資資產 ÷ 5，可投資資產＝現金＋未套牢持股（虧 30% 以上不計）。
健康度＝可投資資產 ÷ 總資產，低於門檻時不做任何補足動作，等帳戶恢復。
  O1 棘輪（對照）：跌深／定期加碼基準改 max(進場額度, 當天可投資資產 ÷ 5)
  O2 買點再現補足：持股再次符合完整買進條件時，補到當天額度 × 首買比例
  O4 新錢優先補舊持股：追加資金當天，先補殖利率仍達門檻、低於當天額度的持股
  O2＋O4；O2 健康度 0.6／0.9／不設
輸出 results/budget_growth_eval.csv、budget_growth_money.csv"""
import pandas as pd

import rules_research as rr
import oos_study as oos
import param_opt as po
import portfolio_study as ps
import robust_study as rs
from backtest import RESULTS
from portfolio_contrib import irr
from portfolio_electronics import CAPITAL
from stock_fit import paired_from_files

H = 0.8


def main():
    po.setup(); G = rs.G; d = G["dates"]
    po.apply(rr.BASE); kw = po.to_kw(rr.BASE)
    variants = {
        "正式版 E＋D": {},
        "U1 只補賺錢部位＋現金>一筆首買": {"topup": {"signal": True, "profit_only": True, "cash_min_first": True, "health_min": H}},
        "U2 只補賺錢部位（無現金底線）": {"topup": {"signal": True, "profit_only": True, "health_min": H}},
        "U3 U1＋新錢先補賺錢持股": {"topup": {"signal": True, "newmoney": True, "profit_only": True, "cash_min_first": True, "health_min": H}},
        "T4 上一輪（虧損部位也補）": {"topup": {"signal": True, "track": True, "cash_min_first": True, "health_min": H}},
    }
    if "--round2" in __import__("sys").argv:
        variants.update({
        "T1 額度跟隨可投資資產·套牢凍結": {"topup": {"track": True, "health_min": H}},
        "T2 O2 補足＋額度跟隨": {"topup": {"signal": True, "track": True, "health_min": H}},
        "T3 O2＋O4＋額度跟隨": {"topup": {"signal": True, "newmoney": True, "track": True, "health_min": H}},
        "T4 T2＋現金>一筆首買才補": {"topup": {"signal": True, "track": True, "cash_min_first": True, "health_min": H}},
        "T5 T3＋現金>一筆首買才補": {"topup": {"signal": True, "newmoney": True, "track": True, "cash_min_first": True, "health_min": H}},
        "O2 買點再現補足（上一輪）": {"topup": {"signal": True, "health_min": H}},
        "O2＋O4（上一輪）": {"topup": {"signal": True, "newmoney": True, "health_min": H}},
        })
    if "--all" not in __import__("sys").argv:
        variants.pop("__none__", None)
    _old = {
        "O1 棘輪·健康度0.8（對照）": {"topup": {"ratchet": True, "health_min": H}},
        "O2 買點再現補足·健康度0.8": {"topup": {"signal": True, "health_min": H}},
        "O4 新錢優先補舊持股·健康度0.8": {"topup": {"newmoney": True, "health_min": H}},
        "O2＋O4·健康度0.8": {"topup": {"signal": True, "newmoney": True, "health_min": H}},
        "O2 健康度0.6": {"topup": {"signal": True, "health_min": 0.6}},
        "O2 健康度0.9": {"topup": {"signal": True, "health_min": 0.9}},
        "O2 不設健康度": {"topup": {"signal": True, "health_min": 0.0}},
        "O1＋O2＋O4·健康度0.8": {"topup": {"ratchet": True, "signal": True, "newmoney": True, "health_min": H}},
    }
    if "--all" in __import__("sys").argv:
        variants.update(_old)
    tag = "bgu" if "--round2" not in __import__("sys").argv and "--all" not in __import__("sys").argv else ("bgt" if "--all" not in __import__("sys").argv else "bg")
    s17 = d.get_indexer([pd.Timestamp("2017-01-03")], method="bfill")[0]
    sub = d[s17 + 1:]; months = pd.Series(sub, index=sub).groupby([sub.year, sub.month]).first(); midx = [d.get_loc(t) for t in months.values]
    rows = []
    for name, extra in variants.items():
        for sname, s in (("2017-01-03", s17), ("2016-12-28", 1)):
            for monthly in (0, 100_000):
                idx = [i for i in midx if i > s] if monthly else []
                contrib = {i: monthly / CAPITAL for i in idx} or None
                flows = [CAPITAL] + [monthly] * len(idx); fdates = [d[s]] + [d[i] for i in idx]
                led = []
                tr, eq = ps.run(G["sub"], G["member"], d, capital=CAPITAL, contributions=contrib, start_n=s, ledger=led, **kw, **extra)
                L = pd.DataFrame(led)
                n_sig = int(L["說明"].str.startswith("買點再現").sum()) if len(L) else 0
                n_new = int(L["說明"].str.startswith("新錢補足").sum()) if len(L) else 0
                amt_sig = round(L.loc[L["說明"].str.startswith("買點再現"), "金額"].sum() * CAPITAL / 1e4) if len(L) else 0
                amt_new = round(L.loc[L["說明"].str.startswith("新錢補足"), "金額"].sum() * CAPITAL / 1e4) if len(L) else 0
                rows.append(dict(版本=name, 起跑=sname, 每月投入萬=monthly / 1e4, 期末萬=round(eq.iloc[-1] * CAPITAL / 1e4),
                                 IRR=round(irr(flows, fdates, eq.iloc[-1] * CAPITAL, d[-1]), 1), 回撤=round(oos.nav_dd(eq, contrib), 1),
                                 筆數=len(tr), 勝率=round((tr["報酬%"] > 0).mean() * 100) if len(tr) else None,
                                 買點再現補足次=n_sig, 買點再現補足萬=amt_sig, 新錢補足次=n_new, 新錢補足萬=amt_new,
                                 資金使用率=round(eq.attrs["資金使用率%"])))
        print(f"  {name} 500 萬完成", flush=True)
    mon = pd.DataFrame(rows); mon.to_csv(RESULTS / f"budget_growth_{tag}_money.csv", index=False, encoding="utf-8-sig")
    _to_kw = po.to_kw; res = {}
    try:
        for i, (name, extra) in enumerate(variants.items()):
            po.to_kw = lambda c, extra=extra: {**_to_kw(c), **extra}
            po.CONFIGS[name] = rr.BASE
            m = po.evaluate([name], f"{tag}_{i}").loc[name]
            if i:
                for k_, v in paired_from_files(f"{tag}_0", f"{tag}_{i}").items():
                    m[k_] = v
            res[name] = m
            print(f"  {name} 20 情境完成：三段 {m['三段平均']:.2f}", flush=True)
    finally:
        po.to_kw = _to_kw
    out = pd.DataFrame(res).T
    show = [c for c in ["前7年", "前7年最差10", "前7年回撤", "延續", "單獨", "三段平均", "最差10最小", "標準差平均", "前7年配對", "後3年配對"] if c in out.columns]
    out[show].round(2).to_csv(RESULTS / f"budget_growth_{tag}_eval.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 100, "display.max_columns", 40, "display.unicode.east_asian_width", True):
        print("\n20 情境＋後 3 年（配對相對正式版）"); print(out[show].round(2).to_string())
        print("\n500 萬"); print(mon.to_string())


if __name__ == "__main__":
    main()
