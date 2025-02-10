import sqlite3
import pandas as pd

def load_data():
    """Charge les données depuis la base de données SQLite."""
    conn = sqlite3.connect('data/sdssa_instructions.db')
    query = "SELECT * FROM instructions"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

