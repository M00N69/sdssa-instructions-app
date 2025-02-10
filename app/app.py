import streamlit as st
import pandas as pd
import sqlite3
import os
from whoosh.index import create_in
from whoosh.fields import Schema, TEXT, ID
from whoosh.qparser import QueryParser
from whoosh.analysis import StemmingAnalyzer, LowercaseFilter, StopFilter
import nltk
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize

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
st.title("Instructions Techniques SDSSA")

# Afficher les filtres
st.sidebar.header("Filtres")
years = data['year'].unique()
weeks = data['week'].unique()
all_weeks_option = "Toutes les semaines"
weeks = sorted(set(weeks))
weeks.insert(0, all_weeks_option)  # Ajouter l'option "Toutes les semaines" au début
year = st.sidebar.selectbox("Année", years)
week = st.sidebar.selectbox("Semaine", weeks)
keyword = st.sidebar.text_input("Mot-clé")
advanced_search = st.sidebar.text_input("Recherche avancée")

# Initialiser filtered_data avec toutes les données
filtered_data = data.copy()

# Filtrer les données selon les filtres d'année et de semaine
if week != all_weeks_option:
    filtered_data = filtered_data[(filtered_data['year'] == year) & (filtered_data['week'] == week)]
else:
    filtered_data = filtered_data[filtered_data['year'] == year]

# Filtrer les données selon le mot-clé
if keyword:
    filtered_data = filtered_data[filtered_data.apply(lambda row: keyword.lower() in row['title'].lower() or keyword.lower() in row['objet'].lower() or keyword.lower() in row['resume'].lower(), axis=1)]

# Recherche avancée avec Whoosh
if advanced_search:
    # Normaliser la recherche avancée
    normalized_search = normalize_text(advanced_search)
    # Trouver des synonymes
    synonyms = set()
    for word in word_tokenize(normalized_search):
        synonyms.update(get_synonyms(word))
    synonyms.add(normalized_search)
    
    # Créer une requête qui inclut les synonymes
    query_string = " OR ".join([f"content:{syn}" for syn in synonyms])
    with ix.searcher() as searcher:
        query = QueryParser("content", ix.schema).parse(query_string)
        results = searcher.search(query)
        filtered_data = pd.DataFrame([{
            'year': data.loc[data['title'] == hit['title'], 'year'].values[0],
            'week': data.loc[data['title'] == hit['title'], 'week'].values[0],
            'title': hit['title'],
            'link': data.loc[data['title'] == hit['title'], 'link'].values[0],
            'pdf_link': data.loc[data['title'] == hit['title'], 'pdf_link'].values[0],
            'objet': hit['objet'],
            'resume': hit['resume']
        } for hit in results])
    if filtered_data.empty:
        st.write(f"Aucun résultat trouvé pour la recherche avancée : '{advanced_search}'.")
    else:
        st.write(f"Résultats pour la recherche avancée : '{advanced_search}':")
        st.dataframe(filtered_data[['title', 'link', 'pdf_link', 'objet', 'resume']])
else:
    # Afficher les résultats filtrés par année et semaine
    if filtered_data.empty:
        if week == all_weeks_option:
            st.write(f"Aucun résultat trouvé pour l'année {year}.")
        else:
            st.write(f"Aucun résultat trouvé pour l'année {year}, semaine {week}.")
    else:
        if week == all_weeks_option:
            st.write(f"Résultats pour l'année {year}:")
        else:
            st.write(f"Résultats pour l'année {year}, semaine {week}:")
        st.dataframe(filtered_data[['title', 'link', 'pdf_link', 'objet', 'resume']])

# Téléchargement des données
st.sidebar.header("Télécharger les données")
if st.sidebar.button("Télécharger le CSV"):
    if filtered_data.empty:
        st.sidebar.warning("Aucune donnée à télécharger.")
    else:
        csv = filtered_data.to_csv(index=False).encode('utf-8')
        st.sidebar.download_button(
            label="Télécharger",
            data=csv,
            file_name="sdssa_instructions.csv",
            mime="text/csv"
        )

# Afficher les mises à jour récentes
st.sidebar.header("Mises à jour récentes")
if st.sidebar.button("Afficher les mises à jour récentes"):
    if 'last_updated' not in data.columns:
        st.error("La colonne 'last_updated' est manquante dans la base de données.")
    else:
        recent_updates = data.sort_values(by='last_updated', ascending=False).head(10)
        st.write("Dernières mises à jour :")
        st.dataframe(recent_updates[['title', 'link', 'pdf_link', 'objet', 'resume', 'last_updated']])

# Afficher les détails d'une instruction
st.sidebar.header("Détails d'une instruction")
if filtered_data.empty:
    st.sidebar.warning("Aucune instruction à sélectionner.")
else:
    selected_title = st.sidebar.selectbox("Sélectionner une instruction", filtered_data['title'])
    if selected_title:
        instruction_details = filtered_data[filtered_data['title'] == selected_title].iloc[0]
        st.write(f"### Détails de l'instruction : {selected_title}")
        st.write(f"**Année :** {instruction_details['year']}")
        st.write(f"**Semaine :** {instruction_details['week']}")
        st.write(f"**Objet :** {instruction_details['objet']}")
        st.write(f"**Résumé :** {instruction_details['resume']}")
        st.write(f"**Lien :** [{instruction_details['title']}]({instruction_details['link']})")
        st.write(f"**Télécharger le PDF :** [{instruction_details['title']}]({instruction_details['pdf_link']})")
