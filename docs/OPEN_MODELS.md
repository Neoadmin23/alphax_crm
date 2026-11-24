# Open models for AlphaX CRM AI · النماذج المفتوحة لذكاء AlphaX CRM

> AlphaX CRM 0.42 · checked November 2026. Ratings are guidance; **Test Model** on your own server is the real check.

## Why the model is not inside the app

A model is not code: it is tens of gigabytes of weights and needs a GPU. The full Qwen3.8 27B download is
about 55 GB and wants an 80 GB-class GPU at full precision; even a 4-bit build needs about 14–17 GB of GPU
memory. Frappe Cloud has no GPUs and an app package cannot carry files of that size. So the model runs on its
own GPU server (Ollama or vLLM, both free and open source) and AlphaX connects to it. A server in the Kingdom,
on your network, is also the strongest PDPL position: it passes **KSA Data Residency Mode**.

## The guide

| Model | Licence | GPU size | Arabic | Suitable for | Ollama tag | vLLM / Hugging Face |
|---|---|---|---|---|---|---|
| **Qwen3.8 27B** ⭐<br><sub>27B dense</sub> | Apache 2.0 | 1 x 24 GB (4-bit, ~14 GB weights) · 80 GB for full precision (~54 GB) | Very good (ممتاز) | All AI features | `qwen3.8:27b` | `Qwen/Qwen3.8-27B` |
| **Qwen3.6 27B** ⭐<br><sub>27B dense</sub> | Apache 2.0 | 1 x 24 GB (4-bit, ~17 GB) | Very good (ممتاز) | All AI features | `qwen3.6:27b` | `Qwen/Qwen3.6-27B` |
| **Qwen3.6 35B-A3B (MoE)**<br><sub>35B total / 3B active</sub> | Apache 2.0 | 1 x 24 GB (4-bit, ~20 GB) | Very good (ممتاز) | All AI features | `qwen3.6:35b` | `Qwen/Qwen3.6-35B-A3B` |
| **gpt-oss 20B**<br><sub>21B total / 3.6B active</sub> | Apache 2.0 | 1 x 16 GB | Fair (مقبول) | All AI features | `gpt-oss:20b` | `openai/gpt-oss-20b` |
| **gpt-oss 120B**<br><sub>117B total / 5.1B active</sub> | Apache 2.0 | 1 x 80 GB (H100 class) | Good (جيد) | Data centre | `gpt-oss:120b` | `openai/gpt-oss-120b` |
| **Gemma 4 26B A4B (MoE)**<br><sub>26B total / 3.8B active</sub> | Apache 2.0 | 1 x 24 GB (4-bit) | Good (جيد) | All AI features | `gemma4:26b` | `google/gemma-4-26b-a4b-it` |
| **Gemma 4 31B**<br><sub>31B dense</sub> | Apache 2.0 | 1 x 24 GB at 32K context (tight) · 48 GB recommended | Good (جيد) | All AI features | `gemma4:31b` | `google/gemma-4-31b-it` |
| **Gemma 4 E4B** ⭐<br><sub>~4B effective</sub> | Apache 2.0 | 8 GB GPU or CPU | Fair (مقبول) | Light use (Fast Model) | `gemma4:e4b` | `google/gemma-4-e4b-it` |
| **Llama 4 Scout**<br><sub>109B total / 17B active</sub> | Llama 4 Community Licence | ~55 GB at 4-bit (2 x 24 GB or 1 x 80 GB) | Good (جيد) | Data centre | `llama4:scout` | `meta-llama/Llama-4-Scout-17B-16E-Instruct` |
| **Mistral Small 4**<br><sub>119B total / 6B active</sub> | Apache 2.0 | 4 x H100 or 2 x H200 (vendor minimum) | Fair (مقبول) | Data centre | `—` | `mistralai (Mistral Small 4 collection)` |
| **Mistral Small 3.2 24B**<br><sub>24B dense</sub> | Apache 2.0 | 1 x 24 GB (4-bit) | Fair (مقبول) | All AI features | `mistral-small3.2` | `mistralai/Mistral-Small-3.2-24B-Instruct-2506` |
| **DeepSeek V4 Flash**<br><sub>284B total / 13B active</sub> | MIT | 8 x B200 class (data centre) | Good (جيد) | Data centre | `—` | `deepseek-ai (DeepSeek V4 collection)` |

⭐ = recommended starting point (main model, or Fast Model for the small one).

- **All AI features**: lead brief, drafts, intent detection, next best action, quotation reminders, follow-up
  sequences and Ask AI. Use 27B-class models or larger here.
- **Light use**: spell check and translation as the *Fast Model*. Small models (2B–9B) fumble Ask AI and
  multi-step reasoning.
- **Data centre**: needs one 80 GB GPU or several GPUs.
- Licences: Apache 2.0 and MIT allow commercial use. The **Llama 4 Community Licence** has use restrictions:
  read it before production use.

## In AlphaX CRM Settings › AI Assist

1. **Preset**: *Ollama (self-hosted)*, *vLLM (self-hosted)*, *AlphaX GPU server kit* or *OpenRouter (hosted
   open models)*. It fills in the server type and address.
2. **Find Models on Server** lists what is installed (Ollama `/api/tags`, vLLM/OpenAI `/v1/models`), labels the
   models the guide knows, and fills in **Model** or **Fast Model** with one click. The saved API key is only
   sent to the server it was saved for.
