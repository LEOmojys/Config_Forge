"""Backend entry point: `python -m backend.api.app` or `python app.py`."""
from .app import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.api.app:app", host="0.0.0.0", port=8000, reload=True)
