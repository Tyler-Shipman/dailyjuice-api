from datetime import datetime
import os
import subprocess

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

app = FastAPI()

OUTPUT_FILE = "todays_bets.png"


def run_daily_bets(force=False):
    """
    Runs the daily bets generator.
    If force=True, removes today's cache first.
    """

    if force:
        today = datetime.now().strftime("%Y-%m-%d")
        cache_file = f"cache_{today}.png"

        if os.path.exists(cache_file):
            os.remove(cache_file)
            print(f"Removed cache: {cache_file}")

    subprocess.run(
        ["python", "daily_bets.py"],
        check=True
    )


@app.get("/")
def home():
    return {
        "status": "Daily Juice API running"
    }


@app.get("/todays-bets")
def todays_bets():

    try:
        run_daily_bets()

    except subprocess.CalledProcessError:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate today's bets image"
        )

    if not os.path.exists(OUTPUT_FILE):
        raise HTTPException(
            status_code=500,
            detail="Image was not generated"
        )

    return FileResponse(
        OUTPUT_FILE,
        media_type="image/png"
    )


@app.get("/refresh")
def refresh():

    try:
        run_daily_bets(force=True)

    except subprocess.CalledProcessError:
        raise HTTPException(
            status_code=500,
            detail="Failed to refresh today's bets image"
        )

    if not os.path.exists(OUTPUT_FILE):
        raise HTTPException(
            status_code=500,
            detail="Image was not generated"
        )

    return FileResponse(
        OUTPUT_FILE,
        media_type="image/png"
    )
