import re
import unicodedata

from .errors import ApiError

USERNAME_RE = re.compile(r"^[a-z0-9._]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


def clean_text(value, max_len=255):
    value = unicodedata.normalize("NFC", str(value))
    value = "".join(ch for ch in value if unicodedata.category(ch)[0] != "C")
    return value.strip()[:max_len]


def clean_name(value):
    name = clean_text(value or "", 255)
    if not name or len(name) > 80:
        raise ApiError("validation_error", "Full name is required (1 to 80 characters).", 400)
    return name


def clean_username(value):
    username = clean_text(value or "", 30).lower()
    if not USERNAME_RE.match(username):
        raise ApiError(
            "validation_error",
            "Username must be 3 to 30 characters: letters, digits, dot or underscore.",
            400,
        )
    return username


def clean_email(value, required=False):
    email = clean_text(value or "", 255).lower()
    if not email:
        if required:
            raise ApiError("validation_error", "Email is required.", 400)
        return None
    if not EMAIL_RE.match(email):
        raise ApiError("validation_error", "Enter a valid email address.", 400)
    return email


def check_password(value):
    if not isinstance(value, str) or len(value) < MIN_PASSWORD:
        raise ApiError(
            "validation_error", f"Password must be at least {MIN_PASSWORD} characters.", 400
        )
    if len(value) > 200:
        raise ApiError("validation_error", "Password is too long.", 400)
    return value
