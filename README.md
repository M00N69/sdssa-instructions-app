# sdssa-instructions-app
INstruction DGAL SDSSA
sdssa-instructions-app/
│
├── app/                        # Dossier pour l'application Streamlit
│   ├── app.py                  # Script principal de l'application Streamlit
│   ├── utils.py                # Fonctions utilitaires (ex : lecture de la base de données)
│   ├── styles.css              # Fichier CSS pour le design de l'application
│   └── assets/                 # Dossier pour les images ou autres ressources statiques
│       └── logo.png            # Exemple : logo de l'application
│
├── data/                       # Dossier pour les données
│   ├── sdssa_instructions_2019_2025.csv  # Fichier CSV généré avec Colab
│   ├── sdssa_instructions.db   # Base de données SQLite
│   └── logs/                   # Dossier pour les fichiers de logs
│       └── update_log.txt      # Fichier de log des mises à jour
│
├── scripts/                    # Dossier pour les scripts de mise à jour
│   └── update_script.py        # Script de mise à jour hebdomadaire
│
├── .github/workflows/           # Dossier pour les workflows GitHub Actions
│   └── update_data.yml          # Workflow pour la mise à jour automatique des données
│
├── requirements.txt            # Fichier des dépendances Python
├── README.md                   # Documentation du projet
└── LICENSE                     # Licence du projet


# SDSSA Instructions App

Cette application permet de visualiser et de télécharger les instructions techniques "SDSSA" de janvier 2019 à la semaine 6 de 2025. Les données sont mises à jour automatiquement chaque semaine.

## Fonctionnalités

- Afficher les instructions techniques existantes.
- Filtrer les données par année, semaine, ou mots-clés.
- Télécharger les données sous forme de CSV ou PDF.
- Voir les mises à jour récentes.

## Structure du projet

```plaintext
sdssa-instructions-app/
│
├── app/                        # Dossier pour l'application Streamlit
│   ├── app.py                  # Script principal de l'application Streamlit
│   ├── utils.py                # Fonctions utilitaires
│   ├── styles.css              # Fichier CSS pour le design de l'application
│   └── assets/                 # Dossier pour les images ou autres ressources statiques
│       └── logo.png            # Exemple : logo de l'application
│
├── data/                       # Dossier pour les données
│   ├── sdssa_instructions_2019_2025.csv  # Fichier CSV initial
│   ├── sdssa_instructions.db   # Base de données SQLite
│   └── logs/                   # Dossier pour les fichiers de logs
│       └── update_log.txt      # Fichier de log des mises à jour
│
├── scripts/                    # Dossier pour les scripts de mise à jour
│   └── update_script.py        # Script de mise à jour hebdomadaire
│
├── .github/workflows/           # Dossier pour les workflows GitHub Actions
│   └── update_data.yml          # Workflow pour la mise à jour automatique des données
│
├── requirements.txt            # Fichier des dépendances Python
├── README.md                   # Documentation du projet
└── LICENSE                     # Licence du projet

