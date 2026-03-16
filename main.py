#!/usr/bin/env python3
"""
GramSnap signing proxy — FastAPI service
Accepts: POST /instagram/userInfo   {"username": "..."}
         POST /instagram/postsV2    {"username": "...", "maxId": ""}
Returns: GramSnap API response JSON
"""
import hashlib, json, os, time, urllib.request
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import curl_cffi.requests as cf_requests

SECRET_SUFFIX = os.environ["GRAMSNAP_SECRET_SUFFIX"]
_TS = int(os.environ.get("GRAMSNAP_TS", "1772697360946"))
FLARESOLVER_URL = os.environ.get("FLARESOLVER_URL", "https://flaresolver.4stepai.cloud/v1")
GRAMSNAP_BASE = "https://gramsnap.com"

app = FastAPI()

# Cache cookies — FlareSolverr is slow; refresh every 25 min (cf_clearance lasts ~30 min)
_cookie_cache: dict = {"cookies": None, "ua": None, "fetched_at": 0}

def get_cookies():
    now = time.time()
    if _cookie_cache["cookies"] and (now - _cookie_cache["fetched_at"]) < 1500:
        return _cookie_cache["cookies"], _cookie_cache["ua"]
    req_body = json.dumps({"cmd": "request.get", "url": f"{GRAMSNAP_BASE}/en/", "maxTimeout": 60000}).encode()
    r = urllib.request.Request(FLARESOLVER_URL, data=req_body, headers={"Content-Type": "application/json"})
    flare = json.loads(urllib.request.urlopen(r, timeout=90).read())
    cookies = {c["name"]: c["value"] for c in flare["solution"]["cookies"]}
    ua = flare["solution"]["userAgent"]
    _cookie_cache.update({"cookies": cookies, "ua": ua, "fetched_at": now})
    return cookies, ua

def sort_keys(obj):
    return dict(sorted(obj.items()))

def gramsnap_post(path, body_dict):
    cookies, ua = get_cookies()
    ts = int(time.time() * 1000)
    msg = json.dumps(sort_keys(body_dict), separators=(",", ":")) + str(ts) + SECRET_SUFFIX
    sig = hashlib.sha256(msg.encode()).hexdigest()
    payload = {**sort_keys(body_dict), "ts": ts, "_ts": _TS, "_tsc": 0, "_s": sig}
    resp = cf_requests.post(
        f"{GRAMSNAP_BASE}{path}",
        json=payload,
        cookies=cookies,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Origin": GRAMSNAP_BASE,
            "Referer": f"{GRAMSNAP_BASE}/",
            "User-Agent": ua,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        },
        impersonate="chrome110",
        timeout=30,
    )
    if not resp.ok:
        # Invalidate cache so next request gets fresh cookies
        _cookie_cache["fetched_at"] = 0
        raise HTTPException(status_code=resp.status_code, detail=f"GramSnap returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


class UserInfoReq(BaseModel):
    username: str

class PostsReq(BaseModel):
    username: str
    maxId: Optional[str] = ""


@app.post("/instagram/userInfo")
def user_info(req: UserInfoReq):
    return gramsnap_post("/api/v1/instagram/userInfo", {"username": req.username})

@app.post("/instagram/postsV2")
def posts_v2(req: PostsReq):
    return gramsnap_post("/api/v1/instagram/postsV2", {"username": req.username, "maxId": req.maxId or ""})

@app.get("/health")
def health():
    return {"status": "ok", "_ts": _TS, "cookies_cached": _cookie_cache["cookies"] is not None}
