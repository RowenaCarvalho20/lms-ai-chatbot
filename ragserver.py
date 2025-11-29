import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss
import fitz  # PyMuPDF for PDF

API_KEY = "AIzaSyBbk3_WQRufc8dsR4JNvf4C2pAr3i-hLK4"

app = Flask(__name__)
CORS(app)

# Simple cache
rag_cache = {
    "chunks": None,
    "index": None,
    "model": None
}

TRANSCRIPT_PATH = os.path.join("transcripts", "Video1.txt")   # <-- FIXED PATH


def load_transcript():
    """Loads ONLY ONE transcript file: transcripts/Video1.txt"""

    if not os.path.exists(TRANSCRIPT_PATH):
        print("❌ Transcript file not found:", os.path.abspath(TRANSCRIPT_PATH))
        return None, None, None

    print("📄 Loading transcript:", os.path.abspath(TRANSCRIPT_PATH))

    # Read file
    with open(TRANSCRIPT_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    # Chunk the text
    chunks = []
    for i in range(0, len(text), 500):
        part = text[i:i+500].strip()
        if part:
            chunks.append(part)

    print(f"📑 Created {len(chunks)} chunks from transcript.")

    # Embeddings
    model = SentenceTransformer("sentence-transformers/paraphrase-MiniLM-L3-v2")
    embeddings = model.encode(chunks, convert_to_numpy=True)

    # FAISS index
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)

    print("🔥 Transcript successfully processed!")
    return chunks, index, model



def get_rag():
    """Return cached or freshly loaded embeddings."""
    if rag_cache["chunks"] is None:
        rag_cache["chunks"], rag_cache["index"], rag_cache["model"] = load_transcript()
    return rag_cache["chunks"], rag_cache["index"], rag_cache["model"]



@app.route("/ask", methods=["POST"])
def ask():
    data = request.json
    question = data.get("question", "")

    print("\n==============================")
    print("📌 Incoming question:", question)
    print("==============================")

    chunks, index, model = get_rag()

    if chunks is None:
        return jsonify({"answer": "Transcript file missing on server."})

    # Encode question
    q = model.encode(question, convert_to_numpy=True)

    # FAISS search
    distances, ids = index.search(np.array([q]), 4)
    avg_distance = float(np.mean(distances))

    print("🔍 Average distance:", avg_distance)

    # Reject irrelevant questions
    if avg_distance > 3.0:
        print("⚠ Low similarity, but still answering.")

    # Build context
    context = "\n\n".join([chunks[i] for i in ids[0]])

    # Gemini prompt
    prompt = f"""
Transcript:
{context}

Question:
{question}

Answer based ONLY on the transcript above.
"""

    # Gemini API call
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-latest:generateContent?key={API_KEY}"

    payload = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }

    response = requests.post(url, json=payload)
    data = response.json()

    try:
        answer = data["candidates"][0]["content"]["parts"][0]["text"]
    except:
        answer = "I couldn't extract a valid answer."

    print("🤖 Gemini answer:", answer)
    return jsonify({"answer": answer})



if __name__ == "__main__":
    print("🚀 RAG server running at http://localhost:8000/ask")
    app.run(host="0.0.0.0", port=8000)
