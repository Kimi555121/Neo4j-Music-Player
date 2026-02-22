# 🎵 Grafové doporučování hudby

Tento projekt je praktickou součástí bakalářské práce. Jedná se o sadu aplikací, které demonstrují využití grafových algoritmů pro doporučování hudby. Řešení kombinuje grafovou databázi Neo4j s programovacím jazykem Python.

## 📁 Obsah projektu

Projekt obsahuje 4 hlavní soubory:

* **`Neo4jMusicPlayer.py`** – Desktopová aplikace 
* **`JupyterMusicPlayer.ipynb`** – Jupyter aplikace 
* **`DataVisualiser.ipynb`** – Vizualizace dat 
* **`PlantUMLdocumentation.ipynb`** – Dokumentace 

## ⚙️ Požadavky a Instalace

Pro spuštění je nutné mít nainstalovaný **Python 3.8+** a běžící instanci databáze **Neo4j Desktop (verze 5.x)**.

### 1. Instalace knihoven
Nainstalujte potřebné závislosti pomocí správce balíčků `pip`:

```bash
pip install neo4j pygame mutagen pandas matplotlib seaborn pillow ipywidgets plantuml
```

### 2. Nastavení databáze
Aplikace očekávají běžící lokální databázi Neo4j.
* **V souboru JupyterMusicPlayer.ipynb: V druhé buňce kódu upravte proměnné uri, user a password v metodě Neo4jConnection.**
* **V souboru DataVisualiser.ipynb: V druhé buňce kódu upravte parametry metody Neo4jAnalytics.**
    

    



### 1. Instalace knihoven
Nainstalujte potřebné závislosti pomocí správce balíčků `pip`:
### 1. Instalace knihoven
Nainstalujte potřebné závislosti pomocí správce balíčků `pip`:
