import streamlit as st
import pandas as pd
import sqlite3
import os
import requests
from bs4 import BeautifulSoup
from whoosh.index import create_in
from whoosh.fields import Schema, TEXT
from whoosh.qparser import QueryParser
from whoosh.analysis import StemmingAnalyzer, LowercaseFilter, StopFilter
import nltk
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize
from datetime import datetime

# Configuration de la page
st.set_page_config(layout="wide")

# Initialisation NLTK
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')

# Vérification de la base de données
def check_database():
    db_path = 'data/sdssa_instructions.db'
    if not os.path.exists(db_path):
        st.error(f"La base de données {db_path} n'existe pas.")
        st.stop()
    return db_path

# Charger les données SQLite
def load_data(db_path):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM instructions", conn)
    conn.close()
    return df

# Création de l'index Whoosh
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
    for _, row in df.iterrows():
        writer.add_document(title=row['title'], objet=row['objet'], resume=row['resume'],
                            content=f"{row['title']} {row['objet']} {row['resume']}")
    writer.commit()
    return ix

# Recherche avancée avec synonymes
def get_synonyms(word):
    synonyms = set()
    for syn in wordnet.synsets(word):
        for lemma in syn.lemmas():
            synonyms.add(lemma.name().lower())
    return synonyms

def normalize_text(text):
    lemmatizer = WordNetLemmatizer()
    words = word_tokenize(text.lower())
    return ' '.join([lemmatizer.lemmatize(word) for word in words])

# Récupération des nouvelles instructions SDSSA
def get_new_instructions(year, week):
    url = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year}/semaine-{week}"
    response = requests.get(url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        instructions = soup.find_all('a', href=True)
        return [a for a in instructions if 'SDSSA' in a.text]
    return []

# Ajout des nouvelles instructions à la base
def add_instruction_to_db(year, week, title, link, pdf_link, objet, resume):
    conn = sqlite3.connect('data/sdssa_instructions.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM instructions WHERE title = ?", (title,))
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (year, week, title, link, pdf_link, objet, resume, datetime.now()))
        conn.commit()
    
    conn.close()

# Vérification de la base
db_path = check_database()
data = load_data(db_path)

# Création de l'index Whoosh
ix = create_whoosh_index(data)

# Interface utilisateur
st.title("Instructions Techniques DGAL / SDSSA")

# 📌 Recherche avancée
st.sidebar.subheader("Recherche avancée")
advanced_search = st.sidebar.text_input("Recherche avancée")

# 📌 Filtres par année et semaine
with st.sidebar.expander("Filtrer par année et semaine"):
    years = sorted(data['year'].unique(), reverse=True)
    weeks = sorted(data['week'].unique(), reverse=True)
    year = st.selectbox("Année", years)
    week = st.selectbox("Semaine", weeks)

# 📌 Traitement de la recherche
filtered_data = data.copy()

if advanced_search:
    normalized_search = normalize_text(advanced_search)
    synonyms = {normalized_search}
    for word in word_tokenize(normalized_search):
        synonyms.update(get_synonyms(word))

    query_string = " OR ".join([f"content:{syn}" for syn in synonyms])
    with ix.searcher() as searcher:
        query = QueryParser("content", ix.schema).parse(query_string)
        results = searcher.search(query)
        filtered_data = pd.DataFrame([
            {
                'year': data.loc[data['title'] == hit['title'], 'year'].values[0],
                'week': data.loc[data['title'] == hit['title'], 'week'].values[0],
                'title': hit['title'],
                'link': data.loc[data['title'] == hit['title'], 'link'].values[0],
                'pdf_link': data.loc[data['title'] == hit['title'], 'pdf_link'].values[0],
                'objet': hit['objet'],
                'resume': hit['resume']
            } for hit in results])

elif week:
    filtered_data = data[(data['year'] == year) & (data['week'] == week)]

# 📌 Affichage des résultats
st.dataframe(filtered_data[['objet', 'resume']])

# 📌 Sélection d'une instruction
if not filtered_data.empty:
    selected_title = st.selectbox("Sélectionner une instruction", filtered_data['title'])
    if selected_title:
        details = filtered_data[filtered_data['title'] == selected_title].iloc[0]
        st.markdown(f"### {selected_title}")
        st.markdown(f"**Année :** {details['year']}, **Semaine :** {details['week']}")
        st.markdown(f"**Objet :** {details['objet']}")
        st.markdown(f"**Résumé :** {details['resume']}")
        st.markdown(f"📎 [Lien]({details['link']}) | 📄 [PDF]({details['pdf_link']})")

# 📌 Mise à jour des données
if st.sidebar.button("Mettre à jour les données"):
    latest_year, latest_week = data[['year', 'week']].max()
    current_year, current_week = datetime.now().isocalendar()[:2]

    for year in range(latest_year, current_year + 1):
        for week in range(latest_week + 1, current_week + 1):
            new_instructions = get_new_instructions(year, week)
            for instruction in new_instructions:
                add_instruction_to_db(year, week, instruction.text, f"https://info.agriculture.gouv.fr{instruction['href']}", "", "OBJET", "RESUME")
    
    data = load_data(db_path)
    st.success("Mise à jour réussie !")


