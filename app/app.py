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
import subprocess
import hashlib
import glob
import shutil
from PIL import Image
from io import BytesIO
import base64  # Ajout de l'import pour encodage base64

# Configuration de la page Streamlit avec plus d'options
st.set_page_config(
    page_title="SDSSA Instructions - Visualisation et Recherche",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Styles CSS personnalisés ---
st.markdown(
    """
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E3A8A;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.8rem;
        font-weight: 600;
        color: #2563EB;
        margin-top: 1.5rem;
        margin-bottom: 1rem;
    }
    .card {
        background-color: #F9FAFB;
        border-radius: 10px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 20px;
    }
    .highlight-text {
        background-color: #DBEAFE;
        padding: 2px 5px;
        border-radius: 3px;
    }
    .success-message {
        background-color: #D1FAE5;
        color: #065F46;
        padding: 10px;
        border-radius: 5px;
        font-weight: 500;
    }
    .warning-message {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 10px;
        border-radius: 5px;
        font-weight: 500;
    }
    .error-message {
        background-color: #FEE2E2;
        color: #B91C1C;
        padding: 10px;
        border-radius: 5px;
        font-weight: 500;
    }
    .info-box {
        border-left: 4px solid #3B82F6;
        padding: 10px 15px;
        background-color: #EFF6FF;
        margin: 10px 0;
    }
    .stButton button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
        font-weight: 500;
    }
    .stSelectbox div[data-baseweb="select"] {
        border-radius: 5px;
    }
    .status-badge {
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 500;
    }
    .badge-success {
        background-color: #D1FAE5;
        color: #065F46;
    }
    .badge-warning {
        background-color: #FEF3C7;
        color: #92400E;
    }
    .tab-content {
        padding: 15px;
        border: 1px solid #E5E7EB;
        border-radius: 0 0 5px 5px;
        margin-top: -5px;
    }
    /* Footer style */
    .footer {
        text-align: center;
        margin-top: 50px;
        padding: 20px;
        border-top: 1px solid #E5E7EB;
        color: #6B7280;
    }
    /* Tableaux plus modernes */
    .dataframe-modern {
        border-collapse: collapse;
        width: 100%;
        border-radius: 8px;
        overflow: hidden;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .dataframe-modern th {
        background-color: #2563EB;
        color: white;
        padding: 12px;
        text-align: left;
    }
    .dataframe-modern td {
        padding: 10px;
        border-bottom: 1px solid #E5E7EB;
    }
    .dataframe-modern tr:nth-child(even) {
        background-color: #F3F4F6;
    }
    .dataframe-modern tr:hover {
        background-color: #EFF6FF;
    }
</style>
""",
    unsafe_allow_html=True,
)

# --- Initialisation de la session state ---
if "db_last_checked" not in st.session_state:
    st.session_state.db_last_checked = None
if "is_db_updated" not in st.session_state:
    st.session_state.is_db_updated = False
if "search_results" not in st.session_state:
    st.session_state.search_results = None
if "selected_instruction" not in st.session_state:
    st.session_state.selected_instruction = None
if "filter_year" not in st.session_state:
    st.session_state.filter_year = None
if "filter_week" not in st.session_state:
    st.session_state.filter_week = None
if "update_frequency" not in st.session_state:
    st.session_state.update_frequency = "Hebdomadaire"

# --- Initialisation NLTK ---
@st.cache_resource
def initialize_nltk():
    """Initialise les ressources NLTK."""
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt")

    try:
        nltk.data.find("corpora/wordnet")
    except LookupError:
        nltk.download("wordnet")
        nltk.download("omw-1.4")

initialize_nltk()

# --- Configuration des répertoires ---
os.makedirs("data", exist_ok=True)
os.makedirs("indexdir", exist_ok=True)
os.makedirs("backups", exist_ok=True)

# --- Fonction pour télécharger la base de données depuis GitHub ---
def download_db_from_github(force=False):
    """Télécharge la base de données depuis GitHub si une version plus récente est disponible."""
    # URL directe vers le fichier dans le dépôt GitHub
    github_raw_url = "https://raw.githubusercontent.com/M00N69/sdssa-instructions-app/main/data/sdssa_instructions.db"
    local_db_path = "data/sdssa_instructions.db"

    # Définir les headers avec un User-Agent
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        # Vérifier si le fichier existe localement et obtenir sa date de modification
        local_modification_time = None
        local_hash = None
        if os.path.exists(local_db_path):
            local_modification_time = os.path.getmtime(local_db_path)
            local_modification_date = datetime.fromtimestamp(local_modification_time)

            # Calculer le hash de la base locale pour détecter les changements
            with open(local_db_path, "rb") as f:
                local_hash = hashlib.md5(f.read()).hexdigest()

            with st.status(
                f"📅 Base de données locale du {local_modification_date.strftime('%d/%m/%Y à %H:%M')}"
            ):
                st.write("Vérification des mises à jour...")

        # Télécharger directement le fichier sans vérifier les en-têtes (plus fiable)
        with st.spinner("Téléchargement de la base de données..."):
            response = requests.get(
                github_raw_url, headers=headers, allow_redirects=True, timeout=30
            )

            if response.status_code == 200:
                # Calculer le hash de la nouvelle version
                new_content = response.content
                new_hash = hashlib.md5(new_content).hexdigest()

                # Vérifier si le contenu a réellement changé ou si le téléchargement est forcé
                if force or not local_hash or new_hash != local_hash:
                    # Créer une sauvegarde datée
                    if os.path.exists(local_db_path):
                        backup_date = datetime.now().strftime("%Y%m%d_%H%M%S")
                        backup_path = f"backups/sdssa_instructions_{backup_date}.db"
                        shutil.copy2(local_db_path, backup_path)
                        st.write(f"✅ Sauvegarde créée: {backup_path}")

                    # Écrire la nouvelle version
                    with open(local_db_path, "wb") as f:
                        f.write(new_content)

                    st.success("✅ Base de données mise à jour avec succès!")
                    st.session_state.is_db_updated = True

                    # Limiter le nombre de sauvegardes (garder les 5 plus récentes)
                    backups = sorted(glob.glob("backups/sdssa_instructions_*.db"))
                    if len(backups) > 5:
                        for old_backup in backups[:-5]:
                            os.remove(old_backup)

                    return True
                else:
                    st.info(
                        "📌 Le contenu de la base de données est identique - aucune mise à jour nécessaire"
                    )
                    return True
            else:
                st.error(f"❌ Erreur lors du téléchargement: {response.status_code}")
                return False

    except Exception as e:
        st.error(f"❌ Erreur lors du téléchargement de la base de données: {e}")
        st.error(traceback.format_exc())
        return False

# --- Fonctions de gestion de la base de données SQLite ---
def get_db_connection():
    """Crée et retourne une connexion à la base de données avec un context manager."""
    db_path = "data/sdssa_instructions.db"
    if not os.path.exists(db_path):
        st.error(
            "❌ Base de données non trouvée! Veuillez télécharger la base de données depuis GitHub."
        )
        st.stop()

    return sqlite3.connect(db_path)

def ensure_database_structure():
    """Vérifie et crée la structure de la base de données."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
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
                """
            )
            conn.commit()

            # Vérifier si la colonne last_updated existe
            cursor.execute("PRAGMA table_info(instructions)")
            columns = [column[1] for column in cursor.fetchall()]
            if "last_updated" not in columns:
                cursor.execute("ALTER TABLE instructions ADD COLUMN last_updated TIMESTAMP")
                conn.commit()

            return True
        except sqlite3.Error as e:
            st.error(f"❌ Erreur base de données: {e}")
            return False

