import io
import json
import os
import pdfplumber
from flask import Flask, request, jsonify, render_template, send_file
from anthropic import Anthropic
from dotenv import load_dotenv
from pdf_generator import ResumeTooLongError, generate_resume_pdf

load_dotenv()

app = Flask(__name__)
client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def _env_flag(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _startup_url(host, port):
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}"


def run_server():
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", os.environ.get("APP_PORT", "5000")))

    if not _env_flag("USE_WAITRESS"):
        app.run(debug=True, host=host, port=port)
        return

    print(f"Open {_startup_url(host, port)}", flush=True)

    try:
        from waitress import serve
    except ImportError as exc:
        raise RuntimeError(
            "Waitress is not installed. Run `pip install -r requirements.txt`."
        ) from exc

    serve(app, host=host, port=port)


@app.route("/")
def index():
    return render_template("index.html")


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


@app.route("/tailor", methods=["POST"])
def tailor():
    data = request.get_json()
    resume = data.get("resume", "").strip()
    job_description = data.get("job_description", "").strip()

    if not resume or not job_description:
        return jsonify({"error": "Both resume and job description are required."}), 400

    prompt = f"""You are an expert resume writer. Tailor the provided resume to match the job description.

RULES:
1. Only modify content — rephrase bullets, reorder skills, emphasize relevant experience
2. Do NOT invent experience, jobs, or skills the candidate doesn't have
3. Integrate keywords from the job description naturally where truthful
4. Prioritize the most relevant bullet points first in each role
5. Keep all sections and structural elements
6. Preserve important information and relevant keywords from the original resume whenever truthful
7. The final resume must fit on a single page in a traditional Times-style resume layout
8. Prefer concise wording, but do not drop important experience or relevant keywords just to save space

Return a JSON object with this EXACT schema (no explanation, no markdown, just the JSON):

{{
  "name": "full name",
  "contact": "phone | email | url1 | url2 | url3",
  "sections": [
    {{
      "title": "SECTION NAME IN CAPS",
      "entries": [ ... ]
    }}
  ]
}}

Entry types:
- SKILLS section entries: {{"label": "Category", "text": "skill1, skill2, ..."}}
- All other entries: {{
    "heading": "Organization or Institution Name",
    "heading_right": "Date (optional)",
    "subheading": "Degree or Role (italic, optional)",
    "subheading_right": "GPA or similar (bold, optional)",
    "body": "Paragraph text like Relevant Coursework (optional)",
    "bullets": ["bullet 1", "bullet 2"]
  }}

RESUME:
{resume}

JOB DESCRIPTION:
{job_description}"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude wrapped the JSON
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        resume_json = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: return raw text only (no PDF option)
        return jsonify({"tailored_resume": raw, "resume_json": None})

    display_text = _json_to_text(resume_json)
    return jsonify({"tailored_resume": display_text, "resume_json": resume_json})


@app.route("/download-pdf", methods=["POST"])
def download_pdf():
    data = request.get_json()
    resume_json = data.get("resume_json")
    if not resume_json:
        return jsonify({"error": "No resume data provided."}), 400

    try:
        pdf_bytes = generate_resume_pdf(resume_json)
    except ResumeTooLongError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {e}"}), 500

    name = resume_json.get("name", "Resume").replace(" ", "_")
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{name}_Tailored.pdf",
    )


def _json_to_text(data):
    """Convert structured resume JSON to readable plain text for the UI panel."""
    lines = []
    lines.append(data.get("name", ""))
    lines.append(data.get("contact", ""))
    lines.append("")

    for section in data.get("sections", []):
        lines.append(section["title"])
        lines.append("-" * len(section["title"]))
        entries = section.get("entries", [])
        is_skills = entries and "label" in entries[0]

        for entry in entries:
            if is_skills:
                lines.append(f"{entry.get('label', '')}: {entry.get('text', '')}")
            else:
                head  = entry.get("heading", "")
                hdate = entry.get("heading_right", "")
                lines.append(f"{head}  {hdate}".strip())

                sub  = entry.get("subheading", "")
                subr = entry.get("subheading_right", "")
                if sub or subr:
                    lines.append(f"{sub}  {subr}".strip())

                if entry.get("body"):
                    lines.append(entry["body"])

                for bullet in entry.get("bullets", []):
                    lines.append(f"  • {bullet}")
        lines.append("")

    return "\n".join(lines).strip()


if __name__ == "__main__":
    run_server()
