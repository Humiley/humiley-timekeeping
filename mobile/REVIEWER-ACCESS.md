# App Review — giving Apple a way to sign in

The portal requires Microsoft 365 sign-in, so Apple's reviewer **cannot get past the login
without an account**. If you don't provide one, the app is rejected under Guideline 2.1
(app doesn't work) or 5.1.1. Do this before you submit.

## Recommended: a dedicated, throwaway review account

Create one Microsoft 365 account used only for App Review, then disable it after approval.

1. In **Microsoft 365 admin** (admin.microsoft.com) → **Users → Active users → Add a user**:
   - Name: `App Review` · Username: `appreview@humiley.com`
   - Assign a license that includes sign-in (any that lets Graph `/me` work).
2. **Turn off multi-factor authentication for this one account** so the reviewer isn't stuck
   on a 2-step code:
   - Entra admin → **Users → appreview → Authentication methods**, and make sure no MFA is
     required (or exclude this account from your Conditional Access MFA policy).
   - If your tenant forces MFA and you can't exclude it, instead give the reviewer a working
     TOTP: set it up in an authenticator, and paste **both** the password and the current
     6-digit code note in the review notes — but MFA-off is far simpler.
3. In the **Humiley Portal**, sign in once as an admin and make sure `appreview@humiley.com`
   exists as an employee record (so it maps to a role). Give it plain **staff** access — the
   reviewer only needs to see the app work, not admin features.
4. Put some **sample data** in (or use the demo seed) so the reviewer sees real screens, not
   empty lists. Do **not** expose real employees' personal data.

## Paste this into App Store Connect → App Review Information → Notes

```
This is an internal business app for Humiley Group Inc. staff. Sign-in uses Microsoft 365.

Demo account for review:
  Email:    appreview@humiley.com
  Password: <the password you set>
  MFA:      disabled for this account

The login opens in the system browser and returns to the app. Location is requested only when
the user taps "Check in" (to confirm presence at an approved site) — there is no background
tracking. Camera/Photos are used only when attaching a bill or receipt.
Privacy policy: https://portal.humiley.com/privacy
```

Also fill **App Review Information → Contact**: your name, phone, and `hr@humiley.com`.

## After approval
Disable or delete `appreview@humiley.com` in Microsoft 365 so the review credential can't be reused.

## If you'd rather not expose a login at all
Use **TestFlight** (internal testers — no public review) or **Apple Business Manager custom apps**
(private distribution to your organisation). Both avoid the public-review login problem entirely,
and suit an internal tool for ~15 staff better than a public App Store listing.
