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
def ensure_database_structure(): # ... (no changes)
    db_path = 'data/sdssa_instructions.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("""CREATE TABLE IF NOT EXISTS instructions (id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER, week INTEGER, title TEXT UNIQUE, link TEXT, pdf_link TEXT, objet TEXT, resume TEXT, last_updated TIMESTAMP)""")
        conn.commit()
        cursor.execute("PRAGMA table_info(instructions)"); columns = [column[1] for column in cursor.fetchall()]
        if 'last_updated' not in columns: cursor.execute("ALTER TABLE instructions ADD COLUMN last_updated TIMESTAMP"); conn.commit()
        return True
    except sqlite3.Error as e: st.error(f"Erreur base de données: {e}"); return False
    finally: cursor.close(); conn.close()

def check_database(): # ... (no changes)
    db_path = 'data/sdssa_instructions.db'
    if not os.path.exists(db_path): st.error(f"Base de données {db_path} introuvable."); st.stop()
    return db_path

def load_data(db_path): # ... (no changes)
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM instructions", conn)
    conn.close()
    return df

def add_instruction_to_db(year, week, title, link, pdf_link, objet, resume): # ... (no changes)
    conn = sqlite3.connect('data/sdssa_instructions.db')
    cursor = conn.cursor()
    try: cursor.execute("""INSERT OR REPLACE INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (year, week, title, link, pdf_link, objet, resume, datetime.now())); conn.commit(); return True
    except sqlite3.Error as e: st.error(f"Erreur DB insertion/mise à jour: {e}"); conn.rollback(); return False
    finally: cursor.close(); conn.close()

def get_new_instructions(year, week): # ... (no changes)
    url = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year}/semaine-{week}"
    try: response = requests.get(url, timeout=10); response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
    except requests.exceptions.RequestException as e: st.error(f"Erreur de requête HTTP pour {url}: {e}"); return []

    soup = BeautifulSoup(response.content, 'html.parser')
    instructions = soup.find_all('a', href=True)
    sdssa_instructions = [a for a in instructions if 'SDSSA' in a.text]
    new_instructions = []
    for instruction in sdssa_instructions:
        href = instruction['href']
        if not href.startswith(('http://', 'https://')): href = f"https://info.agriculture.gouv.fr{href}"
        link = href; pdf_link = link.replace("/detail", "/telechargement")
        try: detail_response = requests.get(link, timeout=10); detail_response.raise_for_status()
        except requests.exceptions.RequestException as e: st.warning(f"Erreur détails {link}: {e}"); new_instructions.append((instruction.text, link, pdf_link, "OBJET : Inconnu", "RESUME : Inconnu")); continue # Skip to next instruction on detail fetch fail

        detail_soup = BeautifulSoup(detail_response.content, 'html.parser')
        objet_tag = detail_soup.find('b', text="OBJET : "); objet = objet_tag.next_sibling.strip() if objet_tag and objet_tag.next_sibling else "OBJET : Inconnu"
        resume_tag = detail_soup.find('b', text="RESUME : "); resume = resume_tag.next_sibling.strip() if resume_tag and resume_tag.next_sibling else "RESUME : Inconnu"
        new_instructions.append((instruction.text, link, pdf_link, objet, resume))
    return new_instructions


def create_whoosh_index(df): # ... (no changes)
    analyzer = StemmingAnalyzer() | LowercaseFilter() | StopFilter()
    schema = Schema(title=TEXT(stored=True, analyzer=analyzer), objet=TEXT(stored=True, analyzer=analyzer), resume=TEXT(stored=True, analyzer=analyzer), content=TEXT(analyzer=analyzer))
    index_dir = "indexdir"
    if not os.path.exists(index_dir): os.mkdir(index_dir)
    try:
        ix = open_dir(index_dir) if exists_in(index_dir) else create_in(index_dir, schema); st.info("Index Whoosh: " + ("ouverture existant..." if exists_in(index_dir) else "création..."))
        writer = ix.writer(); 
        for _, row in df.iterrows(): writer.add_document(title=row['title'], objet=row['objet'], resume=row['resume'], content=f"{row['title']} {row['objet']} {row['resume']}")
        writer.commit(); st.success("Index Whoosh mis à jour.")
        return ix
    except LockError as e: st.error(f"Erreur verrouillage index Whoosh: {e}"); st.error("Réessayez plus tard."); st.stop(); return None
    except Exception as e: st.error(f"Erreur index Whoosh: {e}"); st.error(traceback.format_exc()); st.stop(); return None

def get_synonyms(word): # ... (no changes)
    synonyms = set(); for syn in wordnet.synsets(word): for lemma in syn.lemmas(): synonyms.add(lemma.name().lower())
    return synonyms

def normalize_text(text): # ... (no changes)
    lemmatizer = WordNetLemmatizer(); words = word_tokenize(text.lower()); normalized_words = [lemmatizer.lemmatize(word) for word in words]
    return ' '.join(normalized_words)

# --- Initialisation et Chargement des Données --- # ... (no changes)
ensure_database_structure(); db_path = check_database(); data = load_data(db_path)
required_columns = ['year', 'week', 'title', 'link', 'pdf_link', 'objet', 'resume']
missing_columns = [col for col in required_columns if col not in data.columns]
if missing_columns: st.error(f"Colonnes manquantes: {', '.join(missing_columns)}"); st.stop()
ix = create_whoosh_index(data)
if ix is None: st.error("Échec initialisation index Whoosh."); st.stop()

# --- Interface Utilisateur Streamlit --- # ... (no changes - UI elements)
st.title("Instructions Techniques DGAL / SDSSA")
with st.expander("Instructions"): st.markdown("""<div style="background-color: #f9f9f9; padding: 10px; border-radius: 5px;"><p>Bienvenue ! Filtrez par année/semaine ou mots-clés.</p><p>Téléchargez les données via le bouton latéral.</p><p><strong>Note :</strong> Recherche avancée prioritaire.</p></div>""", unsafe_allow_html=True)
st.sidebar.subheader("Recherche avancée"); advanced_search = st.sidebar.text_input("Recherche avancée"); st.sidebar.markdown("Utilisez la recherche avancée pour inclure des synonymes et obtenir des résultats plus précis.")
with st.sidebar.expander("Filtrer par année et semaine"): years = data['year'].unique(); weeks = data['week'].unique(); all_weeks_option = "Toutes les semaines"; weeks = sorted(set(weeks)); weeks.insert(0, all_weeks_option); year = st.selectbox("Année", years); week = st.selectbox("Semaine", weeks)
st.sidebar.markdown("""<div style="text-align: center; margin-top: 20px; width: 100%;"><a href="https://www.visipilot.com" target="_blank"><img src="https://github.com/M00N69/sdssa-instructions-app/blob/main/app/assets/logo.png?raw=true" alt="Visipilot Logo" style="width: 100%;"></a></div>""", unsafe_allow_html=True)

# --- Filtrage des données et Affichage des Résultats --- # ... (no changes - data filtering and display)
filtered_data = data.copy()
if advanced_search: normalized_search = normalize_text(advanced_search); synonyms = set(); [synonyms.update(get_synonyms(word)) for word in word_tokenize(normalized_search)]; synonyms.add(normalized_search); query_string = " OR ".join([f"content:{syn}" for syn in synonyms]); with ix.searcher() as searcher: query = QueryParser("content", ix.schema).parse(query_string); results = searcher.search(query); filtered_data = pd.DataFrame([{ 'year': data.loc[data['title'] == hit['title'], 'year'].values[0], 'week': data.loc[data['title'] == hit['title'], 'week'].values[0], 'title': hit['title'], 'link': data.loc[data['title'] == hit['title'], 'link'].values[0], 'pdf_link': data.loc[data['title'] == hit['title'], 'pdf_link'].values[0], 'objet': hit['objet'], 'resume': hit['resume'] } for hit in results])
else: filtered_data = filtered_data[(filtered_data['year'] == year) & (filtered_data['week'] == week)] if week != all_weeks_option else filtered_data[filtered_data['year'] == year]
if filtered_data.empty: st.write("Aucun résultat.")
else: st.write("Résultats :"); st.dataframe(filtered_data[['objet', 'resume']]); st.header("Détails Instruction"); selected_title = st.selectbox("Sélectionner une instruction", filtered_data['title']); instruction_details = filtered_data[filtered_data['title'] == selected_title].iloc[0] if selected_title else None; if instruction_details is not None: st.markdown(f"### Détails: {selected_title}"); st.markdown(f"**Année:** {instruction_details['year']}"); st.markdown(f"**Semaine:** {instruction_details['week']}"); st.markdown(f"**Objet:** {instruction_details['objet']}"); st.markdown(f"**Résumé:** {instruction_details['resume']}"); st.markdown(f"**Lien:** [{instruction_details['title']}]({instruction_details['link']})"); st.markdown(f"**PDF:** [{instruction_details['title']}]({instruction_details['pdf_link']})")

# --- Téléchargement et Mise à Jour --- # ... (corrected update logic and download button)
st.sidebar.header("Télécharger les données")
if st.sidebar.download_button("Télécharger le CSV", data=filtered_data.to_csv(index=False).encode('utf-8') if not filtered_data.empty else "", file_name="sdssa_instructions.csv", mime="text/csv", disabled=filtered_data.empty):
    if filtered_data.empty: st.sidebar.warning("Aucune donnée à télécharger.")

if st.sidebar.button("Mettre à jour les données"):
    with st.spinner("Mise à jour des instructions..."):
        db_path = check_database()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        new_notes_added = False

        try:
            cursor.execute("SELECT MAX(year), CAST(MAX(week) AS INTEGER) FROM instructions")
            latest_year_db, latest_week_db = cursor.fetchone()
            latest_year_db = latest_year_db if latest_year_db else 2019
            latest_week_db = latest_week_db if latest_week_db else 0

            current_year, current_week, _ = datetime.now().isocalendar()

            st.write(f"**DEBUG - DB Latest Year:** {latest_year_db}, **DB Latest Week:** {latest_week_db}")
            st.write(f"**DEBUG - Current Year:** {current_year}, **Current Week:** {current_week}")

            weeks_to_check = []
            processed_weeks = set()
            start_year = latest_year_db
            start_week = latest_week_db + 1

            if latest_year_db is None:
                st.write("**DEBUG - Condition: Empty Database - Starting from 2019**")
                start_year = 2019
                start_week = 1
            else:
                st.write(f"**DEBUG - Starting check from Year:** {start_year}, **Week:** {start_week}")

            for year_to_check in range(start_year, current_year + 1):
                for week_num in range(1, 53): # Check ALL weeks 1-52 for EVERY year in range
                    if year_to_check == start_year and week_num < start_week: # Skip weeks before start_week in start_year
                        continue
                    if year_to_check == current_year and week_num > current_week: # Stop checking after current_week in current_year
                        break 

                    if (year_to_check, week_num) not in processed_weeks:
                        weeks_to_check.append((year_to_check, week_num))
                        processed_weeks.add((year_to_check, week_num))
                        st.write(f"**DEBUG - Adding week to check:** {(year_to_check, week_num)}")


            st.write(f"**Semaines à vérifier (FINAL):** {weeks_to_check}") # DEBUG

            new_instructions_total = 0
            for year_to_check, week_num in weeks_to_check:
                url_to_check = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year_to_check}/semaine-{week_num}"
                st.write(f"Vérification de l'URL: {url_to_check}")

                instructions = get_new_instructions(year_to_check, week_num)
                st.write(f"Instructions récupérées pour année {year_to_check}, semaine {week_num}: {len(instructions)}")
                new_instructions_total += len(instructions)


                for title, link, pdf_link, objet, resume in instructions:
                    if add_instruction_to_db(year_to_check, week_num, title, link, pdf_link, objet, resume):
                        new_notes_added = True

            if new_notes_added:
                st.success(f"{new_instructions_total} nouvelles instructions ajoutées !")
            else:
                st.info("Aucune nouvelle instruction trouvée.")

            data = load_data(db_path)
            ix = create_whoosh_index(data)

            if new_notes_added:
                github_push_logic() # Call GitHub push function
            elif ix:
                st.info("Base de données locale mise à jour, mais aucune nouvelle instruction trouvée. Pas de publication GitHub.")


        except Exception as e:
            st.error(f"Erreur lors de la mise à jour: {e}")
            st.error(traceback.format_exc())
        finally:
            conn.close()

def github_push_logic(): # Encapsulated GitHub push logic for clarity - No changes here
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

# --- Mises à jour récentes et Options avancées (sidebar) --- # ... (no changes)
st.sidebar.header("Mises à jour récentes")
if st.sidebar.button("Afficher les mises à jour récentes"):
    if 'last_updated' not in data.columns: st.error("Colonne 'last_updated' manquante.")
    else: recent_updates = data.sort_values(by='last_updated', ascending=False).head(10); st.write("Dernières mises à jour :"); st.dataframe(recent_updates[['title', 'link', 'pdf_link', 'objet', 'resume', 'last_updated']])
with st.sidebar.expander("Options avancées"): auto_update_freq = st.sidebar.selectbox("Fréquence MAJ auto", ["Désactivée", "Quotidienne", "Hebdomadaire", "Mensuelle"]); 
if auto_update_freq != "Désactivée": st.info(f"MAJ auto: {auto_update_freq}")
