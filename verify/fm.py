"""FinMind fetch with on-disk cache (raw JSON response). Waits on 402."""
import json, os, time, sys, requests
from pathlib import Path
CACHE = Path("data/universe/_verify_cache/finmind")
CACHE.mkdir(parents=True, exist_ok=True)
API = "https://api.finmindtrade.com/api/v4/data"
CALLS = 0
SESSION = requests.Session()
_TOKEN = os.environ.get("FINMIND_TOKEN") or os.environ.get("KEY")  # token 只放 header，不寫檔
if _TOKEN:
    SESSION.headers["Authorization"] = f"Bearer {_TOKEN}"
def get(dataset, data_id="", start="2006-01-01", end="2026-10-31"):
    global CALLS
    f = CACHE / f"{dataset}_{data_id or 'ALL'}_{start}_{end}.json"
    if f.exists():
        return json.loads(f.read_text())["data"]
    p = {"dataset": dataset, "start_date": start, "end_date": end}
    if data_id: p["data_id"] = data_id
    while True:
        try:
            r = SESSION.get(API, params=p, timeout=90)
        except requests.RequestException as e:
            print("conn err", e, file=sys.stderr); time.sleep(10); continue
        try: body = r.json()
        except ValueError: body = {}
        st = body.get("status", r.status_code)
        if r.status_code == 402 or st == 402:
            print(f"402 after {CALLS} calls: {body.get('msg')}; sleep 420s", file=sys.stderr, flush=True)
            time.sleep(420); continue
        if r.status_code != 200 or st != 200:
            raise RuntimeError(f"{dataset} {data_id} HTTP {r.status_code} {str(body)[:300]}")
        CALLS += 1
        f.write_text(json.dumps(body, ensure_ascii=False))
        time.sleep(0.5)
        return body["data"]
