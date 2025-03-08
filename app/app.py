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
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration de la page
st.set_page_config(layout="wide")

# Exécuter le script d'initialisation NLTK
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')

# Créer le répertoire data s'il n'existe pas
os.makedirs('data', exist_ok=True)

# Fonction pour vérifier et créer la structure de la base de données si nécessaire
def ensure_database_structure():
    db_path = 'data/sdssa_instructions.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # Vérifier si la table existe
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='instructions'")
        table_exists = cursor.fetchone()

        if not table_exists:
            # Créer la table si elle n'existe pas
            cursor.execute("""
                CREATE TABLE instructions (
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
            st.success("Structure de la base de données créée avec succès.")

        # Vérifier si la colonne last_updated existe
        cursor.execute("PRAGMA table_info(instructions)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'last_updated' not in columns:
            cursor.execute("ALTER TABLE instructions ADD COLUMN last_updated TIMESTAMP")
            conn.commit()
            st.success("Colonne last_updated ajoutée à la table instructions.")

        return True
    except sqlite3.Error as e:
        st.error(f"Erreur lors de la création de la structure de la base de données: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

# Appeler la fonction pour s'assurer que la structure de la base de données est correcte
ensure_database_structure()

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
    index_dir = "indexdir" # Define index directory
    if not os.path.exists(index_dir):
        os.mkdir(index_dir)

    try:
        if not exists_in(index_dir): # Check if index already exists
            ix = create_in(index_dir, schema) # Create a new index
            st.info("Creating Whoosh index...") # Inform user index is being created
        else:
            ix = open_dir(index_dir) # Open existing index
            st.info("Opening existing Whoosh index...") # Inform user existing index is being opened

        writer = ix.writer() # Get writer - this is where LockError can occur
        for index, row in df.iterrows():
            writer.add_document(title=row['title'], objet=row['objet'], resume=row['resume'], content=f"{row['title']} {row['objet']} {row['resume']}")
        writer.commit()
        st.success("Whoosh index updated successfully.") # Indicate index update success
        return ix

    except LockError as e:
        st.error(f"Erreur de verrouillage de l'index Whoosh: {e}") # More informative error message
        st.error("Veuillez réessayer de mettre à jour les données plus tard. Si le problème persiste, redémarrez l'application.") # User guidance
        st.stop() # Stop the app to prevent further issues with locked index
        return None # Or handle as appropriate, e.g., return a flag indicating failure
    except Exception as e: # Catch other potential exceptions during indexing
        st.error(f"Erreur inattendue lors de la création/mise à jour de l'index Whoosh: {e}")
        st.error(traceback.format_exc()) # Show full traceback for debugging
        st.stop()
        return None


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
    try:
        response = requests.get(url, timeout=10)  # Ajouter un timeout
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

                # Récupérer l'objet et le résumé
                try:
                    detail_response = requests.get(link, timeout=10)
                    if detail_response.status_code == 200:
                        soup = BeautifulSoup(detail_response.content, 'html.parser')
                        objet = "OBJET : Inconnu"
                        resume = "RESUME : Inconnu"

                        # Trouver l'objet
                        objet_tag = soup.find('b', text="OBJET : ")
                        if objet_tag and objet_tag.next_sibling:
                            objet = objet_tag.next_sibling.strip()

                        # Trouver le résumé
                        resume_tag = soup.find('b', text="RESUME : ")
                        if resume_tag and resume_tag.next_sibling:
                            resume = resume_tag.next_sibling.strip()

                        new_instructions.append((instruction.text, link, pdf_link, objet, resume))
                except requests.RequestException as e:
                    st.warning(f"Erreur lors de la récupération des détails pour {link}: {e}")
                    # Ajouter quand même l'instruction avec des informations partielles
                    new_instructions.append((instruction.text, link, pdf_link, "OBJET : Inconnu", "RESUME : Inconnu"))

            return new_instructions
        else:
            st.warning(f"Impossible de récupérer les données pour l'année {year} semaine {week} (Status code: {response.status_code})")
            return []
    except requests.RequestException as e:
        st.error(f"Erreur de connexion pour l'année {year} semaine {week}: {e}")
        return []

# Fonction pour ajouter une instruction à la base de données
def add_instruction_to_db(year, week, title, link, pdf_link, objet, resume):
    conn = sqlite3.connect('data/sdssa_instructions.db')
    cursor = conn.cursor()
    try:
        # Vérifier si l'instruction existe déjà
        cursor.execute("SELECT COUNT(*) FROM instructions WHERE title = ?", (title,))
        exists = cursor.fetchone()[0]

        if exists > 0:
            # Mettre à jour l'instruction existante
            cursor.execute("""
                UPDATE instructions
                SET year=?, week=?, link=?, pdf_link=?, objet=?, resume=?, last_updated=?
                WHERE title=?
            """, (year, week, link, pdf_link, objet, resume, datetime.now(), title))
        else:
            # Insérer une nouvelle instruction
            cursor.execute("""
                INSERT INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (year, week, title, link, pdf_link, objet, resume, datetime.now()))

        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"Erreur d'insertion/mise à jour dans la base de données: {e}")
        conn.rollback()
        return False
    finally:
        cursor.close()
        conn.close()

