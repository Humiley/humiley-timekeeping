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
   (name, category = Business, privacy policy URL, screenshots), attach the build, and submit
   to **TestFlight** (internal testing, instant) or the **App Store** (review, ~1–3 days).

### App details already set for you
- App name: **Humiley** · Bundle id: `com.humiley.portal`
- Loads: `https://portal.humiley.com` (see `mobile/capacitor.config.json`)
- Icon: `mobile/resources/icon.png` · Splash: `mobile/resources/splash.png` (navy brand)
- Status-bar / splash background: `#0b2649`

### Important: Microsoft 365 sign-in inside the app
Microsoft sometimes blocks sign-in inside an embedded web view for security. The config already
allows the Microsoft login domains (`login.microsoftonline.com`, `*.msauth.net`, …). If sign-in
is refused inside the wrapped app, the fix is one of:
- In **Entra ID (Azure AD) → App registrations → Humiley Portal → Authentication**, add the iOS
  redirect and allow public-client/native flows; **or**
- Have the portal open the M365 login in the **system browser** (ASWebAuthenticationSession)
  instead of the in-app web view. *(Tell me and I'll add this to the portal — it's a small change.)*

The **PWA (Phase 1) has no such issue** because it runs in real Safari — which is why it's the
recommended path unless you specifically need the App Store listing.

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
