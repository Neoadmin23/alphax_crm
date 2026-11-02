# AlphaX GPU server kit · حزمة خادم الذكاء الاصطناعي

An open model (Ollama or vLLM) on your own GPU server, behind **Caddy**:

- **HTTPS** with an automatic Let's Encrypt certificate for your domain.
- **API key** on every request (`Authorization: Bearer …`, which is how AlphaX sends its API Key).
- **Only chat and the model list pass**: `POST /api/chat`, `POST /v1/chat/completions`, `GET /api/tags`,
  `GET /v1/models`. Model management (`/api/pull`, `/api/delete`, `/api/create`, `/api/push`, `/api/show`…)
  and vLLM admin/metrics endpoints answer 404 from the internet. Ollama and vLLM publish no ports.

It can serve as the base of a NeotecAI hosted offering: one kit per customer or region.

## Requirements

| | Minimum | Notes |
|---|---|---|
| GPU | 1 × NVIDIA 24 GB (RTX 4090 / L4 24 GB / A10 24 GB / RTX 6000 Ada) | 27B-class model at 4-bit. 80 GB (H100) for gpt-oss 120B or full precision. |
| RAM / disk | 32 GB RAM · 100 GB SSD | models are 15–60 GB each |
| Software | Ubuntu 22.04/24.04, NVIDIA driver, Docker + NVIDIA Container Toolkit | `nvidia-smi` must work inside Docker |
| Network | ports 80 and 443 open, a DNS A record for `AI_DOMAIN` | e.g. `ai.your-company.sa` |
| Location | a data centre in the Kingdom | keeps CRM data in KSA (PDPL) |

## Install (Ollama, the simplest)

```bash
cp .env.example .env
nano .env                      # AI_DOMAIN, ACME_EMAIL, AI_API_KEY (openssl rand -hex 32), OLLAMA_MODEL
docker compose --profile ollama up -d
docker compose logs -f ollama-pull    # waits for the model download (~17 GB for qwen3.8:27b)
./check.sh
```

## Install (vLLM, for many concurrent users)

```bash
# in .env: UPSTREAM=vllm:8000, VLLM_MODEL, VLLM_SERVED_NAME, VLLM_TOOL_PARSER (see the model card)
docker compose --profile vllm up -d
./check.sh
```

The `--tool-call-parser` matters only for clients that use tool calling (AlphaX itself uses JSON-schema
output). Usual values: `qwen3_coder` for Qwen 3.6+, `openai` for gpt-oss, `llama4_pythonic` for Llama 4,
`mistral` for Mistral. Confirm on each model card.

## What `check.sh` verifies

```
PASS  no key -> 401
PASS  wrong key -> 401
PASS  model management blocked (/api/pull -> 404)
PASS  /api/delete blocked
PASS  models with key (/api/tags): qwen3.8:27b
PASS  chat answer from qwen3.8:27b
```

## Connect AlphaX CRM

AlphaX CRM Settings › AI Assist:

1. **Preset**: *AlphaX GPU server kit* (Ollama) or *vLLM (self-hosted)*. Set **AI Base URL** to
   `https://ai.your-company.sa` (vLLM: `https://ai.your-company.sa/v1`).
2. **API Key**: the `AI_API_KEY` value. Save.
3. **Find Models on Server** → **Use as Model**. Save.
4. **Test Model** → should show **Passed**.
5. **KSA Data Residency Mode** on, and the host in **Allowed AI Hosts**.

## Operations

- Update: `docker compose pull && docker compose --profile ollama up -d`
- Add a model (Ollama): `docker compose exec ollama ollama pull gemma4:e4b` (from the server only)
- Rotate the key: change `AI_API_KEY` in `.env`, `docker compose up -d caddy`, update AlphaX.
- GPU use: `nvidia-smi`; Caddy access log: `docker compose logs caddy`.

---

<div dir="rtl">

## بالعربية

حزمة Docker تشغّل نموذجاً مفتوحاً (Ollama أو vLLM) على خادمكم الخاص خلف **Caddy** الذي يصدر شهادة HTTPS تلقائياً ويتحقق من مفتاح الواجهة البرمجية في كل طلب. لا يمر إلا طلب المحادثة وقائمة النماذج؛ أما إدارة النماذج (التنزيل والحذف وغيرها) فمحجوبة عن الإنترنت.

**المتطلبات:** معالج NVIDIA بذاكرة 24 جيجابايت على الأقل، و32 جيجابايت رام، و100 جيجابايت تخزين SSD، وUbuntu مع Docker وNVIDIA Container Toolkit، والمنفذان 80 و443، وسجل DNS للنطاق، ويفضّل مركز بيانات داخل المملكة.

**التثبيت:**
1. انسخ `.env.example` إلى `.env` واملأ النطاق والبريد والمفتاح (`openssl rand -hex 32`) واسم النموذج.
2. شغّل `docker compose --profile ollama up -d` (أو `--profile vllm`).
3. شغّل `./check.sh`: يجب أن يرفض الطلب بدون مفتاح (401) وأن يعرض النماذج مع المفتاح.

**الربط مع AlphaX CRM:** الإعداد المسبق «AlphaX GPU server kit»، ثم عنوان الخادم والمفتاح، ثم «البحث عن النماذج على الخادم»، ثم «اختبار النموذج» حتى تظهر النتيجة **ناجح**، ثم تفعيل وضع إقامة البيانات وإضافة النطاق إلى المضيفين المسموح بهم.

</div>
