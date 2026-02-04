from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from openai import OpenAI 
import re
import os

# --- CONFIGURATION ---
# Note: In production, use os.getenv("OPENAI_API_KEY") for security
OPENAI_API_KEY = "" 

client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI()

# --- THE PERSONA ---
PERSONA_SYSTEM_PROMPT = """
You are "Martha", a 74-year-old retired nurse. You are not tech-savvy.
A scammer is messaging you. Your goal is to keep them talking to waste their time.
- Act naive and slightly confused.
- Ask how to send the money or open the link.
- Make occasional typos.
- NEVER admit you are an AI.
- Keep your reply under 3 sentences.
"""

# --- HELPER: Extract Data ---
def extract_intelligence(text: str):
    intel = {
        "upi_ids": [],
        "links": [],
        "phone_numbers": []
    }
    # Using a guard to ensure text is a string
    if not text:
        return intel
        
    intel["upi_ids"] = re.findall(r'[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}', text)
    intel["links"] = re.findall(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', text)
    intel["phone_numbers"] = re.findall(r'\b\d{10}\b', text)
    return intel
# --- THE FRONT DOOR (Root Endpoint) ---
@app.get("/")
def home():
    return {"status": "alive", "message": "Honeypot Agent is running! Send POST requests to /chat"}
# --- THE ENDPOINT ---
@app.post("/chat")
async def chat_endpoint(request: Request, x_api_key: str = Header(None)):
    
    # 1. SECURITY CHECK
    if x_api_key != "my-secret-password-123":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 2. GET THE MESSAGE
    body = await request.json()
    
    # Safely extract message with a fallback to an empty string
    scammer_msg = body.get("message") or body.get("text") or body.get("input") or ""
    
    if not scammer_msg:
        return {"error": "No message field found in JSON"}

    # 3. ANALYZE (Extract Intel)
    intelligence_data = extract_intelligence(scammer_msg)

    # 4. GENERATE REPLY
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": PERSONA_SYSTEM_PROMPT},
                {"role": "user", "content": f"Scammer said: '{scammer_msg}'. Reply as Martha:"}
            ],
            max_tokens=100,
            temperature=0.7
        )
        
        # FIX: Pylance check. completion.choices[0].message.content can be None.
        raw_content = completion.choices[0].message.content
        bot_reply = raw_content.strip() if raw_content is not None else "Oh dear, I'm a bit confused."
        
    except Exception as e:
        print(f"OpenAI Error: {e}")
        bot_reply = "Oh dear, I am having trouble with my internet connection."

    # 5. DETERMINE STATUS
    status = "engaged"
    if intelligence_data["upi_ids"] or intelligence_data["links"]:
        status = "intelligence_captured"

    # 6. RETURN JSON RESPONSE
    return {
        "reply": bot_reply,
        "intelligence": intelligence_data,
        "status": status
    }