import pandas as pd
import requests
import streamlit as st


import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

# Make the backend folder importable (so "from main import app" works)
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))


def backend_is_running() -> bool:
    """True if something already listens on port 8000."""
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", 8000)) == 0


@st.cache_resource          # runs only once, not on every click
def start_backend():
    if backend_is_running():            # e.g. you started uvicorn yourself
        return
    from main import app as fastapi_app
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=8000, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):                 # wait up to 5 seconds until it is ready
        if server.started:
            break
        time.sleep(0.1)


try:
    start_backend()
except Exception as e:
    st.error(f"Backend could not start: {e}")
    st.stop()


API_URL = "http://127.0.0.1:8000"

st.title("AI Meeting Notes Generator")

# Hide Streamlit's default "200MB per file" text
st.markdown(
    """
    <style>
    [data-testid="stFileUploaderDropzoneInstructions"] {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

audio = st.file_uploader(
    "Upload meeting recording", type=["mp3", "wav", "mp4", "m4a"]
)
st.caption("Supported: MP3, WAV, MP4, M4A. Maximum 25 MB.")


def reset_review():
    """Forget the old notes and edits (used when new notes are made)."""
    for key in ("notes", "summary_edit", "items_edit"):
        st.session_state.pop(key, None)


# ---------- Step 1: audio -> transcript (calls /meetings) ----------
if audio and st.button("Convert to text"):
    with st.spinner("Converting speech to text..."):
        try:
            response = requests.post(
                f"{API_URL}/meetings",
                files={"file": (audio.name, audio.getvalue())},
                timeout=300,
            )
        except requests.exceptions.ConnectionError:
            st.error("Cannot reach the backend. Is FastAPI running on port 8000?")
            st.stop()

    if response.status_code == 200:
        reset_review()
        st.session_state["transcript"] = response.json()["transcript"]
    else:
        st.error(response.json().get("detail", "Something went wrong"))

# ---------- Step 2: transcript -> notes (calls /notes) ----------
if "transcript" in st.session_state:
    transcript = st.text_area(
        "Transcript (you can edit it)", st.session_state["transcript"], height=250
    )

    if st.button("Generate summary and action items"):
        with st.spinner("AI is writing the notes..."):
            try:
                response = requests.post(
                    f"{API_URL}/notes",
                    json={"transcript": transcript},
                    timeout=120,
                )
            except requests.exceptions.ConnectionError:
                st.error("Cannot reach the backend. Is FastAPI running on port 8000?")
                st.stop()

        if response.status_code == 200:
            reset_review()
            st.session_state["notes"] = response.json()
        else:
            st.error(response.json().get("detail", "Something went wrong"))

# ---------- Step 3: review and edit, then download the PDF (calls /export) ----------
if "notes" in st.session_state:
    notes = st.session_state["notes"]

    st.subheader("Review and edit")

    summary = st.text_area("Summary", notes["summary"], height=150, key="summary_edit")

    st.write("Action items (click a cell to edit, use the empty last row to add one)")
    items_table = pd.DataFrame(
        notes["action_items"], columns=["task", "owner", "deadline"]
    )
    edited_table = st.data_editor(items_table, num_rows="dynamic", key="items_edit")

    # Turn the table into a list and remove rows with an empty task
    rows = edited_table.fillna("").to_dict("records")
    action_items = [row for row in rows if str(row["task"]).strip()]

    # Ask the backend to build the PDF from the edited notes
    try:
        pdf_response = requests.post(
            f"{API_URL}/export",
            json={
                "transcript": transcript,
                "summary": summary,
                "action_items": action_items,
            },
            timeout=60,
        )
        if pdf_response.status_code == 200:
            st.download_button(
                "Download PDF",
                data=pdf_response.content,
                file_name="meeting-notes.pdf",
                mime="application/pdf",
            )
        else:
            st.error("Could not create the PDF.")
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach the backend. Is FastAPI running on port 8000?")
