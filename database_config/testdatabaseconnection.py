# Manually check both test and production database connections with SELECT version().
# This script runs immediately, even if imported; it does not check project tables.

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("TEST_DATABASE_URL")

try:
    connection = psycopg2.connect(db_url)
    cursor = connection.cursor()

    cursor.execute("SELECT version();")
    db_version = cursor.fetchone()

    print("Success! Connected to Test Neon PostgreSQL")
    print("Database version: ", db_version[0])

    cursor.close()
    connection.close()

except Exception as error:
    print("Failed to connect: ", error)

# This second check uses production, unlike the API's development fallback.
load_dotenv()
db_url = os.getenv("PROD_DATABASE_URL")

try:
    connection = psycopg2.connect(db_url)
    cursor = connection.cursor()

    cursor.execute("SELECT version();")
    db_version = cursor.fetchone()

    print("Success! Connected to Prod Neon PostgreSQL")
    print("Database version: ", db_version[0])

    cursor.close()
    connection.close()

except Exception as error:
    print("Failed to connect: ", error)
