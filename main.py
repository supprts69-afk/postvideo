"""Render entrypoint.  Start command:  uvicorn main:app --host 0.0.0.0 --port $PORT
(ekta-i instance/worker chalao, --workers deo na)"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from worker import Importer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

importer = Importer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(importer.run())
    yield
    await importer.stop()
    task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)


# GET + HEAD dui-i accept kore (UptimeRobot HEAD pathay)
@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"ok": True, **importer.status()}
