from __future__ import annotations

import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


def mount_ui(app: FastAPI, base_dir: str) -> None:
    app.mount("/static", StaticFiles(directory=os.path.join(base_dir, "static")), name="static")
    templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))

    @app.get("/ui", response_class=HTMLResponse)
    def ui(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})
