"""Sample external webhook subscriber (FastAPI). Run: uvicorn main:app --port 9000"""
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import receiver_service as rs

app = FastAPI(title="Secure Tokens - Sample Webhook Receiver")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
receiver = rs.Receiver()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/receiver/webhooks/secure-tokens")
async def webhook(request: Request):
    raw = await request.body()  # verify against the RAW bytes, never re-serialised JSON
    status, body = receiver.handle(raw, dict(request.headers))
    return JSONResponse(status_code=status, content=body)


class SecretConfig(BaseModel):
    subscription_id: str
    secret: str


@app.put("/receiver/config/secret")
def set_secret(cfg: SecretConfig, x_receiver_token: str | None = Header(default=None)):
    if x_receiver_token != rs.ADMIN_TOKEN:
        raise HTTPException(403, "Invalid receiver token")
    receiver.set_secret(cfg.subscription_id, cfg.secret)
    return {"configured": cfg.subscription_id}


@app.get("/receiver/events")
def events(limit: int = 200):
    return receiver.list_events(limit)


@app.get("/receiver/events/{event_id}")
def event(event_id: str):
    rows = receiver.get_event(event_id)
    if not rows:
        raise HTTPException(404, "Event not received")
    return rows


@app.post("/receiver/reset")
def reset(x_receiver_token: str | None = Header(default=None)):
    if x_receiver_token != rs.ADMIN_TOKEN:
        raise HTTPException(403, "Invalid receiver token")
    receiver.reset()
    return {"reset": True}
