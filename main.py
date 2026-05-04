import os
import json
import re
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# Firebase init
cred_json = os.environ.get("FIREBASE_CREDENTIALS")
if cred_json:
    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
else:
    cred = credentials.Certificate("serviceAccount.json")

firebase_admin.initialize_app(cred)
db = firestore.client()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

# ──────────────────────────────────────────
# Parser: رسالة واحدة → قايمة سجلات
# ──────────────────────────────────────────
def extract_field(text, key):
    pattern = rf"{key}\s*[:\-]\s*([^\n\r]+)"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None

def parse_message(text):
    if not text:
        return []

    يوم    = extract_field(text, "اليوم")
    تاريخ  = extract_field(text, "التاريخ")
    مجموعة = extract_field(text, "المجموعة")

    if not يوم and not مجموعة:
        return []

    projects   = re.findall(r"المشروع\s*[:\-]\s*([^\n\r]+)", text)
    personnels = re.findall(r"عدد الأفراد\s*[:\-]\s*([^\n\r]+)", text)
    engineers  = re.findall(r"مهندس الموقع\s*[:\-]\s*([^\n\r]+)", text)

    projects   = [p.strip() for p in projects]
    personnels = [p.strip() for p in personnels]
    engineers  = [p.strip() for p in engineers]

    if not projects:
        return [{
            "اليوم":        يوم or "—",
            "التاريخ":      تاريخ or "—",
            "المجموعة":     مجموعة or "—",
            "المشروع":      "—",
            "عدد الأفراد":  personnels[0] if personnels else "—",
            "مهندس الموقع": engineers[0] if engineers else "—",
        }]

    records = []
    for i, proj in enumerate(projects):
        records.append({
            "اليوم":        يوم or "—",
            "التاريخ":      تاريخ or "—",
            "المجموعة":     مجموعة or "—",
            "المشروع":      proj,
            "عدد الأفراد":  personnels[i] if i < len(personnels) else "—",
            "مهندس الموقع": engineers[i] if i < len(engineers) else "—",
        })
    return records

# ──────────────────────────────────────────
# Webhook endpoint
# ──────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
@app.route("/webhook/<path:token>", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": True})

    # ── رسالة جديدة أو معدلة ──
    message = data.get("message") or data.get("edited_message")
    if message:
        chat_id  = str(message.get("chat", {}).get("id", ""))
        msg_id   = str(message.get("message_id", ""))
        text     = message.get("text", "")

        # امسح السجلات القديمة لنفس الرسالة (في حالة تعديل)
        old_docs = db.collection("haraka").where("_msgId", "==", msg_id).stream()
        for doc in old_docs:
            doc.reference.delete()

        # احفظ السجلات الجديدة
        records = parse_message(text)
        for i, rec in enumerate(records):
            rec["_msgId"]  = msg_id
            rec["_chatId"] = chat_id
            doc_id = f"{msg_id}_{i}"
            db.collection("haraka").document(doc_id).set(rec)

    # ── رسالة اتمسحت ──
    deleted = (data.get("message") or {})
    if "deleted_messages" in data:
        for d in data["deleted_messages"]:
            msg_id = str(d.get("message_id", ""))
            old_docs = db.collection("haraka").where("_msgId", "==", msg_id).stream()
            for doc in old_docs:
                doc.reference.delete()

    # Telegram بيبعت deleted كـ update منفصل
    if data.get("message") is None and data.get("edited_message") is None:
        # ممكن يكون deleted_message في شكل تاني
        pass

    return jsonify({"ok": True})

@app.route("/", methods=["GET"])
def index():
    return "Daily Haraka Webhook is running ✅"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
