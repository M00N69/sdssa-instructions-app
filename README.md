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

