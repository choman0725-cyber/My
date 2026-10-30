"""第 1 名底（續抱殖利率 5% / 4.5%）下，精算每個停利 % 的差異，並測試「殖利率跌破門檻後直接用技術線型出場」。

停利 %：0（殖利率跌破門檻、扣成本不賠就賣）、3、5、8、10、12、15、18、20、25、30、40
技術出場（殖利率已 < 門檻且出現賣訊才賣）：
  訊號：價量賣訊（爆量上影線/爆量長黑）、跌破月線、價量賣訊或 KD 死叉
  是否需獲利：不限 / 扣成本不賠
  搭配：純技術（不設停利）/ 技術＋停利 20%
用法：python target_scan.py
"""
import pandas as pd

import param_opt as po
from backtest import RESULTS

TARGETS = [0.0, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.40]
SIGNALS = {"價量賣訊": "tech_sell", "跌破月線": "reversal_Rb", "價量或KD死叉": "reversal_Rc"}


def main():
    po.setup()
    rows = []
    for hy in (5.0, 4.5):
        for t in TARGETS:
            name = f"續抱{hy}｜停利{t:.0%}"
            po.CONFIGS[name] = {**po.BASE_A, "hold_yield": hy, "target": t}
            rows.append((hy, f"停利{t:.0%}", name))
        for sname, col in SIGNALS.items():
            for pname, prof in (("不限", False), ("需獲利", True)):
                for mname, t in (("純技術", 9.0), ("技術＋停利20%", 0.20)):
                    name = f"續抱{hy}｜{mname}·{sname}·{pname}"
                    po.CONFIGS[name] = {**po.BASE_A, "hold_yield": hy, "target": t, "tech_exit": col, "tech_profit": prof}
                    rows.append((hy, f"{mname}·{sname}·{pname}", name))
    names = [r[2] for r in rows]
    print(f"{len(names)} 個設定", flush=True)
    m = po.evaluate(names, "target")
    out = pd.DataFrame([dict(續抱殖利率=hy, 出場=d, **m.loc[n].to_dict()) for hy, d, n in rows])
    out.round(2).to_csv(RESULTS / "target_scan.csv", index=False, encoding="utf-8-sig")
    with pd.option_context("display.width", 320, "display.max_rows", 200, "display.unicode.east_asian_width", True):
        for hy in (5.0, 4.5):
            print(f"\n===== 續抱殖利率 {hy}% =====")
            print(out[out["續抱殖利率"] == hy][["出場"] + po.SHOW + ["超過2年比例", "前7年回撤"]].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
