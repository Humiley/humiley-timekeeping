# App Store Connect — listing text (ready to paste)

Everything below is drafted to Apple's character limits. Paste into App Store Connect
when you create the app record. `⟵ N` shows the field's max length.

---

## Basics
| Field | Value |
|---|---|
| **App Name** ⟵30 | `Humiley Portal` |
| **Subtitle** ⟵30 | `Workplace, HR & approvals` |
| **Bundle ID** | `com.humiley.portal` |
| **Primary category** | Business |
| **Secondary category** | Productivity |
| **Primary language** | English (U.S.) — the app is bilingual EN / Tiếng Việt |
| **Price** | Free |

## URLs
| Field | Value |
|---|---|
| **Privacy Policy URL** | `https://portal.humiley.com/privacy` |
| **Support URL** | `https://portal.humiley.com` (or a support page — email hr@humiley.com) |
| **Marketing URL** (optional) | `https://humiley.com` |

## Promotional text ⟵170
```
The Humiley People & Workplace Portal — attendance, leave, expense approvals with
e-signatures, projects and CRM, in one secure app. Sign in with Microsoft 365.
```

## Description ⟵4000
```
Humiley Portal is the official People & Workplace app for Humiley Group Inc. It brings
the company's day-to-day operations into one secure place, with Microsoft 365 single
sign-on and full English / Tiếng Việt support.

For employees
• Check in and out with location confirmation at approved work sites
• Request leave and track your balances
• Submit expense claims, travel and payment requests — attach bills or photos, which
  are combined into a single PDF
• Set a personal signing PIN and e-sign your submissions
• See your profile, payslips, training and goals

For managers and directors
• A three-level approval flow — the requester submits, the direct manager reviews, and
  a director gives final approval — every step captured as an electronic signature
• A company-wide Finance Control view of all payments, claims and travel, with monthly,
  quarterly and yearly filters
• Approvals inbox, dashboards and reports

Also included
• Projects (PMC) — charter, scope, schedule, cost, risk, quality and more
• CRM — pipeline, companies, contacts and deals
• Devices and asset management

Security and privacy
• Microsoft 365 sign-in; access is limited to authorised Humiley accounts
• Electronic signatures with an audit trail
• Signing PINs are stored only as a salted one-way hash
• Data is encrypted in transit

This app is intended for Humiley employees and authorised contractors. A Humiley
Microsoft 365 account is required to sign in.
```

## Keywords ⟵100 (comma-separated, no spaces after commas)
```
humiley,workplace,hr,attendance,leave,expense,approval,timesheet,payroll,crm,project,esignature
```

## Version release notes ⟵4000 (for the first version)
```
First release of the Humiley Portal app:
• Microsoft 365 sign-in
• Attendance check-in, leave, and expense/travel/payment requests
• Three-level approvals with electronic signatures and a signing PIN
• Finance Control, projects, CRM and asset management
• English / Tiếng Việt
```

---

## App Privacy (the "App Privacy" questionnaire in App Store Connect)

Answer **"Yes, we collect data."** For each type below: purpose = **App Functionality**,
**linked to the user's identity = Yes**, **used for tracking = No** (we do not track across
other companies' apps or sell data).

| Data type (Apple category) | Collected | Notes |
|---|---|---|
| Contact Info → **Name**, **Email address** | Yes | From Microsoft 365 sign-in |
| Identifiers → **User ID** | Yes | Employee/account id |
| Location → **Precise Location** | Yes | Only at check-in; **not** used to track the user |
| User Content → **Photos or Videos** | Yes | Bill/receipt/ticket uploads |
| User Content → **Other User Content** | Yes | Documents, request details |
| Financial Info → **Other Financial Info** | Yes | Claim/payment amounts; payroll/bank where applicable |
| Sensitive Info | Yes | Employment/HR data |
| Contacts / Browsing / Search history / Ads | **No** | Not collected |
| Usage Data, Diagnostics | Optional | You may mark Diagnostics = No if you don't collect crash data |

> "Used for tracking" = **No** across the board — there is no advertising and no third-party
> data sharing. This keeps you out of App Tracking Transparency requirements.

## Age rating
All content = **None** → rating **4+**. It's a business tool with no objectionable content.

---

## App Review notes (paste into "Notes" for the reviewer)
```
This is an internal business app for Humiley Group Inc. employees. Sign-in requires a
Humiley Microsoft 365 account. For review, please use this demo account:

  Email:    <create a test M365 account, e.g. appreview@humiley.com>
  Password: <password>
  (2-step verification: <how the reviewer receives the code, or disable MFA for this test account>)

The app is a native wrapper around our secure web portal (portal.humiley.com). Location is
used only when the user taps "Check in", to confirm presence at an approved work site — it is
not used for background tracking. Camera/Photos are used only when a user attaches a bill or
receipt. Privacy policy: https://portal.humiley.com/privacy
```
> ⚠️ You **must** give the reviewer a working way in, or the app is rejected (Guideline 2.1 /
> 5.1.1). Easiest: create a dedicated `appreview@humiley.com` M365 account with MFA off (or an
> app-specific method), used only for review. Delete or disable it after approval.

## TestFlight — "What to Test" ⟵4000
```
Please test on iPhone and iPad:
1. Sign in with your Humiley Microsoft 365 account (the login opens in the system browser
   and returns to the app).
2. Check in / out on the Check In screen — allow location when asked.
3. Submit a leave request and an expense claim (attach a photo of a receipt).
4. Managers: review/approve an item from the Approvals inbox; sign with your PIN or Microsoft 365.
5. Switch language EN ⇄ VN (top bar) and confirm labels translate.
Report anything that doesn't load, the sign-in returning to the app, or icons/layout issues.
```

---

## Screenshots you'll need (capture on device or Simulator)
Apple needs at least one set; these sizes cover current requirements:
- **iPhone 6.7"** (e.g. iPhone 15 Pro Max) — 1290 × 2796 — **required**
- **iPad 12.9"** (6th gen) — 2048 × 2732 — required if you ship for iPad
Good screens to show: the welcome/sign-in, the dashboard, Check-in, an expense claim with an
attached bill, the 3-level Approvals view, and the e-signature dialog. Avoid showing real
employee personal data — use the demo/sample data.

## Reminder
For an internal-only rollout to your team you can skip the public App Store entirely and use
**TestFlight** (up to 100 internal testers, no public review) or **Apple Business Manager
custom apps** — both faster and lower-risk than a public listing. The **PWA** needs none of this.
