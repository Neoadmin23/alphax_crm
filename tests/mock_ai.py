"""Mock AI server for AlphaX CRM tests. Speaks Ollama (/api/chat, /api/tags) and
OpenAI-compatible (/v1/chat/completions, /v1/models). Picks a canned answer from the system
prompt, records every request to /srv/mock/ax/<n>.json, and misbehaves on purpose where the
app's safety rules must catch it.  Run: python mock_ai.py [port]"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT = "/srv/mock/ax"
os.makedirs(OUT, exist_ok=True)
TYPOS = {"recieve": "receive", "maintainance": "maintenance", "teh": "the", "Recieved": "Received",
         "الشركه": "الشركة", "اسعار": "أسعار", "مسؤل": "مسؤول"}
BAD = [{"original": "please deliver", "corrected": "kindly ship"}, {"original": "HP 26A", "corrected": "HP 26X"},
       {"original": "Neotek", "corrected": "Neotech"}, {"original": "ghostword", "corrected": "ghost word"}]
COUNTER = [len(os.listdir(OUT))]  # continue numbering after a restart


def answer(system, user):
    s = system
    if "classify a client's email" in s:
        t = user.lower()
        if "postpone" in t or "next quarter" in t or "تأجيل" in user:
            return {"intent": "postpone", "confidence": 88, "summary": "Client asks to revisit next quarter."}
        if "sign" in t or "contract" in t:
            return {"intent": "ready_to_sign", "confidence": 91, "summary": "Client asks for the contract."}
        if "discount" in t or "revise" in t:
            return {"intent": "revision", "confidence": 80, "summary": "Client asks for a revised price."}
        if "not interested" in t:
            return {"intent": "rejected", "confidence": 90, "summary": "Client declined."}
        return {"intent": "interested", "confidence": 70, "summary": "Client wants details."}
    if "Write a brief for the salesperson" in s:
        return {"summary": "Retail chain evaluating POS; quotation sent.", "last_interaction": "Email on the latest date asking about pricing.",
                "open_items": ["Reply to pricing question", "Quotation follow-up"]}
    if "spelling corrector" in s:
        text = user.split("<<<", 1)[-1]
        ch = [{"original": k, "corrected": v} for k, v in TYPOS.items()
              if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", text)]
        ch += [b for b in BAD if b["original"] in text or b["original"] == "ghostword"]
        return {"changes": ch}
    if "professional business translator" in s:
        arabic = "Modern Standard Arabic" in s
        prefix = "ترجمة: " if arabic else "Translation: "
        if user.startswith("Translate each string"):
            arr = json.loads(user.split("\n", 1)[1])
            return {"translations": [prefix + x for x in arr]}
        out = prefix + user
        if "DROPTOKEN" in user:
            out = out.replace("⟦1⟧", "")
        if "CHANGENUM" in user:
            out = out.replace("500", "600")
        return {"translation": out}
    if "writing assistant" in s:
        tag = "Improved" if "Improve the wording" in s else "Formal" if "formal business tone" in s else "Short"
        return {"text": f"{tag}: {user}"}
    if "coach a B2B salesperson" in s:
        return {"summary": "Engaged lead asking for POS pricing for 12 branches.",
                "next_action": "Call Sara to confirm branch count and book a demo",
                "channel": "Call", "in_days": 1, "reasons": ["Replied within 24h", "Clear need", "Open quotation"]}
    if "research prospect companies" in s:
        return {"brief": "Acme runs 12 retail stores in Riyadh.", "industry": "Retail", "size_hint": "unknown",
                "relevance": "Needs a ZATCA-ready POS."}
    if "sequence to this lead" in s:
        step = re.search(r"Write email (\d+) of (\d+)", s).group(1)
        lang = "Arabic" if "Modern Standard Arabic" in s else "English"
        return {"subject": f"Step {step} ({lang})", "body_html": f"<p>Hello, follow-up {step}.</p>"}
    if "about to expire" in s:
        return {"subject": "Your quotation is about to expire", "body_html": "<p>Kind reminder.</p>"}
    if "query planner" in s:
        if "by source" in user.lower() or "حسب المصدر" in user:
            return {"capability": "aggregate", "params": {"doctype": "Lead", "group_by": "source", "metric": "count"}}
        ans = "مرحبا، هذه إجابة عامة." if "Modern Standard Arabic" in s else "Hello, this is a general answer."
        return {"capability": "none", "answer": ans}
    if "CRM assistant. The user asked" in s:
        return "يوجد عملاء محتملون حسب المصدر." if "Modern Standard Arabic" in s else "There are leads by source."
    if "sales qualification assistant" in s:
        return {"fit": "High", "urgency": "Medium", "intent": "POS for branches", "summary": "Good fit lead."}
    if "first response" in s:
        return "Thank you for contacting us. شكرا لتواصلكم."
    if "Summarize this sales opportunity" in s:
        return "Opportunity is progressing; next step is a demo."
    if "connection test" in s:
        return "OK"
    return "unhandled"


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            return self._send(200, {"models": [{"name": "llama3.1"}, {"name": "qwen3.5-9b"}]})
        if self.path.endswith("/models"):
            return self._send(200, {"data": [{"id": "llama3.1"}, {"id": "qwen3.5-9b"}]})
        self._send(404, {})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = req.get("messages", [])
        system = next((m["content"] for m in msgs if m["role"] == "system"), "")
        user = next((m["content"] for m in msgs if m["role"] == "user"), "")
        COUNTER[0] += 1
        json.dump({"path": self.path, "headers": dict(self.headers), "req": req},
                  open(f"{OUT}/{COUNTER[0]:05d}.json", "w"), ensure_ascii=False)
        if "FAIL500" in user:
            return self._send(500, {"error": "boom"})
        result = answer(system, user)
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        if self.path == "/api/chat":
            return self._send(200, {"message": {"role": "assistant", "content": content},
                                    "prompt_eval_count": 100, "eval_count": 50})
        if self.path.endswith("/chat/completions"):
            return self._send(200, {"choices": [{"message": {"role": "assistant", "content": content}}],
                                    "usage": {"prompt_tokens": 120, "completion_tokens": 60}})
        self._send(404, {"error": "unknown path"})

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8090), H).serve_forever()
