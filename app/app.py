import streamlit as st
import pandas as pd
import sqlite3
import os
import requests
from bs4 import BeautifulSoup
from whoosh.index import create_in, exists_in, open_dir, LockError
from whoosh.fields import Schema, TEXT, ID
from whoosh.qparser import QueryParser
from whoosh.analysis import StemmingAnalyzer, LowercaseFilter, StopFilter
import nltk
from nltk.corpus import wordnet
from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize
from datetime import datetime, timedelta
import time
import traceback
import subprocess  # Pour les commandes git

# Configuration de la page Streamlit
st.set_page_config(layout="wide")

# --- Initialisation NLTK ---
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')

# --- Configuration des répertoires ---
os.makedirs('data', exist_ok=True)

# --- Fonctions de gestion de la base de données SQLite ---
def ensure_database_structure():
    """Vérifie et crée la structure de la base de données."""
    db_path = 'data/sdssa_instructions.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
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
            )
        """)
        conn.commit()
        cursor.execute("PRAGMA table_info(instructions)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'last_updated' not in columns:
            cursor.execute("ALTER TABLE instructions ADD COLUMN last_updated TIMESTAMP")
            conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"Erreur base de données: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def check_database():
    """Vérifie si la base de données existe."""
    db_path = 'data/sdssa_instructions.db'
    if not os.path.exists(db_path):
        st.error(f"Base de données {db_path} introuvable.")
        st.stop()
    return db_path

def load_data(db_path):
    """Charge les données depuis la base de données."""
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM instructions", conn)
    conn.close()
    return df

def add_instruction_to_db(year, week, title, link, pdf_link, objet, resume):
    """Ajoute ou met à jour une instruction dans la base de données."""
    conn = sqlite3.connect('data/sdssa_instructions.db')
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (year, week, title, link, pdf_link, objet, resume, datetime.now()))
        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"Erreur DB insertion/mise à jour: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

# --- Fonctions de Web Scraping ---
def get_new_instructions(year, week):
    """Récupère les nouvelles instructions SDSSA pour une année et semaine données."""
    url = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year}/semaine-{week}"
    try:
        response = requests.get(url, timeout=10)
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
                try:
                    detail_response = requests.get(link, timeout=10)
                    if detail_response.status_code == 200:
                        soup = BeautifulSoup(detail_response.content, 'html.parser')
                        objet_tag = soup.find('b', text="OBJET : ")
                        objet = objet_tag.next_sibling.strip() if objet_tag and objet_tag.next_sibling else "OBJET : Inconnu"
                        resume_tag = soup.find('b', text="RESUME : ")
                        resume = resume_tag.next_sibling.strip() if resume_tag and resume_tag.next_sibling else "RESUME : Inconnu"
                        new_instructions.append((instruction.text, link, pdf_link, objet, resume))
                except requests.RequestException as e:
                    st.warning(f"Erreur détails {link}: {e}")
                    new_instructions.append((instruction.text, link, pdf_link, "OBJET : Inconnu", "RESUME : Inconnu"))
            return new_instructions
        else:
            st.warning(f"Impossible de récupérer année {year} semaine {week} (Status: {response.status_code})")
            return []
    except requests.RequestException as e:
        st.error(f"Erreur connexion année {year} semaine {week}: {e}")
        return []

# --- Fonctions de Normalisation de Texte et Indexation Whoosh ---
def create_whoosh_index(df):
    """Crée ou ouvre l'index Whoosh."""
    analyzer = StemmingAnalyzer() | LowercaseFilter() | StopFilter()
    schema = Schema(title=TEXT(stored=True, analyzer=analyzer),
                    objet=TEXT(stored=True, analyzer=analyzer),
                    resume=TEXT(stored=True, analyzer=analyzer),
                    content=TEXT(analyzer=analyzer))
    index_dir = "indexdir"
    if not os.path.exists(index_dir):
        os.mkdir(index_dir)
    try:
        if not exists_in(index_dir):
            ix = create_in(index_dir, schema)
            st.info("Création index Whoosh...")
        else:
            ix = open_dir(index_dir)
            st.info("Ouverture index Whoosh existant...")
        writer = ix.writer()
        for index, row in df.iterrows():
            writer.add_document(title=row['title'], objet=row['objet'], resume=row['resume'], content=f"{row['title']} {row['objet']} {row['resume']}")
        writer.commit()
        st.success("Index Whoosh mis à jour.")
        return ix
    except LockError as e:
        st.error(f"Erreur verrouillage index Whoosh: {e}")
        st.error("Réessayez plus tard ou redémarrez l'app.")
        st.stop()
        return None
    except Exception as e:
        st.error(f"Erreur index Whoosh: {e}")
        st.error(traceback.format_exc())
        st.stop()
        return None

