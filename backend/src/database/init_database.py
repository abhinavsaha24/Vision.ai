import logging

from backend.src.database.db import init_db

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)


def initialize_database():

    try:

        init_db()

        logging.info("Database initialized successfully")

    except Exception as e:
        logging.error("Database initialization failed: %s", e)

        raise


if __name__ == "__main__":

    initialize_database()