def check_table_structure():
    """Vérifie la structure actuelle de la table instructions."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(instructions)")
        columns = cursor.fetchall()
        for column in columns:
            print(column)

def add_id_column_if_missing():
    """Ajoute la colonne 'id' si elle est manquante."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE instructions ADD COLUMN id INTEGER PRIMARY KEY AUTOINCREMENT")
            conn.commit()
            print("Colonne 'id' ajoutée avec succès.")
        except sqlite3.OperationalError as e:
            print(f"Erreur lors de l'ajout de la colonne 'id': {e}")

def recreate_table():
    """Recrée la table instructions avec la structure correcte."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS instructions")
        cursor.execute(
            """
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
            """
        )
        conn.commit()
        print("Table 'instructions' recréée avec succès.")

def load_data():
    """Charge les données depuis la base de données avec mise en cache."""

    # Utiliser le cache de Streamlit pour optimiser les performances
    @st.cache_data(ttl=300)  # Cache valide pendant 5 minutes
    def _load_data():
        with get_db_connection() as conn:
            query = "SELECT * FROM instructions"
            df = pd.read_sql_query(query, conn)
            return df

    try:
        return _load_data()
    except Exception as e:
        st.error(f"❌ Erreur lors du chargement des données: {e}")
        return pd.DataFrame()

def get_instruction_details(title):
    """Récupère les détails d'une instruction spécifique."""
    with get_db_connection() as conn:
        query = "SELECT * FROM instructions WHERE title = ?"
        df = pd.read_sql_query(query, conn, params=(title,))
        if not df.empty:
            return df.iloc[0]
        return None

