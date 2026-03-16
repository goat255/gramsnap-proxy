#!/usr/bin/env python3
"""
Instagram provider proxy — FastAPI service
FastDL (P1):        POST /fastdl/userInfo          {"username": "..."}
                    POST /fastdl/postsV2           {"username": "...", "maxId": ""}
GramSnap (P2):      POST /instagram/userInfo       {"username": "..."}
                    POST /instagram/postsV2        {"username": "...", "maxId": ""}
SSSInstagram (P3):  POST /sssinstagram/userInfo    {"username": "..."}
                    POST /sssinstagram/postsV2     {"username": "...", "maxId": ""}
"""
import hashlib, hmac, json, os, time, urllib.request
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import curl_cffi.requests as cf_requests

# GramSnap config
SECRET_SUFFIX = os.environ["GRAMSNAP_SECRET_SUFFIX"]
_TS = int(os.environ.get("GRAMSNAP_TS", "1772697360946"))
FLARESOLVER_URL = os.environ.get("FLARESOLVER_URL", "https://flaresolver.4stepai.cloud/v1")
GRAMSNAP_BASE = "https://gramsnap.com"

# FastDL config
FASTDL_HMAC_KEY = bytes.fromhex(os.environ.get("FASTDL_HMAC_KEY", "792525efde6d921d6055a5d62dcebd39c8b5364e99fa87c5adf0e89391266d9c"))
FASTDL_TS = int(os.environ.get("FASTDL_TS", "1773148641059"))
FASTDL_BASE = "https://api-wh.fastdl.app"

# SSSInstagram config
SSS_HMAC_KEY = bytes.fromhex(os.environ.get("SSS_HMAC_KEY", "df73cf7be343f9701ce0f2ae809f9bd752e82fbb7017f463141664465b8ce8e0"))
SSS_TS = int(os.environ.get("SSS_TS", "1770970183770"))
SSS_BASE = "https://api-wh.sssinstagram.com"

app = FastAPI()

# Cookie caches — FlareSolverr is slow; refresh every 25 min (cf_clearance lasts ~30 min)
_gramsnap_cookies: dict = {"cookies": None, "ua": None, "fetched_at": 0}
_fastdl_cookies: dict = {"cookies": None, "ua": None, "fetched_at": 0}

def _fetch_cf_cookies(url, cache):
    now = time.time()
    if cache["cookies"] and (now - cache["fetched_at"]) < 1500:
        return cache["cookies"], cache["ua"]
    req_body = json.dumps({"cmd": "request.get", "url": url, "maxTimeout": 60000}).encode()
    r = urllib.request.Request(FLARESOLVER_URL, data=req_body, headers={"Content-Type": "application/json"})
    flare = json.loads(urllib.request.urlopen(r, timeout=90).read())
    cookies = {c["name"]: c["value"] for c in flare["solution"]["cookies"]}
    ua = flare["solution"]["userAgent"]
    cache.update({"cookies": cookies, "ua": ua, "fetched_at": now})
    return cookies, ua

def get_gramsnap_cookies():
    return _fetch_cf_cookies(f"{GRAMSNAP_BASE}/en/", _gramsnap_cookies)

def get_fastdl_cookies():
    return _fetch_cf_cookies(f"{FASTDL_BASE}/", _fastdl_cookies)

def sort_keys(obj):
    return dict(sorted(obj.items()))

def gramsnap_post(path, body_dict):
    cookies, ua = get_gramsnap_cookies()
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
        _gramsnap_cookies["fetched_at"] = 0
        raise HTTPException(status_code=resp.status_code, detail=f"GramSnap returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


class UserInfoReq(BaseModel):
    username: str

class PostsReq(BaseModel):
    username: str
    maxId: Optional[str] = ""


def fastdl_post(path, body_dict):
    cookies, ua = get_fastdl_cookies()
    sorted_body = sort_keys(body_dict)
    json_str = json.dumps(sorted_body, separators=(",", ":"))
    ts = int(time.time() * 1000)
    sig = hmac.new(FASTDL_HMAC_KEY, (json_str + str(ts)).encode(), hashlib.sha256).hexdigest()
    payload = {**sorted_body, "ts": ts, "_ts": FASTDL_TS, "_tsc": 0, "_sv": 2, "_s": sig}
    resp = cf_requests.post(
        f"{FASTDL_BASE}{path}",
        json=payload,
        cookies=cookies,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://fastdl.app",
            "Referer": "https://fastdl.app/",
            "User-Agent": ua,
        },
        impersonate="chrome110",
        timeout=30,
    )
    if not resp.ok:
        _fastdl_cookies["fetched_at"] = 0
        raise HTTPException(status_code=resp.status_code, detail=f"FastDL returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


@app.post("/fastdl/userInfo")
def fastdl_user_info(req: UserInfoReq):
    return fastdl_post("/api/v1/instagram/userInfo", {"username": req.username})

@app.post("/fastdl/postsV2")
def fastdl_posts_v2(req: PostsReq):
    return fastdl_post("/api/v1/instagram/postsV2", {"username": req.username, "maxId": req.maxId or ""})


@app.post("/instagram/userInfo")
def user_info(req: UserInfoReq):
    return gramsnap_post("/api/v1/instagram/userInfo", {"username": req.username})

@app.post("/instagram/postsV2")
def posts_v2(req: PostsReq):
    return gramsnap_post("/api/v1/instagram/postsV2", {"username": req.username, "maxId": req.maxId or ""})

def sss_post(path, body_dict):
    sorted_body = sort_keys(body_dict)
    json_str = json.dumps(sorted_body, separators=(",", ":"))
    ts = int(time.time() * 1000)
    sig = hmac.new(SSS_HMAC_KEY, (json_str + str(ts)).encode(), hashlib.sha256).hexdigest()
    payload = {**sorted_body, "ts": ts, "_ts": SSS_TS, "_tsc": 0, "_sv": 2, "_s": sig}
    resp = cf_requests.post(
        f"{SSS_BASE}{path}",
        json=payload,
        headers={
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://sssinstagram.com",
            "Referer": "https://sssinstagram.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
        impersonate="chrome110",
        timeout=30,
    )
    if not resp.ok:
        raise HTTPException(status_code=resp.status_code, detail=f"SSSInstagram returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


@app.post("/sssinstagram/userInfo")
def sss_user_info(req: UserInfoReq):
    return sss_post("/api/v1/instagram/userInfo", {"username": req.username})

@app.post("/sssinstagram/postsV2")
def sss_posts_v2(req: PostsReq):
    return sss_post("/api/v1/instagram/postsV2", {"username": req.username, "maxId": req.maxId or ""})

@app.get("/health")
def health():
    return {"status": "ok", "fastdl_ts": FASTDL_TS, "gramsnap_ts": _TS, "sss_ts": SSS_TS, "fastdl_cookies": _fastdl_cookies["cookies"] is not None, "gramsnap_cookies": _gramsnap_cookies["cookies"] is not None}
