# Hospitality Agent Cloud — Public REST API (v1)

## Base URL
`https://api.yourdomain.com/api/v1`

---

## 1. Authentication & Scoped API Keys
All public API requests must include an API Key in the `X-API-Key` or `Authorization: Bearer <key>` header.

- Key Format: `hac_live_...` (Production) or `hac_test_...` (Sandbox)
- Managing Keys: Use `POST /api/v1/developer/api-keys` to provision scoped keys.
- Supported Scopes: `agents:read`, `agents:write`, `conversations:read`, `conversations:write`, `reservations:read`, `reservations:write`, `webhooks:manage`.

---

## 2. Rate Limiting & Quotas
APIs enforce per-tenant and per-key rate limits via token buckets:

### Response Headers:
- `X-RateLimit-Limit`: Maximum requests per minute.
- `X-RateLimit-Remaining`: Remaining capacity in current token window.
- `Retry-After`: Seconds to wait before retrying when rate-limited (HTTP 429).

---

## 3. Idempotency Keys
For all mutating operations (`POST`, `PUT`, `DELETE`), consumers must pass an `Idempotency-Key` header with a unique UUID v4:

```http
POST /api/v1/reservations HTTP/1.1
Host: api.yourdomain.com
Idempotency-Key: 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d
Content-Type: application/json
```
If a network disconnect occurs and the request is retried with the same key within 24 hours, the server returns the cached response with `X-Cache-Lookup: HIT`.

---

## 4. Customer Webhook Subscriptions & Verification
Customers can subscribe to outbound events (`conversation.created`, `handoff.requested`, `booking.created`, `ticket.created`).

### Verifying Webhook Signatures:
Every delivery includes signature headers:
```http
X-HAC-Signature: t=1791894000,v1=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
```

To verify:
1. Extract timestamp `t` and signature `v1`.
2. Reject requests where `abs(current_timestamp - t) > 300` seconds.
3. Compute expected signature:
   ```python
   import hmac, hashlib
   signed_payload = f"{t}.{request_body}".encode("utf-8")
   expected = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
   assert hmac.compare_digest(expected, v1)
   ```
