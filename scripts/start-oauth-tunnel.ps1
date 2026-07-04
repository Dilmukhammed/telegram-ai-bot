# Quick public HTTPS tunnel for Google OAuth callback (port 8787).
# After start, copy the https://*.trycloudflare.com URL into GOOGLE_PUBLIC_BASE_URL
# and register {URL}/oauth/google/callback in Google Cloud (Web OAuth client).

Write-Host "Starting Cloudflare quick tunnel -> http://127.0.0.1:8787"
Write-Host "Keep this window open while the bot runs."
cloudflared tunnel --url http://127.0.0.1:8787
