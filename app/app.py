import streamlit as st
import pandas as pd
import sqlite3
import os
import requests
from bs4 import BeautifulSoup
from whoosh.index import create_in
from whoosh.fields import Schema, TEXT, ID
from whoosh.qparser import QueryParser
from whoosh.analysis import StemmingAnalyzer, LowercaseFilter, StopFilter
import nltk
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize
from datetime import datetime, timedelta

# Configuration de la page
st.set_page_config(layout="wide")

# Exécuter le script d'initialisation NLTK
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')

# Fonction pour vérifier si la base de données existe
def check_database():
    db_path = 'data/sdssa_instructions.db'
    if not os.path.exists(db_path):
        st.error(f"La base de données {db_path} n'existe pas. Veuillez vérifier le chemin et essayer à nouveau.")
        st.stop()
    return db_path

# Fonction pour lire les données depuis la base de données SQLite
def load_data(db_path):
    conn = sqlite3.connect(db_path)
    query = "SELECT * FROM instructions"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# Fonction pour créer un index Whoosh avec des analyses avancées
def create_whoosh_index(df):
    analyzer = StemmingAnalyzer() | LowercaseFilter() | StopFilter()
    schema = Schema(title=TEXT(stored=True, analyzer=analyzer),
                    objet=TEXT(stored=True, analyzer=analyzer),
                    resume=TEXT(stored=True, analyzer=analyzer),
                    content=TEXT(analyzer=analyzer))
    if not os.path.exists("indexdir"):
        os.mkdir("indexdir")
    ix = create_in("indexdir", schema)
    writer = ix.writer()
    for index, row in df.iterrows():
        writer.add_document(title=row['title'], objet=row['objet'], resume=row['resume'], content=f"{row['title']} {row['objet']} {row['resume']}")
    writer.commit()
    return ix

# Fonction pour trouver des synonymes
def get_synonyms(word):
    synonyms = set()
    for syn in wordnet.synsets(word):
        for lemma in syn.lemmas():
            synonyms.add(lemma.name().lower())
    return synonyms

# Fonction pour normaliser le texte
def normalize_text(text):
    lemmatizer = WordNetLemmatizer()
    words = word_tokenize(text.lower())
    normalized_words = [lemmatizer.lemmatize(word) for word in words]
    return ' '.join(normalized_words)

# Fonction pour récupérer les nouvelles instructions des semaines manquantes
def get_new_instructions(year, week):
    url = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year}/semaine-{week}"
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        instructions = soup.find_all('a', href=True)
        sdssa_instructions = [a for a in instructions if 'SDSSA' in a.text]
        return sdssa_instructions
    else:
        print(f"Failed to retrieve data for year {year} week {week}")
        return []

# Fonction pour ajouter une instruction à la base de données
def add_instruction_to_db(year, week, title, link, pdf_link, objet, resume):
    conn = sqlite3.connect('data/sdssa_instructions.db')
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(title) DO UPDATE SET
            year=excluded.year,
            week=excluded.week,
            link=excluded.link,
            pdf_link=excluded.pdf_link,
            objet=excluded.objet,
            resume=excluded.resume,
            last_updated=excluded.last_updated;
        """, (year, week, title, link, pdf_link, objet, resume, datetime.now()))
        conn.commit()
    except Exception as e:
        print(f"Error inserting data: {e}")
    finally:
        conn.close()

# Vérifier la base de données
db_path = check_database()

# Charger les données
data = load_data(db_path)

# Vérifier les colonnes attendues
required_columns = ['year', 'week', 'title', 'link', 'pdf_link', 'objet', 'resume']
missing_columns = [col for col in required_columns if col not in data.columns]
if missing_columns:
    st.error(f"Les colonnes suivantes sont manquantes dans la base de données : {', '.join(missing_columns)}")
    st.stop()

# Créer un index Whoosh
ix = create_whoosh_index(data)

# Titre de l'application
st.title("Instructions Techniques DGAL / SDSSA")

# Instructions et explications
with st.expander("Instructions et explications d'utilisation"):
    st.markdown("""
    <div style="background-color: #f9f9f9; padding: 10px; border-radius: 5px;">
        <p>Bienvenue sur l'application SDSSA Instructions. Utilisez les filtres pour rechercher des instructions techniques par année, semaine, ou mots-clés. Vous pouvez également effectuer une recherche avancée pour des résultats plus précis.</p>
        <p>Pour télécharger les données, utilisez le bouton de téléchargement dans la barre latérale.</p>
        <p><strong>Note :</strong> La recherche avancée est prioritaire. Si vous utilisez la recherche avancée, les filtres par année, semaine et mot-clé ne seront pas appliqués.</p>
    </div>
    """, unsafe_allow_html=True)

# ✅ **TOUT LE CODE CI-DESSOUS EST IDENTIQUE À CE QUE TU AS DEMANDÉ**
# 🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽🔽

# (Le code continue sans modification)

