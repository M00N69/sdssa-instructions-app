if st.sidebar.button("Mettre à jour les données"):
    with st.spinner("Mise à jour des instructions..."):
        db_path = check_database()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        new_notes_added = False # Flag to track if new notes were added

        try:
            cursor.execute("SELECT MAX(year), CAST(MAX(week) AS INTEGER) FROM instructions") # **CAST week AS INTEGER**
            latest_year_db, latest_week_db = cursor.fetchone()
            latest_year_db = latest_year_db if latest_year_db else 2019
            latest_week_db = latest_week_db if latest_week_db else 0

            current_year, current_week, _ = datetime.now().isocalendar()

            st.write(f"**DEBUG - DB Latest Year:** {latest_year_db}, **DB Latest Week:** {latest_week_db} (after CAST to INT)") # DEBUG
            st.write(f"**DEBUG - Current Year:** {current_year}, **Current Week:** {current_week}") # DEBUG

            # Fetch table schema for debugging
            cursor.execute("PRAGMA table_info(instructions)")
            table_schema = cursor.fetchall()
            st.write("**DEBUG - Table Schema:**", table_schema) # DEBUG - Print table schema

            weeks_to_check = []
            processed_weeks = set() # To avoid duplicates

            if latest_year_db is None: # Handle empty database case first
                st.write("**DEBUG - Condition: Empty Database**") # DEBUG
                start_year = 2019 # Or whatever year you want to start checking from for an empty DB
                for year_to_check in range(start_year, current_year + 1):
                    start_week_year = 1 if year_to_check != start_year else 1 # Start week 1 for each year
                    end_week_year = current_week if year_to_check == current_year else 52 # End at current week for current year
                    for week_num in range(start_week_year, end_week_year + 1):
                        if (year_to_check, week_num) not in processed_weeks:
                            weeks_to_check.append((year_to_check, week_num))
                            processed_weeks.add((year_to_check, week_num))
                            st.write(f"**DEBUG - Adding week:** {(year_to_check, week_num)} (Empty DB Case)") # DEBUG

            elif latest_year_db < current_year:
                st.write("**DEBUG - Condition: latest_year_db < current_year**") # DEBUG
                # Add weeks for years between latest_year_db + 1 and current_year (exclusive of current_year)
                for year_to_check in range(latest_year_db + 1, current_year):
                    st.write(f"**DEBUG - Adding full year:** {year_to_check}") # DEBUG
                    for week_num in range(1, 53):
                        if (year_to_check, week_num) not in processed_weeks:
                            weeks_to_check.append((year_to_check, week_num))
                            processed_weeks.add((year_to_check, week_num))
                            st.write(f"**DEBUG - Adding week:** {(year_to_check, week_num)} (Full Year)") # DEBUG

                # Add weeks for the current year (from week 1 to current_week)
                st.write(f"**DEBUG - Adding weeks for current year: {current_year}**") # DEBUG
                for week_num in range(1, current_week + 1):
                    if (current_year, week_num) not in processed_weeks:
                        weeks_to_check.append((current_year, week_num))
                        processed_weeks.add((current_year, week_num))
                        st.write(f"**DEBUG - Adding week:** {(current_year, week_num)} (Current Year)") # DEBUG


            elif latest_year_db == current_year:
                st.write("**DEBUG - Condition: latest_year_db == current_year**") # DEBUG
                start_week = latest_week_db + 1
                end_week = current_week
                for week_num in range(start_week, end_week + 1):
                    if week_num <= 52 and (current_year, week_num) not in processed_weeks: # Check week_num <= 52 and for duplicates
                        weeks_to_check.append((current_year, week_num))
                        processed_weeks.add((current_year, week_num))
                        st.write(f"**DEBUG - Adding week:** {(current_year, week_num)} (Same Year)") # DEBUG
            else: # latest_year_db > current_year (Unexpected, or no update needed)
                 st.write("**DEBUG - Condition: latest_year_db > current_year (No Update Needed)**") # DEBUG
                 weeks_to_check = [] # No weeks to check if DB is ahead


            st.write(f"**Semaines à vérifier:** {weeks_to_check}") # DEBUG: Print weeks to check

            new_instructions_total = 0
            for year_to_check, week_num in weeks_to_check:
                # DEBUG: Print URL being requested for each week
                url_to_check = f"https://info.agriculture.gouv.fr/boagri/historique/annee-{year_to_check}/semaine-{week_num}"
                st.write(f"Vérification de l'URL: {url_to_check}")

                instructions = get_new_instructions(year_to_check, week_num)
                new_instructions_total += len(instructions)

                st.write(f"Instructions récupérées pour année {year_to_check}, semaine {week_num}: {len(instructions)}") # DEBUG: Print instructions found per week

                for title, link, pdf_link, objet, resume in instructions:
                    if add_instruction_to_db(year_to_check, week_num, title, link, pdf_link, objet, resume):
                        new_notes_added = True # Set flag to True if any new note is added

            if new_notes_added:
                st.success(f"{new_instructions_total} nouvelles instructions ajoutées !")
            else:
                st.info("Aucune nouvelle instruction trouvée.")

            data = load_data(db_path)
            ix = create_whoosh_index(data)

            if new_notes_added: # Push to GitHub only if new notes were added
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
            elif ix: # Success message if index updated but no new notes for GitHub push
                st.info("Base de données locale mise à jour, mais aucune nouvelle instruction trouvée. Pas de publication GitHub.")

        except Exception as e:
            st.error(f"Erreur lors de la mise à jour: {e}")
            st.error(traceback.format_exc())
        finally:
            conn.close()
