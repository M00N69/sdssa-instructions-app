import streamlit as st
import pandas as pd
import sqlite3

# Fonction pour lire les données depuis la base de données SQLite
def load_data():
    conn = sqlite3.connect('data/sdssa_instructions.db')
    query = "SELECT * FROM instructions"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# Charger les données
data = load_data()

# Titre de l'application
st.title("Instructions Techniques SDSSA")

# Afficher les filtres
st.sidebar.header("Filtres")
year = st.sidebar.selectbox("Année", data['year'].unique())
week = st.sidebar.selectbox("Semaine", data[data['year'] == year]['week'].unique())
keyword = st.sidebar.text_input("Mot-clé")

# Filtrer les données
filtered_data = data[(data['year'] == year) & (data['week'] == week)]
if keyword:
    filtered_data = filtered_data[filtered_data.apply(lambda row: keyword.lower() in row['title'].lower() or keyword.lower() in row['objet'].lower() or keyword.lower() in row['resume'].lower(), axis=1)]

# Afficher les résultats
st.write(f"Résultats pour l'année {year}, semaine {week}:")
st.dataframe(filtered_data[['title', 'link', 'pdf_link', 'objet', 'resume']])

# Téléchargement des données
st.sidebar.header("Télécharger les données")
if st.sidebar.button("Télécharger le CSV"):
    st.sidebar.download_button(
        label="Télécharger",
        data=filtered_data.to_csv(index=False).encode('utf-8'),
        file_name="sdssa_instructions.csv",
        mime="text/csv"
    )

