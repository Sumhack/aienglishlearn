from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
from passlib.context import CryptContext

from app.config import get_settings


# Use argon2 to avoid bcrypt's 72-byte password limit.
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


@dataclass(frozen=True)
class AuthUser:
    user_id: str
    email: str
    name: str
    password_hash: str
    created_at: str


class AuthUserError(Exception):
    pass


def _table():
    settings = get_settings()
    # if settings.aws_access_key_id and settings.aws_secret_access_key:
    #     resource = boto3.resource(
    #         "dynamodb",
    #         region_name=settings.aws_region,
    #         aws_access_key_id=settings.aws_access_key_id,
    #         aws_secret_access_key=settings.aws_secret_access_key,
    #     )
    # else:
    resource = boto3.resource(
            "dynamodb",
            region_name= "ap-south-1",
        )
    return resource.Table(settings.aws_users_table)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_user_by_email(email: str) -> AuthUser | None:
    table = _table()
    response = table.query(
        IndexName="email_index",
        KeyConditionExpression=Key("email").eq(email),
        Limit=1,
    )
    items = response.get("Items", [])
    if not items:
        return None
    item = items[0]
    return AuthUser(
        user_id=item["user_id"],
        email=item["email"],
        name=item["name"],
        password_hash=item["password_hash"],
        created_at=item["created_at"],
    )


def create_user(*, name: str, email: str, password: str) -> AuthUser:
    if get_user_by_email(email):
        raise AuthUserError("Email already registered")

    table = _table()
    user_id = str(uuid4())
    password_hash = pwd_context.hash(password)
    created_at = _now_utc()

    table.put_item(
        Item={
            "user_id": user_id,
            "email": email,
            "name": name,
            "password_hash": password_hash,
            "created_at": created_at,
        }
    )

    return AuthUser(
        user_id=user_id,
        email=email,
        name=name,
        password_hash=password_hash,
        created_at=created_at,
    )


def verify_user(*, email: str, password: str) -> AuthUser:
    user = get_user_by_email(email)
    if not user:
        raise AuthUserError("Invalid email or password")
    if not pwd_context.verify(password, user.password_hash):
        raise AuthUserError("Invalid email or password")
    return user

def get_or_create_user_from_google(*, email: str, name: str, google_id: str) -> AuthUser:
    # Check if user already exists (could be an email/password account)
    existing_user = get_user_by_email(email)
    
    if existing_user:
        # User exists — return them as-is (merges Google login with existing account)
        return existing_user

    # New user — create them without a password
    table = _table()
    user_id = str(uuid4())
    created_at = _now_utc()

    table.put_item(
        Item={
            "user_id": user_id,
            "email": email,
            "name": name,
            "password_hash": "",  # no password for Google users
            "google_id": google_id,
            "created_at": created_at,
        }
    )

    return AuthUser(
        user_id=user_id,
        email=email,
        name=name,
        password_hash="",
        created_at=created_at,
    )