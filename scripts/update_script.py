import sqlite3
import os
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime

# 📌 Chemin vers la base de données
DB_PATH = "data/sdssa_instructions.db"

# 📌 Fonction pour s'assurer que la base est prête
def setup_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Vérifier si la table instructions existe
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS instructions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        year INTEGER,
        week INTEGER,
        title TEXT UNIQUE,
        link TEXT,
        pdf_link TEXT,
        objet TEXT,
        resume TEXT,
        last_updated TIMESTAMP
    );
    """)

    # Vérifier que la colonne `title` est UNIQUE
    cursor.execute("PRAGMA index_list(instructions);")
    indexes = cursor.fetchall()
    if not any("unique_title" in index for index in indexes):
        try:
            cursor.execute("CREATE UNIQUE INDEX unique_title ON instructions(title);")
        except sqlite3.OperationalError:
            pass  # Si l'index existe déjà

    conn.commit()
    conn.close()

# 📌 Fonction pour corriger les liens mal formatés
def fix_links():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, link, pdf_link FROM instructions;")
    rows = cursor.fetchall()

    for row in rows:
        record_id, link, pdf_link = row

        # Corriger les liens mal formés
        if link and link.startswith("https://info.agriculture.gouv.frhttps"):
            corrected_link = link.replace("https://info.agriculture.gouv.frhttps", "https")
            corrected_pdf_link = pdf_link.replace("https://info.agriculture.gouv.frhttps", "https")

            cursor.execute("""
                UPDATE instructions
                SET link = ?, pdf_link = ?
                WHERE id = ?;
            """, (corrected_link, corrected_pdf_link, record_id))

    conn.commit()
    conn.close()

# 📌 Fonction pour récupérer les nouvelles instructions
def get_new_instructions(year, week):
    url = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year}/semaine-{week}"
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        instructions = soup.find_all('a', href=True)

        result = []
        for a in instructions:
            if 'SDSSA' in a.text:
                link = f"https://info.agriculture.gouv.fr{a['href']}"
                pdf_link = link.replace("/detail", "/telechargement")
                result.append((year, week, a.text, link, pdf_link, "OBJET : Inconnu", "RESUME : Inconnu"))

        return result
    else:
        print(f"❌ Échec de récupération des données pour {year} Semaine {week}")
        return []

# 📌 Fonction pour ajouter les instructions à la base de données
def update_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Identifier la dernière semaine enregistrée
    cursor.execute("SELECT MAX(year), MAX(week) FROM instructions;")
    latest_entry = cursor.fetchone()
    latest_year, latest_week = latest_entry if latest_entry != (None, None) else (2019, 1)

    current_year, current_week = datetime.now().isocalendar()[:2]

    # Trouver les semaines à vérifier
    weeks_to_check = []
    for year in range(latest_year, current_year + 1):
        start_week = latest_week + 1 if year == latest_year else 1
        end_week = current_week if year == current_year else 52
        for week in range(start_week, end_week + 1):
            weeks_to_check.append((year, week))

    print(f"📅 Semaines à vérifier : {weeks_to_check}")

    # Récupérer les nouvelles instructions
    new_instructions = []
    for year, week in weeks_to_check:
        new_instructions.extend(get_new_instructions(year, week))

    print(f"📄 {len(new_instructions)} nouvelles instructions trouvées.")

    # Ajouter les nouvelles instructions à la base de données
    added_count = 0
    for instruction in new_instructions:
        year, week, title, link, pdf_link, objet, resume = instruction
        cursor.execute("SELECT COUNT(*) FROM instructions WHERE title = ?", (title,))
        exists = cursor.fetchone()[0]

        if exists == 0:
            cursor.execute("""
                INSERT INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (year, week, title, link, pdf_link, objet, resume, datetime.now()))
            added_count += 1

    conn.commit()
    conn.close()

    print(f"✅ {added_count} nouvelles instructions ajoutées.")

# 📌 Exécuter les mises à jour
if __name__ == "__main__":
    print("🔄 Initialisation de la base de données...")
    setup_database()

    print("🛠 Correction des liens mal formés...")
    fix_links()

    print("📡 Récupération et mise à jour des instructions...")
    update_database()

    print("✅ Mise à jour terminée !")

