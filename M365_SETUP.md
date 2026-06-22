# Microsoft 365 sign-in (with 2-step verification)

The app already has the full Microsoft 365 (Azure AD / Entra ID) login built in.
**2-step verification (MFA) is handled by Microsoft automatically** — once your tenant
requires it, the sign-in prompts for the second factor. No code change is needed.

To switch the portal from demo login to real M365 login, do the 4 steps below.

---

## 1. Register an app in Azure (Entra ID)

Azure Portal → **Microsoft Entra ID → App registrations → New registration**

- **Name:** Humiley People & Workplace Portal
- **Supported account types:** *Accounts in this organizational directory only (Single tenant)*
- **Redirect URI:** platform **Single-page application (SPA)**, value = your portal URL **with a trailing slash**, e.g.
  - `https://humiley-portal.onrender.com/`  (Render)
  - `https://your-domain.com/`  (Mat Bao)
  - Add one entry per URL you use. (The Codespaces preview URL can be added too.)

After it's created, copy:
- **Application (client) ID**  → this is your `CLIENT_ID`
- **Directory (tenant) ID**    → this is your `TENANT_ID`

## 2. API permissions

App registration → **API permissions → Add a permission → Microsoft Graph → Delegated**:
- `User.Read`  (required — reads the signed-in user's profile/email)
- `Mail.Send`  (optional — lets the portal send approval emails silently)

Click **Grant admin consent**.

## 3. Turn on the keys on the server

Set two environment variables on the host, then restart:

```bash
TK_M365_CLIENT_ID=<your client id>
TK_M365_TENANT_ID=<your tenant id>
```

- **Render:** Service → *Environment* → add both → Save (auto-redeploys).
- **Mat Bao VPS / Docker:** add `-e TK_M365_CLIENT_ID=… -e TK_M365_TENANT_ID=…` to `docker run`.

The backend then reports `demo:false`, and the login page goes live: the **Sign in with
Microsoft 365** button performs the real Azure redirect (with MFA), and the demo
Manager/Staff buttons disappear.

## 4. Enable 2-step verification (MFA)

Microsoft Entra ID → **Properties → Manage security defaults → Security defaults = Enabled**
(or create a Conditional Access policy requiring MFA). Each user enrolls a second factor
(Microsoft Authenticator / SMS) on first sign-in. This is the "2-step verification."

---

## Important: employee emails must match

The portal maps the signed-in Microsoft account's email to an employee record. Make sure each
employee's **Work Email** in the Employee Database matches their real M365 sign-in address
(e.g. `name@humiley.com`). Anyone without a matching record is refused with a clear message.

> Until the keys are set, the portal stays in demo mode (Manager / Staff quick-login) so it
> always remains accessible.
