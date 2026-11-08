# Supabase OAuth setup

The web app now offers Google and Apple sign-in through Supabase OAuth. The
browser only starts the provider flow; provider credentials remain in the
Supabase project configuration.

## Redirect URLs

Add these URLs to the Supabase Auth URL configuration:

- `http://localhost:3000/auth/callback`
- `https://www.apex4traders.com/auth/callback` (canonical production origin)
- `https://apex4traders-web.onrender.com/auth/callback` (hosted smoke-test origin)

The web client intentionally sends hosted sign-up, confirmation, password
reset and social-auth callbacks to `https://www.apex4traders.com`. This keeps a
confirmation link from landing on a preview or service hostname. The Render
URL remains allowlisted for operational smoke tests and direct navigation, but
the Supabase **Site URL** should be the canonical production URL. This change
must be made by the owner in Supabase Auth; it is not part of a code deploy.

The callback accepts a safe `next` query parameter and never redirects to an
external origin.

## Google

1. Create a Google OAuth web client in Google Cloud Console.
2. Copy the client ID and client secret into the Supabase Google provider.
3. Add the Supabase-provided callback URL to the Google client's authorised
   redirect URIs.
4. Enable the provider and test both a new account and an existing account.

## Apple

1. Create an Apple Services ID and configure Sign in with Apple for the web.
2. Register the Supabase callback URL with Apple and create the required key.
3. Copy the Apple provider values into the Supabase Apple provider settings.
4. Enable the provider and test on a real Apple ID. Apple may return a private
   relay address; the application must treat it as a normal verified email.

If a provider is not enabled, the sign-in button surfaces Supabase's error and
does not claim that authentication succeeded. OAuth availability must be
verified in the Supabase dashboard before announcing it in a launch campaign.
