import os
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import requests
import mysql.connector
import re

# --------------------------------------------------
# CONFIG & APP INITIALIZATION (MUST BE AT THE TOP)
# --------------------------------------------------
app = Flask(__name__)  # <--- THIS WAS MISSING AT THE TOP
CORS(app)

API_KEY = os.getenv("AIzaSyA_5ST3kWAsMY4GS23FLeAiPkR_-Su1Shs")

TRANSCRIPT_PATH = os.path.join("transcripts", "ai_ml.txt")
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "ragdb",
    "port": 3307
}

# --------------------------------------------------
# FRONTEND UI (The Visual Chat Window)
# --------------------------------------------------
@app.route("/")
def home():
    html_code = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Course Assistant</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: 'Segoe UI', sans-serif; margin: 0; display: flex; flex-direction: column; height: 100vh; background: #f0f2f5; }
            .chat-container { flex: 1; padding: 15px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
            .msg { max-width: 85%; padding: 10px 14px; border-radius: 18px; line-height: 1.5; font-size: 14px; }
            .user { align-self: flex-end; background: #003366; color: white; border-bottom-right-radius: 4px; }
            .bot { align-self: flex-start; background: white; color: #333; border: 1px solid #ddd; border-bottom-left-radius: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.1); }
            .input-area { padding: 10px; background: white; border-top: 1px solid #ddd; display: flex; gap: 8px; }
            input { flex: 1; padding: 12px; border: 1px solid #ccc; border-radius: 25px; outline: none; font-size: 14px; }
            button { background: #003366; color: white; border: none; padding: 10px 20px; border-radius: 25px; cursor: pointer; font-weight: 600; }
            .loading { font-size: 12px; color: #666; margin-left: 15px; display: none; margin-bottom: 5px; }
        </style>
    </head>
    <body>
        <div class="chat-container" id="box">
            <div class="msg bot">👋 Hi! I'm your AI Course Assistant. Ask me anything from the syllabus!</div>
        </div>
        <div class="loading" id="typing">AI is thinking...</div>
        <div class="input-area">
            <input type="text" id="inp" placeholder="Type a question..." onkeypress="if(event.key==='Enter') send()">
            <button onclick="send()">Send</button>
        </div>

        <script>
            async function send() {
                const inp = document.getElementById("inp");
                const box = document.getElementById("box");
                const typing = document.getElementById("typing");
                const txt = inp.value.trim();
                if (!txt) return;

                // 1. Show User Message
                box.innerHTML += `<div class="msg user">${txt}</div>`;
                inp.value = "";
                box.scrollTop = box.scrollHeight;
                typing.style.display = "block";

                try {
                    // 2. Call Your Existing API
                    const res = await fetch("/ask", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ question: txt })
                    });
                    const data = await res.json();
                    
                    // 3. Show Bot Response (Convert newlines to HTML breaks)
                    const ans = data.answer.replace(/\\n/g, "<br>");
                    box.innerHTML += `<div class="msg bot">${ans}</div>`;
                } catch (e) {
                    box.innerHTML += `<div class="msg bot" style="color:red">❌ Error connecting to server.</div>`;
                }
                
                typing.style.display = "none";
                box.scrollTop = box.scrollHeight;
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_code)

# --------------------------------------------------
# SAVE CHAT TO DB
# --------------------------------------------------
def save_chat(question, answer):
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO chat_history (question, answer)
            VALUES (%s, %s)
            """,
            (question, answer)
        )
        conn.commit()
        cur.close()
        conn.close()
        print("💾 Chat saved.")
    except Exception as e:
        print("❌ DB ERROR:", e)

# --------------------------------------------------
# TRANSCRIPT CACHE
# --------------------------------------------------
rag_cache = {"chunks": None}
def load_transcript():
    if not os.path.exists(TRANSCRIPT_PATH):
        print("❌ Transcript not found:", os.path.abspath(TRANSCRIPT_PATH))
        return None
    print("📄 Loading transcript…")
    with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    chunks = []
    for i in range(0, len(text), 500):
        part = text[i:i + 500].strip()
        if part:
            chunks.append(part)
    print(f"📑 Loaded {len(chunks)} chunks.")
    return chunks

def get_chunks():
    if rag_cache["chunks"] is None:
        rag_cache["chunks"] = load_transcript()
    return rag_cache["chunks"]

# --------------------------------------------------
# STRICT WORD-LEVEL RANKING
# --------------------------------------------------
def rank_chunks(question, chunks):
    q_words = set(re.findall(r"\b\w+\b", question.lower()))
    scored = []
    for c in chunks:
        c_words = set(re.findall(r"\b\w+\b", c.lower()))
        score = len(q_words & c_words)   # STRICT word match
        scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:5]

# --------------------------------------------------
# GEMINI CALL
# --------------------------------------------------
def ask_gemini(context, question):
    prompt = f"""
You are an AI study assistant for university students.

IMPORTANT FORMATTING RULES (FOLLOW STRICTLY):
- Use ONLY this bullet style: ▸
- Leave EXACTLY ONE BLANK LINE after EVERY bullet point
- Do NOT use '*' or '-' for bullets
- Do NOT write long paragraphs

IMPORTANT CONTENT RULES:
- Explain concepts like a teacher, not like a reporter
- If a term is broader than the transcript, give a short general definition and relate it to the transcript
- If the question is NOT covered in the transcript:
  ▸ Begin with a BOLD line clearly stating it is not covered
  ▸ Leave one blank line after it
  ▸ Then list what the transcript actually discusses in bullet points

When answering:
- Use the transcript as the reference
- You may rephrase and simplify for understanding

Transcript Context:
{context}

User Question:
{question}
"""
    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"

    payload = {
        "model": "gemini-2.5-flash",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    res = requests.post(url, json=payload, headers=headers)
    data = res.json()

    print("📌 Gemini raw:", data)

    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return "I could not extract a valid answer."

# --------------------------------------------------
# SMALL TALK
# --------------------------------------------------
SMALLTALK = {
    "hi": "Hi there! 😊 How can I help you today?",
    "hello": "Hello! 👋 What’s on your mind?",
    "hey": "Heyy! 😄 How’s it going?",
    "heyy": "Heyyy! ✨ What would you like to learn today?",
    "hii": "Hii! 😊 Ask me anything anytime!",
    "how are you": "I'm doing great! 😄 How about *you*?",
    "how are you?": "I’m feeling awesome! 💙 How are *you* doing?",
    "how r u": "I’m good! Thanks for asking 😊 What about you?",
    "i am fine": "That’s wonderful to hear! 😊 Let me know if you need help!",
    "im fine": "Glad to know you're doing fine! 💙 Ask me anything!",
    "i am good": "That’s nice! 😄 Ready to learn something?",
    "i'm good": "Happy to hear that! 😊 What shall we study?",
    "im doing great": "Love that energy!! 🌟 Let’s learn something new!",
    "i am great": "Amazing!! 💙 What can I help you with?",
    "all good": "Great! 😄 Let me know whenever you have doubts!",
    "good": "Nice! 😊 I’m here when you need help.",
    "nice": "Awesome! 😄 What can I help you with?",
    "how is your day": "My day’s been fun helping students like you! 📚💙 How’s yours?",
    "how’s your day": "It's going great! 😄 How about your day?",
    "hows your day": "It's been productive! 💙 What about yours?",
    "thank you": "You're most welcome! 😊 Always happy to help!",
    "thanks": "Anytime! 💙 I’m right here if you need anything!",
    "thankyou": "You're welcome! 😊",
    "i need help": "Of course! 😊 Tell me what you need help with!",
    "can you help me": "Absolutely! 💙 What would you like to understand?",
    "i have a doubt": "Sure! 😊 Tell me your doubt, I’ll explain it simply.",
    "help me": "I got you! ✨ What do you need help with?",
    "explain this": "Sure! 😊 Send it to me — I’ll break it down neatly!",
    "okay": "Okay! 😊 Feel free to ask more questions anytime.",
    "ok": "Alright! 💙 I’m right here if you need anything!",
    "cool": "Cool! 😄 What else can I help you with?",
    "bye": "Bye! 👋 Have a great day!",
    "good night": "Good night! 🌙 Sleep well!",
    "gn": "Good night! 💙 Sweet dreams!"
}

# --------------------------------------------------
# MAIN API
# --------------------------------------------------
@app.route("/ask", methods=["POST"])
def ask():
    question = request.json.get("question", "").strip().lower()
    print("\n-----------------------------")
    print("🔍 New question:", question)
    # SMALL TALK
    for phrase in SMALLTALK:
        if phrase == question:
            answer = SMALLTALK[phrase]
            save_chat(question, answer)
            return jsonify({"answer": answer})
    chunks = get_chunks()
    if chunks is None:
        answer = "Transcript missing, but I can still help! 😊"
        save_chat(question, answer)
        return jsonify({"answer": answer})
    ranked = rank_chunks(question, chunks)
    # ❌ NOT IN SYLLABUS — FINAL GUARANTEE
    if sum(score for score, _ in ranked) == 0:
        answer = "📚 This is not in the syllabus \n\n👉 Please ask questions from the syllabus only 😊"
        save_chat(question, answer)
        return jsonify({"answer": answer})
    best_chunks = [c for _, c in ranked]
    context = "\n\n---\n\n".join(best_chunks)
    answer = ask_gemini(context, question)
    save_chat(question, answer)
    print("🤖 Final Answer:", answer)
    return jsonify({"answer": answer})

# --------------------------------------------------
# RUN SERVER
# --------------------------------------------------
if __name__ == "__main__":
    print("🚀 RAG Server running at http://localhost:8000/ask")
    app.run(host="0.0.0.0", port=8000)
