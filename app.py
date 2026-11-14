import uvicorn
from app.main import app as fastapi_app

if __name__ == "__main__":
    # Hugging Face Spaces routes all web traffic through port 7860
    uvicorn.run(fastapi_app, host="0.0.0.0", port=7860)