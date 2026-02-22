# Instalace závislostí:
# pip install neo4j pygame mutagen

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pygame
import os
from neo4j import GraphDatabase
from pathlib import Path
import hashlib
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
import time
from datetime import datetime
import threading
import io
from PIL import Image, ImageTk
from mutagen.id3 import ID3, APIC


# === 1. NEO4J PŘIPOJENÍ ===
class Neo4jConnection:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def query(self, query, parameters=None):
        with self.driver.session() as session:
            result = session.run(query, parameters)
            return [record.data() for record in result]

    def verify_connection(self):
        self.driver.verify_connectivity()


# === 2. SPRÁVA UŽIVATELŮ ===
class UserManager:
    def __init__(self, neo4j_conn):
        self.conn = neo4j_conn

    def register_user(self, username):
        """Registrace nového uživatele"""
        check_query = """
        MATCH (u:User {name: $username})
        RETURN u.userId as userId
        """
        result = self.conn.query(check_query, {"username": username})

        if result:
            return None, "Uživatelské jméno již existuje"

        user_id = hashlib.md5(username.encode()).hexdigest()[:8]

        create_query = """
        CREATE (u:User {name: $username, userId: $userId})
        RETURN u.userId as userId
        """
        self.conn.query(create_query, {"username": username, "userId": user_id})

        return user_id, "Registrace úspěšná"

    def login_user(self, username):
        """Přihlášení existujícího uživatele"""
        query = """
        MATCH (u:User {name: $username})
        RETURN u.userId as userId, u.name as name
        """
        result = self.conn.query(query, {"username": username})

        if result:
            return result[0]['userId'], "Přihlášení úspěšné"
        else:
            return None, "Uživatel neexistuje"


# === 3. NAČÍTÁNÍ MP3 SOUBORŮ ===
class MusicLibraryScanner:
    def __init__(self, neo4j_conn):
        self.conn = neo4j_conn

    def scan_directory(self, directory_path, progress_callback=None):
        """Naskenuje složku a vytvoří uzly v Neo4j"""
        mp3_files = list(Path(directory_path).rglob("*.mp3"))

        if not mp3_files:
            return 0

        for i, file_path in enumerate(mp3_files):
            try:
                self._process_mp3_file(str(file_path))
                if progress_callback:
                    progress_callback(i + 1, len(mp3_files))
            except Exception as e:
                print(f"Chyba při zpracování {file_path.name}: {e}")

        return len(mp3_files)

    def _process_mp3_file(self, file_path):
        """Zpracuje jeden MP3 soubor a vytvoří uzly"""
        try:
            audio = MP3(file_path, ID3=EasyID3)
            duration = int(audio.info.length)
            title = audio.get('title', [Path(file_path).stem])[0]
            artist_name = audio.get('artist', ['Unknown Artist'])[0]
            genre_name = audio.get('genre', ['Unknown'])[0]
        except:
            audio = MP3(file_path)
            duration = int(audio.info.length)
            title = Path(file_path).stem
            artist_name = "Unknown Artist"
            genre_name = "Unknown"

        track_id = hashlib.md5(file_path.encode()).hexdigest()[:12]
        artist_id = hashlib.md5(artist_name.encode()).hexdigest()[:8]

        query = """
        MERGE (a:Artist {artistId: $artist_id})
        ON CREATE SET a.name = $artist_name

        MERGE (g:Genre {name: $genre_name})

        MERGE (t:Track {trackId: $track_id})
        ON CREATE SET 
            t.title = $title,
            t.duration = $duration,
            t.filePath = $file_path

        MERGE (t)-[:IS_PERFORMED_BY]->(a)
        MERGE (t)-[:BELONGS_TO]->(g)
        """

        self.conn.query(query, {
            "track_id": track_id,
            "title": title,
            "duration": duration,
            "file_path": file_path,
            "artist_id": artist_id,
            "artist_name": artist_name,
            "genre_name": genre_name
        })

    def get_all_tracks(self):
        """Vrátí všechny skladby z databáze"""
        query = """
        MATCH (t:Track)-[:IS_PERFORMED_BY]->(a:Artist)
        OPTIONAL MATCH (t)-[:BELONGS_TO]->(g:Genre)
        RETURN t.trackId as trackId, t.title as title, t.duration as duration,
               t.filePath as filePath, a.name as artist, a.artistId as artistId,
               g.name as genre
        ORDER BY t.title
        """
        return self.conn.query(query)