def get_synonyms(word):
    """Récupère les synonymes d'un mot."""
    synonyms = set()
    for syn in wordnet.synsets(word):
        for lemma in syn.lemmas():
            synonyms.add(lemma.name().lower())
    return synonyms

def normalize_text(text):
    """Normalise le texte."""
    lemmatizer = WordNetLemmatizer()
    words = word_tokenize(text.lower())
    normalized_words = [lemmatizer.lemmatize(word) for word in words]
    return ' '.join(normalized_words)

# --- Initialisation et Chargement des Données ---
ensure_database_structure()
db_path = check_database()
data = load_data(db_path)
required_columns = ['year', 'week', 'title', 'link', 'pdf_link', 'objet', 'resume']
missing_columns = [col for col in required_columns if col not in data.columns]
if missing_columns:
    st.error(f"Colonnes manquantes: {', '.join(missing_columns)}")
    st.stop()
ix = create_whoosh_index(data)
if ix is None:
    st.error("Échec initialisation index Whoosh.")
    st.stop()

# --- Interface Utilisateur Streamlit ---
st.title("Instructions Techniques DGAL / SDSSA")

with st.expander("Instructions"):
    st.markdown("""
    <div style="background-color: #f9f9f9; padding: 10px; border-radius: 5px;">
        <p>Bienvenue ! Filtrez par année/semaine ou mots-clés.</p>
        <p>Téléchargez les données via le bouton latéral.</p>
        <p><strong>Note :</strong> Recherche avancée prioritaire.</p>
    </div>
    """, unsafe_allow_html=True)

# --- Barre latérale ---
st.sidebar.subheader("Recherche avancée")
advanced_search = st.sidebar.text_input("Recherche avancée")

with st.sidebar.expander("Filtrer par année et semaine"):
    years = data['year'].unique()
    weeks = data['week'].unique()
    all_weeks_option = "Toutes les semaines"
    weeks = sorted(set(weeks))
    weeks.insert(0, all_weeks_option)
    year = st.selectbox("Année", years)
    week = st.selectbox("Semaine", weeks)

st.sidebar.markdown("""
    <div style="text-align: center; margin-top: 20px; width: 100%;">
        <a href="https://www.visipilot.com" target="_blank">
            <img src="https://github.com/M00N69/sdssa-instructions-app/blob/main/app/assets/logo.png?raw=true" alt="Visipilot Logo" style="width: 100%;">
        </a>
    </div>
    """, unsafe_allow_html=True)

# --- Filtrage et Affichage ---
filtered_data = data.copy()

if advanced_search:
    normalized_search = normalize_text(advanced_search)
    synonyms = set()
    for word in word_tokenize(normalized_search):
        synonyms.update(get_synonyms(word))
    synonyms.add(normalized_search)
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
    if week != all_weeks_option:
        filtered_data = filtered_data[(filtered_data['year'] == year) & (filtered_data['week'] == week)]
    else:
        filtered_data = filtered_data[filtered_data['year'] == year]

if filtered_data.empty:
    st.write("Aucun résultat.")