# Fonction pour vérifier les nouvelles notes
def check_for_new_notes():
    db_path = check_database()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # Vérifier la connexion à la base de données
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='instructions';")
        table_exists = cursor.fetchone()
        if not table_exists:
            st.error("La table 'instructions' n'existe pas dans la base de données.")
            return

        # Trouver la dernière semaine enregistrée
        cursor.execute("SELECT MAX(year), MAX(week) FROM instructions;")
        latest_entry = cursor.fetchone()

        # Si la base est vide, on commence en 2019 semaine 1
        if latest_entry == (None, None):
            latest_year, latest_week = 2019, 1
        else:
            latest_year, latest_week = latest_entry

        st.write(f"Dernière année enregistrée : {latest_year}, Dernière semaine enregistrée : {latest_week}")

        current_year, current_week, _ = datetime.now().isocalendar()
        st.write(f"Année actuelle : {current_year}, Semaine actuelle : {current_week}")

        # Vérifier si la base de données est à jour
        if latest_year > current_year or (latest_year == current_year and latest_week >= current_week):
            st.info("La base de données est déjà à jour.")
            return

        # Identifier les semaines à vérifier
        weeks_to_check = []
        for year in range(latest_year, current_year + 1):
            start_week = latest_week + 1 if year == latest_year else 1
            end_week = current_week if year == current_year else 52 # Corrected to current_week
            if year == current_year:
                end_week = current_week # Ensure end_week is current_week for current year
            else:
                end_week = 52 # For past years, check up to week 52

            for week in range(start_week, end_week + 1):
                weeks_to_check.append((year, week))

        st.write(f"Semaines à vérifier : {weeks_to_check}") # Display weeks to be checked
        progress_bar = st.progress(0)

        # Récupérer uniquement les nouvelles instructions
        new_instructions = []
        for i, (year, week) in enumerate(weeks_to_check):
            instructions = get_new_instructions(year, week)
            st.write(f"Instructions récupérées pour l'année {year} semaine {week}: {len(instructions)}") # Display num instructions per week
            for title, link, pdf_link, objet, resume in instructions:
                # Vérifier si cette instruction est déjà en base
                cursor.execute("SELECT COUNT(*) FROM instructions WHERE title = ?", (title,))
                exists = cursor.fetchone()[0]

                if exists == 0:
                    new_instructions.append((year, week, title, link, pdf_link, objet, resume))

            # Mettre à jour la barre de progression
            progress = (i + 1) / len(weeks_to_check)
            progress_bar.progress(progress)

        st.write(f"{len(new_instructions)} nouvelles instructions trouvées.")

        # Ajouter les nouvelles instructions à la base
        added_count = 0
        for instruction in new_instructions:
            year, week, title, link, pdf_link, objet, resume = instruction
            # Utiliser la fonction add_instruction_to_db au lieu d'exécuter directement la requête
            if add_instruction_to_db(year, week, title, link, pdf_link, objet, resume):
                added_count += 1

        if added_count > 0:
            st.success(f"{added_count} nouvelles instructions ont été ajoutées !")
        else:
            st.info("Aucune nouvelle instruction trouvée.")

    except sqlite3.Error as e:
        st.error(f"Erreur SQLite : {e}")
    except Exception as e:
        st.error(f"Erreur inattendue : {e}")
        st.error(traceback.format_exc())
    finally:
        cursor.close()
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
    with st.spinner("Vérification des nouvelles instructions..."):
        check_for_new_notes()
        # Recharger les données après la mise à jour
        data = load_data(db_path)
        # Recréer l'index Whoosh
        ix = create_whoosh_index(data)
        if ix:
            st.success("Mise à jour terminée et données rechargées.")
        else:
            st.error("La mise à jour de l'index a échoué. Veuillez consulter les erreurs ci-dessus.")

# Afficher les mises à jour récentes
st.sidebar.header("Mises à jour récentes")
if st.sidebar.button("Afficher les mises à jour récentes"):
    if 'last_updated' not in data.columns:
        st.error("La colonne 'last_updated' est manquante dans la base de données.")
    else:
        recent_updates = data.sort_values(by='last_updated', ascending=False).head(10)
        st.write("Dernières mises à jour :")
        st.dataframe(recent_updates[['title', 'link', 'pdf_link', 'objet', 'resume', 'last_updated']])

# Options avancées pour la mise à jour automatique
with st.sidebar.expander("Options avancées"):
    auto_update_freq = st.selectbox(
        "Fréquence de mise à jour automatique",
        ["Désactivée", "Quotidienne", "Hebdomadaire", "Mensuelle"]
    )

    if auto_update_freq != "Désactivée":
        st.info(f"La mise à jour automatique est configurée sur: {auto_update_freq}")
        # Cette fonctionnalité nécessiterait un mécanisme de planification
        # comme APScheduler, ou une configuration externe avec cron