# === 4. DOPORUČOVACÍ SYSTÉMY ===
class MusicRecommender:
    def __init__(self, neo4j_conn):
        self.conn = neo4j_conn

    def collaborative_filtering(self, user_id, limit=10):
        """Kolaborativní filtrování"""
        query = """
        MATCH (u:User {userId: $user_id})-[l1:LISTENED_TO]->(t:Track)
        WITH u, collect(t) as user_tracks

        MATCH (other:User)-[l2:LISTENED_TO]->(t2:Track)
        WHERE other <> u AND t2 IN user_tracks
        WITH u, other, count(t2) as common_tracks, user_tracks
        WHERE common_tracks > 0
        ORDER BY common_tracks DESC
        LIMIT 10

        MATCH (other)-[:LISTENED_TO]->(rec:Track)
        WHERE NOT rec IN user_tracks
        WITH rec, count(DISTINCT other) as popularity
        ORDER BY popularity DESC
        LIMIT $limit

        MATCH (rec)-[:IS_PERFORMED_BY]->(a:Artist)
        OPTIONAL MATCH (rec)-[:BELONGS_TO]->(g:Genre)
        RETURN rec.trackId as trackId, rec.title as title, 
               a.name as artist, a.artistId as artistId, g.name as genre, 
               rec.filePath as filePath, popularity
        """
        return self.conn.query(query, {"user_id": user_id, "limit": limit})

    def content_based_filtering(self, user_id, limit=10):
        """Filtrování založené na obsahu"""
        query = """
        MATCH (u:User {userId: $user_id})-[:LISTENED_TO]->(t:Track)
        MATCH (t)-[:BELONGS_TO]->(g:Genre)
        MATCH (t)-[:IS_PERFORMED_BY]->(a:Artist)
        WITH u, collect(DISTINCT g) as user_genres, collect(DISTINCT a) as user_artists,
             collect(t) as listened_tracks

        MATCH (rec:Track)-[:BELONGS_TO]->(g2:Genre)
        WHERE g2 IN user_genres AND NOT rec IN listened_tracks
        MATCH (rec)-[:IS_PERFORMED_BY]->(a2:Artist)
        WITH rec, a2, 
             CASE WHEN a2 IN user_artists THEN 2 ELSE 1 END as score
        ORDER BY score DESC, rec.title
        LIMIT $limit

        OPTIONAL MATCH (rec)-[:BELONGS_TO]->(g:Genre)
        RETURN rec.trackId as trackId, rec.title as title,
               a2.name as artist, a2.artistId as artistId, g.name as genre, 
               rec.filePath as filePath, score
        """
        return self.conn.query(query, {"user_id": user_id, "limit": limit})

    def hybrid_recommendation(self, user_id, limit=10, alpha=0.6):
        """
        Hybridní doporučení s parametrem Alpha.
        alpha = váha pro kolaborativní filtr (0.0 až 1.0)
        (1 - alpha) = váha pro obsahový filtr
        """
        query = """
        // 1. Zjistíme preference uživatele
        MATCH (u:User {userId: $user_id})-[:LISTENED_TO]->(t:Track)
        WITH u, collect(t) as listened_tracks

        MATCH (u)-[:LISTENED_TO]->(:Track)-[:BELONGS_TO]->(g:Genre)
        WITH u, listened_tracks, collect(DISTINCT g) as user_genres

        // 2. Najdeme podobné uživatele (peer group)
        MATCH (u)-[:LISTENED_TO]->(t_common:Track)<-[:LISTENED_TO]-(other:User)
        WITH u, listened_tracks, user_genres, collect(DISTINCT other) as peer_group

        // 3. Hledáme kandidáty (neslyšené skladby)
        MATCH (rec:Track)
        WHERE NOT rec IN listened_tracks

        // 4. Výpočet dílčích skóre

        // A) Kolaborativní skóre (S_collab)
        OPTIONAL MATCH (rec)<-[:LISTENED_TO]-(peer)
        WHERE peer IN peer_group
        WITH rec, user_genres, count(peer) as raw_collab_score

        // B) Obsahové skóre (S_content)
        OPTIONAL MATCH (rec)-[:BELONGS_TO]->(rg:Genre)
        WITH rec, raw_collab_score,
             CASE WHEN rg IN user_genres THEN 1.0 ELSE 0.0 END as content_score

        // 5. Normalizace a Finální výpočet
        // POZOR: raw_collab_score může být např. 5 nebo 10. content_score je max 1.
        // Aby vzorec fungoval správně, je dobré collab_score 'zploštit' nebo omezit,
        // ale pro jednoduchost zde použijeme raw hodnotu.

        WITH rec,
             (raw_collab_score * $alpha) + (content_score * (1.0 - $alpha)) as final_score

        WHERE final_score > 0
        ORDER BY final_score DESC
        LIMIT $limit

        // 6. Vrácení výsledků
        MATCH (rec)-[:IS_PERFORMED_BY]->(a:Artist)
        OPTIONAL MATCH (rec)-[:BELONGS_TO]->(g:Genre)
        RETURN rec.trackId as trackId, rec.title as title,
               a.name as artist, g.name as genre, rec.filePath as filePath,
               final_score as score
        """
        return self.conn.query(query, {
            "user_id": user_id,
            "limit": limit,
            "alpha": alpha  # Předáváme alfu jako parametr
        })

    def record_listen(self, user_id, track_id, listen_duration, listen_date):
        """Zaznamenání poslechu skladby"""
        query = """
        MATCH (u:User {userId: $user_id}), (t:Track {trackId: $track_id})
        MERGE (u)-[l:LISTENED_TO]->(t)
        ON CREATE SET l.listenDate = $listen_date, l.listenDuration = $listen_duration
        ON MATCH SET l.listenDate = $listen_date, l.listenDuration = l.listenDuration + $listen_duration
        """
        self.conn.query(query, {
            "user_id": user_id,
            "track_id": track_id,
            "listen_duration": listen_duration,
            "listen_date": listen_date
        })

    def add_fan_relationship(self, user_id, artist_id):
        """Přidání vazby IS_A_FAN_OF"""
        query = """
        MATCH (u:User {userId: $user_id}), (a:Artist {artistId: $artist_id})
        MERGE (u)-[:IS_A_FAN_OF]->(a)
        """
        self.conn.query(query, {"user_id": user_id, "artist_id": artist_id})

    def get_fan_community_stats(self, artist_id):
        """Získá statistiky o fanouškovské skupině daného umělce"""
        query = """
        MATCH (a:Artist {artistId: $artist_id})

        // 1. Zjistit počet fanoušků
        OPTIONAL MATCH (fan:User)-[:IS_A_FAN_OF]->(a)
        WITH a, count(fan) as total_fans, collect(fan.name) as fan_names

        // 2. Zjistit, co tato komunita poslouchá JINÉHO (nejčastěji)
        // Najdi fanoušky -> jejich poslechy -> jiné umělce
        OPTIONAL MATCH (community_member:User)-[:IS_A_FAN_OF]->(a)
        MATCH (community_member)-[:LISTENED_TO]->(:Track)-[:IS_PERFORMED_BY]->(other_artist:Artist)
        WHERE other_artist <> a
        WITH a, total_fans, fan_names, other_artist, count(*) as strength
        ORDER BY strength DESC
        LIMIT 5

        RETURN total_fans, fan_names, 
               collect({artist: other_artist.name, affinity: strength}) as related_tastes
        """
        return self.conn.query(query, {"artist_id": artist_id})

    def get_user_fan_status(self, user_id, artist_id):
        """Zjistí, zda je uživatel členem skupiny"""
        query = """
        MATCH (u:User {userId: $user_id}), (a:Artist {artistId: $artist_id})
        RETURN EXISTS((u)-[:IS_A_FAN_OF]->(a)) as is_member
        """
        result = self.conn.query(query, {"user_id": user_id, "artist_id": artist_id})
        return result[0]['is_member'] if result else False

    def remove_fan_relationship(self, user_id, artist_id):
        """Odebrání vazby IS_A_FAN_OF"""
        query = """
        MATCH (u:User {userId: $user_id})-[r:IS_A_FAN_OF]->(a:Artist {artistId: $artist_id})
        DELETE r
        """
        self.conn.query(query, {"user_id": user_id, "artist_id": artist_id})


