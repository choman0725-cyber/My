# 臺灣50指數 (0050) / 臺灣高股息指數 (0056) 成分股歷史 2006-01-02 ~ 2026-10-29

> 2006-01 ~ 2015 的部分見文末「2006-01 ~ 2015 延伸」（由元大每日 PCF 直接取得）。

This file goes with `constituents.csv` (columns etf,effective_date,stock_id,name; one row per stock per period). Compiled 2026-10-29.

## 方法 / Method

1. **Official add/delete records.** Every periodic review and every non-periodic change (merger or delisting) comes from the FTSE Russell / TWSE announcements. These were published on TWSE news (2015-12 to 2016-09) and on 臺灣指數公司 (TIP) news (2016-11 onward). TIP news list API: `https://backend.taiwanindex.com.tw/api/media_event/news?year=YYYY&per_page=500` (header `TI-Language: zh`). Each item is viewable at `https://taiwanindex.com.tw/news/<id>`. TWSE items are at `https://www.twse.com.tw/rwd/zh/news/newsDetail?id=<id>`.
2. **Starting list.** The list in effect on 2016-01-01 is taken directly from the Yuanta ETF daily PCF (申購買回清單) for 2016-01-04 (`https://etfapi.yuantaetfs.com/ectranslation/api/bridge?APIType=ETFAPI&CompanyName=YUANTAFUNDS&PageName=/x&DeviceId=null&FuncId=PCF/Daily&AppName=ETF&Device=3&Platform=ETF&ticker=0050&date=YYYYMMDD`, ticker=0056 for 0056). The PCF is the ETF basket, not an official index file, but it equals the index list here (see step 4).
3. **Forward reconstruction.** Each later period = previous period minus deletions plus additions, as announced. Two checks run at every step: each deleted stock was in the prior list, and no added stock was already in it. Both passed for every step.
4. **Cross-check.** Every reconstructed period was compared with the Yuanta PCF for every weekday from 2015-06 to 2026-10-30 (about 4,900 daily baskets). All periods match, with two kinds of exception: (a) the 0056 3-5 day transition window, when the ETF still holds the deleted stocks; (b) three short ETF lags, listed under Flags. The final reconstructed lists equal the 2026-10-30 PCF for both ETFs. The 0050 list from 2026-06-22 also matches FTSE's constituent weight file as at 30 June 2026 (https://research.ftserussell.com/analytics/factsheets/Home/DownloadConstituentsWeights/?indexdetails=TW50). The zh.wikipedia 臺灣50指數 change table (https://zh.wikipedia.org/wiki/臺灣50指數) agrees, except that it folds two special changes into the next quarter (see below).
5. **Source vs reconstructed.** The 2016-01 starting lists come directly from a source (ETF PCF). Every later period was *reconstructed forward from add/delete announcements* and then *verified against a full list from a source* (the daily PCF). No period relies on reconstruction alone.
6. effective_date is the first trading day the new list applies (the announcement's 生效日). From 2019 on, 0056 reviews are phased in over 3-5 trading days (過渡期). The first of those days is used.
7. Names are the TWSE short names as most recently shown in the Yuanta PCF (e.g. 2883 凱基金 = former 開發金, 2887 台新新光金 = former 台新金). Names with `*` (康霈*, 矽力*-KY, 材料*-KY) are TWSE official abbreviations.

## 方法論重點 / Methodology findings (the brief's assumptions about 0056 were partly wrong)

- **臺灣50**: 50 stocks, reviewed quarterly (Mar/Jun/Sep/Dec), effective the next trading day after the 3rd Friday. Confirmed. Universe: TWSE-listed stocks only.
- **臺灣高股息 review months**: 0056 was not on an annual December review. In 2015-2016 its semi-annual reviews were in **March and September** (effective 2015-09-21, 2016-03-21, 2016-09-19). From **June 2017** they moved to **June and December**. The March 2017 announcement (titled 定期/不定期審核) only deleted 2707 晶華. I found no notice that states the switch itself; it is inferred from the sequence of announcements. *(flag)*
- **Deletion-only quarterly checks**: In the off-quarters (Jun/Dec in 2015; Mar/Sep from 2017), and mid-period, a 0056 stock is deleted **without replacement** when it leaves the 臺灣50 + 中型100 universe, or under the zero-dividend rule (rules 4.2.1/4.2.6; rule 5.5 for mid-period removals). So **the 0056 count is sometimes below 30/50** (29, 27, 49). The CSV keeps the true index count and does not pad to 30/50.
- **30 -> 50 change**: announced 2022-10-21 (TIP news 222, rules V3.1 -> V3.2, https://taiwanindex.com.tw/news/222). It was a one-time expansion at the **December 2022** semi-annual review (data cut-off 2022-11-21, effective **2022-12-19**, 26 additions / 5 deletions; TIP news 227). The same rule change moved the buffer from 15/46 to 35/66 and waived the 5-in/5-out cap when there are fewer than 50 candidates. The review stayed semi-annual (Jun/Dec) with deletion-only checks in Mar/Sep. TIP news 228 (2022-12-30) points to FTSE's supplementary note on the expansion.
- A later 0056 rule change (ground rules V3.8) added eligibility screens: Taiwan incorporation, analyst dividend forecasts, liquidity, 6-month return and equity ratio. It took effect from the December 2025 review (TIP 指數重要訊息 notice dated 2025-10-01, https://backend.taiwanindex.com.tw/api/downloadFile/HomepageBlocks/11/tw).

## 0050: 期間清單與異動 / periods and changes (37 periods)

| # | effective_date | count | type | additions 納入 | deletions 刪除 | source | list basis |
|---|---|---|---|---|---|---|---|
| 1 | 2015-09-21 | 50 | list in effect on 2016-01-01 | - | - | Yuanta PCF 2016-01-04 | taken directly from source (ETF PCF) |
| 2 | 2016-06-20 | 50 | review 2016Q2 | 2324 仁寶 | 2227 裕日車 | https://www.twse.com.tw/rwd/zh/news/newsDetail?id=98224FCD975E4801AA8532DAAF306219 | reconstructed from announcement; verified against PCF |
| 3 | 2016-11-30 | 50 | special: Micron cash acquisition of 華亞科 | 2823 中壽 | 3474 華亞科 | https://taiwanindex.com.tw/news/30 | reconstructed from announcement; verified against PCF |
| 4 | 2017-06-19 | 50 | review 2017Q2 | 2633 台灣高鐵 | 1476 儒鴻 | https://taiwanindex.com.tw/news/56 | reconstructed from announcement; verified against PCF |
| 5 | 2018-03-19 | 50 | review 2018Q1 | 5871 中租-KY | 2207 和泰車 | https://taiwanindex.com.tw/news/77 | reconstructed from announcement; verified against PCF |
| 6 | 2018-04-18 | 50 | special: ASE/SPIL merger into holding co | 2327 國巨 | 2325 矽品 | https://taiwanindex.com.tw/news/85 | reconstructed from announcement; verified against PCF |
| 7 | 2018-04-30 | 50 | special: code change 2311 日月光 -> 3711 日月光投控 (holding company listed 2018-04-30) | 3711 日月光投控 | 2311 日月光 | Yuanta 0050 PCF (no index announcement found) + https://taiwanindex.com.tw/news/85 | reconstructed from announcement; verified against PCF |
| 8 | 2018-06-19 | 50 | review 2018Q2 (announced effective 2018-06-18, a market holiday) | 2492 華新科 | 2324 仁寶 | https://taiwanindex.com.tw/news/91 | reconstructed from announcement; verified against PCF |
| 9 | 2018-12-22 | 50 | review 2018Q4 (Saturday make-up trading day) | 5876 上海商銀 | 2492 華新科 | https://taiwanindex.com.tw/news/101 | reconstructed from announcement; verified against PCF |
| 10 | 2019-03-18 | 50 | review 2019Q1 | 2207 和泰車 | 2354 鴻準 | https://taiwanindex.com.tw/news/110 | reconstructed from announcement; verified against PCF |
| 11 | 2019-06-24 | 50 | review 2019Q2 | 9910 豐泰 | 3481 群創 | https://taiwanindex.com.tw/news/120 | reconstructed from announcement; verified against PCF |
| 12 | 2019-09-23 | 50 | review 2019Q3 | 2888 新光金 | 2409 友達 | https://taiwanindex.com.tw/news/126 | reconstructed from announcement; verified against PCF |
| 13 | 2020-06-22 | 50 | review 2020Q2 | 6669 緯穎 | 9904 寶成 | https://taiwanindex.com.tw/news/149 | reconstructed from announcement; verified against PCF |
| 14 | 2020-09-21 | 50 | review 2020Q3 | 2379 瑞昱、6415 矽力*-KY | 2888 新光金、2823 中壽 | https://taiwanindex.com.tw/news/169 | reconstructed from announcement; verified against PCF |
| 15 | 2020-12-21 | 50 | review 2020Q4 | 3034 聯詠 | 2301 光寶科 | https://taiwanindex.com.tw/news/171 | reconstructed from announcement; verified against PCF |
| 16 | 2021-03-22 | 50 | review 2021Q1 | 1590 亞德客-KY、8046 南電 | 2883 凱基金、2890 永豐金 | https://taiwanindex.com.tw/news/178 | reconstructed from announcement; verified against PCF |
| 17 | 2021-06-21 | 50 | review 2021Q2 | 2603 長榮、2615 萬海、2609 陽明、2409 友達 | 2633 台灣高鐵、6669 緯穎、2105 正新、2474 可成 | https://taiwanindex.com.tw/news/181 | reconstructed from announcement; verified against PCF |
| 18 | 2021-09-22 | 50 | review 2021Q3 | 8454 富邦媒 | 1102 亞泥 | https://taiwanindex.com.tw/news/191 | reconstructed from announcement; verified against PCF |
| 19 | 2021-12-20 | 50 | review 2021Q4 | 3037 欣興 | 1402 遠東新 | https://taiwanindex.com.tw/news/198 | reconstructed from announcement; verified against PCF |
| 20 | 2022-03-21 | 50 | review 2022Q1 | 2883 凱基金 | 4938 和碩 | https://taiwanindex.com.tw/news/203 | reconstructed from announcement; verified against PCF |
| 21 | 2022-06-20 | 50 | review 2022Q2 | 6770 力積電 | 8454 富邦媒 | https://taiwanindex.com.tw/news/211 | reconstructed from announcement; verified against PCF |
| 22 | 2022-09-19 | 50 | review 2022Q3 | 2890 永豐金 | 6770 力積電 | https://taiwanindex.com.tw/news/221 | reconstructed from announcement; verified against PCF |
| 23 | 2022-12-19 | 50 | review 2022Q4 | 1402 遠東新 | 2409 友達 | https://taiwanindex.com.tw/news/227 | reconstructed from announcement; verified against PCF |
| 24 | 2023-03-20 | 50 | review 2023Q1 | 1605 華新 | 8046 南電 | https://taiwanindex.com.tw/news/234 | reconstructed from announcement; verified against PCF |
| 25 | 2023-06-19 | 50 | review 2023Q2 | 4938 和碩 | 6415 矽力*-KY | https://taiwanindex.com.tw/news/247 | reconstructed from announcement; verified against PCF |
| 26 | 2023-09-18 | 50 | review 2023Q3 | 2345 智邦、2301 光寶科、3231 緯創、6669 緯穎 | 1402 遠東新、1605 華新、2615 萬海、2609 陽明 | https://taiwanindex.com.tw/news/263 | reconstructed from announcement; verified against PCF |
| 27 | 2024-03-18 | 50 | review 2024Q1 | 3661 世芯-KY | 9910 豐泰 | https://taiwanindex.com.tw/news/294 | reconstructed from announcement; verified against PCF |
| 28 | 2024-06-24 | 50 | review 2024Q2 | 3017 奇鋐 | 2801 彰銀 | https://taiwanindex.com.tw/news/303 | reconstructed from announcement; verified against PCF |
| 29 | 2024-09-23 | 50 | review 2024Q3 | 6446 藥華藥 | 2408 南亞科 | https://taiwanindex.com.tw/news/320 | reconstructed from announcement; verified against PCF |
| 30 | 2024-12-23 | 50 | review 2024Q4 | 2609 陽明 | 1590 亞德客-KY | https://taiwanindex.com.tw/news/337 | reconstructed from announcement; verified against PCF |
| 31 | 2025-03-24 | 50 | review 2025Q1 | 2615 萬海 | 1326 台化 | https://taiwanindex.com.tw/news/350 | reconstructed from announcement; verified against PCF |
| 32 | 2025-06-23 | 50 | review 2025Q2 | 2383 台光電 | 3037 欣興 | https://taiwanindex.com.tw/news/362 | reconstructed from announcement; verified against PCF |
| 33 | 2025-09-22 | 50 | review 2025Q3 | 6919 康霈*、2059 川湖 | 6446 藥華藥、1101 台泥 | https://taiwanindex.com.tw/news/382 | reconstructed from announcement; verified against PCF |
| 34 | 2025-12-22 | 50 | review 2025Q4 | 3665 貿聯-KY、2360 致茂、3653 健策、2408 南亞科 | 5871 中租-KY、4938 和碩、5876 上海商銀、2609 陽明 | https://taiwanindex.com.tw/news/391 | reconstructed from announcement; verified against PCF |
| 35 | 2026-03-23 | 50 | review 2026Q1 | 2368 金像電、7769 鴻勁、2449 京元電子、3037 欣興、2344 華邦電 | 3665 貿聯-KY、3034 聯詠、2912 統一超、2379 瑞昱、2615 萬海 | https://taiwanindex.com.tw/news/405 | reconstructed from announcement; verified against PCF |
| 36 | 2026-06-22 | 50 | review 2026Q2 | 3665 貿聯-KY、3443 創意、8046 南電、4958 臻鼎-KY | 6919 康霈*、2002 中鋼、1301 台塑、2207 和泰車 | https://taiwanindex.com.tw/news/424 | reconstructed from announcement; verified against PCF |
| 37 | 2026-09-21 | 50 | review 2026Q3 | 6446 藥華藥 | 3661 世芯-KY | https://taiwanindex.com.tw/news/450 | reconstructed from announcement; verified against PCF |

## 0056: 期間清單與異動 / periods and changes (31 periods)

| # | effective_date | count | type | additions 納入 | deletions 刪除 | source | list basis |
|---|---|---|---|---|---|---|---|
| 1 | 2015-12-21 | 29 | list in effect on 2016-01-01 | - | - | Yuanta PCF 2016-01-04 | taken directly from source (ETF PCF) |
| 2 | 2016-03-21 | 30 | semi-annual review 2016-03 | 6176 瑞儀、2542 興富發、9933 中鼎、4938 和碩、4958 臻鼎-KY | 2227 裕日車、2362 藍天、5522 遠雄、2451 創見 | https://www.twse.com.tw/rwd/zh/news/newsDetail?id=F307F7D528D74B72A28152B3A821AE37 | reconstructed from announcement; verified against PCF |
| 3 | 2016-09-19 | 30 | semi-annual review 2016-09 | 2345 智邦、5264 鎧勝-KY、1477 聚陽、5871 中租-KY、2707 晶華 | 2327 國巨、1102 亞泥、2392 正崴、2379 瑞昱、1723 中碳 | https://www.twse.com.tw/rwd/zh/news/newsDetail?id=B1040B04A87E4E63A10FA0573ECF39CE | reconstructed from announcement; verified against PCF |
| 4 | 2017-03-20 | 29 | 2017-03 review (定期/不定期): deletion only | 無 | 2707 晶華 | https://taiwanindex.com.tw/news/45 | reconstructed from announcement; verified against PCF |
| 5 | 2017-06-19 | 30 | semi-annual review 2017-06 | 2409 友達、8150 南茂、1909 榮成、3481 群創、2451 創見 | 2915 潤泰全、5871 中租-KY、4958 臻鼎-KY、9945 潤泰新 | https://taiwanindex.com.tw/news/56 | reconstructed from announcement; verified against PCF |
| 6 | 2017-12-18 | 30 | semi-annual review 2017-12 | 2352 佳世達、1704 榮化、3706 神達、1326 台化、2891 中信金 | 2451 創見、9933 中鼎、1909 榮成、5264 鎧勝-KY、8150 南茂 | https://taiwanindex.com.tw/news/72 | reconstructed from announcement; verified against PCF |
| 7 | 2018-04-18 | 29 | special: 矽品 delisted (ASE/SPIL holding co) | 無 | 2325 矽品 | https://taiwanindex.com.tw/news/85 | reconstructed from announcement; verified against PCF |
| 8 | 2018-06-19 | 30 | semi-annual review 2018-06 | 6116 彩晶、2027 大成鋼、2451 創見、3711 日月光投控、2439 美律 | 2376 技嘉、2377 微星、2883 凱基金、3481 群創 | https://taiwanindex.com.tw/news/91 | reconstructed from announcement; verified against PCF |
| 9 | 2018-12-22 | 30 | semi-annual review 2018-12 | 2327 國巨、2376 技嘉、2408 南亞科、2337 旺宏、2377 微星 | 2027 大成鋼、2345 智邦、3706 神達、3711 日月光投控、1477 聚陽 | https://taiwanindex.com.tw/news/101 | reconstructed from announcement; verified against PCF |
| 10 | 2019-01-24 | 29 | special: 李長榮化工 taken private | 無 | 1704 榮化 | https://taiwanindex.com.tw/news/106 | reconstructed from announcement; verified against PCF |
| 11 | 2019-06-24 | 30 | semi-annual review 2019-06 | 2915 潤泰全、3532 台勝科、9945 潤泰新、3005 神基、2027 大成鋼 | 2891 中信金、2337 旺宏、2409 友達、6116 彩晶 | https://taiwanindex.com.tw/news/120 | reconstructed from announcement; verified against PCF |
| 12 | 2019-12-23 | 30 | semi-annual review 2019-12 | 2492 華新科、1605 華新、1102 亞泥、2404 漢唐 | 6239 力成、9945 潤泰新、2352 佳世達、2542 興富發 | https://taiwanindex.com.tw/news/132 | reconstructed from announcement; verified against PCF |
| 13 | 2020-06-22 | 30 | semi-annual review 2020-06 | 2458 義隆、9933 中鼎、3044 健鼎、1434 福懋、2809 京城銀 | 2327 國巨、1326 台化、2027 大成鋼、2408 南亞科、3532 台勝科 | https://taiwanindex.com.tw/news/149 | reconstructed from announcement; verified against PCF |
| 14 | 2020-12-21 | 30 | semi-annual review 2020-12 | 2883 凱基金、5522 遠雄、2542 興富發 | 3034 聯詠、2492 華新科、1605 華新 | https://taiwanindex.com.tw/news/171 | reconstructed from announcement; verified against PCF |
| 15 | 2021-03-22 | 27 | quarterly (deletion-only) review 2021-03 | 無 | 2439 美律、2451 創見、9933 中鼎 | https://taiwanindex.com.tw/news/178 | reconstructed from announcement; verified against PCF |
| 16 | 2021-06-21 | 30 | semi-annual review 2021-06 | 2409 友達、3481 群創、2441 超豐、2603 長榮、2108 南帝 | 2347 聯強、3005 神基 | https://taiwanindex.com.tw/news/181 | reconstructed from announcement; verified against PCF |
| 17 | 2021-12-20 | 30 | semi-annual review 2021-12 | 3034 聯詠、2002 中鋼、2606 裕民、2347 聯強、2014 中鴻 | 2809 京城銀、2883 凱基金、1434 福懋、2915 潤泰全、2404 漢唐 | https://taiwanindex.com.tw/news/198 | reconstructed from announcement; verified against PCF |
| 18 | 2022-03-21 | 29 | quarterly (deletion-only) review 2022-03 | 無 | 2108 南帝 | https://taiwanindex.com.tw/news/203 | reconstructed from announcement; verified against PCF |
| 19 | 2022-06-20 | 30 | semi-annual review 2022-06 | 2454 聯發科、2006 東和鋼鐵、2303 聯電、3036 文曄、2609 陽明 | 2542 興富發、3481 群創、2886 兆豐金、2606 裕民 | https://taiwanindex.com.tw/news/211 | reconstructed from announcement; verified against PCF |
| 20 | 2022-09-19 | 29 | quarterly (deletion-only) review 2022-09 | 無 | 2458 義隆 | https://taiwanindex.com.tw/news/221 | reconstructed from announcement; verified against PCF |
| 21 | 2022-12-19 | 50 | semi-annual review 2022-12; one-time expansion 30->50 | 3711 日月光投控、3017 奇鋐、3665 貿聯-KY、2474 可成、2891 中信金、2383 台光電、1402 遠東新、1301 台塑、2542 興富發、2317 鴻海、2809 京城銀、3189 景碩、2337 旺宏、1303 南亞、8046 南電、6239 力成、2379 瑞昱、2915 潤泰全、2890 永豐金、2027 大成鋼、1802 台玻、6271 同欣電、2606 裕民、2637 慧洋-KY、2885 元大金、4958 臻鼎-KY | 2002 中鋼、2014 中鴻、2441 超豐、1101 台泥、2609 陽明 | https://taiwanindex.com.tw/news/227<br>https://taiwanindex.com.tw/news/222 | reconstructed from announcement; verified against PCF |
| 22 | 2023-06-19 | 50 | semi-annual review 2023-06 | 2353 宏碁、1477 聚陽、2886 兆豐金、6669 緯穎、1907 永豐餘 | 3017 奇鋐、2603 長榮、2337 旺宏、1802 台玻、6271 同欣電 | https://taiwanindex.com.tw/news/247 | reconstructed from announcement; verified against PCF |
| 23 | 2023-09-18 | 49 | quarterly (deletion-only) review 2023-09 | 無 | 2637 慧洋-KY | https://taiwanindex.com.tw/news/263 | reconstructed from announcement; verified against PCF |
| 24 | 2023-12-18 | 50 | semi-annual review 2023-12 | 2105 正新、3005 神基、9917 中保科、1605 華新、6285 啟碁 | 3189 景碩、2606 裕民、6669 緯穎、1907 永豐餘 | https://taiwanindex.com.tw/news/276 | reconstructed from announcement; verified against PCF |
| 25 | 2024-06-24 | 50 | semi-annual review 2024-06 | 5871 中租-KY、3532 台勝科、4919 新唐、1319 東陽、9941 裕融 | 2409 友達、3665 貿聯-KY、1301 台塑、2542 興富發、8046 南電 | https://taiwanindex.com.tw/news/303 | reconstructed from announcement; verified against PCF |
| 26 | 2024-09-23 | 49 | quarterly (deletion-only) review 2024-09 | 無 | 4919 新唐 | https://taiwanindex.com.tw/news/320 | reconstructed from announcement; verified against PCF |
| 27 | 2024-12-23 | 50 | semi-annual review 2024-12 | 2618 長榮航、2603 長榮、2542 興富發、2880 華南金、4763 材料*-KY、5876 上海商銀、1504 東元、2609 陽明 | 1402 遠東新、5522 遠雄、3532 台勝科、2809 京城銀、2915 潤泰全、9917 中保科、1605 華新 | https://taiwanindex.com.tw/news/337 | reconstructed from announcement; verified against PCF |
| 28 | 2025-06-23 | 50 | semi-annual review 2025-06 | 2883 凱基金、9904 寶成、3023 信邦、2887 台新新光金、1216 統一 | 2383 台光電、2542 興富發、4763 材料*-KY、1303 南亞、2609 陽明 | https://taiwanindex.com.tw/news/362 | reconstructed from announcement; verified against PCF |
| 29 | 2025-12-22 | 50 | semi-annual review 2025-12 | 2884 玉山金、2645 長榮航太、3045 台灣大 | 5871 中租-KY、1504 東元、4958 臻鼎-KY | https://taiwanindex.com.tw/news/391 | reconstructed from announcement; verified against PCF |
| 30 | 2026-03-23 | 49 | quarterly (deletion-only) review 2026-03 | 無 | 9941 裕融 | https://taiwanindex.com.tw/news/405 | reconstructed from announcement; verified against PCF |
| 31 | 2026-06-22 | 50 | semi-annual review 2026-06 | 1513 中興電、4904 遠傳、1303 南亞、2408 南亞科、2344 華邦電 | 1477 聚陽、6176 瑞儀、1319 東陽、2006 東和鋼鐵 | https://taiwanindex.com.tw/news/424 | reconstructed from announcement; verified against PCF |

### Reviews with no change (no new period created)

- 0050: 2016-03, 2016-09, 2016-12, 2017-03, 2017-09, 2017-12, 2018-09, 2019-12, 2020-03 and 2023-12 were all announced as 納入：無 / 刪除：無 (TWSE F307F7D528D74B72A28152B3A821AE37, B1040B04A87E4E63A10FA0573ECF39CE; TIP news 31, 45, 68, 72, 96, 132, 141, 276). The 2015-12 review (TWSE A5D0AD24A68B4961A54CC3D91E29159F) also had no 臺灣50 change.
- 0056: The 2016-12 announcement and the Mar/Sep announcements of 2017-2020 have no 高股息 section; the PCF confirms no change, apart from the special deletions listed below. 2021-09, 2023-03, 2024-03, 2025-03, 2025-09 and 2026-09 were announced with no 高股息 change.

## Start of the first periods

- 0050: the list in effect on 2016-01-01 started on **2015-09-21** (1476 儒鴻 in, 2498 宏達電 out; confirmed by PCF). The 2015-12 review made no change.
- 0056: the list in effect on 2016-01-01 has **29** stocks and started on **2015-12-21**. It is the 2015-09-21 semi-annual list (30 stocks) minus 2393 億光. 億光 was deleted when it dropped out of 中型100 at the Dec-2015 quarterly review (TWSE A5D0AD24A68B4961A54CC3D91E29159F, item 五, '非定期審核時所發生之變動').

## 特殊/非定期異動 / Special mid-period changes

| date | index | change | reason | source |
|---|---|---|---|---|
| 2015-12-21 | 0056 | -2393 億光 (no replacement) | dropped from 中型100 at the quarterly review | https://www.twse.com.tw/rwd/zh/news/newsDetail?id=A5D0AD24A68B4961A54CC3D91E29159F |
| 2016-11-30 | 0050 | +2823 中壽 / -3474 華亞科 | Micron cash acquisition of 華亞科 (delisted). Wikipedia lists this under 2016-12 | https://taiwanindex.com.tw/news/30 |
| 2018-04-18 | 0050 | +2327 國巨 / -2325 矽品 | 日月光 and 矽品 merged into 日月光投控. Wikipedia lists 國巨 and 矽品 under 2018-06 (the 2018-06 review was in fact +2492 華新科 / -2324 仁寶) | https://taiwanindex.com.tw/news/85, https://taiwanindex.com.tw/news/91 |
| 2018-04-18 | 0056 | -2325 矽品 (no replacement) | same merger; rule 5.5 | https://taiwanindex.com.tw/news/85 |
| 2018-04-30 | 0050 | 2311 日月光 -> 3711 日月光投控 | code change when the holding company listed. Announcement 85 says 2311 stays in the index; the switch shows in the PCF on 2018-04-30. **No separate notice found** *(flag)* | TIP 85 + Yuanta PCF |
| 2019-01-24 | 0056 | -1704 榮化 (no replacement) | 李長榮化工 became a wholly owned subsidiary of 楷榮 and delisted (last trade 2019-01-23) | https://taiwanindex.com.tw/news/106 |
| 2020-07-10 | none | 2371 大同 removed from 中型100 | not a 0050/0056 member; no effect | https://taiwanindex.com.tw/news/158, https://taiwanindex.com.tw/news/159 |
| 2020-12-24 | none | 2448 晶電 -> 3714 富采 (中型100) | not a 0050/0056 member in 2016-2026; no effect | https://taiwanindex.com.tw/news/173 |
| 2021-01-07 | none | 5264 鎧勝-KY removed (中型100) | merged into 和碩; had already left 0056 on 2017-12-18 | https://taiwanindex.com.tw/news/176 |
| 2021-12-20 | none | 2823 中壽 removed (中型100) | share swap with 開發金; had already left 0050 on 2020-09-21 | https://taiwanindex.com.tw/news/199 |

In 2022-2026 the daily PCF shows no unannounced membership change. Two renames kept the same code: 2883 開發金 -> 凱基金 (2024), and 2887 台新金 -> 台新新光金 (2025, after absorbing 2888 新光金). 2888 新光金 was a 0050 constituent from 2019-09-23 to 2020-09-18 and is now delisted following the merger into 台新.

## 不確定 / Flags

1. **Short lags between the ETF and the index.** The CSV follows the index announcements. The 0050 PCF did not hold 2408 南亞科 until 2025-12-31 (index add 2025-12-22) or 3037 欣興 until 2026-04-14 (index add 2026-03-23). The 0056 PCF kept 4763 材料*-KY until 2025-07-11 (index delete 2025-06-23). The FTSE 30-Jun-2026 weight file confirms 2408 and 3037 are in the index. The likely cause is the ETF's handling of limit-up / liquidity. Low risk.
2. **2311 -> 3711 switch date (2018-04-30)** comes from the PCF only. Users may want to treat 2311/3711 as one continuous constituent.
3. **0056 review-cycle change (Mar/Sep -> Jun/Dec, between Sep 2016 and Jun 2017)** is inferred; no rule-change notice was found. The membership itself is confirmed by the announcements and the PCF.
4. **0056 counts below the nominal size.** These periods have 29 stocks: 2015-12-21, 2017-03-20, 2018-04-18, 2019-01-24, 2022-03-21 and 2022-09-19. The 2021-03-22 period has 27. These periods have 49: 2023-09-18, 2024-09-23 and 2026-03-23. These are the real index counts, not gaps in the data. The brief's 'exactly 30/50 per period' rule cannot be met without inventing stocks.
5. **Effective-date conventions.** The 2018-06 review was announced as effective 2018-06-18, which was a market holiday, so 2018-06-19 is used. The 2018-12 review took effect on Saturday 2018-12-22, a make-up trading day. The 2021-09 review took effect on 2021-09-22 (Wednesday, after the Mid-Autumn holiday). For 0056 from 2019, the CSV uses day 1 of the 3-5 day 過渡期.
6. **Starting lists are ETF baskets.** The 2016-01 starting lists are ETF PCF baskets, not an official index constituent file. They are consistent with every later announcement (every deleted stock was a member) and with Wikipedia's 0050 history.
7. **Market.** Both indices select only TWSE-listed (上市) stocks. The TIP index page gives the sample population as 'Listed companies of Taiwan Stock Exchange', and the 0056 universe is 臺灣50 + 中型100. So every stock_id here was 上市 while it was a constituent. Delisted or merged codes are kept as they were: 2311, 2325, 3474, 2823, 1704, 2888, 5264.


## 2006-01 ~ 2015 延伸（build_constituents_pcf.py，2026-10-31 新增）

**來源**：元大投信每日 PCF（申購買回清單），0050 自 2006-01-02、0056 自 2007-12-20（上市）起每個工作日，共 4,727 天，全部抓到。
這段沒有逐筆核對 FTSE 公告（證交所新聞頁擋程式存取），**名單直接取自 ETF 實際持股**，與 2016 年後「公告推算＋PCF 驗證」的做法不同。

**方法**
1. 每日持股＝實物申購清單 ∪ 權重清單。個股除權息、暫停交易時會改用現金替代、暫時不在清單裡，缺席 ≤ 20 個交易日補回。
2. 同一次調整，ETF 會分幾天買賣（2013 年起明顯，例如先買後賣、清單短暫 51～52 檔），相鄰 5 個交易日內的變動合併成一次。
3. 生效日：若該月第三個週五後首個交易日（指數生效規則）落在首次變動日的前 3 ～ 後 2 個交易日內，用該日；否則視為特殊事件，用 PCF 首次變動日。
4. 接點：PCF 名單與原名單第一期（0050 2015-09-21、0056 2015-12-21）完全接上；差異只有該日本身的換股（0050 +1476 −2498；0056 2393 億光 2015-12-22 刪除）。
5. 本期間新增 37 檔股票（2015 前已被剔除者），例如 2498 宏達電、3009 奇美電、3012 廣輝、2475 華映、3697 晨星、3673 TPK、5854 合庫（→ 5880 合庫金）。

**觀察到的規則**
- 0050：2006–2011 年審核多在 1／4／7／10 月，2011-06 起為 3／6／9／12 月（中間有過渡，例如 2006-09、2007-03、2010-03／06）；都是第三個週五後首個交易日生效。
- 0056：2008–2011-01 半年審核在 1／7 月（4／10 月只刪不補），2011-09 起改為 3／9 月（6／12 月只刪不補），因此有 27～29 檔的期間。
- 特殊事件（非定期）：2009-05-13 南亞科→華亞科、2010-03-10 奇美電（併入群創，期間 49 檔）、2011-12-01 合庫→合庫金（代號換）、2014-01-15 晨星（併入聯發科）→華亞科。

**有疑慮**
- 0056 上市首日（2007-12-20）PCF 只有 27 檔，指數應為 30 檔，可能是 ETF 剛成立尚未買齊；2008-01-21 起為 30 檔。
- 生效日依指數規則推定，ETF 實際換股可能晚 1～3 天（例如 2006-09 PCF 在 09-20 才換，生效日記為 09-18）。
- 名稱用 PCF 當時名稱（例如 F-TPK、F-晨星）；仍存在的股票用現在的名稱。

### 0050（2006-01 ~ 2015-06）
| etf | effective_date | count | type | additions 納入 | deletions 刪除 |
|---|---|---|---|---|---|
| 0050 | 2006-01-02 | 50 | PCF 起始（2006-01-02 已在名單） | - | - |
| 0050 | 2006-01-23 | 50 | 定期審核（第三個週五後首個交易日） | 3034 聯詠 | 6116 彩晶 |
| 0050 | 2006-04-24 | 50 | 定期審核（第三個週五後首個交易日） | 8078 華寶通訊 | 2201 裕隆 |
| 0050 | 2006-07-24 | 50 | 定期審核（第三個週五後首個交易日） | 1216 統一、3474 華亞科、8046 南電 | 2352 佳世達、2609 陽明、2610 華航 |
| 0050 | 2006-09-18 | 50 | 定期審核（第三個週五後首個交易日） | 3008 大立光 | 3012 廣輝電子 |
| 0050 | 2007-01-22 | 50 | 定期審核（第三個週五後首個交易日） | 1101 台泥、3481 群創 | 2603 長榮、8078 華寶通訊 |
| 0050 | 2007-03-19 | 50 | 定期審核（第三個週五後首個交易日） | 1102 亞泥 | 6004 元大證 |
| 0050 | 2007-04-23 | 50 | 定期審核（第三個週五後首個交易日） | 2885 元大金 | 2475 華映 |
| 0050 | 2007-07-23 | 50 | 定期審核（第三個週五後首個交易日） | 2912 統一超 | 3008 大立光 |
| 0050 | 2007-10-22 | 50 | 定期審核（第三個週五後首個交易日） | 2347 聯強 | 2884 玉山金 |
| 0050 | 2008-04-21 | 50 | 定期審核（第三個週五後首個交易日） | 1722 台肥、2603 長榮 | 2474 可成、3034 聯詠 |
| 0050 | 2008-10-20 | 50 | 定期審核（第三個週五後首個交易日） | 3231 緯創 | 2887 台新金 |
| 0050 | 2009-01-19 | 50 | 定期審核（第三個週五後首個交易日） | 2105 正新 | 3474 華亞科 |
| 0050 | 2009-05-13 | 50 | 非定期（依 PCF 首次變動日） | 3474 華亞科 | 2408 南亞科 |
| 0050 | 2010-01-18 | 50 | 定期審核（第三個週五後首個交易日） | 2448 晶電 | 2603 長榮 |
| 0050 | 2010-03-10 | 49 | 非定期（依 PCF 首次變動日） | - | 3009 奇美電 |
| 0050 | 2010-03-22 | 50 | 定期審核（第三個週五後首個交易日） | 6239 力成 | - |
| 0050 | 2010-06-21 | 50 | 定期審核（第三個週五後首個交易日） | 4938 和碩 | 6239 力成 |
| 0050 | 2011-01-24 | 50 | 定期審核（第三個週五後首個交易日） | 2618 長榮航、3673 F-TPK | 3474 華亞科、8046 南電 |
| 0050 | 2011-06-20 | 50 | 定期審核（第三個週五後首個交易日） | 2474 可成、3008 大立光 | 4938 和碩、9904 寶成 |
| 0050 | 2011-09-19 | 50 | 定期審核（第三個週五後首個交易日） | 1802 台玻、2201 裕隆 | 2448 晶電、2618 長榮航 |
| 0050 | 2011-12-01 | 50 | 非定期（依 PCF 首次變動日） | 5880 合庫金 | 5854 合庫 |
| 0050 | 2012-03-19 | 50 | 定期審核（第三個週五後首個交易日） | 2207 和泰車 | 2888 新光金 |
| 0050 | 2012-06-18 | 50 | 定期審核（第三個週五後首個交易日） | 3697 F-晨星 | 1802 台玻 |
| 0050 | 2013-06-24 | 50 | 定期審核（第三個週五後首個交易日） | 2884 玉山金、4938 和碩 | 2347 聯強、3231 緯創 |
| 0050 | 2013-09-23 | 50 | 定期審核（第三個週五後首個交易日） | 2887 台新金 | 2353 宏碁 |
| 0050 | 2013-12-23 | 50 | 定期審核（第三個週五後首個交易日） | 2227 裕日車、9904 寶成 | 1722 台肥、3673 F-TPK |
| 0050 | 2014-01-15 | 50 | 非定期（依 PCF 首次變動日） | 3474 華亞科 | 3697 F-晨星 |
| 0050 | 2014-06-23 | 50 | 定期審核（第三個週五後首個交易日） | 2395 研華 | 2201 裕隆 |
| 0050 | 2014-12-22 | 50 | 定期審核（第三個週五後首個交易日） | 2408 南亞科 | 2324 仁寶 |

### 0056（2007-12 ~ 2015-09）
| etf | effective_date | count | type | additions 納入 | deletions 刪除 |
|---|---|---|---|---|---|
| 0056 | 2007-12-20 | 27 | PCF 起始（2006-01-02 已在名單） | - | - |
| 0056 | 2008-01-21 | 30 | 定期審核（第三個週五後首個交易日） | 2395 研華、2408 南亞科、2855 統一證、3045 台灣大、3474 華亞科 | 1101 台泥、2204 中華 |
| 0056 | 2008-07-21 | 30 | 定期審核（第三個週五後首個交易日） | 2325 矽品、2337 旺宏、2548 華固、6116 彩晶、8008 建興電 | 1605 華新、2395 研華、2408 南亞科、3474 華亞科、9904 寶成 |
| 0056 | 2008-10-20 | 28 | 定期審核（第三個週五後首個交易日） | - | 2401 凌陽、2548 華固 |
| 0056 | 2009-01-19 | 30 | 定期審核（第三個週五後首個交易日） | 1704 榮化、2014 中鴻、2324 仁寶、2441 超豐、2612 中航、9907 統一實 | 1434 福懋、2855 統一證、3367 英華達、6116 彩晶 |
| 0056 | 2009-07-20 | 30 | 定期審核（第三個週五後首個交易日） | 1717 長興、2542 興富發、5203 訊連、5608 四維航、9933 中鼎 | 1303 南亞、1704 榮化、2002 中鋼、2615 萬海、6505 台塑化 |
| 0056 | 2009-10-19 | 27 | 定期審核（第三個週五後首個交易日） | - | 1710 東聯、5203 訊連、5608 四維航 |
| 0056 | 2010-01-18 | 30 | 定期審核（第三個週五後首個交易日） | 1434 福懋、2374 佳能、2498 宏達電、2548 華固、9917 中保 | 2441 超豐、9907 統一實 |
| 0056 | 2010-07-19 | 30 | 定期審核（第三個週五後首個交易日） | 1710 東聯、2489 瑞軒、2501 國建、4938 和碩、5522 遠雄 | 2006 東鋼、2014 中鴻、2353 宏碁、8046 南電、8078 華寶通訊 |
| 0056 | 2010-10-18 | 29 | 定期審核（第三個週五後首個交易日） | - | 2612 中航 |
| 0056 | 2011-01-24 | 30 | 定期審核（第三個週五後首個交易日） | 1101 台泥、2379 瑞昱、2382 廣達、2451 創見、2454 聯發科 | 1434 福懋、2498 宏達電、2501 國建、4938 和碩 |
| 0056 | 2011-06-20 | 29 | 定期審核（第三個週五後首個交易日） | - | 2374 佳能 |
| 0056 | 2011-09-19 | 30 | 定期審核（第三個週五後首個交易日） | 1303 南亞、2006 東鋼、2303 聯電、2327 國巨、2385 群光、3231 緯創 | 2356 英業達、2489 瑞軒、2605 新興、9917 中保、9933 中鼎 |
| 0056 | 2012-03-19 | 30 | 定期審核（第三個週五後首個交易日） | 1304 台聚、1723 中碳、4725 信昌化、6285 啟碁、8422 可寧衛 | 1717 長興、2006 東鋼、2327 國巨、2337 旺宏、8008 建興電 |
| 0056 | 2012-09-24 | 30 | 定期審核（第三個週五後首個交易日） | 1102 亞泥、1314 中石化、2498 宏達電、2883 開發金、3702 大聯大 | 1303 南亞、2451 創見、2454 聯發科、2606 裕民、4725 信昌化 |
| 0056 | 2013-03-18 | 30 | 定期審核（第三個週五後首個交易日） | 2450 神腦、5264 F-鎧勝、6176 瑞儀、9904 寶成、9933 中鼎 | 1314 中石化、1723 中碳、2883 開發金、5522 遠雄、6285 啟碁 |
| 0056 | 2013-09-23 | 30 | 定期審核（第三個週五後首個交易日） | 2357 華碩、2451 創見、2458 義隆、3673 F-TPK、5534 長虹 | 1304 台聚、2450 神腦、2498 宏達電、5264 F-鎧勝、8422 可寧衛 |
| 0056 | 2013-12-23 | 29 | 定期審核（第三個週五後首個交易日） | - | 2458 義隆 |
| 0056 | 2014-03-24 | 30 | 定期審核（第三個週五後首個交易日） | 2347 聯強、2449 京元電、2501 國建、6239 力成、9945 潤泰新 | 1301 台塑、1326 台化、2303 聯電、9904 寶成 |
| 0056 | 2014-06-23 | 29 | 定期審核（第三個週五後首個交易日） | - | 5534 長虹 |
| 0056 | 2014-09-22 | 30 | 定期審核（第三個週五後首個交易日） | 2356 英業達、2376 技嘉、2377 微星、2915 潤泰全、9907 統一實 | 1710 東聯、2501 國建、2548 華固、3673 F-TPK |
| 0056 | 2015-03-23 | 30 | 定期審核（第三個週五後首個交易日） | 1723 中碳、2227 裕日車、2392 正崴、2439 美律、2883 開發金 | 2103 台橡、2451 創見、2542 興富發、9907 統一實、9933 中鼎 |
| 0056 | 2015-06-22 | 29 | 定期審核（第三個週五後首個交易日） | - | 2439 美律 |
| 0056 | 2015-09-21 | 30 | 定期審核（第三個週五後首個交易日） | 2327 國巨、2362 藍天、2393 億光、2451 創見、5522 遠雄 | 2412 中華電、3045 台灣大、4904 遠傳、6176 瑞儀 |
