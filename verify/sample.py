import random, os
ids = sorted(f[:-4] for f in os.listdir('data/universe/prices'))
REQ = ['6669','2880','2330','2382','2412','2408','2633','0050','8454','2357']
rng = random.Random(20261031)
rest = rng.sample([s for s in ids if s not in REQ], 20)
PRICE30 = REQ + sorted(rest)
