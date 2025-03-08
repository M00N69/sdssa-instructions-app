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

# Configuration de la page Streamlit
st.set_page_config(layout="wide")

# --- Initialisation NLTK ---
# Assure que les ressources NLTK nécessaires sont téléchargées.
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')
nltk.download('wordnet')
nltk.download('omw-1.4')

# --- Configuration des répertoires ---
# Crée le répertoire 'data' pour la base de données s'il n'existe pas.
os.makedirs('data', exist_ok=True)

# --- Fonctions de gestion de la base de données SQLite ---

def ensure_database_structure():
    """
    Vérifie si la structure de la base de données SQLite est correcte et la crée si nécessaire.
    Crée la table 'instructions' avec les colonnes appropriées si elle n'existe pas.
    Ajoute la colonne 'last_updated' si elle est manquante.
    """
    db_path = 'data/sdssa_instructions.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # Vérification de l'existence de la table 'instructions'
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='instructions'")
        table_exists = cursor.fetchone()

        if not table_exists:
            # Création de la table 'instructions' si elle n'existe pas
            st.write("Création de la table 'instructions' dans la base de données...") # Indication de l'action
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
        else:
            st.info("La table 'instructions' existe déjà.") # Indication que la table existe

        # Vérification de l'existence de la colonne 'last_updated'
        cursor.execute("PRAGMA table_info(instructions)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'last_updated' not in columns:
            # Ajout de la colonne 'last_updated' si elle est manquante
            st.write("Ajout de la colonne 'last_updated' à la table 'instructions'...") # Indication de l'action
            cursor.execute("ALTER TABLE instructions ADD COLUMN last_updated TIMESTAMP")
            conn.commit()
            st.success("Colonne 'last_updated' ajoutée à la table instructions.")
        else:
            st.info("La colonne 'last_updated' existe déjà.") # Indication que la colonne existe

        return True
    except sqlite3.Error as e:
        st.error(f"Erreur lors de la création de la structure de la base de données: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def check_database():
    """
    Vérifie si le fichier de base de données SQLite existe.
    Arrête l'application Streamlit si la base de données est introuvable.
    """
    db_path = 'data/sdssa_instructions.db'
    if not os.path.exists(db_path):
        st.error(f"La base de données {db_path} n'existe pas. Veuillez vérifier le chemin et essayer à nouveau.")
        st.stop() # Arrête l'exécution de l'application
    return db_path

def load_data(db_path):
    """
    Charge les données depuis la base de données SQLite dans un DataFrame pandas.
    """
    conn = sqlite3.connect(db_path)
    query = "SELECT * FROM instructions"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def add_instruction_to_db(year, week, title, link, pdf_link, objet, resume):
    """
    Ajoute ou met à jour une instruction dans la base de données SQLite.
    Si une instruction avec le même titre existe déjà, elle est mise à jour; sinon, une nouvelle instruction est insérée.
    """
    conn = sqlite3.connect('data/sdssa_instructions.db')
    cursor = conn.cursor()
    try:
        # Vérifie si une instruction avec le même titre existe déjà
        cursor.execute("SELECT COUNT(*) FROM instructions WHERE title = ?", (title,))
        exists = cursor.fetchone()[0]

        if exists > 0:
            # Mise à jour de l'instruction existante
            st.write(f"Mise à jour de l'instruction existante: {title}") # Indication de l'action
            cursor.execute("""
                UPDATE instructions
                SET year=?, week=?, link=?, pdf_link=?, objet=?, resume=?, last_updated=?
                WHERE title=?
            """, (year, week, link, pdf_link, objet, resume, datetime.now(), title))
        else:
            # Insertion d'une nouvelle instruction
            st.write(f"Insertion d'une nouvelle instruction: {title}") # Indication de l'action
            cursor.execute("""
                INSERT INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (year, week, title, link, pdf_link, objet, resume, datetime.now()))

        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"Erreur d'insertion/mise à jour dans la base de données: {e}")
        conn.rollback() # Annule la transaction en cas d'erreur
        return False
    finally:
        cursor.close()
        conn.close()

# --- Fonctions de Web Scraping ---

def get_new_instructions(year, week):
    """
    Récupère les nouvelles instructions SDSSA pour une année et une semaine données depuis le site web du ministère de l'Agriculture.
    Extrait le titre, le lien, le lien PDF, l'objet et le résumé de chaque instruction.
    """
    url = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year}/semaine-{week}"
    try:
        response = requests.get(url, timeout=10)  # Ajout d'un timeout pour éviter les blocages
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            instructions = soup.find_all('a', href=True) # Recherche tous les liens
            sdssa_instructions = [a for a in instructions if 'SDSSA' in a.text] # Filtre pour les instructions SDSSA
            new_instructions = []
            for instruction in sdssa_instructions:
                href = instruction['href']
                if not href.startswith(('http://', 'https://')):
                    href = f"https://info.agriculture.gouv.fr{href}" # Construction d'URL absolue
                link = href
                pdf_link = link.replace("/detail", "/telechargement") # Construction du lien PDF

                # Récupération de l'objet et du résumé depuis la page de détail de l'instruction
                try:
                    detail_response = requests.get(link, timeout=10)
                    if detail_response.status_code == 200:
                        soup = BeautifulSoup(detail_response.content, 'html.parser')
                        objet = "OBJET : Inconnu" # Valeur par défaut si l'objet n'est pas trouvé
                        resume = "RESUME : Inconnu" # Valeur par défaut si le résumé n'est pas trouvé

                        # Extraction de l'objet
                        objet_tag = soup.find('b', text="OBJET : ")
                        if objet_tag and objet_tag.next_sibling:
                            objet = objet_tag.next_sibling.strip()

                        # Extraction du résumé
                        resume_tag = soup.find('b', text="RESUME : ")
                        if resume_tag and resume_tag.next_sibling:
                            resume = resume_tag.next_sibling.strip()

                        new_instructions.append((instruction.text, link, pdf_link, objet, resume))
                except requests.RequestException as e:
                    st.warning(f"Erreur lors de la récupération des détails pour {link}: {e}")
                    # Ajout de l'instruction avec des informations partielles en cas d'erreur
                    new_instructions.append((instruction.text, link, pdf_link, "OBJET : Inconnu", "RESUME : Inconnu"))

            return new_instructions
        else:
            st.warning(f"Impossible de récupérer les données pour l'année {year} semaine {week} (Status code: {response.status_code})")
            return []
    except requests.RequestException as e:
        st.error(f"Erreur de connexion pour l'année {year} semaine {week}: {e}")
        return []

def check_for_new_notes():
    """
    Vérifie et ajoute les nouvelles instructions SDSSA à la base de données.
    Compare la dernière année/semaine enregistrée dans la base de données avec l'année/semaine actuelle.
    Récupère les instructions manquantes depuis le site web et les ajoute à la base de données.
    """
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

        # Trouver la dernière année et semaine enregistrées dans la base de données
        cursor.execute("SELECT MAX(year), MAX(week) FROM instructions;")
        latest_entry = cursor.fetchone()

        # Si la base de données est vide, commencer la vérification à partir de 2019, semaine 1
        if latest_entry == (None, None):
            latest_year, latest_week = 2019, 1
        else:
            latest_year, latest_week = latest_entry

        st.write(f"Dernière année enregistrée (base de données): {latest_year}, Dernière semaine enregistrée (base de données): {latest_week}")
        current_year, current_week, _ = datetime.now().isocalendar()
        st.write(f"Année actuelle : {current_year}, Semaine actuelle : {current_week}")

        # **REVISED DETAILED DEBUGGING OF "UP-TO-DATE" CONDITION**
        st.write("--- Début du débogage de la condition 'mise à jour nécessaire' (REVISÉ) ---")
        is_db_empty = latest_entry == (None, None)
        st.write(f"La base de données est vide ? : {is_db_empty}")
        is_latest_year_less_than_current_year = latest_year < current_year if latest_year is not None else False # Handle None case
        st.write(f"Dernière année < Année actuelle ? : {is_latest_year_less_than_current_year}")
        is_same_year_and_latest_week_less_than_current_week = False
        if latest_year == current_year:
            is_same_year_and_latest_week_less_than_current_week = latest_week < current_week if latest_week is not None else False # Handle None case
        st.write(f"Même année et Dernière semaine < Semaine actuelle ? (CONDITION ORIGINALE): {is_same_year_and_latest_week_less_than_current_week}")
        is_same_year_and_latest_week_GREATER_than_current_week = False # NEW condition check
        if latest_year == current_year:
            is_same_year_and_latest_week_GREATER_than_current_week = latest_week > current_week if latest_week is not None else False
        st.write(f"Même année et Dernière semaine > Semaine actuelle ? (NOUVELLE CONDITION): {is_same_year_and_latest_week_GREATER_than_current_week}")


        needs_update = is_db_empty or is_latest_year_less_than_current_year or is_same_year_and_latest_week_less_than_current_week or is_same_year_and_latest_week_GREATER_than_current_week # REVISED needs_update condition
        st.write(f"Besoin de mise à jour ? (calculé REVISÉ) : {needs_update}") # Debug print - Calculated needs_update
        st.write("--- Fin du débogage de la condition 'mise à jour nécessaire' (REVISÉ) ---")


        if not needs_update:
            st.info("La base de données est déjà à jour.")
            st.write("Condition pour 'besoin de mise à jour' est FAUSSE (REVISÉE). Base de données considérée à jour.") # Debug print
            return
        else:
            st.write("Condition pour 'besoin de mise à jour' est VRAIE (REVISÉE). Procéder à la vérification des semaines.") # Debug print


        # Identifier les semaines à vérifier
        weeks_to_check = []
        for year in range(latest_year, current_year + 1):
            start_week = latest_week + 1 if year == latest_year else 1
            end_week = current_week if year == current_year else 52
            if year == current_year:
                end_week = current_week
            else:
                end_week = 52

            st.write(f"Pour l'année {year}: start_week={start_week}, end_week={end_week}") # Debug print
            for week in range(start_week, end_week + 1):
                if year == latest_year and week <= latest_week: # Skip already processed weeks
                    st.write(f"Saut de la semaine {week} de l'année {year} (déjà traitée).") # Debug print - Skipping week
                    continue # Skip weeks already in DB
                weeks_to_check.append((year, week))

        st.write(f"Semaines à vérifier : {weeks_to_check}") # Affichage des semaines à vérifier
        progress_bar = st.progress(0) # Barre de progression pour le processus de mise à jour

        # Récupérer les nouvelles instructions pour chaque semaine à vérifier
        new_instructions = []
        for i, (year, week) in enumerate(weeks_to_check):
            instructions = get_new_instructions(year, week)
            st.write(f"Instructions récupérées pour l'année {year} semaine {week}: {len(instructions)}") # Affichage du nombre d'instructions récupérées par semaine
            for title, link, pdf_link, objet, resume in instructions:
                # Vérification si l'instruction existe déjà dans la base de données
                cursor.execute("SELECT COUNT(*) FROM instructions WHERE title = ?", (title,))
                exists = cursor.fetchone()[0]

                if exists == 0:
                    new_instructions.append((year, week, title, link, pdf_link, objet, resume))

            # Mise à jour de la barre de progression
            progress = (i + 1) / len(weeks_to_check)
            progress_bar.progress(progress)

        st.write(f"{len(new_instructions)} nouvelles instructions trouvées.") # Affichage du nombre total de nouvelles instructions trouvées

        # Ajout des nouvelles instructions à la base de données
        added_count = 0
        for instruction in new_instructions:
            year, week, title, link, pdf_link, objet, resume = instruction
            # Utilisation de la fonction add_instruction_to_db pour ajouter ou mettre à jour l'instruction
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
        st.error(traceback.format_exc()) # Affichage de la trace d'erreur complète pour le débogage
    finally:
        cursor.close()
        conn.close()

# --- Fonctions de Normalisation de Texte et Indexation Whoosh ---

def create_whoosh_index(df):
    """
    Crée ou ouvre un index Whoosh pour la recherche en texte intégral.
    Utilise un analyseur avec stemming, lowercase et suppression des mots vides.
    Indexe les colonnes 'title', 'objet' et 'resume' pour la recherche.
    Gère les erreurs de verrouillage de l'index.
    """
    analyzer = StemmingAnalyzer() | LowercaseFilter() | StopFilter() # Analyseur pour l'indexation
    schema = Schema(title=TEXT(stored=True, analyzer=analyzer), # Champ 'title' indexé et stocké
                    objet=TEXT(stored=True, analyzer=analyzer), # Champ 'objet' indexé et stocké
                    resume=TEXT(stored=True, analyzer=analyzer), # Champ 'resume' indexé et stocké
                    content=TEXT(analyzer=analyzer)) # Champ 'content' pour la recherche combinée, indexé mais non stocké
    index_dir = "indexdir" # Répertoire pour stocker l'index Whoosh
    if not os.path.exists(index_dir):
        os.mkdir(index_dir) # Crée le répertoire d'index s'il n'existe pas

    try:
        if not exists_in(index_dir): # Vérifie si l'index existe déjà
            ix = create_in(index_dir, schema) # Crée un nouvel index s'il n'existe pas
            st.info("Création de l'index Whoosh...") # Indique à l'utilisateur que l'index est en cours de création
        else:
            ix = open_dir(index_dir) # Ouvre l'index existant s'il existe
            st.info("Ouverture de l'index Whoosh existant...") # Indique à l'utilisateur que l'index existant est ouvert

        writer = ix.writer() # Obtient un objet writer pour ajouter des documents à l'index
        for index, row in df.iterrows():
            # Ajoute chaque instruction comme un document dans l'index
            writer.add_document(title=row['title'], objet=row['objet'], resume=row['resume'], content=f"{row['title']} {row['objet']} {row['resume']}")
        writer.commit() # Enregistre les changements dans l'index
        st.success("Index Whoosh mis à jour avec succès.") # Indique le succès de la mise à jour de l'index
        return ix # Retourne l'objet index

    except LockError as e:
        st.error(f"Erreur de verrouillage de l'index Whoosh: {e}") # Message d'erreur spécifique pour LockError
        st.error("Veuillez réessayer de mettre à jour les données plus tard. Si le problème persiste, redémarrez l'application.") # Conseils à l'utilisateur
        st.stop() # Arrête l'application en cas d'erreur de verrouillage
        return None # Retourne None pour indiquer que la création/mise à jour de l'index a échoué
    except Exception as e: # Capture d'autres exceptions potentielles lors de l'indexation
        st.error(f"Erreur inattendue lors de la création/mise à jour de l'index Whoosh: {e}")
        st.error(traceback.format_exc()) # Affiche la trace d'erreur complète pour le débogage
        st.stop()
        return None

def get_synonyms(word):
    """
    Récupère les synonymes d'un mot en utilisant WordNet.
    """
    synonyms = set()
    for syn in wordnet.synsets(word): # Recherche les synsets (ensembles de synonymes) pour le mot
        for lemma in syn.lemmas(): # Pour chaque lemma (forme de mot) dans le synset
            synonyms.add(lemma.name().lower()) # Ajoute le nom du lemma (synonyme) en minuscules à l'ensemble
    return synonyms

def normalize_text(text):
    """
    Normalise le texte en le mettant en minuscules et en lemmatisant les mots.
    """
    lemmatizer = WordNetLemmatizer() # Initialise le lemmatizer WordNet
    words = word_tokenize(text.lower()) # Tokenize le texte en mots et met en minuscules
    normalized_words = [lemmatizer.lemmatize(word) for word in words] # Lemmatise chaque mot
    return ' '.join(normalized_words) # Rejoint les mots normalisés en une chaîne de caractères

# --- Initialisation et Chargement des Données ---

# Assure que la structure de la base de données est en place
ensure_database_structure()
# Vérifie que la base de données existe et obtient son chemin
db_path = check_database()
# Charge les données de la base de données dans un DataFrame pandas
data = load_data(db_path)

# Vérification des colonnes requises dans le DataFrame chargé
required_columns = ['year', 'week', 'title', 'link', 'pdf_link', 'objet', 'resume']
missing_columns = [col for col in required_columns if col not in data.columns]
if missing_columns:
    st.error(f"Les colonnes suivantes sont manquantes dans la base de données : {', '.join(missing_columns)}")
    st.stop()

# Création ou ouverture de l'index Whoosh avec les données chargées
ix = create_whoosh_index(data)

# --- Interface Utilisateur Streamlit ---

# Titre principal de l'application
st.title("Instructions Techniques DGAL / SDSSA")

# Zone d'explication et d'instructions pour l'utilisateur (repliable)
with st.expander("Instructions et explications d'utilisation"):
    st.markdown("""
    <div style="background-color: #f9f9f9; padding: 10px; border-radius: 5px;">
        <p>Bienvenue sur l'application SDSSA Instructions. Utilisez les filtres pour rechercher des instructions techniques par année, semaine, ou mots-clés. Vous pouvez également effectuer une recherche avancée pour des résultats plus précis.</p>
        <p>Pour télécharger les données, utilisez le bouton de téléchargement dans la barre latérale.</p>
        <p><strong>Note :</strong> La recherche avancée est prioritaire. Si vous utilisez la recherche avancée, les filtres par année, semaine et mot-clé ne seront pas appliqués.</p>
    </div>
    """, unsafe_allow_html=True)

# --- Barre latérale pour les filtres et actions ---
st.sidebar.subheader("Recherche avancée")
advanced_search = st.sidebar.text_input("Recherche avancée") # Champ de texte pour la recherche avancée
st.sidebar.markdown("Utilisez la recherche avancée pour inclure des synonymes et obtenir des résultats plus précis.")

# Filtres par année et semaine dans un panneau repliable dans la barre latérale
with st.sidebar.expander("Filtrer par année et semaine"):
    years = data['year'].unique() # Années uniques disponibles dans les données
    weeks = data['week'].unique() # Semaines uniques disponibles dans les données
    all_weeks_option = "Toutes les semaines" # Option pour sélectionner toutes les semaines
    weeks = sorted(set(weeks)) # Trie les semaines et supprime les doublons
    weeks.insert(0, all_weeks_option)  # Ajoute l'option "Toutes les semaines" en tête de liste
    year = st.selectbox("Année", years) # Selectbox pour choisir l'année
    week = st.selectbox("Semaine", weeks) # Selectbox pour choisir la semaine

# Logo Visipilot affiché dans la barre latérale
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

# --- Filtrage des données et Affichage des Résultats ---

filtered_data = data.copy() # Initialise les données filtrées avec toutes les données

# Application du filtre de recherche avancée si une requête est entrée
if advanced_search:
    normalized_search = normalize_text(advanced_search) # Normalise le texte de recherche
    synonyms = set() # Ensemble pour stocker les synonymes
    for word in word_tokenize(normalized_search): # Tokenize le texte de recherche normalisé
        synonyms.update(get_synonyms(word)) # Ajoute les synonymes de chaque mot à l'ensemble
    synonyms.add(normalized_search) # Ajoute le texte de recherche normalisé lui-même aux synonymes

    # Construction de la requête Whoosh pour la recherche avec synonymes
    query_string = " OR ".join([f"content:{syn}" for syn in synonyms])
    with ix.searcher() as searcher: # Ouvre un searcher pour effectuer la recherche dans l'index
        query = QueryParser("content", ix.schema).parse(query_string) # Parse la requête
        results = searcher.search(query) # Effectue la recherche
        # Conversion des résultats de Whoosh en DataFrame pandas
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
    # Application des filtres par année et semaine si la recherche avancée n'est pas utilisée
    if week != all_weeks_option:
        filtered_data = filtered_data[(filtered_data['year'] == year) & (filtered_data['week'] == week)]
    else:
        filtered_data = filtered_data[filtered_data['year'] == year]

# Affichage du nombre de résultats filtrés
if filtered_data.empty:
    st.write("Aucun résultat trouvé avec les filtres actuels.")
else:
    st.write("Résultats filtrés :")
    st.dataframe(filtered_data[['objet', 'resume']]) # Affichage des colonnes 'objet' et 'resume'

    # Sélection d'une instruction pour afficher les détails complets
    st.header("Détails d'une instruction")
    selected_title = st.selectbox("Sélectionner une instruction", filtered_data['title']) # Selectbox pour choisir une instruction
    if selected_title:
        instruction_details = filtered_data[filtered_data['title'] == selected_title].iloc[0] # Récupère les détails de l'instruction sélectionnée
        st.markdown(f"### Détails de l'instruction : {selected_title}")
        st.markdown(f"**Année :** {instruction_details['year']}")
        st.markdown(f"**Semaine :** {instruction_details['week']}")
        st.markdown(f"**Objet :** {instruction_details['objet']}")
        st.markdown(f"**Résumé :** {instruction_details['resume']}")
        st.markdown(f"**Lien :** [{instruction_details['title']}]({instruction_details['link']})") # Lien vers la page de l'instruction
        st.markdown(f"**Télécharger le PDF :** [{instruction_details['title']}]({instruction_details['pdf_link']})") # Lien de téléchargement du PDF

# --- Fonctionnalités de Téléchargement et Mise à Jour ---

st.sidebar.header("Télécharger les données")
if st.sidebar.button("Télécharger le CSV"): # Bouton pour télécharger les données filtrées en CSV
    if filtered_data.empty:
        st.sidebar.warning("Aucune donnée à télécharger.") # Avertissement si aucune donnée n'est disponible pour le téléchargement
    else:
        csv = filtered_data.to_csv(index=False).encode('utf-8') # Convertit le DataFrame en CSV
        st.sidebar.download_button(
            label="Télécharger",
            data=csv,
            file_name="sdssa_instructions.csv",
            mime="text/csv"
        )

# Bouton pour déclencher la mise à jour des données
if st.sidebar.button("Mettre à jour les données"):
    with st.spinner("Vérification des nouvelles instructions..."): # Affichage d'un spinner pendant la mise à jour
        check_for_new_notes() # Lance la fonction de vérification et de mise à jour
        # Rechargement des données et de l'index après la mise à jour
        data = load_data(db_path)
        ix = create_whoosh_index(data)
        if ix:
            st.success("Mise à jour terminée et données rechargées.") # Message de succès après la mise à jour
        else:
            st.error("La mise à jour de l'index a échoué. Veuillez consulter les erreurs ci-dessus.") # Message d'erreur si la mise à jour de l'index échoue

# Panneau pour afficher les mises à jour récentes (dans la barre latérale)
st.sidebar.header("Mises à jour récentes")
if st.sidebar.button("Afficher les mises à jour récentes"): # Bouton pour afficher les mises à jour récentes
    if 'last_updated' not in data.columns:
        st.error("La colonne 'last_updated' est manquante dans la base de données.") # Message d'erreur si la colonne 'last_updated' est manquante
    else:
        recent_updates = data.sort_values(by='last_updated', ascending=False).head(10) # Trie et sélectionne les 10 dernières mises à jour
        st.write("Dernières mises à jour :")
        st.dataframe(recent_updates[['title', 'link', 'pdf_link', 'objet', 'resume', 'last_updated']]) # Affichage des dernières mises à jour dans un DataFrame

# Panneau d'options avancées pour la mise à jour automatique (repliable dans la barre latérale)
with st.sidebar.expander("Options avancées"):
    auto_update_freq = st.selectbox(
        "Fréquence de mise à jour automatique",
        ["Désactivée", "Quotidienne", "Hebdomadaire", "Mensuelle"] # Options de fréquence de mise à jour automatique
    )

    if auto_update_freq != "Désactivée":
        st.info(f"La mise à jour automatique est configurée sur: {auto_update_freq}") # Information sur la fréquence de mise à jour automatique sélectionnée
        # Note: La fonctionnalité de mise à jour automatique nécessiterait une planification supplémentaire (par exemple, avec APScheduler ou cron).
