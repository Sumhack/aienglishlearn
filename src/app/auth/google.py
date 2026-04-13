import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
import os

from app.auth.jwt_utils import create_jwt_token
from app.auth.user_store import get_or_create_user_from_google

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
FRONTEND_URL = os.getenv("FRONTEND_URL")

@router.get("/auth/google")
async def google_login():
    google_auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        "&response_type=code"
        "&scope=openid email profile"
        "&access_type=offline"
    )
    return RedirectResponse(google_auth_url)


@router.get("/auth/google/callback")
async def google_callback(code: str):
    # Step 1: Exchange code for tokens
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }
        )

    if token_response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to exchange code")

    tokens = token_response.json()

    # Step 2: Get user info from Google
    async with httpx.AsyncClient() as client:
        user_info_response = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )

    if user_info_response.status_code != 200:
        raise HTTPException(status_code=400, detail="Failed to fetch user info")

    google_user = user_info_response.json()

    # Step 3: Find or create user in DynamoDB
    user = get_or_create_user_from_google(
        email=google_user["email"],
        name=google_user["name"],
        google_id=google_user["id"],
    )

    # Step 4: Issue your JWT exactly like email/password login does
    token, expires_in = create_jwt_token(
        user_id=user.user_id,
        email=user.email,
        name=user.name,
    )

    # Step 5: Redirect to frontend with token
    return RedirectResponse(f"{FRONTEND_URL}/auth/callback?token={token}")