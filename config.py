from dotenv import load_dotenv
import os

load_dotenv()

STATEMENTS_FOLDER = os.getenv("STATEMENTS_FOLDER", "statements")
OUTPUT_FOLDER = os.getenv("OUTPUT_FOLDER", "output")
