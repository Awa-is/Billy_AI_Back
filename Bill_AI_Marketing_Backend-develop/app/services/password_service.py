import bcrypt
from werkzeug.security import check_password_hash


def hash_password(plain_password: str) -> str:
    if plain_password is None:
        raise ValueError("Password is required")
    if not isinstance(plain_password, str):
        raise ValueError("Password must be a string")
    if plain_password.strip() == "":
        raise ValueError("Password cannot be empty")

    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password_hash: str, plain_password: str) -> bool:
    if not password_hash or not plain_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        # Backwards compatibility for legacy Werkzeug hashes.
        try:
            return check_password_hash(password_hash, plain_password)
        except Exception:
            return False

