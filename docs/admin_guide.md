# Enterprise Administrator Guide

## 1. Single Sign-On (SSO) Configuration
Enterprise organizations can configure SAML 2.0 or OpenID Connect (OIDC) through the portal or API:

1. **Navigate to Organization Settings**: `Settings` -> `Single Sign-On (SSO)`.
2. **Configure Provider Details**:
   - For **SAML 2.0**: Enter your Identity Provider (IdP) Metadata URL or upload the Entity ID, SSO Endpoint, and x509 public certificate.
   - For **OIDC**: Provide the Client ID, encrypted Client Secret, and Discovery URL.
3. **Verify Enterprise Domains**:
   - Add your corporate email domain (e.g. `resort-chain.com`).
   - Add the generated DNS TXT record (`hac-verification=<token>`) to your domain DNS settings.
   - Click **Verify Domain** (`POST /api/v1/auth/sso/verify-domain`).
4. **Enforce SSO**:
   - Toggle **Enforce SSO for all organization users**. Once enabled, standard password authentication is permanently rejected for all users with corporate domain emails.

---

## 2. Automated User Provisioning (SCIM 2.0)
Hospitality Agent Cloud supports RFC 7644 SCIM 2.0:

- **SCIM Base URL**: `https://api.yourdomain.com/api/v1/scim/v2`
- **Bearer Token**: Generate a dedicated SCIM bearer token under `Settings` -> `Directory Sync`.
- **Supported Operations**:
  - `GET /Users`: Query user accounts with filter and pagination.
  - `POST /Users`: Provision new users with tenant assignment.
  - `PUT /Users/{id}` / `PATCH /Users/{id}`: Update user metadata or toggle `active: false`.
  - `DELETE /Users/{id}`: Immediate deprovisioning — terminates all active web/mobile sessions within seconds.

---

## 3. Multi-Factor Authentication (MFA) Policy
Administrators can require MFA for all organization members:

1. Go to `Settings` -> `Security Policy`.
2. Toggle **Require MFA for all organization members**.
3. Upon next login, users without MFA will be guided through standard RFC 6238 TOTP enrollment (compatible with Google Authenticator, 1Password, Microsoft Authenticator) and issued 10 single-use emergency recovery codes.

---

## 4. IP Allowlisting
Restrict API and portal access to corporate headquarters, hotel properties, or VPN egress IPs:

1. In `Settings` -> `Security Policy` -> `IP Allowlist`.
2. Add authorized IPv4/IPv6 addresses or CIDR blocks (e.g., `192.0.2.0/24`).
3. Requests originating outside allowlisted CIDR ranges receive HTTP 403 `IP_FORBIDDEN`.

---

## 5. Granular RBAC & Custom Roles
Create bespoke roles with least-privilege permission arrays:

- **Permissions Available**: `agents:read`, `agents:write`, `conversations:read`, `conversations:write`, `properties:read`, `properties:write`, `knowledge:read`, `knowledge:write`, `billing:read`, `billing:write`, `users:read`, `users:write`, `compliance:read`, `compliance:write`.
- Define roles via UI or API: `POST /api/v1/custom-roles`.

---

## 6. Platform Support Access Impersonation
When requesting assistance from platform support engineers:

1. Navigate to `Settings` -> `Support Access`.
2. Click **Grant Support Access** and select a time window (maximum 60 minutes).
3. The platform support engineer is granted a temporary scoped token that automatically logs all actions to the immutable audit trail and renders a prominent banner `X-Support-Impersonation: Active`.
4. Access can be immediately revoked at any time by clicking **Revoke Support Access**.
