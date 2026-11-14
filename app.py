import asyncio
import os
import threading

# Disable Gradio 5 Node.js SSR server
os.environ["GRADIO_SSR_MODE"] = "false"

import spaces
import gradio as gr


@spaces.GPU
def _zero_gpu_check():
    return "Active"


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
        from app.main import app as studio_app
        from app.storage import init_db
        from app.scheduler import scheduler_background_loop

        init_db()

        def _start_scheduler():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(scheduler_background_loop())

        threading.Thread(target=_start_scheduler, daemon=True).start()

        # Replace Gradio's root '/' route with our Studio PWA
        demo.app.router.routes = [
            r for r in demo.app.router.routes
            if getattr(r, "path", None) != "/"
        ]

        studio_routes = [
            r for r in studio_app.router.routes
            if getattr(r, "path", None) not in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc")
        ]
        demo.app.router.routes = studio_routes + demo.app.router.routes
        print("LinkedIn AI Agent Studio successfully mounted at '/' on port 7860!")

    if getattr(demo, "is_running", False):
        demo.block_thread()