def add_instruction_to_db(year, week, title, link, pdf_link, objet, resume):
    """Ajoute ou met à jour une instruction dans la base de données."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                    INSERT OR REPLACE INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (year, week, title, link, pdf_link, objet, resume, datetime.now()),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            st.error(f"❌ Erreur DB insertion/mise à jour: {e}")
            return False

# --- Fonctions de Web Scraping ---
def get_new_instructions(year, week):
    """Récupère les nouvelles instructions SDSSA pour une année et semaine données."""
    url = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year}/semaine-{week}"
    try:
        with st.spinner(f"Récupération données année {year}, semaine {week}..."):
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, "html.parser")
                instructions = soup.find_all("a", href=True)
                sdssa_instructions = [a for a in instructions if "SDSSA" in a.text]
                new_instructions = []

                progress_bar = st.progress(0.0)
                for idx, instruction in enumerate(sdssa_instructions):
                    href = instruction["href"]
                    if not href.startswith(("http://", "https://")):
                        href = f"https://info.agriculture.gouv.fr{href}"
                    link = href
                    pdf_link = link.replace("/detail", "/telechargement")

                    try:
                        detail_response = requests.get(link, timeout=15)
                        if detail_response.status_code == 200:
                            soup = BeautifulSoup(
                                detail_response.content, "html.parser"
                            )
                            objet_tag = soup.find("b", text="OBJET : ")
                            objet = (
                                objet_tag.next_sibling.strip()
                                if objet_tag and objet_tag.next_sibling
                                else "OBJET : Inconnu"
                            )
                            resume_tag = soup.find("b", text="RESUME : ")
                            resume = (
                                resume_tag.next_sibling.strip()
                                if resume_tag and resume_tag.next_sibling
                                else "RESUME : Inconnu"
                            )
                            new_instructions.append(
                                (instruction.text, link, pdf_link, objet, resume)
                            )
                    except requests.RequestException as e:
                        st.warning(f"⚠️ Erreur détails {link}: {e}")
                        new_instructions.append(
                            (
                                instruction.text,
                                link,
                                pdf_link,
                                "OBJET : Inconnu",
                                "RESUME : Inconnu",
                            )
                        )

                    # Mettre à jour la barre de progression
                    progress_bar.progress((idx + 1) / len(sdssa_instructions))
                    # Pause pour éviter de surcharger le serveur
                    time.sleep(0.5)

                return new_instructions
            else:
                st.warning(
                    f"⚠️ Impossible de récupérer année {year} semaine {week} (Status: {response.status_code})"
                )
                return []
    except requests.RequestException as e:
        st.error(f"❌ Erreur connexion année {year} semaine {week}: {e}")
        return []

# --- Fonctions de Normalisation de Texte et Indexation Whoosh ---
@st.cache_resource
def create_whoosh_index(df):
    """Crée ou ouvre l'index Whoosh."""
    analyzer = StemmingAnalyzer() | LowercaseFilter() | StopFilter()
    schema = Schema(
        title=TEXT(stored=True, analyzer=analyzer),
        objet=TEXT(stored=True, analyzer=analyzer),
        resume=TEXT(stored=True, analyzer=analyzer),
        content=TEXT(analyzer=analyzer),
    )
    index_dir = "indexdir"

    try:
        if not exists_in(index_dir) or len(os.listdir(index_dir)) == 0:
            ix = create_in(index_dir, schema)
            with st.spinner("Création index Whoosh..."):
                writer = ix.writer()
                for index, row in df.iterrows():
                    writer.add_document(
                        title=row["title"],
                        objet=row["objet"],
                        resume=row["resume"],
                        content=f"{row['title']} {row['objet']} {row['resume']}",
                    )
                writer.commit()
        else:
            ix = open_dir(index_dir)

        return ix
    except LockError as e:
        st.error(f"❌ Erreur verrouillage index Whoosh: {e}")
        st.error("Réessayez plus tard ou redémarrez l'app.")
        st.stop()
        return None
    except Exception as e:
        st.error(f"❌ Erreur index Whoosh: {e}")
        st.error(traceback.format_exc())
        st.stop()
        return None

