"""比較不同加碼方式（廣達 A/B/C 三版本，只做多）。

現行：首買 40%，跌 10/20/30% 各加碼 20%（= 首買的一半），最多 3 次
新案：首買 50%，跌 15/30% 各加碼 25%（= 首買的一半），最多 2 次
新案：首買 50%，跌 10/20/30% 各加碼 16.7%（= 首買的三分之一），最多 3 次
新案：首買 50%，跌 15/30% 加碼 30% / 20%（先多後少）
新案：首買 50%，跌 10/20/30% 加碼 25% / 15% / 10%（先多後少）
另附：首買 40%，跌 15/30% 各加碼 20%（只用到 80% 額度）、不加碼（首買 100%）
跌幅以首次買價計算。加碼時機：
  仍在門檻下：出現加碼訊號當天，收盤仍須在加碼門檻之下（反彈回門檻之上就不加）
  仍低於首買價：收盤曾跌到門檻即觸發，之後出現訊號且收盤仍低於首次買價就加
  觸發後都加：收盤曾跌到門檻即觸發，之後任何一天出現加碼訊號就加碼（股價回升也照加）
加碼訊號：價量引線（爆量長下影線或爆量長紅）
＋隔天開盤漲回不加：訊號隔天開盤價若已高於該次加碼門檻價，這次不加（資格保留）
用法：python add_scheme_study.py [代號]
"""
import sys

import pandas as pd

import trail_exit_study as tes
from backtest import RESULTS, WARMUP, load
from compare_versions import versions
from yield_entry_study import entries

SCHEMES = {
    "現行：40%＋10/20/30%各20%": (0.40, 0.20, (-0.10, -0.20, -0.30)),
    "新案：50%＋15/30%各25%": (0.50, 0.25, (-0.15, -0.30)),
    "新案：50%＋10/20/30%各16.7%": (0.50, 0.5 / 3, (-0.10, -0.20, -0.30)),
    "新案：50%＋15/30%加30/20%": (0.50, (0.30, 0.20), (-0.15, -0.30)),
    "新案：50%＋10/20/30%加25/15/10%": (0.50, (0.25, 0.15, 0.10), (-0.10, -0.20, -0.30)),
    "參考：40%＋15/30%各20%": (0.40, 0.20, (-0.15, -0.30)),
    "參考：不加碼，一次買滿": (1.00, 0.00, ()),
}


def main(stock_id="2382"):
    df = load(stock_id)
    start = df.index[0] + pd.Timedelta(days=int(WARMUP * 365.25 / 245))
    vs, add = versions(df, stock_id)
    triggers = {"價量引線": add, "任一買點": entries(df)[0]["任一"]}
    combos = [(w + chk, m, "價量引線", oc)
              for w, m in (("仍在門檻下", "same_day"), ("仍低於首買價", "armed_below_first"), ("觸發後都加", "armed"))
              for chk, oc in (("", False), ("＋隔天開盤漲回不加", True))]
    rows = {}
    for sname, (first, add_amt, steps) in SCHEMES.items():
        tes.FIRST, tes.ADD, tes.ADD_STEPS, tes.MAX_ADDS = first, add_amt, steps, len(steps)
        for when, mode, trig, oc in (combos if steps else combos[:1]):
          for vname, (buy, target) in vs.items():
            tr, eq = tes.run(df, buy, triggers[trig], start, df.index[-1], target, add_mode=mode, open_check=oc)
            s = tes.summary(tr, eq)
            rows[(vname, sname, when if steps else "—")] = s | {"筆數": len(tr), "加碼次數": int(tr["加碼"].sum()),
                                        "最深套牢%": tr["最深套牢%"].min(), "最長持有日": tr["持有日"].max()}
    table = pd.DataFrame(rows).T.drop(columns=["最好%"])
    table.index.names = ["版本", "加碼方式", "加碼時機"]
    table = table.sort_index(level=0, sort_remaining=False)
    table.round(2).to_csv(RESULTS / f"{stock_id}_add_schemes.csv", encoding="utf-8-sig")
    with pd.option_context("display.width", 250, "display.unicode.east_asian_width", True):
        print(table.round(1).to_string())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2382")
