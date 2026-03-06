#!/usr/bin/env python3
"""
DS Save Backup – Web-GUI Server
Startet einen lokalen Webserver und öffnet die GUI im Browser.
Benötigt: pip install flask
"""

import json
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from datetime import datetime

try:
    from flask import Flask, jsonify, request, send_from_directory, abort
except ImportError:
    print("Flask nicht gefunden. Bitte installieren: pip install flask")
    sys.exit(1)

# ── Pfade – hier anpassen ──────────────────────────────────────────────────────
DEFAULT_SOURCE_DIR = Path(r"\\Client\D$")
DEFAULT_BACKUP_DIR = Path(r"\\server\share\Backup")
BACKUP_SCRIPT      = Path(__file__).parent / "ds_save_backup.py"
GUI_HTML           = Path(__file__).parent / "ds_backup_gui.html"

MANIFEST_FILE  = "backup_manifest.json"
SD_CONFIG_FILE = "sd_config.json"
LOG_FILE       = "backup_log.txt"
DEFAULT_KEEP   = 5
# ──────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    """Lädt eine JSON-Datei und gibt immer ein dict zurück.
    Falls die Datei nicht existiert, beschädigt ist oder kein dict enthält,
    wird ein leeres dict zurückgegeben."""
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}

def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def human_size(b: float) -> str:
    for unit in ["B", "KB", "MB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} GB"

def real_versions(sd_backup_dir: Path, game_name: str) -> list[str]:
    """Gibt reguläre Backup-Dateien zurück (ohne _vor_restore)."""
    game_dir = sd_backup_dir / game_name
    if not game_dir.exists():
        return []
    files = sorted(
        v.name for v in game_dir.glob(f"{game_name}_*.sav")
        if "_vor_restore" not in v.name
    )
    return files

def restore_versions(sd_backup_dir: Path, game_name: str) -> list[str]:
    """Gibt nur _vor_restore-Dateien zurück."""
    game_dir = sd_backup_dir / game_name
    if not game_dir.exists():
        return []
    return sorted(v.name for v in game_dir.glob(f"{game_name}_*_vor_restore.sav"))

def format_ts(ts: str) -> str:
    """Formatiert einen Timestamp-String lesbar."""
    try:
        base = ts.replace("_restore", "").replace("_vor_restore", "")
        dt = datetime.strptime(base, "%Y%m%d_%H%M%S")
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return ts

def get_keep_for_game(config: dict, game_name: str) -> int:
    spiele = config.get("spiele", {})
    if game_name in spiele:
        return int(spiele[game_name].get("keep_versions", DEFAULT_KEEP))
    return int(config.get("keep_versions_default", DEFAULT_KEEP))


# ─── API ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(GUI_HTML.parent), GUI_HTML.name)


@app.route("/api/config")
def api_config():
    # SD-Label aus ds_card_id.txt lesen falls vorhanden
    sd_label = None
    id_file = DEFAULT_SOURCE_DIR / "ds_card_id.txt"
    if id_file.exists():
        try:
            sd_label = id_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
    return jsonify({
        "backup_dir":     str(DEFAULT_BACKUP_DIR),
        "source_dir":     str(DEFAULT_SOURCE_DIR),
        "sd_card_present": DEFAULT_SOURCE_DIR.exists(),
        "sd_label":       sd_label,
    })


@app.route("/api/cards")
def api_cards():
    """Alle SD-Karten mit Spielen und Versionen."""
    if not DEFAULT_BACKUP_DIR.exists():
        return jsonify([])

    cards = []
    for sd_dir in sorted(DEFAULT_BACKUP_DIR.iterdir()):
        if not sd_dir.is_dir():
            continue
        manifest = load_json(sd_dir / MANIFEST_FILE)
        config   = load_json(sd_dir / SD_CONFIG_FILE)

        games = []
        for rel_path, info in sorted(manifest.items()):
            game_name  = info.get("spiel", Path(rel_path).stem)
            versions   = real_versions(sd_dir, game_name)
            restores   = restore_versions(sd_dir, game_name)
            keep       = get_keep_for_game(config, game_name)
            ts_raw     = info.get("letzte_sicherung", "")

            games.append({
                "name":           game_name,
                "rel_path":       rel_path,
                "sha256":         info.get("sha256", ""),
                "size":           human_size(info.get("groesse_bytes", 0)),
                "size_bytes":     info.get("groesse_bytes", 0),
                "last_backup":    format_ts(ts_raw),
                "last_backup_raw": ts_raw,
                "versions":       versions,
                "version_count":  len(versions),
                "restore_saves":  restores,
                "keep_versions":  keep,
            })

        # Log-Größe
        log_path = sd_dir / LOG_FILE
        log_size = human_size(log_path.stat().st_size) if log_path.exists() else "-"

        cards.append({
            "id":         sd_dir.name,
            "games":      games,
            "game_count": len(games),
            "log_size":   log_size,
            "keep_default": int(config.get("keep_versions_default", DEFAULT_KEEP)),
        })

    return jsonify(cards)


@app.route("/api/log/<sd_id>")
def api_log(sd_id: str):
    """Gibt die letzten N Zeilen des Logs zurück."""
    sd_dir   = DEFAULT_BACKUP_DIR / sd_id
    log_path = sd_dir / LOG_FILE
    if not log_path.exists():
        return jsonify({"lines": []})
    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return jsonify({"lines": [l.rstrip() for l in lines[-200:]]})


@app.route("/api/backup", methods=["POST"])
def api_backup():
    """Startet einen Backup-Lauf."""
    data    = request.json or {}
    dry_run = data.get("dry_run", False)

    if not DEFAULT_SOURCE_DIR.exists():
        return jsonify({"ok": False, "error": "SD-Karte nicht gefunden."}), 400

    cmd = [sys.executable, str(BACKUP_SCRIPT)]
    if dry_run:
        cmd.append("--dry-run")

    import os as _os
    env = _os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8:replace"
    env["PYTHONUTF8"] = "1"

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace", env=env
        )
        output = result.stdout + result.stderr
        return jsonify({"ok": result.returncode == 0, "output": output})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Timeout nach 120s."}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/restore", methods=["POST"])
def api_restore():
    """Stellt eine bestimmte Backup-Version auf die SD zurück."""
    data       = request.json or {}
    sd_id      = data.get("sd_id", "")
    game_name  = data.get("game_name", "")
    version    = data.get("version", "")

    if not all([sd_id, game_name, version]):
        return jsonify({"ok": False, "error": "sd_id, game_name und version erforderlich."}), 400

    sd_dir       = DEFAULT_BACKUP_DIR / sd_id
    manifest     = load_json(sd_dir / MANIFEST_FILE)
    source_file  = sd_dir / game_name / version

    if not source_file.exists():
        return jsonify({"ok": False, "error": f"Backup-Datei nicht gefunden: {source_file}"}), 404

    # rel_path aus Manifest ermitteln
    rel_path = None
    for key, info in manifest.items():
        if info.get("spiel") == game_name:
            rel_path = key
            break
    if rel_path is None:
        for key in manifest:
            if Path(key).stem == game_name:
                rel_path = key
                break

    if rel_path is None:
        return jsonify({"ok": False, "error": f"Kein Manifest-Eintrag für '{game_name}'."}), 404

    target = DEFAULT_SOURCE_DIR / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)

    # Sicherheitskopie
    if target.exists():
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_name = f"{game_name}_{ts}_vor_restore.sav"
        safety_path = sd_dir / game_name / safety_name
        try:
            shutil.copy2(target, safety_path)
        except OSError as e:
            return jsonify({"ok": False, "error": f"Sicherheitskopie fehlgeschlagen: {e}"}), 500

    # Restore
    try:
        shutil.copy2(source_file, target)
    except OSError as e:
        return jsonify({"ok": False, "error": f"Restore fehlgeschlagen: {e}"}), 500

    # Manifest aktualisieren
    if rel_path in manifest:
        manifest[rel_path]["letzte_sicherung"] = datetime.now().strftime("%Y%m%d_%H%M%S") + "_restore"
        save_json(sd_dir / MANIFEST_FILE, manifest)

    return jsonify({"ok": True, "target": str(target)})


@app.route("/api/set_keep", methods=["POST"])
def api_set_keep():
    """Setzt keep_versions für ein Spiel oder als SD-Default."""
    data      = request.json or {}
    sd_id     = data.get("sd_id", "")
    game_name = data.get("game_name")   # None = SD-Default
    value     = data.get("value")

    if not sd_id or value is None:
        return jsonify({"ok": False, "error": "sd_id und value erforderlich."}), 400

    sd_dir     = DEFAULT_BACKUP_DIR / sd_id
    sd_dir.mkdir(parents=True, exist_ok=True)
    config     = load_json(sd_dir / SD_CONFIG_FILE) or {}

    if game_name:
        config.setdefault("spiele", {})[game_name] = {"keep_versions": int(value)}
    else:
        config["keep_versions_default"] = int(value)

    save_json(sd_dir / SD_CONFIG_FILE, config)
    return jsonify({"ok": True})


# ─── Start ────────────────────────────────────────────────────────────────────

def open_browser():
    import time
    time.sleep(0.8)
    webbrowser.open("http://127.0.0.1:5042")

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════╗")
    print("║   🎮  DS Save Backup – Web GUI  v2.1            ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"\n  Backup-Verzeichnis : {DEFAULT_BACKUP_DIR}")
    print(f"  SD-Karte           : {DEFAULT_SOURCE_DIR}")
    print(f"\n  GUI: http://127.0.0.1:5042")
    print("  Beenden: Strg+C\n")
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=5042, debug=False)
