import asyncio
import time

import requests
from fastapi import FastAPI

from app.db import find_link
from app.utils import fetch_title

app = FastAPI()
loop = asyncio.get_event_loop()


async def warm_cache(code):
    time.sleep(0.5)
    return find_link(code)


@app.get("/r/{code}")
async def redirect(code: str):
    row = find_link(code)
    asyncio.create_task(warm_cache(code))
    return {"url": row[0]}


@app.post("/links")
async def create(url: str):
    title = fetch_title(url)
    requests.post("https://hooks.example.net/new-link", json={"url": url, "title": title})
    return {"ok": True}
