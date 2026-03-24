import io
import os
import pdfplumber
from flask import Flask, request, jsonify, render_template
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tailor", methods=["POST"])
def tailor():
    data = request.get_json()
    resume = data.get("resume", "").strip()
    job_description = data.get("job_description", "").strip()

    if not resume or not job_description:
        return jsonify({"error": "Both resume and job description are required."}), 400

    prompt = f"""You are an expert resume writer. Your task is to tailor the provided resume to match the job description as closely as possible.

CRITICAL RULES:
1. Preserve the EXACT formatting, structure, and layout of the original resume (spacing, line breaks, bullet points, capitalization, section headers, etc.)
2. Only modify the CONTENT — rephrase bullet points, reorder skills, and emphasize relevant experience to match the job description
3. Do NOT add fake experience, jobs, or skills the candidate doesn't have
4. Do NOT remove sections or structural elements
5. Integrate keywords and phrases from the job description naturally where truthful
6. Prioritize and reorder bullet points so the most relevant ones appear first
7. Return ONLY the tailored resume — no explanations, no commentary, no markdown code blocks

ORIGINAL RESUME:
{resume}

JOB DESCRIPTION:
{job_description}

TAILORED RESUME:"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    tailored = message.content[0].text.strip()
    return jsonify({"tailored_resume": tailored})


@app.route("/upload-pdf", methods=["POST"])
def upload_pdf():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported."}), 400

    pdf_bytes = f.read()
    text_lines = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text(layout=True)
            if page_text:
                text_lines.append(page_text)

    full_text = "\n\n".join(text_lines).strip()

    if not full_text:
        return jsonify({"error": "Could not extract text from this PDF."}), 422

    return jsonify({"text": full_text})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
