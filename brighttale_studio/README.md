# BrightTale Kids Studio

Independent Telegram-first content studio for short educational children's animations.

Brand: **BrightTale Kids**  
Tagline: **Little stories. Big life lessons.**

## Target channels
- YouTube / YouTube Shorts
- Instagram Reels
- TikTok

## MVP flow
1. New Story
2. Choose lesson/topic
3. Upload reference image (optional)
4. Generate a child-friendly script/storyboard
5. Parent approval gate
6. Render pipeline (scene images/video + voice + captions)
7. Preview
8. Publish All / YouTube / Instagram / TikTok / Save only

## Safety/product defaults
- Parent approval required before render and again before social publishing.
- No child personal details in titles/descriptions/captions.
- Social publishing defaults to private/unlisted where supported until explicitly approved.
- AI-generated disclosure fields are enabled in provider adapters when supported.

## Commercial-ready architecture
This service is isolated from Metra Command Center and has its own Telegram token and deployment settings. It is designed so storage, billing, user accounts, character profiles and social OAuth can be added without coupling to Metra.

## Railway
Deploy this folder as a separate Railway service using `brighttale_studio/Procfile`.

Required now:
- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_TELEGRAM_USER_IDS`
- `PUBLIC_URL`
- `WEBHOOK_SECRET`
- `SETUP_SECRET`

Social credentials are intentionally separate and should only be stored in Railway variables, never committed to GitHub.