def update_whoosh_index(df):
    """Met à jour l'index Whoosh avec les nouvelles données."""
    index_dir = "indexdir"
    if exists_in(index_dir):
        # Supprimer l'ancien index
        for f in os.listdir(index_dir):
            os.remove(os.path.join(index_dir, f))

    # Recréer l'index
    create_whoosh_index(df)

def get_synonyms(word):
    """Récupère les synonymes d'un mot."""
    synonyms = set()
    for syn in wordnet.synsets(word, lang="fra"):
        for lemma in syn.lemmas(lang="fra"):
            synonyms.add(lemma.name().lower())
    return synonyms

def normalize_text(text):
    """Normalise le texte."""
    lemmatizer = WordNetLemmatizer()
    words = word_tokenize(text.lower())
    normalized_words = [lemmatizer.lemmatize(word) for word in words]
    return " ".join(normalized_words)

# --- Fonction de recherche avancée ---
def search_instructions(query, ix, data):
    """Effectue une recherche avancée dans l'index Whoosh."""
    if not query or not ix:
        return data

    normalized_search = normalize_text(query)
    synonyms = set()
    for word in word_tokenize(normalized_search):
        synonyms.update(get_synonyms(word))

    # Ajouter les termes de recherche originaux
    synonyms.add(normalized_search)

    # Créer une requête combinée avec OR
    query_string = " OR ".join([f"content:{syn}" for syn in synonyms])

    try:
        with ix.searcher() as searcher:
            query_parser = QueryParser("content", ix.schema)
            parsed_query = query_parser.parse(query_string)
            results = searcher.search(parsed_query, limit=None)

            if len(results) > 0:
                filtered_data = pd.DataFrame(
                    [
                        {
                            "id": data.loc[data["title"] == hit["title"], "id"].values[
                                0
                            ]
                            if not data.loc[
                                data["title"] == hit["title"], "id"
                            ].empty
                            else None,
                            "year": data.loc[
                                data["title"] == hit["title"], "year"
                            ].values[0]
                            if not data.loc[
                                data["title"] == hit["title"], "year"
                            ].empty
                            else None,
                            "week": data.loc[
                                data["title"] == hit["title"], "week"
                            ].values[0]
                            if not data.loc[
                                data["title"] == hit["title"], "week"
                            ].empty
                            else None,
                            "title": hit["title"],
                            "link": data.loc[
                                data["title"] == hit["title"], "link"
                            ].values[0]
                            if not data.loc[
                                data["title"] == hit["title"], "link"
                            ].empty
                            else None,
                            "pdf_link": data.loc[
                                data["title"] == hit["title"], "pdf_link"
                            ].values[0]
                            if not data.loc[
                                data["title"] == hit["title"], "pdf_link"
                            ].empty
                            else None,
                            "objet": hit["objet"],
                            "resume": hit["resume"],
                            "last_updated": data.loc[
                                data["title"] == hit["title"], "last_updated"
                            ].values[0]
                            if not data.loc[
                                data["title"] == hit["title"], "last_updated"
                            ].empty
                            else None,
                            "score": hit.score,
                        }
                        for hit in results
                        if not data.loc[data["title"] == hit["title"]].empty
                    ]
                )

                # Trier par score de pertinence
                if not filtered_data.empty:
                    filtered_data = filtered_data.sort_values(
                        by="score", ascending=False
                    )

                return filtered_data
            else:
                return pd.DataFrame(columns=data.columns)
    except Exception as e:
        st.error(f"❌ Erreur lors de la recherche: {e}")
        st.error(traceback.format_exc())
        return pd.DataFrame(columns=data.columns)

