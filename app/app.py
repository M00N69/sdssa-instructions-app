import streamlit as st
import pandas as pd
import sqlite3
import os
from whoosh.index import create_in
from whoosh.fields import Schema, TEXT, ID
from whoosh.qparser import QueryParser

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

# Fonction pour créer un index Whoosh
def create_whoosh_index(df):
    schema = Schema(title=TEXT(stored=True), objet=TEXT(stored=True), resume=TEXT(stored=True), content=TEXT)
    if not os.path.exists("indexdir"):
        os.mkdir("indexdir")
    ix = create_in("indexdir", schema)
    writer = ix.writer()
    for index, row in df.iterrows():
        writer.add_document(title=row['title'], objet=row['objet'], resume=row['resume'], content=f"{row['title']} {row['objet']} {row['resume']}")
    writer.commit()
    return ix

# Vérifier la base de données
db_path = check_database()

# Charger les données
data = load_data(db_path)

# Créer un index Whoosh
ix = create_whoosh_index(data)

# Titre de l'application
st.title("Instructions Techniques SDSSA")

# Afficher les filtres
st.sidebar.header("Filtres")
years = data['year'].unique()
weeks = data['week'].unique()
year = st.sidebar.selectbox("Année", years)
week = st.sidebar.selectbox("Semaine", weeks)
keyword = st.sidebar.text_input("Mot-clé")
advanced_search = st.sidebar.text_input("Recherche avancée")

# Filtrer les données
filtered_data = data[(data['year'] == year) & (data['week'] == week)]
if keyword:
    filtered_data = data[data.apply(lambda row: keyword.lower() in row['title'].lower() or keyword.lower() in row['objet'].lower() or keyword.lower() in row['resume'].lower(), axis=1)]

# Recherche avancée avec Whoosh
if advanced_search:
    with ix.searcher() as searcher:
        query = QueryParser("content", ix.schema).parse(advanced_search)
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

# Afficher les résultats
st.write(f"Résultats pour l'année {year}, semaine {week}:")
st.dataframe(filtered_data[['title', 'link', 'pdf_link', 'objet', 'resume']])

# Téléchargement des données
st.sidebar.header("Télécharger les données")
if st.sidebar.button("Télécharger le CSV"):
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
    recent_updates = data.sort_values(by='last_updated', ascending=False).head(10)
    st.write("Dernières mises à jour :")
    st.dataframe(recent_updates[['title', 'link', 'pdf_link', 'objet', 'resume', 'last_updated']])

# Afficher les détails d'une instruction
st.sidebar.header("Détails d'une instruction")
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


