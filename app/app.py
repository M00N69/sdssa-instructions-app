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
    query = "SELECT * FROM instructions"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def add_instruction_to_db(year, week, title, link, pdf_link, objet, resume):
    """Ajoute ou met à jour une instruction dans la base de données."""
    conn = sqlite3.connect('data/sdssa_instructions.db')
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
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
        <a href="https://www.visipilot.com" target_blank">
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
        new_notes_added = False  # Flag pour suivre si de nouvelles notes ont été ajoutées

        try:
            # Récupérer la date de la dernière mise à jour
            cursor.execute("SELECT MAX(last_updated) FROM instructions")
            last_update_str = cursor.fetchone()[0]

            # Définir une date de départ par défaut (3 mois en arrière)
            default_start_date = datetime.now() - timedelta(days=90)

            if last_update_str:
                try:
                    last_update = datetime.strptime(last_update_str, '%Y-%m-%d %H:%M:%S.%f')
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

            st.write(f"**Dernière mise à jour:** {last_update.strftime('%Y-%m-%d')}")
            st.write(f"**Année/semaine de départ:** {start_year}/{start_week}")
            st.write(f"**Année/semaine actuelle:** {current_year}/{current_week}")

            # Générer les semaines à vérifier depuis la dernière mise à jour
            weeks_to_check = []

            # Si même année
            if start_year == current_year:
                for week in range(start_week, current_week + 1):
                    weeks_to_check.append((start_year, week))
            else:
                # Ajouter les semaines restantes de l'année de départ
                for week in range(start_week, 53):  # ISO peut avoir 53 semaines
                    weeks_to_check.append((start_year, week))

                # Ajouter les années intermédiaires complètes
                for year in range(start_year + 1, current_year):
                    for week in range(1, 53):
                        weeks_to_check.append((year, week))

                # Ajouter les semaines de l'année en cours
                for week in range(1, current_week + 1):
                    weeks_to_check.append((current_year, week))

            # Récupérer les combinaisons année/semaine déjà en base
            cursor.execute("SELECT DISTINCT year, week FROM instructions")
            existing_weeks = set((int(row[0]), int(row[1])) for row in cursor.fetchall()]

            # Filtrer pour ne garder que les semaines manquantes
            weeks_to_check = [(year, week) for year, week in weeks_to_check if (year, week) not in existing_weeks]

            st.write(f"**Nombre de semaines manquantes à vérifier:** {len(weeks_to_check)}")

            if len(weeks_to_check) > 10:
                st.warning(f"Attention: {len(weeks_to_check)} semaines à vérifier. Cela peut prendre du temps.")

                # Option pour limiter le nombre de semaines à vérifier
                limit_weeks = st.checkbox("Limiter à 10 semaines les plus récentes", value=True)
                if limit_weeks:
                    weeks_to_check = sorted(weeks_to_check, key=lambda x: (x[0], x[1]), reverse=True)[:10]
                    st.info(f"Vérification limitée aux 10 semaines les plus récentes")

            new_instructions_total = 0
            for year_to_check, week_num in sorted(weeks_to_check):
                with st.status(f"Vérification année {year_to_check}, semaine {week_num}..."):
                    instructions = get_new_instructions(year_to_check, week_num)
                    if instructions:
                        st.write(f"Instructions récupérées: {len(instructions)}")
                        new_instructions_total += len(instructions)

                        for title, link, pdf_link, objet, resume in instructions:
                            if add_instruction_to_db(year_to_check, week_num, title, link, pdf_link, objet, resume):
                                new_notes_added = True
                    time.sleep(0.5)  # Pause pour éviter de surcharger le serveur

            if new_notes_added:
                st.success(f"{new_instructions_total} nouvelles instructions ajoutées !")

                # Recharger les données et mettre à jour l'index
                data = load_data(db_path)
                ix = create_whoosh_index(data)

                # Exécuter la logique GitHub seulement s'il y a de nouvelles instructions
                github_push_logic()
            else:
                st.info("Aucune nouvelle instruction trouvée.")

        except Exception as e:
            st.error(f"Erreur lors de la mise à jour: {e}")
            st.error(traceback.format_exc())
        finally:
            conn.close()

# Mise à jour de la fonction github_push_logic
def github_push_logic():
    """Envoie les mises à jour vers le dépôt GitHub."""
    github_token = st.secrets["GITHUB_TOKEN"]

    try:
        with st.spinner("Publication sur GitHub..."):
            # Configuration Git
            subprocess.run(["git", "config", "--global", "user.name", "Streamlit App"], check=True)
            subprocess.run(["git", "config", "--global", "user.email", "streamlit.app@example.com"], check=True)

            # Ajouter les fichiers modifiés
            subprocess.run(["git", "add", "data/sdssa_instructions.db"], check=True)
            subprocess.run(["git", "add", "indexdir"], check=True)

            # Vérifier s'il y a des changements à committer
            status_result = subprocess.run(["git", "status", "--porcelain"], check=True, capture_output=True, text=True)

            if status_result.stdout.strip():
                # Créer le commit avec un message explicite
                commit_message = f"MAJ auto DB et index via Streamlit App - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                subprocess.run(["git", "commit", "-m", commit_message], check=True)

                # Configurer l'URL du dépôt distant avec le token
                remote_repo = f"https://{github_token}@github.com/M00N69/sdssa-instructions-app.git"
                subprocess.run(["git", "remote", "set-url", "origin", remote_repo], check=True)

                # Pousser les changements
                push_result = subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True, text=True)
                st.success("Publié sur GitHub avec succès!")
            else:
                st.info("Aucun changement à publier sur GitHub.")

    except subprocess.CalledProcessError as e:
        st.error(f"Erreur lors de la publication sur GitHub: {e}")
        if hasattr(e, 'stderr'):
            st.error(f"Détails: {e.stderr}")
    except Exception as e:
        st.error(f"Erreur inattendue lors de la publication GitHub: {e}")
        st.error(traceback.format_exc())

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
