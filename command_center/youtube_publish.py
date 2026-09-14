import os
import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def youtube_configured():
    required = [
        os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
        os.getenv("YOUTUBE_CLIENT_SECRET", "").strip(),
        os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip(),
    ]
    return all(required)


def _access_token():
    if not youtube_configured():
        raise RuntimeError("YouTube OAuth is not configured")
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("YOUTUBE_CLIENT_SECRET", "").strip(),
            "refresh_token": os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip(),
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Google did not return an access token")
    return token


def upload_video(video_bytes, title, description="", privacy_status=None, tags=None):
    token = _access_token()
    privacy_status = privacy_status or os.getenv("YOUTUBE_DEFAULT_PRIVACY", "unlisted").strip() or "unlisted"
    if privacy_status not in {"private", "unlisted", "public"}:
        privacy_status = "unlisted"

    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": "27",
            "tags": (tags or [])[:500],
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": True,
        },
    }

    init = requests.post(
        UPLOAD_URL,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(len(video_bytes)),
        },
        json=metadata,
        timeout=30,
    )
    init.raise_for_status()
    location = init.headers.get("Location")
    if not location:
        raise RuntimeError("YouTube did not return an upload URL")

    upload = requests.put(
        location,
        headers={"Content-Type": "video/mp4"},
        data=video_bytes,
        timeout=600,
    )
    upload.raise_for_status()
    result = upload.json()
    video_id = result.get("id")
    if not video_id:
        raise RuntimeError("YouTube upload completed without a video id")
    return {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "privacy_status": privacy_status,
    }
