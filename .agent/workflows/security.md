---
description: Security checklist for all new features
---

# Security PRD - Honora API

**This document must be consulted before implementing any feature that handles:**
- External API calls (Gemini, Supabase, etc.)
- User input that gets processed or stored
- Endpoints accessible without authentication

---

## 1. API Key Protection

### Requirements
- ❌ **NEVER** hardcode API keys in source code
- ❌ **NEVER** commit `.env` files to Git
- ✅ Store keys in environment variables only
- ✅ Use `os.getenv("KEY_NAME")` to read keys
- ✅ Ensure `.env` is in `.gitignore`

### Checklist
- [ ] API key is in Railway Variables (production)
- [ ] API key is in local `.env` file (development)
- [ ] No API key strings in any `.py`, `.js`, or `.html` files

---

## 2. Rate Limiting

### Requirements
- All AI endpoints must have rate limits to prevent abuse
- Limits should be per-IP or per-job to prevent DoS

### Implementation
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/v2/job/{job_id}/ai-endpoint")
@limiter.limit("10/minute")  # Max 10 requests per minute per IP
async def ai_endpoint(...):
    ...
```

### Recommended Limits
| Endpoint Type | Rate Limit |
|---------------|------------|
| AI text processing | 10/minute |
| Cover art generation | 5/minute |
| Metadata lookup | 20/minute |
| File upload | 5/minute |

---

## 3. Input Validation

### Requirements
- All user input must be validated before processing
- Maximum text lengths must be enforced
- Malicious input patterns must be blocked

### Implementation
```python
MAX_TEXT_LENGTH = 100000  # 100KB max

@app.post("/v2/job/{job_id}/ai-split-paragraphs")
async def ai_split_paragraphs(job_id: str, request: Request):
    body = await request.json()
    text = body.get("text", "")
    
    # Input validation
    if not text:
        return JSONResponse({"error": "Text required"}, status_code=400)
    if len(text) > MAX_TEXT_LENGTH:
        return JSONResponse({"error": f"Text too long (max {MAX_TEXT_LENGTH} chars)"}, status_code=400)
    
    # Proceed with processing...
```

### Validation Checklist
- [ ] Check for empty/null input
- [ ] Enforce maximum length limits
- [ ] Sanitize HTML/script tags if applicable
- [ ] Validate job_id format (UUID)

---

## 4. Error Handling

### Requirements
- Never expose internal error details to users
- Log detailed errors server-side only
- Return generic error messages to clients

### Implementation
```python
try:
    # ... processing
except Exception as e:
    logging.error(f"Internal error: {e}")  # Log full details
    return JSONResponse({"error": "Processing failed"}, status_code=500)  # Generic response
```

---

## 5. New Feature Checklist

Before deploying ANY new endpoint or feature:

- [ ] API keys are not exposed in code
- [ ] Rate limiting is applied (if applicable)
- [ ] Input validation is implemented
- [ ] Error handling doesn't leak internals
- [ ] Tested with malicious input examples
