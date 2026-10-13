import re
from fastapi import HTTPException, status

COMMON_BREACHED_PASSWORDS = {
    "breachedpassword123!", "admin123456!", "welcome1234!", "password12345",
    "qwerty123456", "letmein12345!", "changeme123!", "summer2024!",
    "winter2024!", "company1234!"
}

def validate_password_policy(password: str) -> None:
    """Enforces enterprise password strength policy:
    1. Minimum 12 characters.
    2. At least one uppercase letter.
    3. At least one lowercase letter.
    4. At least one numeric digit.
    5. At least one special symbol.
    6. Not in common breached passwords list.
    """
    if len(password) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 12 characters long."
        )

    if not re.search(r"[A-Z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one uppercase letter."
        )

    if not re.search(r"[a-z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one lowercase letter."
        )

    if not re.search(r"[0-9]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one numeric digit."
        )

    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least one special character."
        )

    if password.lower() in COMMON_BREACHED_PASSWORDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password has been identified in known breach corpuses. Please choose a more secure password."
        )
