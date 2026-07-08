from fastapi import FastAPI
from fastapi.responses import FileResponse
import subprocess
import os

app = FastAPI()

OUTPUT_FILE = "todays_bets.png"


@app.get("/")
def home():
    return {
        "status": "Daily Juice API running"
    }


@app.get("/todays-bets")
def todays_bets():

    # Generate image if needed
    subprocess.run(
        ["python", "daily_bets.py"],
        check=True
    )

    if not os.path.exists(OUTPUT_FILE):
        return {
            "error": "Failed to generate image"
        }

    return FileResponse(
        OUTPUT_FILE,
        media_type="image/png"
    )
