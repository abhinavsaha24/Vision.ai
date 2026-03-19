"""Database connection utilities."""

import os
from urllib.parse import unquote, urlparse


def get_database_connection_params():
    """Parse DATABASE_URL and return connection parameters."""
    db_url = os.getenv("DATABASE_URL", "")

    if not db_url:
        raise ValueError("DATABASE_URL not set")

    # Handle escaped characters (do NOT unescape %23 yet - wait for proper parsing)
    # Pattern: postgresql://user:password@host:port/database
    # We need to be careful because password can contain %23 (escaped #) or %40 (escaped @)

    # Replace %23 with a placeholder to preserve it during parsing
    db_url_safe = db_url.replace("%23", "__ESCAPED_HASH__")

    # Parse using urllib
    parsed = urlparse(db_url_safe)

    # Extract components
    user = parsed.username
    password = unquote(parsed.password) if parsed.password else ""
    # Restore escaped characters in password
    password = password.replace("__ESCAPED_HASH__", "#")

    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    database = parsed.path.lstrip("/") if parsed.path else ""

    return {
        "user": user,
        "password": password,
        "host": host,
        "port": port,
        "database": database,
    }


def get_redis_connection_params():
    """Parse REDIS_URL and return connection parameters."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    parsed = urlparse(redis_url)

    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    db = int(parsed.path.lstrip("/")) if parsed.path else 0

    return {
        "host": host,
        "port": port,
        "db": db,
    }


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    try:
        db_params = get_database_connection_params()
        print("Database parameters:")
        for key, value in db_params.items():
            if key == "password":
                print(f"  {key}: {'***' if value else '(none)'}")
            else:
                print(f"  {key}: {value}")
    except Exception as e:
        print(f"Error: {e}")

    try:
        redis_params = get_redis_connection_params()
        print("\nRedis parameters:")
        for key, value in redis_params.items():
            print(f"  {key}: {value}")
    except Exception as e:
        print(f"Error: {e}")
