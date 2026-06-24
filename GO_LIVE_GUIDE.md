# Humiley People & Workplace Portal — Go-Live Guide

The portal is now a **clean system** connected to **Microsoft 365**. Only **Tony Nguyen
(tony.nguyen@humiley.com)** can sign in until the rest of the team is added.

Portal link: **https://orange-giggle-qv7jwj45jgv7h4wwv-8000.app.github.dev**

Follow the steps in order.

---

## STEP 1 — Sign in as Admin (Tony)

1. Open the portal link above.
2. Press **Cmd + Shift + R** (Mac) / **Ctrl + Shift + R** (Windows) to load the latest page.
3. Click **“Sign in with Microsoft 365”**.
4. In the Microsoft pop-up, sign in with **tony.nguyen@humiley.com** and approve **2-step
   verification** if asked.
5. ✅ You land on the **Company Dashboard** as **Admin** — empty system, just Tony.

> **If you see a “redirect URI mismatch” error:**
> Go to **portal.azure.com → Microsoft Entra ID → App registrations → “Humiley Timekeeping”
> → Authentication → Single-page application → Add URI**, paste your portal address **with NO
> trailing slash** (must match the browser address bar's origin exactly), e.g.:
> `https://orange-giggle-qv7jwj45jgv7h4wwv-8000.app.github.dev`
> then **Save** and try again. (Send me a message if it happens.)

---

## STEP 2 — Add your team

Each person can sign in **only after** they have an employee record with their real
**@humiley.com** email.

### Option A (recommended) — Sync from Microsoft 365 (automatic)
1. Make sure you’re signed in as **Admin** (Tony).
2. Left menu → **Employee Database** → click **“Sync from Microsoft 365”** (top right).
3. The first time, a Microsoft window asks to allow **“Read all users’ full profiles.”**
   Click **Accept** (you must be a Microsoft 365 **admin** to approve this for the company).
4. ✅ Everyone in your Microsoft 365 directory is imported (name, email, department, job title).
   Guests and external accounts are skipped. People already in the system are skipped.
5. Go to **Access & Permissions** (Step 3) to set who is Admin / Editor / Approver / etc.

> If clicking Sync shows **“admin consent required”**: a Microsoft 365 Global Admin must approve
> the **User.Read.All** permission once — in **portal.azure.com → App registrations →
> “Humiley Timekeeping” → API permissions → Add a permission → Microsoft Graph → Delegated →
> User.Read.All → Add → Grant admin consent**. Then click Sync again. (Tell me if you’d like help.)

### Option B — Add one person manually (good for a few people)
1. Left menu → **Employee Database**.
2. Click **+ Add Employee** (top right).
3. Fill in:
   - **Full Name**
   - **Work Email (login)** = their real Microsoft 365 address (e.g. `lan.tran@humiley.com`)
   - **Department**, **Position / Job Title**
   - **Compensation** → pick **Job Grade** (salary auto-fills, you can edit)
   - **System Access** → choose their level (see Step 3)
4. Click **Add Employee**.

### Option B — Import everyone at once (fastest)
1. Left menu → **Employee Database** → **Import**.
2. Upload an **Excel/CSV** with these columns:
   `Name, Email, Department, Position, Job Level`
3. Review and confirm.

> 💡 **Easiest of all:** send the list (names + @humiley.com emails, and dept/title if you
> have them) — or a CSV/Excel file — and I’ll import the whole team for you in one go.

---

## STEP 3 — Set each person’s access level

Left menu → **Access & Permissions** → use the dropdown next to each person:

| Level | What they can do |
|-------|------------------|
| **User** | Self-service only — own check-in, attendance, leave, claims, training |
| **Contributor** | + approve their team’s requests, People & HR modules (add/edit employees, recruitment, performance, devices) |
| **Approver** | + **view** Payroll & Finance (read-only) |
| **Editor** | + **run/edit Payroll** (pay runs, adjustments) — *cannot* assign access levels |
| **Admin** | + **Access & Permissions** (assign levels) — full control |

Changes apply at the person’s next sign-in.

---

## STEP 4 — Tell the team to sign in

Each colleague:
1. Opens the portal link.
2. Clicks **Sign in with Microsoft 365**.
3. Signs in with **their own** Microsoft account.
4. Gets exactly the access level you assigned.

> Add everyone in Step 2 **before** sharing the link widely, or colleagues will see
> “No employee record — ask an admin to add you.”

---

## Good to know

- **Backup:** the previous demo data is backed up on the server (`timekeeping.db.bak-preMS365`)
  and can be restored if ever needed.
- **The link sleeps:** this Codespace link goes idle after ~30 min and isn’t meant for daily
  production. When you’re ready I’ll move it to a permanent home (**Render – free**, or your
  **Mat Bao** server) and register that address in Azure. (See `DEPLOY.md`.)
- **Need to go back to the demo for testing?** Tell me — I can switch it back in ~1 minute.

---

### What I can do for you right now
- **Import your real roster** (send the list or a CSV/Excel) so the whole team can sign in.
- **Move to permanent hosting** when you’re ready.

Just reply with the team list, or say “import”, and I’ll take it from there.
