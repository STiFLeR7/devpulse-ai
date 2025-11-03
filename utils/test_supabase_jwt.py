import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()  # <-- This loads .env

SUPABASE_URL = "https://rynosajakbmusijviehl.supabase.co"
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

assert SUPABASE_KEY, "SUPABASE_KEY missing — check .env or dotenv"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def test():
    r = supabase.table("items").select("*").limit(1).execute()
    print("Connected ✅")
    print("Sample rows:", r.data)

if __name__ == "__main__":
    test()
