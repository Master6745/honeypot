
from dotenv import load_dotenv
load_dotenv()  # This loads the keys from the .env filefrom fastapi import FastAPI, Header, HTTPException, Request
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel
from openai import OpenAI
from pymongo import MongoClient # NEW: Database Tool
import re
import os
import json
from datetime import datetime # NEW: For timestamps

# --- CONFIGURATION ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") 
client = OpenAI(api_key=OPENAI_API_KEY)

# --- DATABASE CONNECTION ---
# We get the link from Render settings (Environment Variables)
MONGO_URI = os.environ.get("MONGO_URI") 

# Safety check: If no DB link, we won't crash, we just won't save
if MONGO_URI:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["honeypot_db"]     # Database Name
    chat_collection = db["chat_logs"]    # Table Name
else:
    chat_collection = None
    print("WARNING: No Database Connected!")

app = FastAPI()

# --- THE GATEKEEPER BRAIN ---
SYSTEM_BRAIN_PROMPT = """
You are a Dual-Core Security Agent.
1. ANALYSIS: Check if message is Scam (Phishing, Financial, Tech Support, Job).
2. RESPONSE:
   - IF NOT SCAM: Reply "SAFE".
   - IF SCAM: Activate Persona (Ramesh/Riya/Vikram). Ask questions to get data.

OUTPUT JSON:
{
  "is_scam": boolean,
  "scam_type": "string",
  "selected_persona": "string",
  "reply": "string"
}
"""

# --- HELPER: Extract Data ---
def extract_intelligence(text: str):
    intel = {
        "upi_ids": [],
        "links": [],
        "phone_numbers": []
    }
    intel["upi_ids"] = re.findall(r'[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}', text)
    intel["links"] = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', text)
    intel["phone_numbers"] = re.findall(r'\b\d{10}\b', text)
    return intel

# --- THE ENDPOINT ---
@app.post("/chat")
async def chat_endpoint(request: Request, x_api_key: str = Header(None)):
    
    # 1. SECURITY CHECK
    if x_api_key != "my-secret-password-123":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. GET THE MESSAGE
    body = await request.json()
    scammer_msg = body.get("message") or body.get("text") or body.get("input")
    
    if not scammer_msg:
        return {"error": "No message found"}

    # 3. ASK THE BRAIN
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
        is_scam = ai_data["is_scam"]
    except Exception as e:
        print(f"Error: {e}")
        return {"error": "AI Processing Failed"}

    # 4. PREPARE THE LOG (What we will save)
    # We save everything, even if we decide to ignore it
    log_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "scammer_message": scammer_msg,
        "is_scam": is_scam,
        "scam_type": ai_data.get("scam_type"),
        "persona_used": ai_data.get("selected_persona"),
        "bot_reply": ai_data.get("reply"),
        "intelligence_extracted": {},
        "status": "ignored"
    }

    # 5. LOGIC BRANCHING
    if not is_scam:
        # Save to DB before returning
        if chat_collection is not None:
            chat_collection.insert_one(log_entry)
            
        return {"status": "ignored", "reply": None}

    # IF SCAM -> EXTRACT INTEL
    intelligence_data = extract_intelligence(scammer_msg)
    
    # Update the Log with the extracted data
    log_entry["intelligence_extracted"] = intelligence_data
    log_entry["status"] = "engaged"
    
    if intelligence_data["upi_ids"] or intelligence_data["links"]:
        log_entry["status"] = "intelligence_captured"

    # Save to DB
    if chat_collection is not None:
        chat_collection.insert_one(log_entry)

    return {
        "reply": ai_data["reply"],
        "intelligence": intelligence_data,
        "status": log_entry["status"],
        "meta": {"saved_to_db": True}
    }