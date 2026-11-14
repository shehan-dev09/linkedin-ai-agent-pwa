import asyncio
import hashlib
import hmac
import os
import threading

# Disable Gradio 5 Node.js SSR server
os.environ["GRADIO_SSR_MODE"] = "false"

import spaces
import gradio as gr
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse


@spaces.GPU
def _zero_gpu_check():
    return "Active"


def _get_expected_token() -> str:
    pwd = os.getenv("STUDIO_PASSWORD", "").strip()
    if not pwd:
        return ""
    return hashlib.sha256(f"shehan_studio_auth::{pwd}".encode("utf-8")).hexdigest()


LOCK_SCREEN_HTML = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Agent Studio — Locked</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #09090b; color: #fafafa; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    </style>
</head>
<body class="min-h-screen flex items-center justify-center p-4">
    <div class="w-full max-w-sm bg-[#111113] border border-zinc-800 rounded-xl p-6 shadow-2xl">
        <div class="flex items-center gap-3 mb-5">
            <div class="w-9 h-9 rounded-lg bg-zinc-100 text-zinc-950 flex items-center justify-center font-bold text-sm">SN</div>
            <div>
                <h1 class="text-sm font-semibold text-zinc-100">Agent Studio Protected</h1>
                <p class="text-[11px] text-zinc-400">Private Autonomous Workspace</p>
            </div>
        </div>
        <form method="POST" action="/studio-login" class="space-y-4">
            <div>
                <label class="block text-[11px] font-mono uppercase tracking-wider text-zinc-400 mb-1.5">Studio Passcode</label>
                <input type="password" name="password" required autofocus placeholder="Enter STUDIO_PASSWORD..."
                    class="w-full px-3.5 py-2.5 text-base bg-zinc-950 border border-zinc-800 rounded-lg text-zinc-100 focus:outline-none focus:border-zinc-500">
            </div>
            __ERROR_BLOCK__
            <button type="submit" class="w-full py-2.5 rounded-lg bg-zinc-100 hover:bg-white text-zinc-950 font-semibold text-xs transition-all cursor-pointer">
                Unlock Studio
            </button>
        </form>
    </div>
</body>
</html>"""


class StudioAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        expected_token = _get_expected_token()
        if not expected_token:
            return await call_next(request)

        path = request.url.path

        # Allow public health-check / cron-job ping & Gradio internal handshake routes
        public_prefixes = (
            "/api/meta",
            "/studio-login",
            "/config",
            "/info",
            "/gradio_api",
            "/startup-events",
            "/heartbeat",
            "/queue",
            "/manifest.json",
            "/sw.js",
        )
        if path.startswith(public_prefixes):
            return await call_next(request)

        cookie_token = request.cookies.get("studio_session", "")
        if hmac.compare_digest(cookie_token, expected_token):
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized. Studio is locked."}, status_code=401)

        html = LOCK_SCREEN_HTML.replace("__ERROR_BLOCK__", "")
        return HTMLResponse(html, status_code=200)


with gr.Blocks() as demo:
    gr.Markdown("LinkedIn AI Agent Studio")
    btn = gr.Button("Status")
    out = gr.Textbox()
    btn.click(_zero_gpu_check, outputs=out)

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        ssr_mode=False,
        prevent_thread_lock=True,
    )

    if getattr(demo, "app", None) is not None:
        from fastapi import Form
        from app.main import app as studio_app
        from app.storage import init_db
        from app.scheduler import scheduler_background_loop

        init_db()

        def _start_scheduler():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(scheduler_background_loop())

        threading.Thread(target=_start_scheduler, daemon=True).start()

        @studio_app.post("/studio-login")
        async def studio_login(password: str = Form(...)):
            expected = _get_expected_token()
            provided = hashlib.sha256(f"shehan_studio_auth::{password.strip()}".encode("utf-8")).hexdigest()
            if expected and hmac.compare_digest(provided, expected):
                resp = RedirectResponse(url="/", status_code=303)
                resp.set_cookie(
                    key="studio_session",
                    value=expected,
                    max_age=365 * 24 * 3600,
                    httponly=True,
                    samesite="none",
                    secure=True,
                )
                return resp
            err_html = '<p class="text-xs text-red-400">Invalid passcode. Please try again.</p>'
            return HTMLResponse(LOCK_SCREEN_HTML.replace("__ERROR_BLOCK__", err_html), status_code=401)

        # Remove Gradio's default '/' route
        demo.app.router.routes = [
            r for r in demo.app.router.routes
            if getattr(r, "path", None) != "/"
        ]

        studio_routes = [
            r for r in studio_app.router.routes
            if getattr(r, "path", None) not in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc")
        ]
        demo.app.router.routes = studio_routes + demo.app.router.routes

        # Bypass add_middleware() startup check by inserting into user_middleware directly
        demo.app.user_middleware.insert(0, Middleware(StudioAuthMiddleware))
        demo.app.middleware_stack = demo.app.build_middleware_stack()
        print("LinkedIn AI Agent Studio mounted with Password Protection enabled!")

    if getattr(demo, "is_running", False):
        demo.block_thread()