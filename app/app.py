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
import base64
from PIL import Image
from io import BytesIO

# Configuration de la page Streamlit avec plus d'options
st.set_page_config(
    page_title="SDSSA Instructions - Visualisation et Recherche",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Styles CSS personnalisés ---
st.markdown("""
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
""", unsafe_allow_html=True)

# --- Initialisation de la session state ---
if 'db_last_checked' not in st.session_state:
    st.session_state.db_last_checked = None
if 'is_db_updated' not in st.session_state:
    st.session_state.is_db_updated = False
if 'search_results' not in st.session_state:
    st.session_state.search_results = None
if 'selected_instruction' not in st.session_state:
    st.session_state.selected_instruction = None
if 'filter_year' not in st.session_state:
    st.session_state.filter_year = None
if 'filter_week' not in st.session_state:
    st.session_state.filter_week = None
if 'update_frequency' not in st.session_state:
    st.session_state.update_frequency = "Hebdomadaire"

# --- Initialisation NLTK ---
@st.cache_resource
def initialize_nltk():
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt')
    
    try:
        nltk.data.find('corpora/wordnet')
    except LookupError:
        nltk.download('wordnet')
        nltk.download('omw-1.4')

initialize_nltk()

# --- Configuration des répertoires ---
os.makedirs('data', exist_ok=True)
os.makedirs('indexdir', exist_ok=True)
os.makedirs('backups', exist_ok=True)

# --- Fonction pour mettre à jour la base de données sur GitHub ---
def push_db_to_github():
    """Pousse la base de données locale vers le dépôt GitHub."""
    # Message de statut pour l'utilisateur
    with st.status("Mise à jour de la base de données sur GitHub...") as status:
        try:
            # Vérifier si le fichier local existe
            local_db_path = "data/sdssa_instructions.db"
            if not os.path.exists(local_db_path):
                st.error("❌ Impossible de trouver la base de données locale à mettre à jour.")
                status.update(label="❌ Échec de la mise à jour", state="error")
                return False

# --- Vérification programmée des mises à jour ---
def check_scheduled_updates():
    """Vérifie s'il est temps de faire une mise à jour programmée."""
    if 'last_auto_update' not in st.session_state:
        st.session_state.last_auto_update = datetime.now() - timedelta(days=2)
        
    current_time = datetime.now()
    time_diff = current_time - st.session_state.last_auto_update
    update_freq = st.session_state.update_frequency
    
    # Déterminer s'il faut faire une mise à jour basée sur la fréquence choisie
    update_needed = False
    
    if update_freq == "Quotidienne" and time_diff.days >= 1:
        update_needed = True
    elif update_freq == "Hebdomadaire" and time_diff.days >= 7:
        update_needed = True
    elif update_freq == "Mensuelle" and time_diff.days >= 30:
        update_needed = True
        
    # Si une mise à jour est nécessaire, essayer de mettre à jour la base de données
    if update_needed:
        st.info(f"🔄 Mise à jour {update_freq.lower()} automatique...")
        success = download_db_from_github()
        if success:
            st.session_state.last_auto_update = current_time
            st.success(f"✅ Mise à jour automatique effectuée ({update_freq.lower()})!")
        return success
    
    return False
    
# --- Formatage des données pour l'affichage ---
def format_data_for_display(df):
    """Formate les données pour un meilleur affichage."""
    if df.empty:
        return df
    
    # Copier pour éviter de modifier l'original
    display_df = df.copy()
    
    # Ajouter des colonnes formatées pour l'affichage
    display_df['affichage_date'] = display_df.apply(
        lambda row: f"{row['year']}-S{row['week']:02d}", axis=1
    )
    
    # Limiter la taille des champs de texte longs
    display_df['resume_court'] = display_df['resume'].apply(
        lambda x: x[:100] + '...' if len(x) > 100 else x
    )
    
    display_df['objet_court'] = display_df['objet'].apply(
        lambda x: x[:100] + '...' if len(x) > 100 else x
    )
    
    return display_df

# --- Interface utilisateur principale ---

# --- Titre de l'application ---
st.markdown("<h1 class='main-header'>📚 Instructions Techniques DGAL / SDSSA</h1>", unsafe_allow_html=True)

# --- Vérifier les mises à jour automatiques ---
if st.session_state.update_frequency != "Désactivée":
    check_scheduled_updates()

# --- Initialisation et Chargement des Données ---
ensure_database_structure()

# Vérifier si la base de données existe, sinon proposer de la télécharger
if not os.path.exists("data/sdssa_instructions.db"):
    st.markdown("<div class='warning-message'>⚠️ Aucune base de données trouvée. Veuillez télécharger la base de données pour commencer.</div>", unsafe_allow_html=True)
    
    if st.button("📥 Télécharger la base de données depuis GitHub"):
        download_db_from_github(force=True)
        st.rerun()
    st.stop()

# Charger les données
data = load_data()
if data.empty:
    st.error("❌ Aucune donnée trouvée dans la base de données.")
    st.stop()

# Créer ou ouvrir l'index Whoosh
ix = create_whoosh_index(data)

# --- Interface principale avec onglets ---
tab1, tab2, tab3, tab4 = st.tabs(["🔍 Recherche", "📊 Visualisation", "⚙️ Mise à jour", "ℹ️ Informations"])

with tab1:
    st.markdown("<h2 class='sub-header'>Recherche d'instructions</h2>", unsafe_allow_html=True)
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        search_query = st.text_input("🔍 Recherche avancée", placeholder="Entrez des mots-clés (ex: hygiène, restauration, contamination...)")
        st.markdown("</div>", unsafe_allow_html=True)

# --- Pied de page ---
st.markdown("<div class='footer'>", unsafe_allow_html=True)
st.markdown("""
<p>Application SDSSA Instructions - Développée avec Streamlit</p>
<p>Dernière mise à jour: Mars 2025</p>
""", unsafe_allow_html=True)

# Logo/Branding dans le footer
st.markdown("""
<div style="text-align: center; margin-top: 20px;">
    <a href="https://www.visipilot.com" target="_blank">
        <img src="https://github.com/M00N69/sdssa-instructions-app/blob/main/app/assets/logo.png?raw=true" alt="Visipilot Logo" style="width: 200px;">
    </a>
</div>
""", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# --- Point d'entrée principal ---
if __name__ == "__main__":
    # Vérifier si c'est la première exécution
    if 'first_run' not in st.session_state:
        st.session_state.first_run = True
        
        # Si la base de données existe mais n'a pas été vérifiée récemment
        if os.path.exists("data/sdssa_instructions.db") and (
            st.session_state.db_last_checked is None or
            (datetime.now() - st.session_state.db_last_checked).days > 1
        ):
            # Vérifier automatiquement les mises à jour au démarrage
            download_db_from_github()

with tab4:
    st.markdown("<h2 class='sub-header'>À propos de l'application</h2>", unsafe_allow_html=True)
    
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("""
    <h3>Instructions Techniques DGAL / SDSSA</h3>
    <p>Cette application permet de consulter, rechercher et gérer les instructions techniques 
    de la Direction Générale de l'Alimentation (DGAL) / Service de la Sécurité Sanitaire des Aliments (SDSSA).</p>
    
    <h4>Fonctionnalités:</h4>
    <ul>
        <li>Recherche avancée avec prise en compte des synonymes</li>
        <li>Filtrage par année et semaine</li>
        <li>Visualisation des données</li>
        <li>Téléchargement automatique depuis GitHub</li>
        <li>Mise à jour automatique configurables</li>
        <li>Système de sauvegarde et restauration</li>
        <li>Mise à jour de la base de données vers GitHub</li>
    </ul>
    
    <h4>Utilisation:</h4>
    <ol>
        <li>Utilisez l'onglet <strong>Recherche</strong> pour trouver des instructions spécifiques</li>
        <li>Consultez l'onglet <strong>Visualisation</strong> pour voir des statistiques sur les données</li>
        <li>Dans l'onglet <strong>Mise à jour</strong>, configurez la fréquence de mise à jour automatique</li>
        <li>Les détails des instructions affichent l'objet, le résumé et des liens vers les documents originaux</li>
        <li>Après des mises à jour locales, envoyez la base de données vers GitHub pour la partager</li>
    </ol>
    """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Informations techniques
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<h3>Informations techniques</h3>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("""
        <h4>Technologies utilisées:</h4>
        <ul>
            <li>Streamlit</li>
            <li>SQLite</li>
            <li>Whoosh (moteur de recherche)</li>
            <li>BeautifulSoup (web scraping)</li>
            <li>NLTK (traitement du langage naturel)</li>
            <li>GitHub API (synchronisation)</li>
        </ul>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown("""
        <h4>Structure des données:</h4>
        <ul>
            <li>Base de données SQLite</li>
            <li>Index de recherche Whoosh</li>
            <li>Sauvegardes automatiques</li>
            <li>Synchronisation avec GitHub</li>
        </ul>
        """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Source des données
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<h3>Source des données</h3>", unsafe_allow_html=True)
    st.markdown("""
    <p>Les données sont extraites du Bulletin Officiel du Ministère de l'Agriculture:</p>
    <a href="https://info.agriculture.gouv.fr/boagri/" target="_blank">https://info.agriculture.gouv.fr/boagri/</a>
    
    <p style="margin-top: 15px;">Dépôt GitHub contenant la base de données:</p>
    <a href="https://github.com/M00N69/sdssa-instructions-app" target="_blank">https://github.com/M00N69/sdssa-instructions-app</a>
    """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Exporter les données
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<h3>Exporter les données</h3>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.download_button(
            "📥 Télécharger toutes les données (CSV)",
            data=data.to_csv(index=False).encode('utf-8'),
            file_name="sdssa_instructions_complete.csv",
            mime="text/csv",
            use_container_width=True
        ):
            st.success("✅ Données téléchargées!")
    
    with col2:
        # Exporter uniquement les instructions récentes
        recent_date = datetime.now() - timedelta(days=90)
        recent_data = data[pd.to_datetime(data['last_updated']) > recent_date]
        
        if not recent_data.empty:
            if st.download_button(
                f"📥 Instructions récentes ({len(recent_data)})",
                data=recent_data.to_csv(index=False).encode('utf-8'),
                file_name="sdssa_instructions_recent.csv",
                mime="text/csv",
                use_container_width=True
            ):
                st.success("✅ Données récentes téléchargées!")
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Gestion des sauvegardes
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<h3>Gestion des sauvegardes</h3>", unsafe_allow_html=True)
    
    backups = sorted(glob.glob("backups/sdssa_instructions_*.db"), reverse=True)
    
    if backups:
        st.write(f"📁 {len(backups)} sauvegardes disponibles:")
        
        for backup in backups:
            backup_name = os.path.basename(backup)
            backup_date = backup_name.replace("sdssa_instructions_", "").replace(".db", "")
            
            try:
                formatted_date = datetime.strptime(backup_date, "%Y%m%d_%H%M%S").strftime("%d/%m/%Y à %H:%M:%S")
            except:
                formatted_date = backup_date
            
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.write(f"📂 Sauvegarde du {formatted_date}")
            
            with col2:
                if st.button(f"🔄 Restaurer", key=f"restore_{backup_name}"):
                    try:
                        # Sauvegarder la base actuelle avant restauration
                        if os.path.exists("data/sdssa_instructions.db"):
                            current_backup = f"backups/pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                            shutil.copy2("data/sdssa_instructions.db", current_backup)
                        
                        # Restaurer la sauvegarde
                        shutil.copy2(backup, "data/sdssa_instructions.db")
                        st.success(f"✅ Base de données restaurée depuis la sauvegarde du {formatted_date}")
                        
                        # Recharger les données
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erreur lors de la restauration: {e}")
    else:
        st.info("📌 Aucune sauvegarde disponible")
    
    st.markdown("</div>", unsafe_allow_html=True)

with tab3:
    st.markdown("<h2 class='sub-header'>Mise à jour des données</h2>", unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<h3>Mise à jour automatique</h3>", unsafe_allow_html=True)
        
        update_freq = st.selectbox(
            "Fréquence de mise à jour automatique",
            options=["Désactivée", "Quotidienne", "Hebdomadaire", "Mensuelle"],
            index=2  # Par défaut: Hebdomadaire
        )
        
        st.session_state.update_frequency = update_freq
        
        if update_freq != "Désactivée":
            st.info(f"🔄 Les mises à jour automatiques sont configurées: {update_freq}")
            
            if st.button("🔄 Vérifier maintenant"):
                download_db_from_github()
        else:
            st.warning("⚠️ Les mises à jour automatiques sont désactivées")
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    with col2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<h3>Mise à jour manuelle</h3>", unsafe_allow_html=True)
        
        st.write("Téléchargez manuellement la dernière version ou mettez à jour avec de nouvelles instructions.")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📥 Télécharger depuis GitHub", use_container_width=True):
                download_db_from_github(force=True)
        
        with col2:
            if st.button("🔎 Rechercher nouvelles instructions", use_container_width=True):
                update_database(weeks_limit=20)
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Nouvelle section pour la mise à jour vers GitHub
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.markdown("<h3>Mise à jour vers GitHub</h3>", unsafe_allow_html=True)
    
    st.write("Envoyer la base de données locale actualisée vers GitHub pour la rendre disponible à tous les utilisateurs.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Obtenir la date de la dernière modification locale
        if os.path.exists("data/sdssa_instructions.db"):
            last_modified = datetime.fromtimestamp(os.path.getmtime("data/sdssa_instructions.db"))
            st.info(f"📅 Version locale: {last_modified.strftime('%d/%m/%Y à %H:%M:%S')}")
        else:
            st.warning("⚠️ Aucune base de données locale trouvée")
    
    with col2:
        if st.button("📤 Envoyer vers GitHub", use_container_width=True, help="Mettre à jour la base de données sur GitHub"):
            # Vérifier si l'utilisateur a fait des mises à jour locales
            if 'is_db_updated' in st.session_state and st.session_state.is_db_updated:
                push_db_to_github()
                # Réinitialiser l'état de mise à jour
                st.session_state.is_db_updated = False
            else:
                if st.checkbox("💡 Aucune mise à jour locale détectée. Envoyer quand même?"):
                    push_db_to_github()
    
    st.markdown("""
    <div class="info-box">
        <p><strong>📌 Note:</strong> Cette fonction met à jour la base de données centrale sur GitHub.
        Cette mise à jour sera disponible pour tous les autres utilisateurs lors de leur prochaine synchronisation.</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("</div>", unsafe_allow_html=True)
            
    # Sélection d'une instruction pour voir les détails
    if 'search_results' in st.session_state and st.session_state.search_results is not None and not st.session_state.search_results.empty:
        results = st.session_state.search_results
        st.markdown("<h3 class='sub-header'>Détails de l'instruction</h3>", unsafe_allow_html=True)
        selected_title = st.selectbox("Sélectionner une instruction", options=results['title'].tolist())
        
        if selected_title:
            st.session_state.selected_instruction = selected_title
            instruction = results[results['title'] == selected_title].iloc[0]
            
            # Affichage détaillé de l'instruction
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                st.markdown(f"<h3>{instruction['title']}</h3>", unsafe_allow_html=True)
                st.markdown(f"<p><strong>Année:</strong> {instruction['year']} | <strong>Semaine:</strong> {instruction['week']}</p>", unsafe_allow_html=True)
                
            with col2:
                st.markdown(f"<p><a href='{instruction['link']}' target='_blank'>🔗 Voir sur le site</a></p>", unsafe_allow_html=True)
                st.markdown(f"<p><a href='{instruction['pdf_link']}' target='_blank'>📄 Télécharger le PDF</a></p>", unsafe_allow_html=True)
            
            st.markdown("<hr>", unsafe_allow_html=True)
            st.markdown(f"<p><strong>Objet:</strong> {instruction['objet']}</p>", unsafe_allow_html=True)
            st.markdown(f"<p><strong>Résumé:</strong> {instruction['resume']}</p>", unsafe_allow_html=True)
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # Bouton pour télécharger cette instruction
            if st.download_button(
                "📥 Télécharger cette instruction (CSV)",
                data=results[results['title'] == selected_title].to_csv(index=False).encode('utf-8'),
                file_name=f"instruction_{instruction['year']}_{instruction['week']}.csv",
                mime="text/csv"
            ):
                st.success("✅ Instruction téléchargée!")

with tab2:
    st.markdown("<h2 class='sub-header'>Visualisation des données</h2>", unsafe_allow_html=True)
    
    # Statistiques générales
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Instructions", len(data))
    
    with col2:
        st.metric("Années couvertes", f"{min(data['year'])} - {max(data['year'])}")
    
    with col3:
        # Correction de l'erreur à la ligne 851
        if 'last_updated' in data.columns and not data['last_updated'].isna().all():
            try:
                last_update = max(pd.to_datetime(data['last_updated'], errors='coerce').dropna())
                last_update_str = last_update.strftime("%d/%m/%Y")
            except (ValueError, TypeError):
                last_update_str = "Non disponible"
        else:
            last_update_str = "Non disponible"
            
        st.metric("Dernière mise à jour", last_update_str)
    
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Graphique par année
    st.markdown("<h3 class='sub-header'>Répartition par année</h3>", unsafe_allow_html=True)
    
    year_counts = data.groupby('year').size().reset_index(name='count')
    
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.bar_chart(year_counts, x='year', y='count')
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Répartition par mois
    st.markdown("<h3 class='sub-header'>Répartition par semaine</h3>", unsafe_allow_html=True)
    
    week_counts = data.groupby('week').size().reset_index(name='count')
    
    st.markdown("<div class='card'>", unsafe_allow_html=True)
    st.line_chart(week_counts, x='week', y='count')
    st.markdown("</div>", unsafe_allow_html=True)
    
    with col2:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        search_button = st.button("🔎 Rechercher", use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Filtres supplémentaires
    with st.expander("Filtres avancés"):
        col1, col2 = st.columns(2)
        
        with col1:
            years = sorted(data['year'].unique(), reverse=True)
            selected_year = st.selectbox("Année", ["Toutes"] + list(years))
            
        with col2:
            if selected_year != "Toutes":
                weeks = sorted(data[data['year'] == selected_year]['week'].unique())
                selected_week = st.selectbox("Semaine", ["Toutes"] + list(weeks))
            else:
                selected_week = "Toutes"
    
    # Effectuer la recherche
    if search_button or search_query or (selected_year != "Toutes"):
        with st.spinner("Recherche en cours..."):
            # Appliquer les filtres par année/semaine
            filtered_data = data.copy()
            
            if selected_year != "Toutes":
                filtered_data = filtered_data[filtered_data['year'] == selected_year]
                
                if selected_week != "Toutes":
                    filtered_data = filtered_data[filtered_data['week'] == selected_week]
            
            # Si recherche textuelle, appliquer la recherche avancée
            if search_query:
                search_results = search_instructions(search_query, ix, filtered_data)
                st.session_state.search_results = search_results
            else:
                st.session_state.search_results = filtered_data
    
    # Afficher les résultats de recherche
    if 'search_results' in st.session_state and st.session_state.search_results is not None:
        results = st.session_state.search_results
        
        if results.empty:
            st.markdown("<div class='info-box'>Aucun résultat trouvé pour cette recherche.</div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='success-message'>📊 {len(results)} instructions trouvées</div>", unsafe_allow_html=True)
            
            # Formater les données pour l'affichage
            display_data = format_data_for_display(results)
            
            # Affichage des résultats sous forme de tableau
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            st.dataframe(
                display_data[['affichage_date', 'title', 'objet_court']],
                column_config={
                    "affichage_date": "Date",
                    "title": "Titre",
                    "objet_court": "Objet"
                },
                use_container_width=True,
                hide_index=True
            )
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        # Afficher toutes les données par défaut si aucune recherche n'a été effectuée
        display_data = format_data_for_display(data)
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.dataframe(
            display_data[['affichage_date', 'title', 'objet_court']],
            column_config={
                "affichage_date": "Date",
                "title": "Titre",
                "objet_court": "Objet"
            },
            use_container_width=True,
            hide_index=True
        )
        st.markdown("</div>", unsafe_allow_html=True)
            
            # Récupérer le token GitHub depuis les secrets Streamlit
            github_token = None
            try:
                github_token = st.secrets["GITHUB_TOKEN"]
                if not github_token:
                    st.error("❌ Token GitHub vide. Veuillez configurer le secret GITHUB_TOKEN dans Streamlit Cloud.")
                    status.update(label="❌ Échec de la mise à jour", state="error")
                    return False
            except Exception as e:
                st.error("❌ Token GitHub manquant. Veuillez configurer le secret GITHUB_TOKEN dans Streamlit Cloud.")
                status.update(label="❌ Échec de la mise à jour", state="error")
                return False
            
            # Informations du dépôt
            owner = "M00N69"
            repo = "sdssa-instructions-app"
            path = "data/sdssa_instructions.db"
            branch = "main"  # ou 'master' selon votre configuration
            
            # Préparation des en-têtes pour l'API GitHub
            headers = {
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            st.write("🔍 Vérification du fichier sur GitHub...")
            
            # 1. Vérifier si le fichier existe déjà sur GitHub pour obtenir son SHA
            url_get_file = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
            response = requests.get(url_get_file, headers=headers)
            
            file_sha = None
            if response.status_code == 200:
                file_sha = response.json().get("sha")
                st.write("✅ Fichier existant trouvé sur GitHub")
            elif response.status_code == 404:
                st.write("ℹ️ Première mise à jour du fichier sur GitHub")
            else:
                st.error(f"❌ Erreur lors de la vérification du fichier sur GitHub: {response.status_code}")
                st.error(response.text)
                status.update(label="❌ Échec de la mise à jour", state="error")
                return False
            
            # 2. Lire et encoder le contenu du fichier local
            with open(local_db_path, "rb") as file:
                file_content = file.read()
                file_content_base64 = base64.b64encode(file_content).decode("utf-8")
            
            st.write("📤 Préparation de la mise à jour...")
            
            # 3. Préparer les données pour la requête
            data = {
                "message": f"Mise à jour de la base de données - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "content": file_content_base64,
                "branch": branch
            }
            
            # Ajouter le SHA si le fichier existe déjà
            if file_sha:
                data["sha"] = file_sha
            
            # 4. Envoyer la mise à jour à GitHub
            st.write("📤 Envoi de la mise à jour vers GitHub...")
            url_update = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
            response = requests.put(url_update, headers=headers, json=data)
            
            if response.status_code in [200, 201]:
                st.success("✅ Base de données mise à jour avec succès sur GitHub!")
                status.update(label="✅ Mise à jour réussie!", state="complete")
                return True
            else:
                st.error(f"❌ Erreur lors de la mise à jour sur GitHub: {response.status_code}")
                st.error(response.text)
                status.update(label="❌ Échec de la mise à jour", state="error")
                return False
                
        except Exception as e:
            st.error(f"❌ Exception lors de la mise à jour sur GitHub: {str(e)}")
            st.error(traceback.format_exc())
            status.update(label="❌ Échec de la mise à jour", state="error")
            return False

# --- Fonction pour télécharger la base de données depuis GitHub ---
def download_db_from_github(force=False):
    """Télécharge la base de données depuis GitHub si une version plus récente est disponible."""
    # URL directe vers le fichier dans le dépôt GitHub
    github_raw_url = "https://raw.githubusercontent.com/M00N69/sdssa-instructions-app/main/data/sdssa_instructions.db"
    local_db_path = "data/sdssa_instructions.db"
    
    # Définir les headers avec un User-Agent
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # Vérifier si le fichier existe localement et obtenir sa date de modification
        local_modification_time = None
        local_hash = None
        if os.path.exists(local_db_path):
            local_modification_time = os.path.getmtime(local_db_path)
            local_modification_date = datetime.fromtimestamp(local_modification_time)
            
            # Calculer le hash de la base locale pour détecter les changements
            with open(local_db_path, 'rb') as f:
                local_hash = hashlib.md5(f.read()).hexdigest()
            
            with st.status(f"📅 Base de données locale du {local_modification_date.strftime('%d/%m/%Y à %H:%M')}"):
                st.write("Vérification des mises à jour...")
        
        # Télécharger directement le fichier sans vérifier les en-têtes (plus fiable)
        with st.spinner("Téléchargement de la base de données..."):
            response = requests.get(github_raw_url, headers=headers, allow_redirects=True, timeout=30)
            
            if response.status_code == 200:
                # Calculer le hash de la nouvelle version
                new_content = response.content
                new_hash = hashlib.md5(new_content).hexdigest()
                
                # Vérifier si le contenu a réellement changé ou si le téléchargement est forcé
                if force or not local_hash or new_hash != local_hash:
                    # Créer une sauvegarde datée
                    if os.path.exists(local_db_path):
                        backup_date = datetime.now().strftime('%Y%m%d_%H%M%S')
                        backup_path = f"backups/sdssa_instructions_{backup_date}.db"
                        shutil.copy2(local_db_path, backup_path)
                        st.write(f"✅ Sauvegarde créée: {backup_path}")
                    
                    # Écrire la nouvelle version
                    with open(local_db_path, 'wb') as f:
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
                    st.info("📌 Le contenu de la base de données est identique - aucune mise à jour nécessaire")
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
        st.error("❌ Base de données non trouvée! Veuillez télécharger la base de données depuis GitHub.")
        st.stop()
        
    return sqlite3.connect(db_path)

def ensure_database_structure():
    """Vérifie et crée la structure de la base de données."""
    with get_db_connection() as conn:
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
            
            # Vérifier si la colonne last_updated existe
            cursor.execute("PRAGMA table_info(instructions)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'last_updated' not in columns:
                cursor.execute("ALTER TABLE instructions ADD COLUMN last_updated TIMESTAMP")
                conn.commit()
                
            return True
        except sqlite3.Error as e:
            st.error(f"❌ Erreur base de données: {e}")
            return False

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
            cursor.execute("""
                INSERT OR REPLACE INTO instructions (year, week, title, link, pdf_link, objet, resume, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (year, week, title, link, pdf_link, objet, resume, datetime.now()))
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
                soup = BeautifulSoup(response.content, 'html.parser')
                instructions = soup.find_all('a', href=True)
                sdssa_instructions = [a for a in instructions if 'SDSSA' in a.text]
                new_instructions = []
                
                progress_bar = st.progress(0.0)
                for idx, instruction in enumerate(sdssa_instructions):
                    href = instruction['href']
                    if not href.startswith(('http://', 'https://')):
                        href = f"https://info.agriculture.gouv.fr{href}"
                    link = href
                    pdf_link = link.replace("/detail", "/telechargement")
                    
                    try:
                        detail_response = requests.get(link, timeout=15)
                        if detail_response.status_code == 200:
                            soup = BeautifulSoup(detail_response.content, 'html.parser')
                            objet_tag = soup.find('b', text="OBJET : ")
                            objet = objet_tag.next_sibling.strip() if objet_tag and objet_tag.next_sibling else "OBJET : Inconnu"
                            resume_tag = soup.find('b', text="RESUME : ")
                            resume = resume_tag.next_sibling.strip() if resume_tag and resume_tag.next_sibling else "RESUME : Inconnu"
                            new_instructions.append((instruction.text, link, pdf_link, objet, resume))
                    except requests.RequestException as e:
                        st.warning(f"⚠️ Erreur détails {link}: {e}")
                        new_instructions.append((instruction.text, link, pdf_link, "OBJET : Inconnu", "RESUME : Inconnu"))
                    
                    # Mettre à jour la barre de progression
                    progress_bar.progress((idx + 1) / len(sdssa_instructions))
                    # Pause pour éviter de surcharger le serveur
                    time.sleep(0.5)
                
                return new_instructions
            else:
                st.warning(f"⚠️ Impossible de récupérer année {year} semaine {week} (Status: {response.status_code})")
                return []
    except requests.RequestException as e:
        st.error(f"❌ Erreur connexion année {year} semaine {week}: {e}")
        return []

# --- Fonctions de Normalisation de Texte et Indexation Whoosh ---
@st.cache_resource
def create_whoosh_index(df):
    """Crée ou ouvre l'index Whoosh."""
    analyzer = StemmingAnalyzer() | LowercaseFilter() | StopFilter()
    schema = Schema(title=TEXT(stored=True, analyzer=analyzer),
                    objet=TEXT(stored=True, analyzer=analyzer),
                    resume=TEXT(stored=True, analyzer=analyzer),
                    content=TEXT(analyzer=analyzer))
    index_dir = "indexdir"
    
    try:
        if not exists_in(index_dir) or len(os.listdir(index_dir)) == 0:
            ix = create_in(index_dir, schema)
            with st.spinner("Création index Whoosh..."):
                writer = ix.writer()
                for index, row in df.iterrows():
                    writer.add_document(title=row['title'], objet=row['objet'], resume=row['resume'], 
                                       content=f"{row['title']} {row['objet']} {row['resume']}")
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
    for syn in wordnet.synsets(word, lang='fra'):
        for lemma in syn.lemmas(lang='fra'):
            synonyms.add(lemma.name().lower())
    return synonyms

def normalize_text(text):
    """Normalise le texte."""
    lemmatizer = WordNetLemmatizer()
    words = word_tokenize(text.lower())
    normalized_words = [lemmatizer.lemmatize(word) for word in words]
    return ' '.join(normalized_words)

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
                filtered_data = pd.DataFrame([{
                    'id': data.loc[data['title'] == hit['title'], 'id'].values[0] if not data.loc[data['title'] == hit['title'], 'id'].empty else None,
                    'year': data.loc[data['title'] == hit['title'], 'year'].values[0] if not data.loc[data['title'] == hit['title'], 'year'].empty else None,
                    'week': data.loc[data['title'] == hit['title'], 'week'].values[0] if not data.loc[data['title'] == hit['title'], 'week'].empty else None,
                    'title': hit['title'],
                    'link': data.loc[data['title'] == hit['title'], 'link'].values[0] if not data.loc[data['title'] == hit['title'], 'link'].empty else None,
                    'pdf_link': data.loc[data['title'] == hit['title'], 'pdf_link'].values[0] if not data.loc[data['title'] == hit['title'], 'pdf_link'].empty else None,
                    'objet': hit['objet'],
                    'resume': hit['resume'],
                    'last_updated': data.loc[data['title'] == hit['title'], 'last_updated'].values[0] if not data.loc[data['title'] == hit['title'], 'last_updated'].empty else None,
                    'score': hit.score,
                } for hit in results if not data.loc[data['title'] == hit['title']].empty])
                
                # Trier par score de pertinence
                if not filtered_data.empty:
                    filtered_data = filtered_data.sort_values(by='score', ascending=False)
                
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
        st.error("❌ Base de données non trouvée! Veuillez d'abord télécharger la base de données.")
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
            
            # Afficher les informations de mise à jour en dehors d'une structure de colonnes
            st.info(f"📅 Dernière mise à jour: {last_update.strftime('%Y-%m-%d')}")
            st.info(f"🔍 Année/semaine de départ: {start_year}/{start_week}")
            st.info(f"📌 Année/semaine actuelle: {current_year}/{current_week}")
            
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
            existing_weeks = set((int(row[0]), int(row[1])) for row in cursor.fetchall())
            
            # Filtrer pour ne garder que les semaines manquantes
            weeks_to_check = [(year, week) for year, week in weeks_to_check if (year, week) not in existing_weeks]
            
            st.write(f"🔍 Nombre de semaines manquantes à vérifier: {len(weeks_to_check)}")
            
            if len(weeks_to_check) > weeks_limit:
                st.warning(f"⚠️ Attention: {len(weeks_to_check)} semaines à vérifier. Limité à {weeks_limit} semaines les plus récentes.")
                weeks_to_check = sorted(weeks_to_check, key=lambda x: (x[0], x[1]), reverse=True)[:weeks_limit]
            
            new_instructions_total = 0
            progress_bar = st.progress(0)
            
            for idx, (year_to_check, week_num) in enumerate(sorted(weeks_to_check)):
                with st.status(f"🔍 Vérification année {year_to_check}, semaine {week_num}..."):
                    instructions = get_new_instructions(year_to_check, week_num)
                    if instructions:
                        st.write(f"📝 Instructions récupérées: {len(instructions)}")
                        new_instructions_total += len(instructions)
                        
                        for title, link, pdf_link, objet, resume in instructions:
                            if add_instruction_to_db(year_to_check, week_num, title, link, pdf_link, objet, resume):
                                new_notes_added = True
                                st.write(f"✅ Ajouté: {title}")
                
                # Mettre à jour la barre de progression
                progress_bar.progress((idx + 1) / len(weeks_to_check))
            
            if new_notes_added:
                st.success(f"✅ {new_instructions_total} nouvelles instructions ajoutées !")
                st.session_state.is_db_updated = True
                
                # Recharger les données et mettre à jour l'index
                data = load_data()
                update_whoosh_index(data)
                
                # Forcer le rechargement des données en cache
                st.cache_data.clear()
                
                return True
            else:
                st.info("📌 Aucune nouvelle instruction trouvée.")
                return False
                
        except Exception as e:
            st.error(f"❌ Erreur lors de la mise à jour: {e}")
            st.error(traceback.format_exc())
            return False
