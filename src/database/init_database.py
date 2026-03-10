from src.database.db import init_db
import logging


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def initialize_database():

    try:

        init_db()

        logging.info("Database initialized successfully")

    except Exception as e:

        logging.error(f"Database initialization failed: {e}")

        raise


if __name__ == "__main__":

    initialize_database()