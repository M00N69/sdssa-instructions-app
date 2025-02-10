import sqlite3
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# Connexion à la base de données SQLite
conn = sqlite3.connect('data/sdssa_instructions.db')
cursor = conn.cursor()

# Fonction pour récupérer les nouvelles instructions de la semaine précédente
def get_new_instructions(year, week):
    url = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year}/semaine-{week}"
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        instructions = soup.find_all('a', href=True)
        sdssa_instructions = [a for a in instructions if 'SDSSA' in a.text]
        return sdssa_instructions
    else:
        print(f"Failed to retrieve data for {year} week {week}")
        return []

# Fonction pour ajouter une instruction à la base de données
def add_instruction_to_db(year, week, title, link, pdf_link, objet, resume):
    cursor.execute("""
        INSERT INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (year, week, title, link, pdf_link, objet, resume, datetime.now()))
    conn.commit()

# Récupérer les nouvelles instructions de la semaine précédente
last_week = datetime.now() - timedelta(days=7)
year = last_week.year
week = last_week.isocalendar()[1]

new_instructions = get_new_instructions(year, week)
for instruction in new_instructions:
    link = f"https://info.agriculture.gouv.fr{instruction['href']}"
    pdf_link = link + "/telechargement"
    objet = "OBJET : Exemple"  # À extraire dynamiquement
    resume = "RESUME : Exemple"  # À extraire dynamiquement
    add_instruction_to_db(year, week, instruction.text, link, pdf_link, objet, resume)

# Fermer la connexion à la base de données
conn.close()

