import json
import os
import uuid
from typing import List                                   

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException, Response   
from groq import Groq
from pydantic import BaseModel

from pdf_export import build_pdf                          

# Read the secrets from the .env file in this folder
load_dotenv()

app = FastAPI(title="AI Meeting Notes Generator")

# The API key comes from the .env file (never write it directly in the code)
api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise RuntimeError("GROQ_API_KEY is missing. Add it to backend/.env")

client = Groq(api_key=api_key)

os.makedirs("uploads", exist_ok=True)

ALLOWED = (".mp3", ".wav", ".mp4", ".m4a")
MAX_MB = 25  
STT_MODEL = os.getenv("STT_MODEL" , "whisper-large-v3-turbo")                         # Groq free tier limit for one file
STT_MODEL = "whisper-large-v3-turbo"  # speech-to-text model
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")  # summary + action items

# The instructions we give to the AI (called the "prompt")
SYSTEM_PROMPT = """You are a meeting assistant.
Use ONLY what is said in the transcript. Never invent anything.
Reply with JSON only, in exactly this format:
{
  "summary": "3 to 5 short sentences about the meeting",
  "action_items": [
    {"task": "what must be done", "owner": "who will do it", "deadline": "by when"}
  ]
}
Rules:
- If the owner or deadline was not said, write "not mentioned".
- If there are no tasks, use an empty list for action_items."""


# ---------- Data shapes (what each endpoint expects to receive) ----------
class NotesRequest(BaseModel):
    transcript: str


class ActionItem(BaseModel):                              
    task: str
    owner: str = "not mentioned"
    deadline: str = "not mentioned"


class ExportRequest(BaseModel):                           
    transcript: str
    summary: str
    action_items: List[ActionItem]


# ---------- Step: File valid? ----------
def validate_file(filename: str, data: bytes):
    if not filename.lower().endswith(ALLOWED):
        raise HTTPException(400, "Wrong file type. Use mp3, wav, mp4 or m4a.")
    if len(data) == 0:
        raise HTTPException(400, "The file is empty.")
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File is too big. Maximum is {MAX_MB} MB.")


# ---------- Step: Convert speech to text ----------
def transcribe_audio(filename: str, data: bytes) -> str:
    result = client.audio.transcriptions.create(
        file=(filename, data),
        model=STT_MODEL,
    )
    return result.text


# ---------- Steps: Summarize with AI + Find action items (one call) ----------
def summarize_and_extract(transcript: str) -> dict:
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcript:\n{transcript}"},
        ],
        response_format={"type": "json_object"},  # the AI must answer in JSON
        temperature=0,                            # 0 = stable, no creativity
    )
    answer = response.choices[0].message.content  # the answer is text (JSON)
    data = json.loads(answer)                     # turn the text into a Python dict
    return {
        "summary": data.get("summary", ""),
        "action_items": data.get("action_items", []),
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "message": "AI Meeting Notes API is running"
    }


# ---------- Endpoint 1: audio in, transcript out ----------
@app.post("/meetings")
async def upload_meeting(file: UploadFile):
    data = await file.read()

    # File valid? (No -> error goes back to the user)
    validate_file(file.filename, data)

    # Upload recording: save the file with a unique name
    ext = os.path.splitext(file.filename)[1].lower()
    saved_name = f"{uuid.uuid4().hex}{ext}"
    with open(f"uploads/{saved_name}", "wb") as f:
        f.write(data)

    # Yes -> Convert speech to text
    try:
        transcript = transcribe_audio(file.filename, data)
    except Exception as e:
        raise HTTPException(502, f"Speech-to-text failed: {e}")

    if not transcript.strip():
        raise HTTPException(400, "No speech was found in this recording.")

    return {"saved_as": saved_name, "transcript": transcript}


# ---------- Endpoint 2: transcript in, summary + action items out ----------
@app.post("/notes")
def create_notes(request: NotesRequest):
    if not request.transcript.strip():
        raise HTTPException(400, "The transcript is empty.")

    try:
        return summarize_and_extract(request.transcript)
    except Exception as e:
        raise HTTPException(502, f"AI notes failed: {e}")


# ---------- Endpoint 3 (NEW): the reviewed notes in, PDF file out ----------
@app.post("/export")
def export_pdf(request: ExportRequest):
    items = [item.model_dump() for item in request.action_items]
    pdf_bytes = build_pdf(request.summary, items, request.transcript)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="meeting-notes.pdf"'},
    )