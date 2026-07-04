# Humiley Portal on iPhone / iPad

There are two ways to run the portal as an app. **Phase 1 works today, for free.**
**Phase 2** puts it on the App Store / TestFlight and needs an Apple Developer account + a Mac.

Both use the same one codebase — the app just loads the live site at <https://portal.humiley.com>.

---

## Phase 1 — Installable app (PWA) · free · live now

Nothing to build. After the next deploy (`git pull && ./update.sh`), anyone can install it:

**iPhone / iPad (Safari):**
1. Open <https://portal.humiley.com> in **Safari** (must be Safari, not Chrome).
2. Tap the **Share** button → **Add to Home Screen** → **Add**.
3. A **Humiley** icon appears on the home screen. Tapping it opens the portal **full-screen** (no browser bars), with a splash screen — it looks and feels like an app.

**Android (Chrome):** menu → **Install app** / **Add to Home screen**.
**Windows / Mac (Edge/Chrome):** the install icon in the address bar.

What you get: home-screen icon, full-screen launch, faster repeat loads, and it **updates itself** every time you deploy the website — no app store, no re-install. Microsoft 365 sign-in works exactly as on the website (it runs in real Safari).

> This is the recommended day-to-day option for the team. It's already wired in
> (manifest, service worker, icons). No cost, no Apple account, no review.

---

## Phase 2 — App Store / TestFlight (Capacitor)

A real native app you can distribute through the App Store or TestFlight. The project is
scaffolded in the **`mobile/`** folder; the native build runs on your Mac.

### You need (your side)
- A **Mac** with **Xcode** (free, from the Mac App Store).
- An **Apple Developer account** — **$99 / year** (<https://developer.apple.com/programs/>).
- **Node.js** installed (<https://nodejs.org>, LTS).

### One-time build steps (run on the Mac, in this repo)
```bash
cd mobile
npm install                      # install Capacitor
npx cap add ios                  # create the native iOS project (mobile/ios/)
npx capacitor-assets generate --ios   # generate app icon + splash from resources/
npx cap sync ios
npx cap open ios                 # opens Xcode
```

### In Xcode
1. Select the **App** target → **Signing & Capabilities** → tick **Automatically manage signing**, pick your **Team** (your Apple Developer account). Bundle identifier is `com.humiley.portal` (change it if you own a different one).
2. Set the **Display Name** to *Humiley* and a **Version** / **Build** number.
3. Pick a real device or *Any iOS Device (arm64)* and **Product → Archive**.
4. In the Organizer window that opens: **Distribute App** → **App Store Connect** → upload.
5. In **App Store Connect** (<https://appstoreconnect.apple.com>): create the app record
   (name, category = Business, privacy policy URL = **https://portal.humiley.com/privacy**, screenshots), attach the build, and submit
   to **TestFlight** (internal testing, instant) or the **App Store** (review, ~1–3 days).

### App details already set for you
- App name: **Humiley** · Bundle id: `com.humiley.portal`
- Loads: `https://portal.humiley.com` (see `mobile/capacitor.config.json`)
- Icon: `mobile/resources/icon.png` · Splash: `mobile/resources/splash.png` (navy brand)
- Status-bar / splash background: `#0b2649`

### Microsoft 365 sign-in inside the app — already wired

Microsoft blocks its login page from rendering inside an embedded web view. The portal now
handles this automatically **when it detects it's running in the native app** (gated behind
`Capacitor.isNativePlatform()` — the website/PWA is completely unchanged): it opens the Microsoft
login in the **system browser**, then catches the redirect back through a custom URL scheme and
finishes the sign-in. `CapacitorHttp` is enabled so the token exchange isn't blocked by CORS.

Two small config steps remain (they can only be done on the Mac / in your Azure tenant):

**1. Register the redirect URI in Entra ID (Azure AD)**
App registrations → **Humiley Portal** → **Authentication** → **Add a platform** →
**Mobile and desktop applications** → add this redirect URI:
```
msauth.com.humiley.portal://auth
```
(Keep the existing **Single-page application** platform with `https://portal.humiley.com` — that's
what the website + PWA use.) Under **Advanced settings**, set **Allow public client flows = Yes**.

**2. Register the URL scheme in Xcode**
In `mobile/ios/App/App/Info.plist`, add (Capacitor's App plugin handles the callback automatically
once the scheme is registered — no AppDelegate edit needed):
```xml
<key>CFBundleURLTypes</key>
<array>
  <dict>
    <key>CFBundleURLSchemes</key>
    <array><string>msauth.com.humiley.portal</string></array>
  </dict>
</array>
```

**Test on a device**, sign in once, and confirm it returns to the app. If the token exchange still
fails, the robust fallback is the native **`@capacitor-community/msal`** plugin (native MSAL +
ASWebAuthenticationSession) — tell me and I'll switch the native path to it.

> The **PWA (Phase 1) never has this issue** because it runs in real Safari — still the recommended
> path for day-to-day team use.

### App Store review note
Apple guideline 4.2 can reject apps that are "just a web page." The portal is a full business
system (HR, finance approvals with e-signatures, camera bill capture, CRM, projects), which
normally satisfies this — but for a public listing, be ready to describe that functionality.
For **internal-only** distribution, prefer **TestFlight** or **Apple Business Manager (custom apps)**,
which skip public review.

---

## Which should we use?
- **Now / everyone:** Phase 1 PWA — free, instant, auto-updating.
- **Later / App Store presence or managed distribution:** Phase 2 Capacitor — when you have the
  Apple account + Mac. Ping me to wire the system-browser M365 sign-in before you submit.
