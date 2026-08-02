"""In-process request rate limiter — sliding-window counters per "bucket:ip" key. Self-contained
   (stdlib only); strict one-way import (app.py -> ratelimit). Extracted from app.py during the
   modularisation. Guards login brute-force and write floods / cheap DoS on the single-process server;
   the counter state lives here and is bounded (long-idle keys are dropped)."""
import collections
import threading
import time

_RATE_LOCK = threading.Lock()
_RATE = collections.defaultdict(collections.deque)   # "bucket:ip" -> deque[timestamps]


def _rate_allow(key, limit, window):
    now = time.time()
    with _RATE_LOCK:
        dq = _RATE[key]
        cutoff = now - window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        if len(_RATE) > 4000:                        # bound memory: drop long-idle keys
            stale = [k for k, v in list(_RATE.items()) if not v or v[-1] < now - 3600]
            for k in stale[:1500]:
                _RATE.pop(k, None)
        return True
