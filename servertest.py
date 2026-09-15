import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
db_url = os.getenv("DATABASE_URL")

try:
    connection = psycopg2.connect(db_url)
    cursor = connection.cursor()

    cursor.execute("SELECT version();")
    db_version = cursor.fetchone()

    print("Success! Connected to Neon PostgreSQL")
    print("Database version: ", db_version[0])

    cursor.close()
    connection.close()

except Exception as error:
    print("Failed to connect: ", error)