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
        new_instructions = []
        for instruction in sdssa_instructions:
            href = instruction['href']
            if not href.startswith(('http://', 'https://')):
                href = f"https://info.agriculture.gouv.fr{href}"
            link = href
            pdf_link = link.replace("/detail", "/telechargement")
            new_instructions.append((instruction.text, link, pdf_link))
        return new_instructions
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
    except sqlite3.Error as e:
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

# Recherche avancée
st.sidebar.subheader("Recherche avancée")
advanced_search = st.sidebar.text_input("Recherche avancée")
st.sidebar.markdown("Utilisez la recherche avancée pour inclure des synonymes et obtenir des résultats plus précis.")

# Filtres par année et semaine dans un expander
with st.sidebar.expander("Filtrer par année et semaine"):
    years = data['year'].unique()
    weeks = data['week'].unique()
    all_weeks_option = "Toutes les semaines"
    weeks = sorted(set(weeks))
    weeks.insert(0, all_weeks_option)  # Ajouter l'option "Toutes les semaines" au début
    year = st.selectbox("Année", years)
    week = st.selectbox("Semaine", weeks)

# Logo Visipilot
st.sidebar.markdown(
    """
    <div style="text-align: center; margin-top: 20px; width: 100%;">
        <a href="https://www.visipilot.com" target="_blank">
            <img src="https://github.com/M00N69/sdssa-instructions-app/blob/main/app/assets/logo.png?raw=true" alt="Visipilot Logo" style="width: 100%;">
        </a>
    </div>
    """,
    unsafe_allow_html=True
)

# Initialiser filtered_data avec toutes les données
filtered_data = data.copy()

# Appliquer les filtres
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
else:
    # Filtrer les données selon les filtres d'année et de semaine
    if week != all_weeks_option:
        filtered_data = filtered_data[(filtered_data['year'] == year) & (filtered_data['week'] == week)]
    else:
        filtered_data = filtered_data[filtered_data['year'] == year]

# Afficher les résultats filtrés
if filtered_data.empty:
    st.write("Aucun résultat trouvé avec les filtres actuels.")
else:
    st.write("Résultats filtrés :")
    st.dataframe(filtered_data[['objet', 'resume']])

    # Sélection d'une instruction pour afficher les détails
    st.header("Détails d'une instruction")
    selected_title = st.selectbox("Sélectionner une instruction", filtered_data['title'])
    if selected_title:
        instruction_details = filtered_data[filtered_data['title'] == selected_title].iloc[0]
        st.markdown(f"### Détails de l'instruction : {selected_title}")
        st.markdown(f"**Année :** {instruction_details['year']}")
        st.markdown(f"**Semaine :** {instruction_details['week']}")
        st.markdown(f"**Objet :** {instruction_details['objet']}")
        st.markdown(f"**Résumé :** {instruction_details['resume']}")
        st.markdown(f"**Lien :** [{instruction_details['title']}]({instruction_details['link']})")
        st.markdown(f"**Télécharger le PDF :** [{instruction_details['title']}]({instruction_details['pdf_link']})")

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

# Bouton pour mettre à jour les données
if st.sidebar.button("Mettre à jour les données"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 🔍 Trouver la dernière semaine enregistrée
        cursor.execute("SELECT MAX(year), MAX(week) FROM instructions;")
        latest_entry = cursor.fetchone()

        # Si la base est vide, on commence en 2019 semaine 1
        latest_year, latest_week = latest_entry if latest_entry != (None, None) else (2019, 1)

        current_year, current_week = datetime.now().isocalendar()[:2]

        # 📅 Identifier les semaines à vérifier (uniquement après la dernière semaine en base)
        weeks_to_check = []
        for year in range(latest_year, current_year + 1):
            start_week = latest_week + 1 if year == latest_year else 1
            end_week = current_week if year == current_year else 52
            for week in range(start_week, end_week + 1):
                weeks_to_check.append((year, week))

        st.write(f"📅 Semaines à vérifier : {weeks_to_check}")

        # 📡 Récupérer uniquement les nouvelles instructions
        new_instructions = []
        for year, week in weeks_to_check:
            instructions = get_new_instructions(year, week)
            for instruction in instructions:
                link = f"https://info.agriculture.gouv.fr{instruction['href']}"
                pdf_link = link.replace("/detail", "/telechargement")

                # Récupérer l'objet et le résumé
                response = requests.get(link)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    objet = soup.find('h1').text.strip() if soup.find('h1') else "OBJET : Inconnu"
                    resume = soup.find('p').text.strip() if soup.find('p') else "RESUME : Inconnu"
                else:
                    objet, resume = "OBJET : Inconnu", "RESUME : Inconnu"

                # 🔍 Vérifier si cette instruction est déjà en base
                cursor.execute("SELECT COUNT(*) FROM instructions WHERE title = ?", (instruction.text,))
                exists = cursor.fetchone()[0]

                if exists == 0:
                    new_instructions.append((year, week, instruction.text, link, pdf_link, objet, resume))

        st.write(f"📄 {len(new_instructions)} nouvelles instructions trouvées.")

        # ✅ Ajouter les nouvelles instructions à la base
        added_count = 0
        for instruction in new_instructions:
            year, week, title, link, pdf_link, objet, resume = instruction
            cursor.execute("""
                INSERT INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (year, week, title, link, pdf_link, objet, resume, datetime.now()))
            added_count += 1

        conn.commit()

        if added_count > 0:
            st.success(f"{added_count} nouvelles instructions ont été ajoutées !")
        else:
            st.info("Aucune nouvelle instruction trouvée.")

    except sqlite3.Error as e:
        st.error(f"Erreur SQLite : {e}")
    except Exception as e:
        st.error(f"Erreur inattendue : {e}")
    finally:
        if cursor:
            try:
                cursor.close()
                st.write("✅ Connexion fermée proprement.")
            except sqlite3.ProgrammingError:
                st.write("⚠️ Impossible de fermer le curseur, il est déjà fermé.")
        if conn:
            try:
                conn.close()
                st.write("✅ Connexion fermée proprement.")
            except sqlite3.ProgrammingError:
                st.write("⚠️ La connexion était déjà fermée.")

# Afficher les mises à jour récentes
st.sidebar.header("Mises à jour récentes")
if st.sidebar.button("Afficher les mises à jour récentes"):
    if 'last_updated' not in data.columns:
        st.error("La colonne 'last_updated' est manquante dans la base de données.")
    else:
        recent_updates = data.sort_values(by='last_updated', ascending=False).head(10)
        st.write("Dernières mises à jour :")
        st.dataframe(recent_updates[['title', 'link', 'pdf_link', 'objet', 'resume', 'last_updated']])

