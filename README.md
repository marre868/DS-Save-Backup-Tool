# 🎮 Nintendo DS Save Backup Tool

> Automatisiertes, prüfsummenbasiertes Backup-System für Nintendo DS Spielstände von Flashcard SD-Karten – entwickelt in Python, konzipiert für Zuverlässigkeit und Erweiterbarkeit. Verfügbar als CLI-Tool und als lokale Web-GUI.

---

## Inhaltsverzeichnis

- [Überblick](#überblick)
- [Features](#features)
- [Architekturidee](#architekturidee)
- [Designentscheidungen](#designentscheidungen)
  - [Warum SHA-256?](#warum-sha-256)
  - [Warum ein Manifest?](#warum-ein-manifest)
  - [Warum Versionsretention?](#warum-versionsretention)
  - [Wie wird Integrität gewährleistet?](#wie-wird-integrität-gewährleistet)
- [Projektstruktur](#projektstruktur)
- [Installation & Voraussetzungen](#installation--voraussetzungen)
- [Konfiguration](#konfiguration)
- [Verwendung – CLI](#verwendung--cli)
  - [Erste Benutzung & SD-Label](#erste-benutzung--sd-label)
  - [Reguläres Backup](#reguläres-backup)
  - [Weitere Befehle](#weitere-befehle)
  - [Versionierung pro Spiel konfigurieren](#versionierung-pro-spiel-konfigurieren)
  - [Spielstand wiederherstellen (Restore)](#spielstand-wiederherstellen-restore)
- [Verwendung – Web-GUI](#verwendung--web-gui)
  - [GUI starten](#gui-starten)
  - [GUI-Funktionen](#gui-funktionen)
- [Backup-Struktur](#backup-struktur)
- [Konfigurationsdateien](#konfigurationsdateien)
- [Fehlerbehandlung](#fehlerbehandlung)
- [Technische Details](#technische-details)
- [Mögliche Erweiterungen](#mögliche-erweiterungen)
- [Lizenz](#lizenz)

---

## Überblick

Nintendo DS Flashcards speichern Spielstände als `.sav`-Dateien auf der MicroSD-Karte – ohne jegliche automatische Sicherung. Geht die Karte verloren, wird sie überschrieben oder korrupt, sind jahrelange Spielfortschritte unwiederbringlich verloren.

Dieses Tool löst das Problem durch ein **vollautomatisches, inkrementelles Backup-System**:

- Es erkennt anhand von SHA-256-Prüfsummen, ob sich ein Spielstand seit dem letzten Backup geändert hat
- Nur tatsächlich geänderte Dateien werden gesichert
- Mehrere SD-Karten werden sauber getrennt und isoliert verwaltet – Spielstände verschiedener Karten werden nie vermischt
- Jedes Spiel bekommt einen eigenen versionierten Backup-Verlauf mit konfigurierbarer Retention
- Die Integrität jeder gesicherten Datei wird unmittelbar nach dem Kopieren verifiziert
- Spielstände können gezielt auf eine frühere Version zurückgespielt werden
- Eine lokale Web-GUI ermöglicht die vollständige Bedienung im Browser

Das Projekt entstand als praktisches Alltagswerkzeug und demonstriert grundlegende Konzepte aus den Bereichen Dateisystemoperationen, Prüfsummenvalidierung, persistente Zustandsverwaltung, REST-API-Design und robuste Fehlerbehandlung in Python.

---

## Features

| Feature | Beschreibung |
|---|---|
| **SHA-256-Vergleich** | Backup nur bei tatsächlicher Änderung – keine redundanten Kopien |
| **SD-Karten-Trennung** | Jede Karte bekommt ein persistentes Label, Spielstände werden nie vermischt |
| **Versionsretention** | Pro Spiel konfigurierbar, wie viele Backup-Versionen behalten werden |
| **Manifest-Tracking** | JSON-Manifest merkt sich Hashes, Zeitstempel und Metadaten dauerhaft |
| **Integritätsverifikation** | Hash der Zieldatei wird nach dem Kopieren gegengeprüft |
| **Restore / Revert** | Gezieltes Zurückspielen einer beliebigen Backup-Version auf die SD-Karte |
| **Dry-Run-Modus** | Simuliert den Backup-Vorgang vollständig, ohne eine Datei zu schreiben |
| **Strukturiertes Logging** | Jeder Vorgang wird in eine Log-Datei pro SD-Karte geschrieben |
| **Web-GUI** | Lokale Flask-Oberfläche für Backup, Restore, Config und Log-Ansicht |
| **Netzwerkpfad-Unterstützung** | Backup-Ziel kann ein UNC-Netzwerkpfad sein (z. B. `\\server\share\...`) |
| **Windows-kompatibel** | Explizite UTF-8-Behandlung, keine Abhängigkeit von Systemencoding |

---

## Architekturidee

Das Projekt gliedert sich in drei Komponenten, die unabhängig voneinander nutzbar sind:

```
+-------------------------------------------------------+
|                   Web-GUI (Browser)                   |
|      ds_backup_gui.html  <-->  ds_backup_server.py    |
|      Flask REST-API  *  Echtzeit-Status  *  Modals    |
+------------------------+------------------------------+
                         |  ruft auf
+------------------------v------------------------------+
|              CLI / Kern  (ds_save_backup.py)          |
|   +------------------+  +-------------------------+  |
|   |   CLI-Schicht     |  |     Logik-Schicht       |  |
|   | argparse          |  | SHA-256-Hashing         |  |
|   | SD-Label-Aufl.    |  | Manifest-Abgleich       |  |
|   | Modus-Steuerung   |  | Backup-Entscheidung     |  |
|   +------------------+  | Retention-Cleanup       |  |
|                          | Integritaetsverifik.    |  |
|                          +-------------------------+  |
+------------------------+------------------------------+
                         |
+------------------------v------------------------------+
|                 Persistenz-Schicht                    |
|   JSON-Manifest  *  SD-Config  *  Log-Datei           |
|   ds_card_id.txt (auf SD)  *  shutil-Dateikopie       |
+-------------------------------------------------------+
```

**Kernprinzip:** Jede SD-Karte ist eine vollständig isolierte Einheit. Sie besitzt ihr eigenes Manifest, ihre eigene Konfigurationsdatei und ihren eigenen Log. Das Backup-Verzeichnis ist entsprechend hierarchisch aufgebaut:

```
Backup-Root/
+-- <SD-Label>/          <- eine Ebene pro physischer SD-Karte
    +-- <Spielname>/     <- eine Ebene pro Spiel
    |   +-- Spiel_20250101_120000.sav
    |   +-- Spiel_20250210_183000.sav
    +-- backup_manifest.json
    +-- sd_config.json
    +-- backup_log.txt
```

Diese Struktur stellt sicher, dass zwei SD-Karten mit identischen Spielen (z. B. zwei Pokemon-Karten unterschiedlicher Spieler) vollständig getrennt gesichert werden und sich gegenseitig nie überschreiben können.

---

## Designentscheidungen

### Warum SHA-256?

Eine naive Implementierung würde Dateien anhand ihres **Änderungsdatums** (`mtime`) vergleichen. Das ist fehleranfällig: Das Betriebssystem, der Dateisystemtreiber oder das bloße Kopieren der Datei können den Zeitstempel verändern, ohne dass sich der Inhalt geändert hat – und umgekehrt kann eine Datei inhaltlich verändert worden sein, ohne dass `mtime` aktualisiert wurde.

**SHA-256** löst dieses Problem fundamental: Der Hash ist eine 256-Bit-Prüfsumme, die deterministisch aus dem Dateiinhalt berechnet wird. Identischer Inhalt → identischer Hash. Jede noch so kleine Änderung → vollständig anderer Hash (Avalanche-Effekt).

Für `.sav`-Dateien, die typischerweise zwischen 8 KB und 512 KB groß sind, ist der Rechenaufwand vernachlässigbar. SHA-256 ist dabei kryptografisch kollisionsresistent – es ist praktisch ausgeschlossen, dass zwei unterschiedliche Spielstände denselben Hash erzeugen.

```
Datei unveraendert --> SHA-256 identisch  --> kein Backup (I/O gespart)
Datei geaendert    --> SHA-256 abweichend --> Backup wird erstellt
```

### Warum ein Manifest?

Das Manifest (`backup_manifest.json`) ist das **Gedächtnis des Tools**. Es speichert für jede bekannte `.sav`-Datei den zuletzt gesicherten SHA-256-Hash, den Zeitstempel der letzten Sicherung, die Dateigröße sowie eine Liste aller vorhandenen Backup-Versionen.

**Ohne Manifest** müsste das Tool bei jedem Lauf alle vorhandenen Backup-Dateien einlesen und hashen, um festzustellen, ob sich etwas geändert hat. Das wäre bei vielen Versionen langsam und komplex.

**Mit Manifest** genügt ein einzelner Hash-Vergleich: aktueller Datei-Hash vs. gespeicherter Hash. Das ist in O(1) entschieden, unabhängig von der Anzahl vorhandener Backups. Das Manifest ist außerdem die Grundlage für `--list` und die Web-GUI und macht den gesamten Backup-Zustand für Menschen lesbar und prüfbar.

### Warum Versionsretention?

Ein einfaches Backup-System würde bei jeder Änderung die alte Datei überschreiben. Das hat einen entscheidenden Nachteil: Wenn ein Spielstand **korrupt gespeichert** wird – was bei Flashcards vorkommen kann – überschreibt das Tool das letzte funktionierende Backup mit dem defekten Stand.

Durch die **Versionsretention** werden die letzten N Versionen jedes Spielstands aufbewahrt. Der Nutzer kann damit zu einem früheren Zustand zurückgehen, falls ein neuerer Stand fehlerhaft ist.

Die Retention ist bewusst **pro Spiel konfigurierbar** statt nur global: Ein aktiv gespieltes Spiel kann 15 Versionen behalten, während ein abgeschlossenes Spiel mit 2 auskommt. Das spart Speicherplatz ohne pauschalen Verlust an Sicherheit. Alte Versionen werden automatisch nach dem FIFO-Prinzip entfernt. Sicherheitskopien, die vor einem Restore automatisch angelegt werden (`_vor_restore`), sind von der Rotation explizit ausgenommen.

### Wie wird Integrität gewährleistet?

Das Tool implementiert eine **zweistufige Integritätssicherung**:

**Stufe 1 – Vor dem Backup:** Der SHA-256-Hash der Quelldatei wird berechnet und mit dem im Manifest gespeicherten Hash verglichen. Nur bei Abweichung wird ein Backup ausgelöst.

**Stufe 2 – Nach dem Backup:** Unmittelbar nach dem Kopieren wird der SHA-256-Hash der **Zieldatei** berechnet und mit dem Hash der Quelldatei verglichen:

```python
shutil.copy2(quelle, ziel)
dest_hash = sha256_of_file(ziel)
if dest_hash != source_hash:
    raise IOError("Hash nach Kopie stimmt nicht ueberein!")
```

Stimmen die Hashes nicht überein, wird ein Fehler geworfen und das Manifest bleibt unverändert. Beim nächsten Lauf wird der Backup-Versuch wiederholt. Eine stille Dateikorruption beim Kopiervorgang – etwa durch einen instabilen Netzwerkpfad – kann damit nicht unbemerkt bleiben. Dieselbe Verifikation gilt auch beim Restore.

---

## Projektstruktur

```
ds-save-backup/
+-- ds_save_backup.py     # CLI-Kern: Backup, Restore, Manifest, Retention
+-- ds_backup_server.py   # Web-GUI Backend (Flask REST-API)
+-- ds_backup_gui.html    # Web-GUI Frontend (Single-File, kein Build-Schritt)
+-- README.md             # Diese Dokumentation
```

`ds_save_backup.py` ist als **eigenständiges Single-File-Skript** konzipiert und benötigt ausschließlich Python-Standardbibliotheken. Die Web-GUI ist optional und benötigt zusätzlich Flask.

---

## Installation & Voraussetzungen

**Voraussetzungen CLI:**
- Python 3.10 oder neuer
- Keine externen Pakete erforderlich

**Voraussetzungen Web-GUI (optional):**
- Flask: `pip install flask`

**Setup:**

```bash
# Repository klonen
git clone https://github.com/marre868/DS-Save-Backup-Tool.git
cd ds-save-backup

# CLI direkt nutzbar
python ds_save_backup.py --help

# Web-GUI starten (oeffnet Browser automatisch)
pip install flask
python ds_backup_server.py
```

---

## Konfiguration

Standardpfade werden am Anfang jeder Datei gesetzt und müssen einmalig angepasst werden.

**`ds_save_backup.py`, Zeilen 24–25:**

```python
DEFAULT_SOURCE_DIR = Path(r"\\Client\D$")        # Pfad zur SD-Karte
DEFAULT_BACKUP_DIR = Path(r"\\server\share\Backup")  # Backup-Zielverzeichnis
```

**`ds_backup_server.py`, Zeilen 16–17** (gleiche Werte wie oben):

```python
DEFAULT_SOURCE_DIR = Path(r"\\Client\D$")
DEFAULT_BACKUP_DIR = Path(r"\\server\share\Backup")
```

> **Wichtig:** Auf Windows immer Raw-Strings (`r"..."`) verwenden, um ungültige Escape-Sequenzen bei Backslash-Pfaden zu vermeiden.

---

## Verwendung – CLI

### Erste Benutzung & SD-Label

Beim allerersten Einstecken einer SD-Karte muss **einmalig** ein Label vergeben werden. Das Label wird als `ds_card_id.txt` auf der SD-Karte gespeichert und ab dann automatisch erkannt:

```bash
python ds_save_backup.py --label "Hauptkarte"
```

```
  i  Label 'Hauptkarte' auf SD-Karte gespeichert (D:\ds_card_id.txt)
```

Ab diesem Zeitpunkt reicht:

```bash
python ds_save_backup.py
```

`--label` wird nie wieder benötigt. Wird eine SD-Karte ohne Label eingesteckt und kein `--label` angegeben, bricht das Skript mit einer erklärenden Meldung ab – um versehentliche Datenvermischung zuverlässig zu verhindern.

### Reguläres Backup

```bash
# Standard (konfigurierter Quell- und Zielpfad)
python ds_save_backup.py

# Andere SD-Karte auf anderem Laufwerk
python ds_save_backup.py --source E:\

# Anderes Backup-Zielverzeichnis
python ds_save_backup.py --backup-dir C:\Users\Name\Saves
```

**Beispielausgabe:**

```
+======================================================+
|    [*]  Nintendo DS Save Backup Tool  v2.1  [*]     |
+======================================================+

  Quelle      : D:\
  SD-Label    : Hauptkarte
  Backup-Pfad : \\server\share\Backup\Hauptkarte

------------------------------------------------------
  SD-Karte: Hauptkarte  |  Scanne: D:\
------------------------------------------------------
  3 .sav Datei(en) gefunden

  o Pokemon Platin  512.0 KB
    Unveraendert - kein Backup noetig

  > Zelda Phantom Hourglass  256.0 KB  [GEAENDERT]  (max. 5 Versionen)
    [OK] Gesichert: Zelda Phantom Hourglass_20250301_143022.sav
    SHA256: a3f8c1d2e9b74f1a...

  o Mario Kart DS  128.0 KB
    Unveraendert - kein Backup noetig

------------------------------------------------------
  Zusammenfassung
------------------------------------------------------
  Gefundene .sav Dateien           3
  Neu gesichert                    0
  Aktualisiert                     1
  Unveraendert (uebersprungen)     2
  Fehler                           0

  [OK]  Backup abgeschlossen!
```

### Weitere Befehle

```bash
# Dry-Run: zeigt was gesichert werden wuerde, ohne zu schreiben
python ds_save_backup.py --dry-run

# Alle Backups aller SD-Karten auflisten
python ds_save_backup.py --list

# Nur eine bestimmte SD-Karte auflisten
python ds_save_backup.py --list --label "Hauptkarte"

# Hilfe
python ds_save_backup.py --help
```

### Versionierung pro Spiel konfigurieren

```bash
# SD-weiten Standard setzen (gilt fuer alle Spiele dieser Karte)
python ds_save_backup.py --set-keep --sd "Hauptkarte" --versions 8

# Fuer ein einzelnes Spiel abweichend konfigurieren
python ds_save_backup.py --set-keep --sd "Hauptkarte" --game "Pokemon Platin" --versions 15
python ds_save_backup.py --set-keep --sd "Hauptkarte" --game "Mario Kart DS" --versions 3
```

Die Einstellungen werden in `sd_config.json` gespeichert und können dort auch direkt bearbeitet werden.

### Spielstand wiederherstellen (Restore)

Mit `--restore` kann jede gesicherte Version eines Spiels direkt auf die SD-Karte zurückgespielt werden.

**Interaktive Auswahl** (empfohlen):

```bash
python ds_save_backup.py --restore --sd "Hauptkarte" --game "Pokemon Platin"
```

Das Tool listet alle verfügbaren Versionen nummeriert auf und fragt nach der Auswahl. Vor dem Überschreiben wird der aktuelle Spielstand automatisch als Sicherheitskopie gesichert (`_vor_restore`-Suffix).

**Direktauswahl per Index** (für Skripting):

```bash
# Index 0 = aelteste Version, letzter Index = neueste
python ds_save_backup.py --restore --sd "Hauptkarte" --game "Pokemon Platin" --version-index 1
```

**Dry-Run:**

```bash
python ds_save_backup.py --restore --sd "Hauptkarte" --game "Pokemon Platin" --dry-run
```

**Ablauf intern:**
1. Backup-Versionen des Spiels auflisten (ohne `_vor_restore`-Dateien)
2. Zielversion bestimmen (interaktiv oder per Index)
3. Aktuellen Spielstand auf der SD als `_vor_restore`-Sicherheitskopie sichern
4. Gewählte Version auf die SD kopieren
5. SHA-256-Hash der wiederhergestellten Datei verifizieren
6. Manifest aktualisieren

---

## Verwendung – Web-GUI

### GUI starten

```bash
pip install flask
python ds_backup_server.py
```

Der Browser öffnet sich automatisch auf `http://127.0.0.1:5042`. Der Server läuft lokal und ist nur vom eigenen Rechner aus erreichbar. Beenden mit `Strg+C`.

### GUI-Funktionen

| Bereich | Funktion |
|---|---|
| **Header** | SD-Karten-Status (online/offline) mit Label und Pfad, aktualisiert sich bei jedem Refresh |
| **Backup starten** | Direkt per Button, inkl. Dry-Run – Ausgabe des CLI-Skripts live im Modal |
| **Übersicht** | Alle SD-Karten und Spiele mit Größe, letztem Backup-Zeitstempel, SHA-256-Kurzanzeige und Versionsbalken |
| **Versionsbalken** | Visueller Fortschrittsbalken pro Spiel: grün (normal) → gelb (>70 %) → rot (voll) |
| **Restore** | Alle Versionen per Klick auswählbar, Sicherheitskopien separat angezeigt, Bestätigungsdialog |
| **Config** | `keep_versions` pro Spiel oder SD-weit direkt in der GUI ändern |
| **Log-Viewer** | Farbcodierter Log (INFO/OK/WARN/ERROR) je SD-Karte, letzte 200 Zeilen |
| **Auto-Refresh** | Automatische Aktualisierung alle 60 Sekunden |

Der Server kommuniziert über eine einfache REST-API mit dem Browser:

| Endpoint | Methode | Funktion |
|---|---|---|
| `/api/config` | GET | SD-Status, Label, Pfade |
| `/api/cards` | GET | Alle SD-Karten mit Spielen und Versionen |
| `/api/log/<sd_id>` | GET | Log-Zeilen einer SD-Karte |
| `/api/backup` | POST | Backup-Lauf starten (optional dry_run) |
| `/api/restore` | POST | Spielstand wiederherstellen |
| `/api/set_keep` | POST | keep_versions konfigurieren |

---

## Backup-Struktur

```
Backup-Root/
+-- Hauptkarte/
|   +-- Pokemon Platin/
|   |   +-- Pokemon Platin_20250101_120000.sav
|   |   +-- Pokemon Platin_20250115_183000.sav
|   |   +-- Pokemon Platin_20250301_090000.sav
|   |   +-- Pokemon Platin_20250301_143500_vor_restore.sav   <- Sicherheitskopie
|   +-- Zelda Phantom Hourglass/
|   |   +-- Zelda Phantom Hourglass_20250301_143022.sav
|   +-- backup_manifest.json
|   +-- sd_config.json
|   +-- backup_log.txt
|
+-- Zweitkarte/
    +-- Pokemon Platin/        <- gleicher Spielname, vollstaendig isoliert
    |   +-- Pokemon Platin_20250220_110000.sav
    +-- backup_manifest.json
    +-- sd_config.json
    +-- backup_log.txt
```

---

## Konfigurationsdateien

### `ds_card_id.txt` (auf der SD-Karte)

Einzeilige Textdatei mit dem Label der Karte. Wird automatisch beim ersten `--label`-Aufruf erstellt. Dient als eindeutiger Bezeichner zum Trennen mehrerer SD-Karten.

```
Hauptkarte
```

### `sd_config.json` (im Backup-Verzeichnis der Karte)

Steuert die Versionsretention. Wird beim ersten Backup-Lauf automatisch mit Standardwerten angelegt. Kann manuell, per `--set-keep` oder über die Web-GUI angepasst werden.

```json
{
  "_hinweis": "keep_versions_default gilt fuer alle Spiele dieser SD-Karte.",
  "keep_versions_default": 5,
  "spiele": {
    "Pokemon Platin": { "keep_versions": 15 },
    "Mario Kart DS":  { "keep_versions": 3  }
  }
}
```

### `backup_manifest.json` (im Backup-Verzeichnis der Karte)

Interner Zustandsspeicher. Wird vom Tool verwaltet, ist aber menschenlesbar und inspizierbar. Enthält für jede Datei den letzten bekannten SHA-256-Hash – Grundlage für die inkrementelle Backup-Entscheidung.

```json
{
  "pokemon platin.sav": {
    "sha256": "a3f8c1d2e9b74f1a...",
    "letzte_sicherung": "20250301_090000",
    "spiel": "Pokemon Platin",
    "groesse_bytes": 524288,
    "keep_versions": 15,
    "backups": [
      "Pokemon Platin_20250101_120000.sav",
      "Pokemon Platin_20250301_090000.sav"
    ]
  }
}
```

> **Hinweis:** Der Manifest-Schlüssel (Dateipfad) wird intern immer lowercase gespeichert, um Doppeleinträge bei Groß-/Kleinschreibungswechsel des Dateinamens zu verhindern. Der Anzeigename (`spiel`) bleibt davon unberührt.

---

## Fehlerbehandlung

Das Tool behandelt Fehler granular – ein fehlgeschlagener Backup eines einzelnen Spiels bricht den gesamten Lauf nicht ab, sondern wird protokolliert und in der Zusammenfassung ausgewiesen.

| Situation | Verhalten |
|---|---|
| SD-Karte nicht gefunden | Abbruch mit erklärender Fehlermeldung |
| SD-Karte ohne Label | Abbruch mit Anleitung zur einmaligen Label-Vergabe |
| Lesefehler einer `.sav`-Datei | Spiel wird übersprungen, Fehler ins Log |
| Hash-Abweichung nach Backup-Kopie | Backup gilt als fehlgeschlagen, Manifest bleibt unverändert |
| Hash-Abweichung nach Restore-Kopie | Restore wird abgebrochen, Fehlermeldung |
| Sicherheitskopie vor Restore fehlgeschlagen | Interaktive Rückfrage, ob trotzdem fortgefahren werden soll |
| Beschädigtes Manifest | Warnung, Manifest wird neu aufgebaut |
| Beschädigte SD-Config | Warnung, Standardwerte werden verwendet |
| JSON-Datei enthält kein Objekt | Sicher abgefangen, leeres dict als Fallback |

---

## Technische Details

| Aspekt | Detail |
|---|---|
| **Sprache** | Python 3.10+ |
| **CLI-Abhängigkeiten** | Nur Standardbibliothek (`hashlib`, `shutil`, `json`, `pathlib`, `argparse`, `logging`) |
| **GUI-Abhängigkeiten** | Flask (Backend), kein JavaScript-Framework (Vanilla JS, kein Build-Schritt) |
| **Hash-Algorithmus** | SHA-256 via `hashlib`, blockweises Lesen à 64 KB |
| **Dateikopie** | `shutil.copy2` (erhält Metadaten wie `mtime`) |
| **Persistenz** | JSON (Manifest, Config), Plaintext (Label, Log) |
| **Manifest-Keys** | Immer lowercase normalisiert (verhindert Duplikate durch Groß-/Kleinschreibung) |
| **Plattform** | Windows (primär), Linux, macOS; UNC-Netzwerkpfade werden unterstützt |
| **Encoding** | stdout/stderr explizit auf UTF-8 gesetzt; subprocess erbt `PYTHONIOENCODING=utf-8` |
| **GUI-Port** | `127.0.0.1:5042` (nur lokal, kein Netzwerkzugriff) |

---

## Mögliche Erweiterungen

- **Automatische Ausführung** via Windows Task Scheduler oder systemd-Timer beim Einstecken der SD-Karte
- **E-Mail- oder Desktop-Benachrichtigung** nach erfolgreichem Backup
- **Komprimierung** der Backup-Dateien (z. B. gzip) zur Speicherplatzreduzierung
- **Cloud-Backup** als zusätzliches Ziel (z. B. via rclone-Integration)

---

## Lizenz

MIT License – freie Verwendung, Anpassung und Weitergabe.

---

*Entwickelt als persönliches Werkzeug und Lernprojekt. Feedback und Pull Requests willkommen.*
