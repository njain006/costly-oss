import uuid
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, Request
from passlib.context import CryptContext
from jose import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.database import db
from app.deps import get_current_user
from app.models.auth import (
    UserRegister, UserLogin, ChangePassword,
    ForgotPassword, ResetPasswordToken, GoogleAuth, RefreshTokenRequest,
)
from app.services.email import send_reset_email
from app.utils.helpers import run_in_thread

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _create_tokens(user_id: str) -> dict:
    access_token = jwt.encode(
        {
            "user_id": user_id,
            "type": "access",
            "exp": datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    refresh_token = jwt.encode(
        {
            "user_id": user_id,
            "type": "refresh",
            "exp": datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return {"access_token": access_token, "refresh_token": refresh_token}


@router.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, user: UserRegister):
    if await db.users.find_one({"email": user.email}):
        raise HTTPException(400, "Email already registered")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    hashed = pwd_context.hash(user.password)
    await db.users.insert_one({
        "user_id": user_id,
        "email": user.email,
        "name": user.name,
        "password_hash": hashed,
        "created_at": datetime.utcnow().isoformat(),
    })
    tokens = _create_tokens(user_id)
    return {
        "token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "user_id": user_id,
        "name": user.name,
        "email": user.email,
        "role": None,
    }


@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, user: UserLogin):
    existing = await db.users.find_one({"email": user.email})
    if not existing or not pwd_context.verify(user.password, existing["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    if existing.get("is_disabled"):
        raise HTTPException(403, "This account has been disabled")
    tokens = _create_tokens(existing["user_id"])
    return {
        "token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "user_id": existing["user_id"],
        "name": existing["name"],
        "email": existing["email"],
        "role": existing.get("role"),
    }


@router.post("/refresh")
async def refresh_token(body: RefreshTokenRequest):
    try:
        payload = jwt.decode(body.refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Invalid token type")
        user_id = payload["user_id"]
        user = await db.users.find_one({"user_id": user_id})
        if not user:
            raise HTTPException(401, "User not found")
        if user.get("is_disabled"):
            raise HTTPException(403, "This account has been disabled")
        tokens = _create_tokens(user_id)
        return {
            "token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "user_id": user["user_id"],
            "name": user.get("name"),
            "email": user.get("email"),
            "role": user.get("role"),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Invalid or expired refresh token")


@router.post("/change-password")
async def change_password(body: ChangePassword, user_id: str = Depends(get_current_user)):
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(404, "User not found")
    if not pwd_context.verify(body.current_password, user["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    new_hash = pwd_context.hash(body.new_password)
    await db.users.update_one({"user_id": user_id}, {"$set": {"password_hash": new_hash}})
    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPassword):
    user = await db.users.find_one({"email": body.email.lower().strip()})
    if user:
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "token": token,
            "user_id": user["user_id"],
            "email": user["email"],
            "expires_at": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
            "used": False,
            "created_at": datetime.utcnow().isoformat(),
        })
        reset_url = f"{settings.app_url}/reset-password?token={token}"
        await run_in_thread(send_reset_email, user["email"], reset_url)
    return {"message": "If that email is registered, you'll receive a reset link shortly."}


@router.post("/reset-password")
async def reset_password_with_token(body: ResetPasswordToken):
    record = await db.password_reset_tokens.find_one({"token": body.token, "used": False})
    if not record:
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")
    if datetime.utcnow() > datetime.fromisoformat(record["expires_at"]):
        raise HTTPException(400, "Reset link has expired (30 min limit). Please request a new one.")
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    new_hash = pwd_context.hash(body.new_password)
    await db.users.update_one({"user_id": record["user_id"]}, {"$set": {"password_hash": new_hash}})
    await db.password_reset_tokens.update_one({"token": body.token}, {"$set": {"used": True}})
    return {"message": "Password reset successfully. You can now sign in."}


@router.post("/google")
async def google_oauth(body: GoogleAuth):
    if not settings.google_client_id:
        raise HTTPException(501, "Google OAuth is not configured on this server")
    try:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
        idinfo = google_id_token.verify_oauth2_token(
            body.credential, google_requests.Request(), settings.google_client_id
        )
        email = idinfo["email"]
        name = idinfo.get("name", email.split("@")[0])
        picture = idinfo.get("picture")
        user = await db.users.find_one({"email": email})
        if not user:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            await db.users.insert_one({
                "user_id": user_id,
                "email": email,
                "name": name,
                "picture": picture,
                "password_hash": None,
                "auth_provider": "google",
                "created_at": datetime.utcnow().isoformat(),
            })
        else:
            if user.get("is_disabled"):
                raise HTTPException(403, "This account has been disabled")
            user_id = user["user_id"]
            name = user.get("name", name)
        tokens = _create_tokens(user_id)
        return {
            "token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "user_id": user_id,
            "name": name,
            "email": email,
            "role": user.get("role") if user else None,
        }
    except ValueError as e:
        raise HTTPException(401, f"Invalid Google credential: {e}")
