# Humiley Portal on Android

There are two ways to run the portal as an app on Android. **Phase 1 works today, for free.**
**Phase 2** puts it on Google Play and needs a Google Play Developer account ($25 one-time).

Both use the same one codebase — the app just loads the live site at <https://portal.humiley.com>.
The companion guide for iPhone/iPad is **`IOS-APP.md`**; this file is the Android equivalent.

---

## Phase 1 — Installable app (PWA) · free · live now

Nothing to build. After the next deploy (`./update.sh`), anyone can install it:

**Android (Chrome):**
1. Open <https://portal.humiley.com> in **Chrome**.
2. Tap the **⋮** menu → **Install app** (or **Add to Home screen**) → **Install**.
3. A **Humiley** icon appears in the app drawer / home screen. Tapping it opens the portal
   **full-screen** (no browser bars), with a splash screen — it looks and feels like an app.

What you get: home-screen icon, full-screen launch, faster repeat loads, and it **updates itself**
every time you deploy the website — no Play Store, no re-install. Microsoft 365 sign-in works exactly
as on the website (it runs in Chrome). This is the recommended day-to-day option for the team.
It's already wired in (`static/manifest.webmanifest`, `static/sw.js`, `static/icons/*` including a
maskable 512 icon for Android's adaptive-icon shape). No cost, no Google account, no review.

---

## Phase 2 — Google Play (Capacitor)

A real native app you can distribute through Google Play (public, closed testing, or a private
Managed Google Play app). The project is scaffolded in the **`mobile/`** folder; the native build
runs on your machine. **Android does not require a Mac** — Windows, macOS or Linux all work.

### You need (your side)
- **Android Studio** (free) — bundles the Android SDK + platform-tools, and a **JDK 17**.
- A **Google Play Developer account** — **$25 one-time** (not annual):
  <https://play.google.com/console>. Identity/organization verification can take a few days.
- **Node.js** LTS installed (<https://nodejs.org>) — same as for iOS.

### One-time build steps (run in this repo)
```bash
cd mobile
npm install                         # installs Capacitor incl. @capacitor/android
npx cap add android                 # creates the native project (mobile/android/, gitignored)
npx capacitor-assets generate --android   # adaptive icon + splash from resources/icon.png & splash.png
npx cap sync android                # copies config/assets, installs the Android plugins
npx cap open android                # opens the project in Android Studio
```

### One required manual edit — the Microsoft-365 deep link
Open **`mobile/android/app/src/main/AndroidManifest.xml`**. Inside the existing
`<activity android:name=".MainActivity" …>` element (the one that already has the `MAIN`/`LAUNCHER`
`<intent-filter>`), add a **second, separate** `<intent-filter>` — do **not** merge it into the
launcher filter, and do **not** add a new activity:

```xml
<intent-filter>
  <action android:name="android.intent.action.VIEW" />
  <category android:name="android.intent.category.DEFAULT" />
  <category android:name="android.intent.category.BROWSABLE" />
  <data android:scheme="msauth.com.humiley.portal" android:host="auth" />
</intent-filter>
```

Then on that same `MainActivity` confirm/set two attributes:
- `android:exported="true"` — Capacitor's template already sets this (required on Android 12+ for
  the deep link to resolve). Verify it's present.
- `android:launchMode="singleTask"` — **add this** (Capacitor's default is not `singleTask`). It makes
  the browser callback re-enter the *same* activity instance that registered the sign-in listener, so
  the token hand-off completes. Without it, sign-in can silently fail to return.

> The whole `msauth.com.humiley.portal` before `://` is the **scheme**, and `auth` is the **host** —
> together they match the redirect `msauth.com.humiley.portal://auth`, mirroring the iOS
> `CFBundleURLSchemes` entry. Do **not** add `android:autoVerify` (that's only for `https://` App Links).

### In Android Studio
1. Confirm the **Application ID** is `com.humiley.portal` (it matches the sign-in scheme suffix — keep it).
2. Set a **versionCode** / **versionName**.
3. **Build → Generate Signed Bundle / APK → Android App Bundle (.aab)** and create an **upload keystore**
   (keep it + its password safe — you need the same key for every future update).
4. For quick testing, just **Run (▶)** onto a connected Android phone or emulator, sign in once with
   Microsoft 365, and confirm the system browser hands back into the app.

### Google Play Console
1. **Create app** → name **Humiley**, type App, category **Business**, Free.
2. Complete the policy declarations: **Privacy policy URL = `https://portal.humiley.com/privacy`**,
   Data safety form, Content rating, Target audience, Ads = No, and **App access** → provide the
   reviewer test credentials (reuse `mobile/REVIEWER-ACCESS.md`).
3. Opt into **Google Play App Signing** (default). Upload the signed **.aab**.
4. Store listing: description (reuse `mobile/APP-STORE-LISTING.md`), 512×512 icon, 1024×500 feature
   graphic, and ≥2 phone screenshots.
5. Release path: start with **Internal testing** (add testers by email, near-instant) to validate M365
   sign-in on a real device, then promote to Closed/Open testing or **Production** (review is usually
   hours to a few days). For internal-only use, **Internal testing** or **Managed Google Play** (private
   app) skips public exposure.

### Microsoft 365 sign-in inside the app — already wired
The same code that powers the iOS app handles Android: it's gated on `Capacitor.isNativePlatform()`
(true on both platforms), so the website/PWA is unchanged. On native it opens the Microsoft login in
the **system browser** and catches the redirect back through the custom scheme
`msauth.com.humiley.portal://auth`. **No `index.html` change is needed for Android.**

One Azure step (shared with iOS — do it once, it covers both):
- Entra ID → App registrations → **Humiley Portal** → **Authentication** → **Add a platform** →
  **Mobile and desktop applications** → add redirect URI **`msauth.com.humiley.portal://auth`**.
  Keep the existing **Single-page application** platform (`https://portal.humiley.com`) for the
  website/PWA. Under **Advanced settings**, set **Allow public client flows = Yes**.

> **No Google Play signing SHA-1/SHA-256 needs to be registered in Entra.** That requirement applies
> only to the *native MSAL Android SDK*; this app uses a plain system-browser + custom-scheme round-trip,
> so the single redirect URI above is shared verbatim by iOS and Android. If the token exchange ever
> fails on a device, the fallback is the native `@capacitor-community/msal` plugin — but *that* would
> then require registering the Play signing-key hash. Avoid it unless necessary.

### Play policy note
Like Apple's guideline 4.2, Google discourages pure "webview wrapper" apps. The portal is a full
business system (HR, finance approvals with e-signatures, camera bill capture, CRM, projects), which
satisfies the minimum-functionality requirement — be ready to describe that in the listing.

---

## Which should we use?
- **Now / everyone:** Phase 1 PWA — free, instant, auto-updating, on both Android and iOS.
- **Later / Play Store or managed distribution:** Phase 2 Capacitor — when you have the $25 Play account.
  Ping me before you submit and I'll help with the manifest deep-link edit and the Azure redirect URI.
