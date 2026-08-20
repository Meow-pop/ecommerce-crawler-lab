"""Owned e-commerce target used only for local crawler engineering practice."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, Set

from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


BASE_DIR = Path(__file__).resolve().parent
SESSION_TTL_SECONDS = 30 * 60
SIGNATURE_TOLERANCE_SECONDS = 30
RATE_LIMIT_WINDOW_SECONDS = 4
RATE_LIMIT_REQUESTS = 4
PAGE_SIZE_MAX = 24


@dataclass
class Session:
    token: str
    created_at: float
    nonces: Set[str] = field(default_factory=set)
    requests: Deque[float] = field(default_factory=deque)


app = FastAPI(
    title="Owned Ecommerce Target Lab",
    description="A local-only target for authorized crawler engineering practice.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
sessions: Dict[str, Session] = {}


BRANDS = ("星桥", "远山", "澄海", "青禾", "北辰", "云岭")
MATERIALS = ("304不锈钢", "316L不锈钢", "钛", "食品级塑料")
CAPACITIES = (300, 350, 400, 450, 500, 600, 750, 900)


def build_products() -> list[dict]:
    products = []
    for index in range(1, 73):
        brand = BRANDS[(index - 1) % len(BRANDS)]
        capacity = CAPACITIES[(index * 3) % len(CAPACITIES)]
        material = MATERIALS[(index * 5) % len(MATERIALS)]
        price = round(29.9 + (index % 17) * 8.5 + (index % 3) * 0.09, 2)
        products.append({
            "product_id": f"LAB-{index:04d}",
            "title": f"{brand}{capacity}ml便携保温杯 {material}",
            "brand": brand,
            "price": price,
            "monthly_sales": 37 + ((index * 317) % 9800),
            "rating": round(4.1 + (index % 9) * 0.1, 1),
            "review_count": 12 + ((index * 113) % 4200),
            "capacity_ml": capacity,
            "material": material,
            "stock": 20 + ((index * 41) % 600),
            "product_url": f"/products/LAB-{index:04d}",
        })
    return products


PRODUCTS = build_products()


def canonical_message(timestamp: str, nonce: str, query: str, page: int, page_size: int) -> str:
    return f"{timestamp}\n{nonce}\n{query}\n{page}\n{page_size}"


def expected_signature(session: Session, message: str) -> str:
    return hmac.new(session.token.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def get_session(session_id: str | None) -> Session:
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="missing or unknown lab session")
    session = sessions[session_id]
    if time.time() - session.created_at > SESSION_TTL_SECONDS:
        sessions.pop(session_id, None)
        raise HTTPException(status_code=401, detail="lab session expired")
    return session


def enforce_rate_limit(session: Session, now: float) -> None:
    while session.requests and now - session.requests[0] >= RATE_LIMIT_WINDOW_SECONDS:
        session.requests.popleft()
    if len(session.requests) >= RATE_LIMIT_REQUESTS:
        retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - session.requests[0]) + 0.99))
        raise HTTPException(
            status_code=429,
            detail="local lab rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    session.requests.append(now)


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "product_count": len(PRODUCTS)}


@app.post("/api/bootstrap")
def bootstrap(response: Response) -> dict:
    session_id = secrets.token_urlsafe(24)
    session = Session(token=secrets.token_hex(24), created_at=time.time())
    sessions[session_id] = session
    response.set_cookie(
        key="lab_session",
        value=session_id,
        httponly=True,
        samesite="strict",
        max_age=SESSION_TTL_SECONDS,
    )
    return {
        "client_token": session.token,
        "expires_in": SESSION_TTL_SECONDS,
        "signature_algorithm": "HMAC-SHA256",
        "canonical_fields": ["timestamp", "nonce", "query", "page", "page_size"],
    }


@app.get("/api/products")
def products(
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1, le=100),
    page_size: int = Query(default=12, ge=1, le=PAGE_SIZE_MAX),
    lab_session: str | None = Cookie(default=None),
    x_lab_timestamp: str | None = Header(default=None),
    x_lab_nonce: str | None = Header(default=None),
    x_lab_signature: str | None = Header(default=None),
) -> dict:
    session = get_session(lab_session)
    if not x_lab_timestamp or not x_lab_nonce or not x_lab_signature:
        raise HTTPException(status_code=401, detail="missing signed request headers")
    try:
        request_timestamp = int(x_lab_timestamp)
    except ValueError as error:
        raise HTTPException(status_code=401, detail="invalid timestamp") from error

    now = time.time()
    if abs(now - request_timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        raise HTTPException(status_code=401, detail="signed request expired")
    if not (8 <= len(x_lab_nonce) <= 100):
        raise HTTPException(status_code=400, detail="invalid nonce")
    if x_lab_nonce in session.nonces:
        raise HTTPException(status_code=409, detail="nonce already used")

    message = canonical_message(x_lab_timestamp, x_lab_nonce, q, page, page_size)
    expected = expected_signature(session, message)
    if not hmac.compare_digest(expected, x_lab_signature.lower()):
        raise HTTPException(status_code=401, detail="invalid signature")

    session.nonces.add(x_lab_nonce)
    if len(session.nonces) > 2000:
        session.nonces.clear()
    enforce_rate_limit(session, now)

    normalized_query = q.strip().lower()
    filtered = [
        product for product in PRODUCTS
        if not normalized_query
        or normalized_query in product["title"].lower()
        or normalized_query in product["brand"].lower()
    ]
    start = (page - 1) * page_size
    items = filtered[start:start + page_size]
    return {
        "schema_version": "1.0",
        "query": q,
        "page": page,
        "page_size": page_size,
        "total": len(filtered),
        "has_next": start + page_size < len(filtered),
        "items": items,
    }