else:
    st.write("Résultats :")
    st.dataframe(filtered_data[['objet', 'resume']])

    st.header("Détails Instruction")
    selected_title = st.selectbox("Sélectionner une instruction", filtered_data['title'])
    if selected_title:
        instruction_details = filtered_data[filtered_data['title'] == selected_title].iloc[0]
        st.markdown(f"### Détails: {selected_title}")
        st.markdown(f"**Année:** {instruction_details['year']}")
        st.markdown(f"**Semaine:** {instruction_details['week']}")
        st.markdown(f"**Objet:** {instruction_details['objet']}")
        st.markdown(f"**Résumé:** {instruction_details['resume']}")
        st.markdown(f"**Lien:** [{instruction_details['title']}]({instruction_details['link']})")
        st.markdown(f"**PDF:** [{instruction_details['title']}]({instruction_details['pdf_link']})")

# --- Téléchargement et Mise à Jour ---
st.sidebar.header("Télécharger")
if st.sidebar.button("Télécharger CSV"):
    if filtered_data.empty:
        st.sidebar.warning("Aucune donnée à télécharger.")
    else:
        csv = filtered_data.to_csv(index=False).encode('utf-8')
        st.sidebar.download_button(label="Télécharger", data=csv, file_name="sdssa_instructions.csv", mime="text/csv")

