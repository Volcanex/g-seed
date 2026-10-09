"""Example API router for the /hello page. Auto-mounted at /api/hello."""

from fastapi import APIRouter

router = APIRouter(tags=["hello"])


@router.get("/")
async def hello():
    return {"message": "Hello from pages/hello/api.py", "ok": True}


@router.get("/echo")
async def echo(msg: str = "hi"):
    return {"echo": msg}