# --- Fonction pour mettre à jour les données ---
def update_database(weeks_limit=10):
    """Met à jour la base de données avec les nouvelles instructions."""
    db_path = "data/sdssa_instructions.db"
    if not os.path.exists(db_path):
        st.error(
            "❌ Base de données non trouvée! Veuillez d'abord télécharger la base de données."
        )
        return False

    with get_db_connection() as conn:
        cursor = conn.cursor()
        new_notes_added = False

        try:
            # Récupérer la date de la dernière mise à jour
            cursor.execute("SELECT MAX(last_updated) FROM instructions")
            last_update_str = cursor.fetchone()[0]

            # Définir une date de départ par défaut (3 mois en arrière)
            default_start_date = datetime.now() - timedelta(days=90)

            if last_update_str:
                try:
                    last_update = datetime.strptime(
                        last_update_str, "%Y-%m-%d %H:%M:%S.%f"
                    )
                    # Si la dernière mise à jour date de plus de 3 mois, utiliser 3 mois en arrière
                    if (datetime.now() - last_update).days > 90:
                        last_update = default_start_date
                except ValueError:
                    last_update = default_start_date
            else:
                # Aucune mise à jour antérieure trouvée, utiliser la date par défaut
                last_update = default_start_date

            # Récupérer l'année et la semaine actuelles
            current_date = datetime.now()
            current_year, current_week, _ = current_date.isocalendar()

            # Récupérer l'année et la semaine de la dernière mise à jour
            start_year, start_week, _ = last_update.isocalendar()

            # Calculer la différence en semaines
            total_weeks_diff= (current_year - start_year) * 52 + (
                current_week - start_week
            )
            weeks_to_check = min(total_weeks_diff, weeks_limit)  # Limiter le nombre de semaines

            if weeks_to_check <= 0:
                st.info("✅ La base de données est déjà à jour.")
                return False

            # Parcourir les semaines à partir de la plus ancienne
            for week_offset in range(weeks_to_check):
                check_date = last_update + timedelta(weeks=week_offset)
                year, week, _ = check_date.isocalendar()
                st.info(f"Vérification de l'année {year}, semaine {week}...")
                new_instructions = get_new_instructions(year, week)

                if new_instructions:
                    for instruction in new_instructions:
                        title, link, pdf_link, objet, resume = instruction
                        # Vérifier si l'instruction existe déjà
                        cursor.execute(
                            "SELECT id FROM instructions WHERE title = ?", (title,)
                        )
                        existing_instruction = cursor.fetchone()
                        if not existing_instruction:
                            # Ajouter à la base de données
                            if add_instruction_to_db(
                                year, week, title, link, pdf_link, objet, resume
                            ):
                                new_notes_added = True
                                st.success(f"✅ Ajouté: {title}")
                        else:
                            #Mettre à jour l'instruction existante
                            if add_instruction_to_db(
                                year, week, title, link, pdf_link, objet, resume
                            ):
                                st.info(f"✅ Mis à jour: {title}")
                    conn.commit()
                else:
                    st.info(f"Aucune nouvelle instruction pour l'année {year}, semaine {week}.")

            if new_notes_added:
                st.success("✅ Mise à jour de la base de données terminée.")
                return True
            else:
                st.info("✅ Aucune nouvelle instruction trouvée.")
                return False

        except sqlite3.Error as e:
            st.error(f"❌ Erreur lors de la mise à jour de la base de données: {e}")
            st.error(traceback.format_exc())
            return False
        except Exception as e:
            st.error(f"❌ Erreur inattendue: {e}")
            st.error(traceback.format_exc())
            return False