3. **Open Models Guide** (also from the setup-script dialog) shows the table above with **Use as Model** /
   **Use as Fast Model** buttons.
4. **Test Model** / **Test Fast Model** run four checks with the prompts AlphaX really uses:
   1. *Structured JSON*: lead qualification in the required JSON shape (essential)
   2. *Arabic spelling*: finds الشركه → الشركة and other Arabic typos
   3. *Ask AI planner*: picks the right capability (AlphaX's tool call) for an English question
   4. *Arabic request*: the same decision for a question asked in Arabic

   Result: **Passed** (4/4), **Partial**, or **Failed** (JSON failed or nothing passed).
   - A main model that **Failed** is kept away from automatic AI: lead classification, next best action,
     intent detection, quotation reminders, follow-up sequences and Ask AI planning. Writing tools and
     drafts a person reviews keep working.
   - A Fast Model that **Failed** is not used; the main model takes over.
   - Changing the server address, server type, path or model resets the result to **Not tested**.
   - **Run Health Check** reports Failed (problem), Partial or Not tested (warning).

## Free hosted tiers

OpenRouter models ending in `:free` (and the `openrouter/free` router) are marked **Free tier · External**.
Their hosts may keep or train on prompts and limits are low (about 20 requests per minute). AlphaX therefore:
- always masks emails and phone numbers before the call, even if PII masking is off;
- blocks them completely in **KSA Data Residency Mode**, even if `openrouter.ai` is in Allowed AI Hosts;
- shows a Health Check warning while one is selected.

Use them to try things out, not for production.

## About Claude and "free Claude" repositories

Anthropic has never released Claude's model weights; Claude is available only through the paid API.
Repositories that offer "free Claude" are proxies reselling someone else's key or unofficial copies.
Do not connect an ERP to them: company data would pass through an unknown server.

## Suggested first setup

1. One 24 GB GPU server in the Kingdom with **Qwen3.8 27B** (or Qwen3.6 27B) on Ollama, using the kit in
   `deploy/gpu-server/`.
2. Preset *AlphaX GPU server kit* → **Find Models on Server** → **Test Model** until it shows **Passed**.
3. Turn on **KSA Data Residency Mode** and add the server's host to Allowed AI Hosts.
4. Optional: `gemma4:e4b` as **Fast Model** for quicker spell check, after **Test Fast Model**.

## Known limits

- Open models still trail the best closed models on reliability at high volume. Keep a person reviewing
  drafts (AlphaX never sends or changes stages without confirmation).
- Ollama tags and Hugging Face names change between releases: **Find Models on Server** shows what is really
  installed; models outside the guide work too after a passed self-test.

---

<div dir="rtl">

## ملخص بالعربية

**لماذا لا يكون النموذج داخل التطبيق؟** النموذج ليس برنامجاً بل ملفات أوزان بعشرات الجيجابايت تحتاج إلى معالج رسومي (GPU). لذلك يعمل النموذج على خادم GPU مستقل (Ollama أو vLLM) ويتصل به AlphaX. وجود الخادم داخل المملكة وعلى شبكتكم هو الأقوى من ناحية نظام حماية البيانات الشخصية، ويجتاز **وضع إقامة البيانات في المملكة**.

**في إعدادات AlphaX CRM ← المساعد الذكي:**
1. **الإعداد المسبق (Preset):** ‏Ollama أو vLLM ذاتي الاستضافة، أو حزمة خادم GPU من AlphaX، أو OpenRouter (خارجي).
2. **البحث عن النماذج على الخادم:** يعرض النماذج المثبتة فعلاً، ويميز المعروفة منها في الدليل، ويعبئ اسم النموذج بنقرة واحدة.
3. **دليل النماذج المفتوحة:** الترخيص، حجم الـGPU، جودة العربية، والاستخدام المناسب لكل نموذج.
4. **اختبار النموذج:** أربعة فحوص (أحدها طلب بالعربية): مخرجات JSON، التدقيق الإملائي العربي، اختيار الأداة في «اسأل الذكاء»، ونفس الاختيار لسؤال عربي. النتيجة: ناجح، جزئي، أو فاشل. النموذج الفاشل لا يُستخدم في الأتمتة التلقائية، والنموذج السريع الفاشل يُستبدل بالنموذج الرئيسي. تغيير عنوان الخادم أو النموذج يعيد النتيجة إلى «لم يُختبر».

**الطبقات المجانية المستضافة** (نماذج OpenRouter المنتهية بـ `:free`) تُعامل دائماً كخدمة **خارجية**: تُخفى البيانات الشخصية دائماً، وتُحجب تماماً في وضع إقامة البيانات، ويظهر تحذير في فحص الصحة. للتجربة فقط وليست للإنتاج.

**Claude:** لم تنشر Anthropic أوزان Claude إطلاقاً، وهو متاح فقط عبر الواجهة البرمجية المدفوعة. المستودعات التي تعرض «Claude مجاناً» وسطاء أو نسخ غير رسمية؛ لا تربطوا نظام ERP بها.

**البداية المقترحة:** خادم بمعالج 24 جيجابايت داخل المملكة يشغّل **Qwen3.8 27B** عبر Ollama باستخدام الحزمة في `deploy/gpu-server/`، ثم «البحث عن النماذج» ← «اختبار النموذج» حتى تظهر **ناجح**، ثم تفعيل وضع إقامة البيانات.

</div>
