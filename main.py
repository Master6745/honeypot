from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from openai import OpenAI
from pymongo import MongoClient
import re
import os
import json
from datetime import datetime

# --- CONFIGURATION ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") 
client = OpenAI(api_key=OPENAI_API_KEY)

# --- DATABASE CONNECTION ---
MONGO_URI = os.environ.get("MONGO_URI") 

if MONGO_URI:
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = mongo_client["honeypot_db"]
        chat_collection = db["chat_logs"]
        # Test the connection immediately
        mongo_client.server_info()
        print("SUCCESS: Connected to MongoDB")
    except Exception as e:
        chat_collection = None
        print(f"WARNING: Database connection failed: {e}")
else:
    chat_collection = None
    print("WARNING: No MONGO_URI found in Environment Variables.")

app = FastAPI()

@app.get("/")
def home():
    return {"status": "alive", "message": "Honeypot Agent is running!"}

# --- THE AGENT BRAIN ---
# This instruction forces the AI to "Chat" if it detects a scam.
SYSTEM_BRAIN_PROMPT = """
You are a Counter-Scam Intelligence Agent.
1. ANALYZE: Is this message a Scam? (Financial, Tech Support, Job, Romance).
2. ACTION:
   - IF SAFE: Output 'is_scam': false. Reply "SAFE".
   - IF SCAM: Output 'is_scam': true. 
     * ACTIVATE PERSONA:
       - Tech Support -> "Ramesh" (Confused old man).
       - Job/Money -> "Riya" (Greedy student).
       - Lottery/Bank -> "Vikram" (Suspicious shopkeeper).
     * GOAL: Reply to the user. Ask a specific question to get their UPI, Phone, or Link.
     * TONE: Keep it short (1-2 sentences). Act dumb or greedy.

OUTPUT JSON:
{
  "is_scam": boolean,
  "scam_type": "string",
  "selected_persona": "string",
  "reply": "string"
}
"""

# --- SMARTER INTEL EXTRACTOR ---
def extract_intelligence(text: str):
    intel = {
        "upi_ids": [],
        "links": [],
        "phone_numbers": []
    }
    # 1. Capture UPI (example@okicici)
    intel["upi_ids"] = re.findall(r'[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}', text)
    
    # 2. Capture Links (http/https)
    intel["links"] = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', text)
    
    # 3. Capture Phone Numbers (Smart Match)
    # Matches: 888-555-0199, +91 98765 43210, 9876543210, 1800-123-4567
    phone_pattern = r'\b(?:\+?\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b'
    intel["phone_numbers"] = re.findall(phone_pattern, text)
    
    return intel

@app.post("/chat")
async def chat_endpoint(request: Request, x_api_key: str = Header(None)):
    
    if x_api_key != "my-secret-password-123":
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        body = await request.json()
    except:
        return {"error": "Invalid JSON"}
        
    scammer_msg = body.get("message") or body.get("text") or body.get("input")
    
    if not scammer_msg:
        return {"error": "No message found"}

    # --- BRAIN PROCESSING ---
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_BRAIN_PROMPT},
                {"role": "user", "content": f"Incoming Message: '{scammer_msg}'"}
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=1.0
        )
        ai_data = json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"AI Error: {e}")
        return {"error": "AI Brain Failed"}

    # --- DATA EXTRACTION ---
    intelligence_data = extract_intelligence(scammer_msg)
    
    # --- LOGGING ---
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "scammer_message": scammer_msg,
        "is_scam": ai_data["is_scam"],
        "scam_type": ai_data.get("scam_type"),
        "persona_used": ai_data.get("selected_persona"),
        "bot_reply": ai_data.get("reply"),
        "intelligence_extracted": intelligence_data,
        "status": "engaged" if ai_data["is_scam"] else "ignored"
    }

    if intelligence_data["upi_ids"] or intelligence_data["links"] or intelligence_data["phone_numbers"]:
        log_entry["status"] = "intelligence_captured"

    # Save to Database (if connected)
    saved_status = False
    if chat_collection is not None:
        try:
            chat_collection.insert_one(log_entry)
            saved_status = True
        except Exception as e:
            print(f"DB Error: {e}")

    # --- FINAL RESPONSE ---
    # If it's a scam, we reply. If safe, we stay silent (None).
    response_reply = ai_data["reply"] if ai_data["is_scam"] else None

    return {
        "reply": response_reply,
        "intelligence": intelligence_data,
        "status": log_entry["status"],
        "meta": {"saved_to_db": saved_status}
    }