# --- Interface utilisateur Streamlit ---
def main():
    """Fonction principale pour l'application Streamlit."""
    st.markdown("<h1 class='main-header'>SDSSA Instructions</h1>", unsafe_allow_html=True)

    # --- Sidebar ---
    st.sidebar.markdown(
        "<h2 class='sub-header'>Options</h2>", unsafe_allow_html=True
    )

    # Option pour forcer la mise à jour
    force_update = st.sidebar.checkbox("Forcer la mise à jour", value=False)

    # Sélecteur de fréquence de mise à jour
    update_frequency = st.sidebar.selectbox(
        "Fréquence de mise à jour",
        ["Hebdomadaire", "Mensuelle", "Trimestrielle"],
        index=["Hebdomadaire", "Mensuelle", "Trimestrielle"].index(
            st.session_state.update_frequency
        ),
    )
    st.session_state.update_frequency = update_frequency

    # Filtres par année et semaine
    available_years = (
        load_data()["year"].unique().tolist()
    )  # Charger les années disponibles depuis les données
    available_years.sort(reverse=True)  # Trier les années
    selected_year = st.sidebar.selectbox("Filtrer par année", [None] + available_years, index=0)
    available_weeks = (
        load_data()[load_data()["year"] == selected_year]["week"].unique().tolist()
        if selected_year
        else []
    )
    available_weeks.sort()
    selected_week = st.sidebar.selectbox("Filtrer par semaine", [None] + available_weeks, index=0)

    # --- Mise à jour de la base de données ---
    if st.sidebar.button("Mettre à jour la base de données"):
        if update_frequency == "Hebdomadaire":
            updated = update_database(weeks_limit=10)  # Vérifier les 10 dernières semaines
        elif update_frequency == "Mensuelle":
            updated = update_database(
                weeks_limit=52
            )  # Approximation : 52 semaines pour 12 mois
        else:  # Trimestrielle
            updated = update_database(
                weeks_limit=156
            )  # Approximation : 156 semaines pour 3 ans
        if updated:
            st.session_state.is_db_updated = True  # Mettre à jour l'état
        else:
            st.session_state.is_db_updated = False
        #Recharger les données après la mise à jour
        df = load_data()
        ix = create_whoosh_index(df)
    # Téléchargement forcé si demandé
    if force_update:
        if download_db_from_github(force=True):
            st.session_state.is_db_updated = True
            df = load_data()
            ix = create_whoosh_index(df)
        else:
            st.session_state.is_db_updated = False

    # --- Chargement et affichage des données ---
    ensure_database_structure()
    df = load_data()

    # Créer l'index Whoosh au démarrage de l'application ou après une mise à jour
    if "whoosh_index" not in st.session_state or st.session_state.is_db_updated:
        ix = create_whoosh_index(df)
        st.session_state.whoosh_index = ix  # Stocker l'index dans la session
        st.session_state.is_db_updated = (
            False  # Réinitialiser le flag après la mise à jour
        )
    else:
        ix = st.session_state.whoosh_index

    # --- Recherche ---
    st.markdown("<h2 class='sub-header'>Recherche</h2>", unsafe_allow_html=True)
    query = st.text_input("Rechercher des instructions (titre, objet, résumé)...")
    if st.button("Rechercher"):
        if not ix:
            st.error("❌ L'index de recherche n'est pas disponible.")
            st.stop()
        st.session_state.search_results = search_instructions(query, ix, df)
    # Afficher les résultats de la recherche
    if query and st.session_state.search_results is not None:
        results_df = st.session_state.search_results
        if results_df.empty:
            st.info("Aucun résultat trouvé pour votre recherche.")
        else:
            st.write(f"Résultats de la recherche : {len(results_df)}")
            st.dataframe(
                results_df[
                    [
                        "year",
                        "week",
                        "title",
                        "objet",
                        "resume",
                        "link",
                        "pdf_link",
                        "last_updated",
                    ]
                ].style.set_properties(**{"text-align": "left"}),
                column_config={
                    "link": st.column_config.LinkColumn("Lien", display_text="Voir"),
                    "pdf_link": st.column_config.LinkColumn(
                        "PDF", display_text="Télécharger"
                    ),
                    "last_updated": st.column_config.DatetimeColumn(
                        "Mis à jour", format="DD/MM/YYYY HH:mm:ss"
                    ),
                },
                hide_index=True,
            )

    # --- Affichage des données ---
    st.markdown("<h2 class='sub-header'>Liste des instructions</h2>", unsafe_allow_html=True)
    # Filtrer les données par année et semaine si des filtres sont sélectionnés
    filtered_df = df.copy()
    if selected_year:
        filtered_df = filtered_df[filtered_df["year"] == selected_year]
    if selected_week:
        filtered_df = filtered_df[filtered_df["week"] == selected_week]

    if not filtered_df.empty:
        st.dataframe(
            filtered_df[
                [
                    "year",
                    "week",
                    "title",
                    "objet",
                    "resume",
                    "link",
                    "pdf_link",
                    "last_updated",
                ]
            ].sort_values(by=["year", "week"], ascending=False).style.set_properties(
                **{"text-align": "left"}
            ),
            column_config={
                "link": st.column_config.LinkColumn("Lien", display_text="Voir"),
                "pdf_link": st.column_config.LinkColumn(
                    "PDF", display_text="Télécharger"
                ),
                "last_updated": st.column_config.DatetimeColumn(
                    "Mis à jour", format="DD/MM/YYYY HH:mm:ss"
                ),
            },
            hide_index=True,
        )
    else:
        st.info("Aucune instruction à afficher avec les filtres sélectionnés.")

    # --- Détails de l'instruction sélectionnée ---
    st.markdown("<h2 class='sub-header'>Détails de l'instruction</h2>", unsafe_allow_html=True)
    selected_title = st.selectbox(
        "Sélectionner une instruction pour voir les détails", [""] + df["title"].tolist()
    )
    if selected_title:
        instruction_details = get_instruction_details(selected_title)
        if instruction_details:
            st.write(
                f"""
                <div class="card">
                    <p><strong>Année:</strong> {instruction_details['year']}</p>
                    <p><strong>Semaine:</strong> {instruction_details['week']}</p>
                    <p><strong>Titre:</strong> {instruction_details['title']}</p>
                    <p><strong>Objet:</strong> {instruction_details['objet']}</p>
                    <p><strong>Résumé:</strong> {instruction_details['resume']}</p>
                    <p><strong>Lien:</strong> <a href="{instruction_details['link']}" target="_blank">Voir l'instruction</a></p>
                    <p><strong>Lien PDF:</strong> <a href="{instruction_details['pdf_link']}" target="_blank">Télécharger le PDF</a></p>
                    <p><strong>Dernière mise à jour:</strong> {instruction_details['last_updated']}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.error("Instruction non trouvée.")

    # --- Footer ---
    st.markdown(
        """
<div class="footer">
    <p>© 2024 SDSSA Instructions. Tous droits réservés.</p>
    <p>Application développée par [Votre Nom/Entreprise].</p>
</div>
""",
        unsafe_allow_html=True,
    )

if __name__ == "__main__":
    main()