if st.sidebar.button("Mettre à jour les données"):
    with st.spinner("Mise à jour des instructions..."):
        db_path = check_database()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        new_notes_added = False # Flag to track if new notes were added

        try:
            cursor.execute("SELECT MAX(year), MAX(week) FROM instructions")
            latest_year_db, latest_week_db = cursor.fetchone()
            latest_year_db = latest_year_db if latest_year_db else 2019
            latest_week_db = latest_week_db if latest_week_db else 0

            current_year, current_week, _ = datetime.now().isocalendar()

            st.write(f"**DEBUG - DB Latest Year:** {latest_year_db}, **DB Latest Week:** {latest_week_db}") # DEBUG
            st.write(f"**DEBUG - Current Year:** {current_year}, **Current Week:** {current_week}") # DEBUG

            weeks_to_check = []
            processed_weeks = set() # To avoid duplicates, although logic should prevent them

            if latest_year_db == current_year:
                st.write("**DEBUG - Condition: latest_year_db == current_year**") # DEBUG
                start_week = latest_week_db + 1
                end_week = current_week
                for week_num in range(start_week, end_week + 1):
                    if (current_year, week_num) not in processed_weeks: # Check for duplicates
                        weeks_to_check.append((current_year, week_num))
                        processed_weeks.add((current_year, week_num))
                        st.write(f"**DEBUG - Adding week:** {(current_year, week_num)} (Same Year)") # DEBUG

            elif latest_year_db < current_year:
                st.write("**DEBUG - Condition: latest_year_db < current_year**") # DEBUG
                # Add weeks for years between latest_year_db + 1 and current_year (exclusive of current_year)
                for year_to_check in range(latest_year_db + 1, current_year):
                    st.write(f"**DEBUG - Adding full year:** {year_to_check}") # DEBUG
                    for week_num in range(1, 53):
                        if (year_to_check, week_num) not in processed_weeks: # Check for duplicates
                            weeks_to_check.append((year_to_check, week_num))
                            processed_weeks.add((year_to_check, week_num))
                            st.write(f"**DEBUG - Adding week:** {(year_to_check, week_num)} (Full Year)") # DEBUG

                # Add weeks for the current year (from week 1 to current_week)
                st.write(f"**DEBUG - Adding weeks for current year: {current_year}**") # DEBUG
                for week_num in range(1, current_week + 1):
                    if (current_year, week_num) not in processed_weeks: # Check for duplicates
                        weeks_to_check.append((current_year, week_num))
                        processed_weeks.add((current_year, week_num))
                        st.write(f"**DEBUG - Adding week:** {(current_year, week_num)} (Current Year)") # DEBUG
            else: # latest_year_db > current_year (shouldn't happen) or latest_year_db is None (empty DB)
                st.write("**DEBUG - Condition: latest_year_db >= current_year or None**") # DEBUG
                #For empty DB or unexpected case, check current year weeks from 1 to current_week
                for week_num in range(1, current_week + 1):
                    if (current_year, week_num) not in processed_weeks:
                        weeks_to_check.append((current_year, week_num))
                        processed_weeks.add((current_year, week_num))
                        st.write(f"**DEBUG - Adding week:** {(current_year, week_num)} (Unexpected/Empty DB Case)") # DEBUG


            st.write(f"**Semaines à vérifier:** {weeks_to_check}") # DEBUG: Print weeks to check

            new_instructions_total = 0
            for year_to_check, week_num in weeks_to_check:
                # DEBUG: Print URL being requested for each week
                url_to_check = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year_to_check}/semaine-{week_num}"
                st.write(f"Vérification de l'URL: {url_to_check}")

                instructions = get_new_instructions(year_to_check, week_num)
                new_instructions_total += len(instructions)

                st.write(f"Instructions récupérées pour année {year_to_check}, semaine {week_num}: {len(instructions)}") # DEBUG: Print instructions found per week

                for title, link, pdf_link, objet, resume in instructions:
                    if add_instruction_to_db(year_to_check, week_num, title, link, pdf_link, objet, resume):
                        new_notes_added = True # Set flag to True if any new note is added

            if new_notes_added:
                st.success(f"{new_instructions_total} nouvelles instructions ajoutées !")
            else:
                st.info("Aucune nouvelle instruction trouvée.")

            data = load_data(db_path)
            ix = create_whoosh_index(data)

            if new_notes_added: # Push to GitHub only if new notes were added
                github_token = st.secrets["GITHUB_TOKEN"]
                repo_path = "."

                try:
                    with st.spinner("Publication sur GitHub..."):
                        subprocess.run(["git", "config", "--global", "user.name", "Streamlit App"], check=True, capture_output=True)
                        subprocess.run(["git", "config", "--global", "user.email", "streamlit.app@example.com"], check=True, capture_output=True)
                        subprocess.run(["git", "add", "data/sdssa_instructions.db", "indexdir"], check=True, capture_output=True)
                        commit_message = "MAJ auto DB et index via Streamlit App"
                        subprocess.run(["git", "commit", "-m", commit_message], check=True, capture_output=True)
                        remote_repo = f"https://{github_token}@github.com/M00N69/sdssa-instructions-app.git"
                        subprocess.run(["git", "push", "origin", "main", "--force"], check=True, capture_output=True)
                    st.success("Publié sur GitHub!")
                except subprocess.CalledProcessError as e:
                    st.error(f"Erreur publication GitHub: {e.stderr.decode()}")
                except Exception as e:
                    st.error(f"Erreur inattendue publication GitHub: {e}")
                    st.error(traceback.format_exc())
            elif ix: # Success message if index updated but no new notes for GitHub push
                st.info("Base de données locale mise à jour, mais aucune nouvelle instruction trouvée. Pas de publication GitHub.")

        except Exception as e:
            st.error(f"Erreur lors de la mise à jour: {e}")
            st.error(traceback.format_exc())
        finally:
            conn.close()

# --- Mises à jour récentes ---
st.sidebar.header("Mises à jour récentes")
if st.sidebar.button("Afficher les mises à jour récentes"):
    if 'last_updated' not in data.columns:
        st.error("Colonne 'last_updated' manquante.")
    else:
        recent_updates = data.sort_values(by='last_updated', ascending=False).head(10)
        st.write("Dernières mises à jour :")
        st.dataframe(recent_updates[['title', 'link', 'pdf_link', 'objet', 'resume', 'last_updated']])

# --- Options avancées ---
with st.sidebar.expander("Options avancées"):
    auto_update_freq = st.selectbox("Fréquence MAJ auto", ["Désactivée", "Quotidienne", "Hebdomadaire", "Mensuelle"])
    if auto_update_freq != "Désactivée":
        st.info(f"MAJ auto: {auto_update_freq}")