# === 5. HUDEBNÍ PŘEHRÁVAČ ===
class MusicPlayer:
    def __init__(self, recommender):
        pygame.mixer.init()
        self.recommender = recommender
        self.current_track_id = None
        self.current_artist_id = None
        self.is_playing = False
        self.current_user_id = None
        self.play_start_time = None

    def play(self, file_path, track_id, artist_id):
        """Přehrání skladby"""
        try:
            if self.current_track_id and self.play_start_time:
                self._record_listen_time()

            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            self.is_playing = True
            self.current_track_id = track_id
            self.current_artist_id = artist_id
            self.play_start_time = time.time()

            return True, "Přehrává se"
        except Exception as e:
            return False, f"Chyba: {e}"

    def pause(self):
        if self.is_playing:
            pygame.mixer.music.pause()
            self.is_playing = False
            return "Pozastaveno"
        else:
            pygame.mixer.music.unpause()
            self.is_playing = True
            return "Pokračuje"

    def stop(self):
        if self.current_track_id and self.play_start_time:
            self._record_listen_time()

        pygame.mixer.music.stop()
        self.is_playing = False
        self.current_track_id = None
        self.current_artist_id = None
        self.play_start_time = None
        return "Zastaveno"

    def _record_listen_time(self):
        """Zaznamenání času poslechu"""
        if not self.current_user_id or not self.current_track_id:
            return

        listen_duration = int(time.time() - self.play_start_time)

        if listen_duration >= 10:
            listen_date = datetime.now().isoformat()
            self.recommender.record_listen(
                self.current_user_id,
                self.current_track_id,
                listen_duration,
                listen_date
            )

    def add_artist_to_favorites(self):
        """Přidání umělce do oblíbených"""
        if self.current_user_id and self.current_artist_id:
            self.recommender.add_fan_relationship(self.current_user_id, self.current_artist_id)
            return True, "Umělec přidán do oblíbených"
        return False, "Žádný umělec není načten"


# === 6. TKINTER APLIKACE ===
class MusicPlayerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🎵 Hudební přehrávač s Neo4j")
        self.root.geometry("900x700")
        self.root.configure(bg="#1e1e1e")

        # Připojení k Neo4j
        self.neo4j_conn = None
        self.user_manager = None
        self.scanner = None
        self.recommender = None
        self.player = None
        self.current_user = None
        self.music_dir = None

        # Progress bar
        self.current_track_duration = 0
        self.current_time_played = 0
        self.timer_loop_id = None  # Pro zrušení smyčky při stopce

        # Zobrazení připojovací obrazovky
        self.show_connection_screen()

    def show_connection_screen(self):
        """Obrazovka pro připojení k Neo4j"""
        self.clear_window()

        frame = tk.Frame(self.root, bg="#1e1e1e")
        frame.pack(expand=True)

        tk.Label(frame, text="🎵 Hudební přehrávač", font=("Arial", 24, "bold"),
                 bg="#1e1e1e", fg="#ffffff").pack(pady=20)

        tk.Label(frame, text="Připojení k Neo4j", font=("Arial", 14),
                 bg="#1e1e1e", fg="#cccccc").pack(pady=10)

        # Vstupní pole
        tk.Label(frame, text="URI:", bg="#1e1e1e", fg="#ffffff").pack()
        uri_entry = tk.Entry(frame, width=40)
        uri_entry.insert(0, "neo4j://127.0.0.1:7687")
        uri_entry.pack(pady=5)

        tk.Label(frame, text="Username:", bg="#1e1e1e", fg="#ffffff").pack()
        user_entry = tk.Entry(frame, width=40)
        user_entry.insert(0, "neo4j")
        user_entry.pack(pady=5)

        tk.Label(frame, text="Password:", bg="#1e1e1e", fg="#ffffff").pack()
        pass_entry = tk.Entry(frame, width=40, show="*")
        pass_entry.pack(pady=5)

        def connect():
            try:
                connection = Neo4jConnection(
                    uri_entry.get(),
                    user_entry.get(),
                    pass_entry.get()
                )

                connection.verify_connection()

                self.neo4j_conn = connection
                self.user_manager = UserManager(self.neo4j_conn)
                self.scanner = MusicLibraryScanner(self.neo4j_conn)
                self.recommender = MusicRecommender(self.neo4j_conn)
                self.player = MusicPlayer(self.recommender)

                messagebox.showinfo("Úspěch", "Připojení k Neo4j úspěšné!")
                self.show_login_screen()
            except Exception as e:
                if 'connection' in locals():
                    connection.close()
                messagebox.showerror("Chyba", f"Nepodařilo se připojit: {e}")

        tk.Button(frame, text="Připojit", command=connect, bg="#4CAF50", fg="white",
                  font=("Arial", 12), padx=20, pady=10).pack(pady=20)

    def show_login_screen(self):
        """Přihlašovací obrazovka"""
        self.clear_window()

        frame = tk.Frame(self.root, bg="#1e1e1e")
        frame.pack(expand=True)

        tk.Label(frame, text="🎵 Přihlášení", font=("Arial", 20, "bold"),
                 bg="#1e1e1e", fg="#ffffff").pack(pady=20)

        tk.Label(frame, text="Uživatelské jméno:", bg="#1e1e1e", fg="#ffffff").pack()
        username_entry = tk.Entry(frame, width=30, font=("Arial", 12))
        username_entry.pack(pady=5)

        def login():
            username = username_entry.get().strip()
            if not username:
                messagebox.showwarning("Upozornění", "Zadej uživatelské jméno")
                return

            user_id, msg = self.user_manager.login_user(username)
            if user_id:
                self.current_user = {"userId": user_id, "name": username}
                self.player.current_user_id = user_id
                messagebox.showinfo("Úspěch", msg)
                self.show_music_directory_screen()
            else:
                messagebox.showerror("Chyba", msg)

        def register():
            username = username_entry.get().strip()
            if not username:
                messagebox.showwarning("Upozornění", "Zadej uživatelské jméno")
                return

            user_id, msg = self.user_manager.register_user(username)
            if user_id:
                self.current_user = {"userId": user_id, "name": username}
                self.player.current_user_id = user_id
                messagebox.showinfo("Úspěch", msg)
                self.show_music_directory_screen()
            else:
                messagebox.showerror("Chyba", msg)

        btn_frame = tk.Frame(frame, bg="#1e1e1e")
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="🔑 Přihlásit se", command=login, bg="#2196F3",
                  fg="white", font=("Arial", 12), padx=20, pady=10).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="📝 Registrovat", command=register, bg="#4CAF50",
                  fg="white", font=("Arial", 12), padx=20, pady=10).pack(side=tk.LEFT, padx=5)

    def show_music_directory_screen(self):
        """Obrazovka pro výběr hudební složky"""
        self.clear_window()

        frame = tk.Frame(self.root, bg="#1e1e1e")
        frame.pack(expand=True)

        tk.Label(frame, text=f"👤 {self.current_user['name']}", font=("Arial", 16, "bold"),
                 bg="#1e1e1e", fg="#ffffff").pack(pady=10)

        tk.Label(frame, text="Vyber složku s hudbou", font=("Arial", 14),
                 bg="#1e1e1e", fg="#cccccc").pack(pady=20)

        def select_directory():
            directory = filedialog.askdirectory(title="Vyber složku s MP3 soubory")
            if directory:
                self.music_dir = directory
                self.scan_music_library()

        tk.Button(frame, text="📁 Vybrat složku", command=select_directory,
                  bg="#FF9800", fg="white", font=("Arial", 14),
                  padx=30, pady=15).pack(pady=10)

        tk.Label(frame, text="nebo", bg="#1e1e1e", fg="#888888").pack(pady=5)

        tk.Button(frame, text="▶ Pokračovat s existující knihovnou",
                  command=self.show_player_screen, bg="#4CAF50", fg="white",
                  font=("Arial", 12), padx=20, pady=10).pack(pady=10)

    def scan_music_library(self):
        """Skenování hudební knihovny"""
        progress_window = tk.Toplevel(self.root)
        progress_window.title("Skenování")
        progress_window.geometry("400x150")
        progress_window.configure(bg="#1e1e1e")

        tk.Label(progress_window, text="Skenování hudební knihovny...",
                 bg="#1e1e1e", fg="#ffffff", font=("Arial", 12)).pack(pady=20)

        progress_var = tk.StringVar(value="0 / 0")
        progress_label = tk.Label(progress_window, textvariable=progress_var,
                                  bg="#1e1e1e", fg="#cccccc")
        progress_label.pack()

        progress_bar = ttk.Progressbar(progress_window, length=300, mode='determinate')
        progress_bar.pack(pady=20)

        def update_progress(current, total):
            progress_var.set(f"{current} / {total}")
            progress_bar['maximum'] = total
            progress_bar['value'] = current
            progress_window.update()

        def scan_thread():
            count = self.scanner.scan_directory(self.music_dir, update_progress)
            progress_window.destroy()
            messagebox.showinfo("Dokončeno", f"Naskenováno {count} skladeb")
            self.show_player_screen()

        threading.Thread(target=scan_thread, daemon=True).start()

    def show_player_screen(self):
        """Hlavní obrazovka přehrávače"""
        self.clear_window()

        # Hlavní frame
        main_frame = tk.Frame(self.root, bg="#1e1e1e")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Header
        header = tk.Frame(main_frame, bg="#2d2d2d")
        header.pack(fill=tk.X, pady=(0, 10))

        tk.Label(header, text=f"👤 {self.current_user['name']}",
                 font=("Arial", 14, "bold"), bg="#2d2d2d", fg="#ffffff").pack(side=tk.LEFT, padx=10, pady=5)

        tk.Button(header, text="🔄 Obnovit knihovnu", command=self.show_music_directory_screen,
                  bg="#FF9800", fg="white").pack(side=tk.RIGHT, padx=5, pady=5)
        tk.Button(header, text="👤 Změnit uživatele", command=self.change_user,
                  bg="#2196F3", fg="white").pack(side=tk.RIGHT, padx=5, pady=5)
        tk.Button(header, text="🔌 Změnit databázi", command=self.change_database,
                  bg="#9C27B0", fg="white").pack(side=tk.RIGHT, padx=5, pady=5)

        # Rozdělení na levou a pravou část
        content_frame = tk.Frame(main_frame, bg="#1e1e1e")
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Levá část
        left_frame = tk.Frame(content_frame, bg="#2d2d2d")
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        # --- NOVÉ: NOW PLAYING PANEL ---
        now_playing_frame = tk.Frame(left_frame, bg="#252525", bd=2, relief=tk.GROOVE)
        now_playing_frame.pack(fill=tk.X, padx=5, pady=5)

        # 1. Obrázek alba (vlevo v panelu)
        # Defaultní prázdný obrázek při startu
        default_img = Image.new('RGB', (150, 150), color='#1e1e1e')
        self.album_art_image = ImageTk.PhotoImage(default_img)

        self.art_label = tk.Label(now_playing_frame, image=self.album_art_image, bg="#252525")
        self.art_label.pack(side=tk.LEFT, padx=10, pady=10)

        # 2. Informace o skladbě (vpravo od obrázku)
        info_frame = tk.Frame(now_playing_frame, bg="#252525")
        info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.lbl_title = tk.Label(info_frame, text="Vyber skladbu", font=("Arial", 16, "bold"),
                                  bg="#252525", fg="white", anchor="w")
        self.lbl_title.pack(fill=tk.X, pady=(10, 5))

        self.lbl_artist = tk.Label(info_frame, text="...", font=("Arial", 12),
                                   bg="#252525", fg="#aaaaaa", anchor="w")
        self.lbl_artist.pack(fill=tk.X)

        # --- NOVÉ: PROGRESS BAR A ČAS ---
        progress_frame = tk.Frame(info_frame, bg="#252525")
        progress_frame.pack(fill=tk.X, pady=(10, 5))

        # Čas vlevo (0:00)
        self.lbl_current_time = tk.Label(progress_frame, text="0:00",
                                         bg="#252525", fg="#aaaaaa", font=("Arial", 9))
        self.lbl_current_time.pack(side=tk.LEFT)

        # Progress bar
        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal",
                                            mode="determinate", length=200)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # Čas vpravo (Celková délka)
        self.lbl_total_time = tk.Label(progress_frame, text="0:00",
                                       bg="#252525", fg="#aaaaaa", font=("Arial", 9))
        self.lbl_total_time.pack(side=tk.RIGHT)

        # --- OVLÁDACÍ TLAČÍTKA (PŘESUNUTA SEM) ---
        control_frame = tk.Frame(info_frame, bg="#252525")
        control_frame.pack(fill=tk.X, pady=15, anchor="w")

        tk.Button(control_frame, text="▶", command=self.play_selected,
                  bg="#4CAF50", fg="white", font=("Arial", 12), width=3).pack(side=tk.LEFT, padx=2)
        tk.Button(control_frame, text="⏸", command=self.pause_music,
                  bg="#FF9800", fg="white", font=("Arial", 12), width=3).pack(side=tk.LEFT, padx=2)
        tk.Button(control_frame, text="⏹", command=self.stop_music,
                  bg="#f44336", fg="white", font=("Arial", 12), width=3).pack(side=tk.LEFT, padx=2)

        # Tlačítka Fanoušek a FanZone
        self.fav_btn = tk.Button(control_frame, text="⭐",
                                 command=self.toggle_favorite_artist,
                                 bg="#2196F3", fg="white", font=("Arial", 11))
        self.fav_btn.pack(side=tk.LEFT, padx=10)

        tk.Button(control_frame, text="👥", command=self.open_fan_zone,
                  bg="#673AB7", fg="white", font=("Arial", 10)).pack(side=tk.LEFT)

        # --- SEZNAM SKLADEB (ZŮSTÁVÁ DOLE) ---
        tk.Label(left_frame, text="📚 Knihovna", font=("Arial", 10, "bold"),
                 bg="#2d2d2d", fg="#aaaaaa").pack(anchor="w", padx=5)

        list_frame = tk.Frame(left_frame, bg="#2d2d2d")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.track_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set,
                                        bg="#3d3d3d", fg="#ffffff",
                                        font=("Arial", 10), selectmode=tk.SINGLE, bd=0)
        self.track_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.track_listbox.yview)

        # Načtení skladeb
        self.tracks_data = self.scanner.get_all_tracks()
        for track in self.tracks_data:
            display_text = f"{track['title']} - {track['artist']}"
            # if track.get('genre'):
            #     display_text += f" ({track['genre']})"
            self.track_listbox.insert(tk.END, display_text)

        # Status label
        self.status_label = tk.Label(left_frame, text="Připraveno",
                                     bg="#2d2d2d", fg="#aaaaaa", font=("Arial", 9))
        self.status_label.pack(pady=5)

        # Pravá část - doporučení
        right_frame = tk.Frame(content_frame, bg="#2d2d2d")
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        tk.Label(right_frame, text="🎯 Doporučení", font=("Arial", 12, "bold"),
                 bg="#2d2d2d", fg="#ffffff").pack(pady=5)

        # Výběr typu doporučení
        rec_frame = tk.Frame(right_frame, bg="#2d2d2d")
        rec_frame.pack(fill=tk.X, padx=5, pady=5)

        self.rec_type = tk.StringVar(value="Kolaborativní filtrování")
        tk.OptionMenu(rec_frame, self.rec_type,
                      "Kolaborativní filtrování",
                      "Obsahové filtrování",
                      "Hybridní doporučení").pack(side=tk.LEFT, padx=5)

        tk.Button(rec_frame, text="🔍 Doporuč", command=self.get_recommendations,
                  bg="#9C27B0", fg="white").pack(side=tk.LEFT)

        # Seznam doporučení
        rec_list_frame = tk.Frame(right_frame, bg="#2d2d2d")
        rec_list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        rec_scrollbar = tk.Scrollbar(rec_list_frame)
        rec_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.rec_listbox = tk.Listbox(rec_list_frame, yscrollcommand=rec_scrollbar.set,
                                      bg="#3d3d3d", fg="#ffffff", font=("Arial", 10))
        self.rec_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rec_scrollbar.config(command=self.rec_listbox.yview)

        self.recommendations_data = []

    def update_progress_loop(self):
        """Aktualizuje progress bar každou vteřinu"""
        # Pokud hraje hudba (není pauza a není stopnuto)
        if self.player.is_playing and self.player.current_track_id:

            # Zvýšíme počítadlo o 1 sekundu
            if self.current_time_played < self.current_track_duration:
                self.current_time_played += 1

                # Aktualizace vizuálu
                self.progress_bar['value'] = self.current_time_played
                self.lbl_current_time.config(text=self.format_time(self.current_time_played))

        # Naplánování dalšího spuštění za 1000 ms (1 sekunda)
        # Uložíme si ID, abychom to mohli případně zrušit
        self.timer_loop_id = self.root.after(1000, self.update_progress_loop)

    def format_time(self, seconds):
        """Převede sekundy na formát MM:SS"""
        m = seconds // 60
        s = seconds % 60
        return f"{m}:{s:02d}"

    def play_selected(self):
        selection = self.track_listbox.curselection()
        if not selection:
            messagebox.showwarning("Upozornění", "Vyber skladbu")
            return

        idx = selection[0]
        track = self.tracks_data[idx]

        # Resetování předchozí smyčky, pokud běží
        if self.timer_loop_id:
            self.root.after_cancel(self.timer_loop_id)

        success, msg = self.player.play(track['filePath'], track['trackId'], track['artistId'])

        if success:
            # 1. Aktualizace textů
            self.lbl_title.config(text=track['title'])
            self.lbl_artist.config(text=track['artist'])

            # 2. Načtení a aktualizace obrázku alba
            new_art = self.get_album_art(track['filePath'])
            self.art_label.configure(image=new_art)
            self.art_label.image = new_art  # DŮLEŽITÉ: Udržet referenci, jinak zmizí!

            # 3. Aktualizace tlačítka oblíbených (z předchozího kroku)
            if self.current_user:
                is_fan = self.recommender.get_user_fan_status(
                    self.current_user['userId'],
                    track['artistId']
                )
                self.update_favorite_button_visuals(is_fan)

            # --- NOVÉ: Nastavení progress baru ---
            self.current_track_duration = track['duration']
            self.current_time_played = 0

            self.progress_bar['maximum'] = self.current_track_duration
            self.progress_bar['value'] = 0

            self.lbl_total_time.config(text=self.format_time(self.current_track_duration))
            self.lbl_current_time.config(text="0:00")

            # Spuštění smyčky
            self.update_progress_loop()

        else:
            messagebox.showerror("Chyba", msg)

    def pause_music(self):
        """Pozastavení/pokračování hudby"""
        msg = self.player.pause()
        self.status_label.config(text=msg, fg="#FF9800")

    def stop_music(self):
        """Zastavení hudby"""
        msg = self.player.stop()
        self.status_label.config(text=msg, fg="#f44336")

        # --- NOVÉ: Zastavení progress baru ---
        if self.timer_loop_id:
            self.root.after_cancel(self.timer_loop_id)
            self.timer_loop_id = None

        self.current_time_played = 0
        self.progress_bar['value'] = 0
        self.lbl_current_time.config(text="0:00")

    def toggle_favorite_artist(self):
        """Přepíná stav oblíbeného umělce (Přidat / Odebrat)"""
        if not self.player.current_artist_id or not self.current_user:
            messagebox.showwarning("Upozornění", "Nejdříve spusť skladbu.")
            return

        user_id = self.current_user['userId']
        artist_id = self.player.current_artist_id

        # 1. Zjistit aktuální stav
        is_fan = self.recommender.get_user_fan_status(user_id, artist_id)

        if is_fan:
            # 2a. Pokud je fanoušek -> Odebrat
            self.recommender.remove_fan_relationship(user_id, artist_id)
            self.update_favorite_button_visuals(False)  # Změnit vzhled na "Nejsem fanoušek"
            messagebox.showinfo("Info", "Umělec odebrán z oblíbených.")
        else:
            # 2b. Pokud není fanoušek -> Přidat
            self.recommender.add_fan_relationship(user_id, artist_id)
            self.update_favorite_button_visuals(True)  # Změnit vzhled na "Jsem fanoušek"
            messagebox.showinfo("Info", "Umělec přidán do oblíbených!")

    def update_favorite_button_visuals(self, is_fan):
        """Mění barvu a text tlačítka podle stavu"""
        if is_fan:
            self.fav_btn.config(text="💔", bg="#f44336")  # Červená
        else:
            self.fav_btn.config(text="⭐", bg="#2196F3")  # Modrá

    def get_recommendations(self):
        """Získání doporučení"""
        self.rec_listbox.delete(0, tk.END)
        self.rec_listbox.insert(tk.END, "🔍 Načítám doporučení...")
        self.root.update()

        rec_type = self.rec_type.get()

        try:
            if rec_type == "Kolaborativní filtrování":
                recs = self.recommender.collaborative_filtering(self.current_user['userId'])
            elif rec_type == "Obsahové filtrování":
                recs = self.recommender.content_based_filtering(self.current_user['userId'])
            else:
                recs = self.recommender.hybrid_recommendation(self.current_user['userId'])

            self.rec_listbox.delete(0, tk.END)
            self.recommendations_data = recs

            if recs:
                for rec in recs:
                    display_text = f"{rec['title']} - {rec['artist']}"
                    # if rec.get('genre'):
                    #     display_text += f" ({rec['genre']})"
                    self.rec_listbox.insert(tk.END, display_text)
            else:
                self.rec_listbox.insert(tk.END, "Zatím nemám dostatek dat pro doporučení")
        except Exception as e:
            self.rec_listbox.delete(0, tk.END)
            self.rec_listbox.insert(tk.END, f"Chyba: {e}")

    def clear_window(self):
        """Vymazání všech widgetů z okna"""
        for widget in self.root.winfo_children():
            widget.destroy()

    def change_user(self):
        """Změna uživatele"""
        # Zastavit aktuální přehrávání
        if self.player:
            self.player.stop()

        # Vymazat aktuálního uživatele
        self.current_user = None
        if self.player:
            self.player.current_user_id = None

        # Zobrazit přihlašovací obrazovku
        self.show_login_screen()

    def change_database(self):
        """Změna databázového připojení"""
        # Zastavit aktuální přehrávání
        if self.player:
            self.player.stop()

        # Zavřít aktuální připojení
        if self.neo4j_conn:
            try:
                self.neo4j_conn.close()
            except:
                pass

        # Vymazat všechna data
        self.neo4j_conn = None
        self.user_manager = None
        self.scanner = None
        self.recommender = None
        self.player = None
        self.current_user = None
        self.music_dir = None

        # Zobrazit připojovací obrazovku
        self.show_connection_screen()

    def open_fan_zone(self):
        """Otevře okno s analýzou fanouškovské skupiny"""
        if not self.player.current_artist_id:
            messagebox.showwarning("Upozornění", "Nejdříve spusť nějakou skladbu.")
            return

        # Vytvoření nového okna
        fan_window = tk.Toplevel(self.root)
        fan_window.title("Fan Zone Dashboard")
        fan_window.geometry("500x400")
        fan_window.configure(bg="#2d2d2d")

        # Načtení dat
        stats = self.recommender.get_fan_community_stats(self.player.current_artist_id)
        is_member = self.recommender.get_user_fan_status(self.current_user['userId'],
                                                         self.player.current_artist_id)

        # Pokud nejsou data, ukončit
        if not stats:
            tk.Label(fan_window, text="Žádná data.", bg="#2d2d2d", fg="white").pack()
            return

        data = stats[0]  # První řádek výsledku

        # --- UI Komponenty ---

        # 1. Hlavička
        tk.Label(fan_window, text=f"Komunita fanoušků",
                 font=("Arial", 16, "bold"), bg="#2d2d2d", fg="#ffffff").pack(pady=10)

        # 2. Status uživatele (Členství)
        status_color = "#4CAF50" if is_member else "#757575"
        status_text = "JSI ČLENEM SKUPINY ✅" if is_member else "NEJSI ČLENEM ❌"

        tk.Label(fan_window, text=status_text, font=("Arial", 12, "bold"),
                 bg="#2d2d2d", fg=status_color).pack(pady=5)

        # 3. Statistiky
        stat_frame = tk.Frame(fan_window, bg="#3d3d3d", padx=10, pady=10)
        stat_frame.pack(fill=tk.X, padx=20, pady=10)

        tk.Label(stat_frame, text=f"Počet členů: {data['total_fans']}",
                 bg="#3d3d3d", fg="white", font=("Arial", 12)).pack(anchor="w")

        # Zobrazení jmen (limit 5)
        names = data['fan_names'][:5]
        names_str = ", ".join(names)
        if len(data['fan_names']) > 5:
            names_str += " a další..."

        tk.Label(stat_frame, text=f"Členové: {names_str}",
                 bg="#3d3d3d", fg="#aaaaaa", font=("Arial", 10)).pack(anchor="w", pady=5)

        # 4. Co komunita doporučuje (Analýza grafu)
        tk.Label(fan_window, text="Tato komunita také miluje:",
                 font=("Arial", 12, "bold"), bg="#2d2d2d", fg="#ffffff").pack(pady=(20, 10))

        if data['related_tastes']:
            for item in data['related_tastes']:
                tk.Label(fan_window, text=f"🎵 {item['artist']} (shoda: {item['affinity']})",
                         bg="#2d2d2d", fg="#FF9800", font=("Arial", 11)).pack()
        else:
            tk.Label(fan_window, text="Zatím málo dat pro analýzu.",
                     bg="#2d2d2d", fg="#aaaaaa").pack()

    def get_album_art(self, file_path):
        """Vytáhne obal alba z MP3, nebo vrátí defaultní obrázek"""
        image = None
        try:
            audio = MP3(file_path, ID3=ID3)
            if audio.tags:
                for tag in audio.tags.values():
                    if tag.FrameID == 'APIC':  # APIC je ID3 tag pro obrázek
                        image_data = tag.data
                        image = Image.open(io.BytesIO(image_data))
                        break
        except Exception as e:
            print(f"Nelze načíst obal: {e}")

        # Pokud není obrázek, vytvoříme šedý čtverec (Placeholder)
        if image is None:
            image = Image.new('RGB', (150, 150), color='#3d3d3d')

        # Změna velikosti na 150x150 px (aby to nebylo moc velké)
        image = image.resize((150, 150), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)

# === 7. SPUŠTĚNÍ APLIKACE ===
def main():
    root = tk.Tk()
    app = MusicPlayerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()