#!/usr/bin/env python3
"""
+======================================================+
|        Nintendo DS Save Backup Tool v2.1             |
|   Sichert .sav Dateien von Flashcard SD-Karten       |
+======================================================+
"""

import os
import sys
import shutil
import hashlib
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path

# Sicherstellen dass stdout/stderr immer UTF-8 verwenden (wichtig auf Windows)
import io as _io
if isinstance(sys.stdout, _io.TextIOWrapper):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if isinstance(sys.stderr, _io.TextIOWrapper):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


# --- Konfiguration ------------------------------------------------------------

DEFAULT_SOURCE_DIR = Path(r"\\Client\D$")
DEFAULT_BACKUP_DIR = Path(r"\\server\share\Backup")

MANIFEST_FILE      = "backup_manifest.json"
LOG_FILE           = "backup_log.txt"
SD_CONFIG_FILE     = "sd_config.json"   # Konfiguration pro SD-Karte (keep_versions etc.)

DEFAULT_KEEP_VERSIONS = 5


# --- Farben für Terminal-Output -----------------------------------------------

class Colors:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    GRAY    = "\033[90m"

def colorize(text: str, color: str) -> str:
    if sys.stdout.isatty():
        return f"{color}{text}{Colors.RESET}"
    return text

def print_header():
    header = (
        "\n+======================================================+\n"
        "|    [*]  Nintendo DS Save Backup Tool  v2.1  [*]     |\n"
        "+======================================================+"
    )
    print(colorize(header, Colors.CYAN))

def print_section(title: str):
    print(f"\n{colorize('-' * 54, Colors.GRAY)}")
    print(colorize(f"  {title}", Colors.BOLD + Colors.BLUE))
    print(colorize('-' * 54, Colors.GRAY))


# --- SHA256-Prüfung -----------------------------------------------------------

def sha256_of_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# --- SD-Karten Identifikation -------------------------------------------------

def get_sd_card_id(source_dir: Path, label: str | None) -> str | None:
    """
    Bestimmt die eindeutige ID der SD-Karte.

    - --label gegeben → schreibt ds_card_id.txt auf die SD (einmalig), gibt Label zurück
    - ds_card_id.txt vorhanden → liest sie aus, gibt ID zurück
    - Weder noch → gibt None zurück (Aufrufer muss abbrechen)
    """
    id_file = source_dir / "ds_card_id.txt"

    if label:
        clean = label.strip().replace(" ", "_")
        # Auf SD-Karte persistieren (nur wenn noch nicht gesetzt oder anders)
        existing = None
        if id_file.exists():
            try:
                existing = id_file.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        if existing != clean:
            try:
                id_file.write_text(clean, encoding="utf-8")
                print(colorize(
                    f"  i  Label '{clean}' auf SD-Karte gespeichert ({id_file})",
                    Colors.CYAN
                ))
            except OSError as e:
                print(colorize(
                    f"  !  Konnte ds_card_id.txt nicht schreiben: {e}\n"
                    f"     Label wird nur fuer diesen Lauf verwendet.",
                    Colors.YELLOW
                ))
        return clean

    # Kein --label → ds_card_id.txt auf SD prüfen
    if id_file.exists():
        try:
            content = id_file.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError as e:
            print(colorize(f"  !  Konnte ds_card_id.txt nicht lesen: {e}", Colors.YELLOW))

    # Nichts gefunden → None signalisiert dem Aufrufer: Abbruch nötig
    return None


def resolve_sd_backup_dir(base_backup_dir: Path, sd_id: str) -> Path:
    return base_backup_dir / sd_id


# --- SD-Konfig (keep_versions pro Spiel) --------------------------------------

def load_sd_config(sd_backup_dir: Path) -> dict:
    """
    Lädt die Konfigurationsdatei dieser SD-Karte.
    Struktur:
    {
      "keep_versions_default": 5,
      "spiele": {
        "Pokemon Platin": { "keep_versions": 10 },
        "Zelda":          { "keep_versions": 3  }
      }
    }
    """
    cfg_path = sd_backup_dir / SD_CONFIG_FILE
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logging.warning("SD-Konfig beschädigt - nutze Standardwerte.")
    return {}

def save_sd_config(sd_backup_dir: Path, config: dict):
    cfg_path = sd_backup_dir / SD_CONFIG_FILE
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def get_keep_versions_for_game(sd_config: dict, game_name: str, global_default: int) -> int:
    """Gibt keep_versions zurück: spiel-spezifisch > SD-Default > globaler Default."""
    spiele = sd_config.get("spiele", {})
    if game_name in spiele:
        return int(spiele[game_name].get("keep_versions", global_default))
    return int(sd_config.get("keep_versions_default", global_default))


# --- Manifest -----------------------------------------------------------------

def load_manifest(sd_backup_dir: Path) -> dict:
    manifest_path = sd_backup_dir / MANIFEST_FILE
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            logging.warning("Manifest beschädigt - wird neu erstellt.")
    return {}

def save_manifest(sd_backup_dir: Path, manifest: dict):
    manifest_path = sd_backup_dir / MANIFEST_FILE
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


# --- Logging einrichten -------------------------------------------------------

def setup_logging(sd_backup_dir: Path):
    log_path = sd_backup_dir / LOG_FILE
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.getLogger().handlers[1].setLevel(logging.WARNING)


# --- Hilfsfunktionen ----------------------------------------------------------

def find_sav_files(source_dir: Path) -> list[Path]:
    return sorted(source_dir.rglob("*.sav"))

def human_readable_size(size_bytes: float) -> str:
    for unit in ["B", "KB", "MB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} GB"

def timestamp_str() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


# --- Backup-Logik -------------------------------------------------------------

def backup_saves(
    source_dir: Path,
    base_backup_dir: Path,
    sd_id: str,
    dry_run: bool = False,
    global_keep_versions: int = DEFAULT_KEEP_VERSIONS,
) -> dict:
    """
    Hauptfunktion: Scannt source_dir nach .sav Dateien und sichert geänderte.
    Backup-Struktur: base_backup_dir / <SD-Label> / <Spielname> / <Spielname>_<Timestamp>.sav
    """
    sd_backup_dir = resolve_sd_backup_dir(base_backup_dir, sd_id)
    sd_backup_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(sd_backup_dir)

    manifest  = load_manifest(sd_backup_dir)
    sd_config = load_sd_config(sd_backup_dir)

    # Konfig-Datei beim ersten Lauf anlegen
    if not (sd_backup_dir / SD_CONFIG_FILE).exists():
        default_config = {
            "_hinweis": (
                "keep_versions_default gilt fuer alle Spiele dieser SD-Karte. "
                "Unter 'spiele' kann pro Spiel ein eigener Wert gesetzt werden."
            ),
            "keep_versions_default": global_keep_versions,
            "spiele": {}
        }
        save_sd_config(sd_backup_dir, default_config)
        print(colorize(
            f"  i  Neue Konfig angelegt: {sd_backup_dir / SD_CONFIG_FILE}",
            Colors.CYAN
        ))

    sav_files = find_sav_files(source_dir)

    stats = {
        "gefunden":     len(sav_files),
        "gesichert":    0,
        "unveraendert": 0,
        "fehler":       0,
        "neu":          0,
    }

    print_section(f"SD-Karte: {colorize(sd_id, Colors.YELLOW)}  |  Scanne: {source_dir}")
    print(f"  {colorize(str(len(sav_files)), Colors.BOLD)} .sav Datei(en) gefunden\n")

    if not sav_files:
        print(colorize("  Keine .sav Dateien gefunden.", Colors.YELLOW))
        return stats

    for sav_path in sav_files:
        game_name = sav_path.stem
        # rel_path als Manifest-Key immer lowercase → verhindert Doppeleinträge bei
        # Groß-/Kleinschreibungswechsel des Dateinamens (z.B. nach Umbenennung auf der SD)
        rel_path  = str(sav_path.relative_to(source_dir)).lower()
        keep_ver  = get_keep_versions_for_game(sd_config, game_name, global_keep_versions)

        try:
            current_hash = sha256_of_file(sav_path)
            file_size    = sav_path.stat().st_size
        except (OSError, PermissionError) as e:
            print(colorize(f"  x Fehler beim Lesen: {rel_path} -> {e}", Colors.RED))
            logging.error("Lesefehler: %s - %s", rel_path, e)
            stats["fehler"] += 1
            continue

        prev      = manifest.get(rel_path, {})
        prev_hash = prev.get("sha256")
        is_new    = prev_hash is None

        size_str = colorize(human_readable_size(file_size), Colors.GRAY)
        name_str = colorize(game_name, Colors.BOLD)
        ver_str  = colorize(f"(max. {keep_ver} Versionen)", Colors.GRAY)

        if current_hash == prev_hash:
            print(f"  {colorize('o', Colors.GRAY)} {name_str}  {size_str}")
            print(f"    {colorize('Unveraendert - kein Backup noetig', Colors.GRAY)}")
            stats["unveraendert"] += 1
            continue

        label = colorize("NEU", Colors.GREEN) if is_new else colorize("GEAENDERT", Colors.YELLOW)
        print(f"  {colorize('>', Colors.CYAN)} {name_str}  {size_str}  [{label}]  {ver_str}")

        if not dry_run:
            game_backup_dir = sd_backup_dir / game_name
            game_backup_dir.mkdir(parents=True, exist_ok=True)

            ts            = timestamp_str()
            dest_filename = f"{game_name}_{ts}.sav"
            dest_path     = game_backup_dir / dest_filename

            try:
                shutil.copy2(sav_path, dest_path)

                dest_hash = sha256_of_file(dest_path)
                if dest_hash != current_hash:
                    raise IOError("Hash nach Kopie stimmt nicht ueberein!")

                print(f"    {colorize('[OK] Gesichert:', Colors.GREEN)} {dest_filename}")
                print(f"    SHA256: {colorize(current_hash[:16] + '...', Colors.GRAY)}")
                logging.info("Gesichert: %s -> %s (SHA256: %s)", rel_path, dest_path, current_hash)

                _cleanup_old_versions(game_backup_dir, game_name, keep_ver)

                manifest[rel_path] = {
                    "sha256":           current_hash,
                    "letzte_sicherung": ts,
                    "spiel":            game_name,
                    "groesse_bytes":    file_size,
                    "keep_versions":    keep_ver,
                    "backups":          prev.get("backups", []) + [dest_filename],
                }

                stats["gesichert"] += 1
                if is_new:
                    stats["neu"] += 1

            except (OSError, IOError) as e:
                print(colorize(f"    x Backup-Fehler: {e}", Colors.RED))
                logging.error("Backup-Fehler: %s - %s", rel_path, e)
                stats["fehler"] += 1
        else:
            print(f"    {colorize('[DRY-RUN] Wuerde sichern:', Colors.MAGENTA)} {game_name}_{timestamp_str()}.sav")
            stats["gesichert"] += 1
            if is_new:
                stats["neu"] += 1

    if not dry_run:
        save_manifest(sd_backup_dir, manifest)

    return stats


def _cleanup_old_versions(game_backup_dir: Path, game_name: str, keep: int):
    # _vor_restore-Dateien gehören nicht zur regulären Versions-Rotation
    versions  = sorted(
        v for v in game_backup_dir.glob(f"{game_name}_*.sav")
        if "_vor_restore" not in v.name
    )
    to_delete = versions[:-keep] if len(versions) > keep else []
    for old in to_delete:
        try:
            old.unlink()
            logging.info("Alte Version entfernt: %s", old.name)
        except OSError as e:
            logging.warning("Konnte alte Version nicht loeschen: %s - %s", old.name, e)


# --- Zusammenfassung ----------------------------------------------------------

def print_summary(stats: dict, sd_backup_dir: Path, dry_run: bool):
    print_section("Zusammenfassung")

    rows = [
        ("Gefundene .sav Dateien",     str(stats["gefunden"]),                 Colors.CYAN),
        ("Neu gesichert",              str(stats["neu"]),                      Colors.GREEN),
        ("Aktualisiert",               str(stats["gesichert"] - stats["neu"]), Colors.YELLOW),
        ("Unveraendert (uebersprungen)", str(stats["unveraendert"]),            Colors.GRAY),
        ("Fehler",                     str(stats["fehler"]),                   Colors.RED),
    ]

    for label, value, color in rows:
        print(f"  {label:<34} {colorize(value, color + Colors.BOLD)}")

    if dry_run:
        print(colorize("\n  [DRY-RUN] Keine Dateien wurden tatsaechlich gesichert.", Colors.MAGENTA))
    else:
        print(f"\n  Backup-Verzeichnis : {colorize(str(sd_backup_dir), Colors.CYAN)}")
        print(f"  Konfig-Datei       : {colorize(str(sd_backup_dir / SD_CONFIG_FILE), Colors.CYAN)}")
        print(f"  Log-Datei          : {colorize(str(sd_backup_dir / LOG_FILE), Colors.CYAN)}")

    if stats["fehler"] > 0:
        print(colorize(f"\n  ! {stats['fehler']} Fehler aufgetreten. Bitte Log pruefen.", Colors.RED))
    elif stats["gesichert"] == 0:
        print(colorize("\n  [OK]  Alle Saves sind aktuell - nichts zu tun!", Colors.GREEN))
    else:
        print(colorize("\n  [OK]  Backup abgeschlossen!", Colors.GREEN))


# --- Listbefehl ---------------------------------------------------------------

def list_backups(base_backup_dir: Path, sd_filter: str | None = None):
    """Zeigt alle SD-Karten und ihre gesicherten Saves."""
    print_section("Vorhandene Backups")

    if not base_backup_dir.exists():
        print(colorize("  Kein Backup-Verzeichnis gefunden.", Colors.YELLOW))
        return

    sd_dirs = [d for d in sorted(base_backup_dir.iterdir()) if d.is_dir()]
    if not sd_dirs:
        print(colorize("  Keine Backups gefunden.", Colors.YELLOW))
        return

    for sd_dir in sd_dirs:
        if sd_filter and sd_dir.name != sd_filter:
            continue

        manifest  = load_manifest(sd_dir)
        sd_config = load_sd_config(sd_dir)

        print(f"\n  SD-Karte: {colorize(sd_dir.name, Colors.YELLOW + Colors.BOLD)}")

        if not manifest:
            print(colorize("     (noch keine Saves gesichert)", Colors.GRAY))
            continue

        for rel_path, info in sorted(manifest.items()):
            name       = info.get("spiel", Path(rel_path).stem)
            ts         = info.get("letzte_sicherung", "?")
            size       = human_readable_size(info.get("groesse_bytes", 0))
            hash_short = info.get("sha256", "?")[:16] + "..."
            keep_ver   = get_keep_versions_for_game(sd_config, name, DEFAULT_KEEP_VERSIONS)
            # Echte Dateien auf Disk zählen (exkl. _vor_restore) statt manifest-Liste
            real_versions = list_versions_for_game(sd_dir, name)
            latest = real_versions[-1].name if real_versions else "-"

            print(f"\n     {colorize(name, Colors.BOLD)}")
            print(f"        Letzte Sicherung  : {colorize(ts, Colors.CYAN)}")
            print(f"        Dateigroesse      : {colorize(size, Colors.GRAY)}")
            print(f"        SHA256            : {colorize(hash_short, Colors.GRAY)}")
            print(f"        Versionen ({len(real_versions):>2}/{keep_ver:<2}) : {colorize(latest, Colors.GREEN)}")


# --- keep-versions Konfig bearbeiten ------------------------------------------

def set_keep_versions(
    base_backup_dir: Path,
    sd_id: str,
    game_name: str | None,
    value: int,
):
    """Setzt keep_versions für ein einzelnes Spiel oder als SD-weiten Default."""
    sd_backup_dir = resolve_sd_backup_dir(base_backup_dir, sd_id)
    sd_backup_dir.mkdir(parents=True, exist_ok=True)
    config = load_sd_config(sd_backup_dir)

    if game_name:
        if "spiele" not in config:
            config["spiele"] = {}
        config["spiele"][game_name] = {"keep_versions": value}
        print(colorize(
            f"  [OK] '{game_name}' auf SD '{sd_id}': keep_versions = {value}",
            Colors.GREEN
        ))
    else:
        config["keep_versions_default"] = value
        print(colorize(
            f"  [OK] SD-Default fuer '{sd_id}': keep_versions = {value}",
            Colors.GREEN
        ))

    save_sd_config(sd_backup_dir, config)



# --- Restore / Revert ---------------------------------------------------------

def list_versions_for_game(sd_backup_dir: Path, game_name: str) -> list[Path]:
    """Gibt alle regulären Backup-Versionen eines Spiels zurück (ohne _vor_restore)."""
    game_dir = sd_backup_dir / game_name
    if not game_dir.exists():
        return []
    return sorted(
        v for v in game_dir.glob(f"{game_name}_*.sav")
        if "_vor_restore" not in v.name
    )


def restore_save(
    source_dir: Path,
    base_backup_dir: Path,
    sd_id: str,
    game_name: str,
    version_index: int | None,
    dry_run: bool = False,
):
    """
    Stellt eine gesicherte .sav-Version eines Spiels auf die SD-Karte zurück.

    Ablauf:
      1. Backup-Versionen des Spiels auflisten
      2. Zielversion bestimmen (per Index oder interaktiver Auswahl)
      3. Aktuelle .sav auf SD als Sicherheitskopie im Backup ablegen
      4. Gewählte Version auf die SD kopieren
      5. Hash der wiederhergestellten Datei verifizieren
      6. Manifest aktualisieren
    """
    sd_backup_dir = resolve_sd_backup_dir(base_backup_dir, sd_id)
    setup_logging(sd_backup_dir)

    print_section(f"Restore  |  SD: {colorize(sd_id, Colors.YELLOW)}  |  Spiel: {colorize(game_name, Colors.BOLD)}")

    versions = list_versions_for_game(sd_backup_dir, game_name)

    if not versions:
        print(colorize(f"  x  Keine Backup-Versionen fuer '{game_name}' auf SD '{sd_id}' gefunden.", Colors.RED))
        print(colorize(f"     Backup-Pfad geprueft: {sd_backup_dir / game_name}", Colors.GRAY))
        sys.exit(1)

    # -- Versionen anzeigen --
    print(f"\n  Verfuegbare Versionen fuer {colorize(game_name, Colors.BOLD)}:\n")
    for i, v in enumerate(versions):
        marker = colorize("(neueste)", Colors.GREEN) if i == len(versions) - 1 else ""
        size   = human_readable_size(v.stat().st_size)
        print(f"    [{colorize(str(i), Colors.CYAN + Colors.BOLD)}]  {v.name}  {colorize(size, Colors.GRAY)}  {marker}")

    # -- Zielversion bestimmen --
    if version_index is not None:
        if version_index < 0 or version_index >= len(versions):
            print(colorize(
                f"\n  x  Index {version_index} ungueltig. Gueltig: 0 bis {len(versions) - 1}",
                Colors.RED
            ))
            sys.exit(1)
        chosen = versions[version_index]
    else:
        # Interaktive Auswahl
        print()
        while True:
            try:
                raw = input(colorize(
                    f"  Welche Version wiederherstellen? [0-{len(versions)-1}]: ",
                    Colors.YELLOW
                ))
                idx = int(raw.strip())
                if 0 <= idx < len(versions):
                    chosen = versions[idx]
                    break
                print(colorize(f"  Bitte eine Zahl zwischen 0 und {len(versions)-1} eingeben.", Colors.RED))
            except (ValueError, EOFError):
                print(colorize("  Ungueltige Eingabe. Abbruch.", Colors.RED))
                sys.exit(1)

    print(f"\nGewaehlte Version : {colorize(chosen.name, Colors.CYAN)}")

    # -- Zieldatei auf SD ermitteln --
    # Primär: rel_path aus dem Manifest nutzen - enthält den originalen Pfad inkl.
    # korrektem Dateinamen (z.B. "Spielname.nds.sav") und Unterordner.
    manifest  = load_manifest(sd_backup_dir)
    rel_path  = None
    for key in manifest:
        if manifest[key].get("spiel") == game_name:
            rel_path = key
            break
    # Fallback: Schlüssel endet auf game_name.sav (ältere Einträge ohne "spiel"-Feld)
    if rel_path is None:
        for key in manifest:
            if Path(key).stem == game_name or key == f"{game_name}.sav":
                rel_path = key
                break

    if rel_path is not None:
        sav_target = source_dir / rel_path
        sav_target.parent.mkdir(parents=True, exist_ok=True)
        if not sav_target.exists():
            print(colorize(
                f"  i  Originaldatei nicht mehr auf SD vorhanden - wird neu angelegt:\n"
                f"     {sav_target}",
                Colors.YELLOW
            ))
    else:
        # Manifest kennt das Spiel nicht → rekursiv suchen
        sav_candidates = list(source_dir.rglob(f"*{game_name}*.sav"))
        if sav_candidates:
            sav_target = sav_candidates[0]
            if len(sav_candidates) > 1:
                print(colorize(
                    f"  !  Mehrere passende .sav-Dateien gefunden, verwende: {sav_target}",
                    Colors.YELLOW
                ))
        else:
            sav_target = source_dir / f"{game_name}.sav"
            print(colorize(
                f"  !  Kein Manifest-Eintrag und keine .sav auf SD gefunden.\n"
                f"     Lege Datei ab unter: {sav_target}\n"
                f"     Bitte manuell in den richtigen Spielordner verschieben!",
                Colors.YELLOW
            ))

    # -- Bestätigung --
    print()
    print(colorize("  +-------------------------------------------------+", Colors.YELLOW))
    print(colorize("  |  ACHTUNG: Diese Aktion ueberschreibt den        |", Colors.YELLOW))
    print(colorize("  |  aktuellen Spielstand auf der SD-Karte!         |", Colors.YELLOW))
    print(colorize("  +-------------------------------------------------+", Colors.YELLOW))
    print(f"  Ziel auf SD : {colorize(str(sav_target), Colors.CYAN)}")
    print(f"  Quelle      : {colorize(chosen.name, Colors.CYAN)}")

    if dry_run:
        print(colorize("\n  [DRY-RUN] Kein Schreibvorgang - Abbruch.", Colors.MAGENTA))
        return

    print()
    try:
        confirm = input(colorize("  Wirklich wiederherstellen? [j/N]: ", Colors.RED + Colors.BOLD))
    except EOFError:
        confirm = ""

    if confirm.strip().lower() not in ("j", "ja", "y", "yes"):
        print(colorize("  Abgebrochen.", Colors.GRAY))
        return

    # -- Schritt 1: Aktuelle SD-Datei als Sicherheitskopie sichern --
    if sav_target.exists():
        print()
        print(colorize("  Sichere aktuellen Spielstand vor dem Restore...", Colors.GRAY))
        ts               = timestamp_str()
        safety_dir       = sd_backup_dir / game_name
        safety_dir.mkdir(parents=True, exist_ok=True)
        safety_filename  = f"{game_name}_{ts}_vor_restore.sav"
        safety_path      = safety_dir / safety_filename
        try:
            shutil.copy2(sav_target, safety_path)
            safety_hash = sha256_of_file(safety_path)
            print(colorize(f"  [OK] Sicherheitskopie: {safety_filename}", Colors.GRAY))
            logging.info("Sicherheitskopie vor Restore: %s (SHA256: %s)", safety_path, safety_hash)
        except OSError as e:
            print(colorize(f"  !  Sicherheitskopie fehlgeschlagen: {e}", Colors.YELLOW))
            print(colorize("     Trotzdem fortfahren? [j/N]: ", Colors.RED), end="")
            try:
                c2 = input()
            except EOFError:
                c2 = ""
            if c2.strip().lower() not in ("j", "ja", "y", "yes"):
                print(colorize("  Abgebrochen.", Colors.GRAY))
                return

    # -- Schritt 2: Gewählte Version auf SD kopieren --
    restore_hash_src = sha256_of_file(chosen)
    try:
        shutil.copy2(chosen, sav_target)
    except OSError as e:
        print(colorize(f"\n  x  Restore fehlgeschlagen beim Kopieren: {e}", Colors.RED))
        logging.error("Restore fehlgeschlagen: %s -> %s: %s", chosen, sav_target, e)
        sys.exit(1)

    # -- Schritt 3: Integrität der wiederhergestellten Datei prüfen --
    restore_hash_dst = sha256_of_file(sav_target)
    if restore_hash_dst != restore_hash_src:
        print(colorize(
            "\n  x  Hash-Abweichung nach Restore! Die Datei auf der SD koennte beschaedigt sein.",
            Colors.RED
        ))
        logging.error(
            "Hash-Abweichung nach Restore: erwartet %s, erhalten %s",
            restore_hash_src, restore_hash_dst
        )
        sys.exit(1)

    print(colorize(f"\n  [OK]  Restore erfolgreich!", Colors.GREEN))
    print(f"     Datei    : {colorize(str(sav_target), Colors.CYAN)}")
    print(f"     Version  : {colorize(chosen.name, Colors.CYAN)}")
    print(f"     SHA256   : {colorize(restore_hash_dst[:16] + '...', Colors.GRAY)}")
    logging.info("Restore: %s -> %s (SHA256: %s)", chosen, sav_target, restore_hash_dst)

    # -- Schritt 4: Manifest aktualisieren --
    # manifest und rel_path wurden bereits oben beim Ermitteln des Zielpfads gesetzt
    if rel_path and rel_path in manifest:
        manifest[rel_path]["sha256"]           = restore_hash_dst
        manifest[rel_path]["letzte_sicherung"] = f"{timestamp_str()}_restore"
        save_manifest(sd_backup_dir, manifest)
        print(colorize("     Manifest aktualisiert.", Colors.GRAY))


# --- CLI ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Nintendo DS Save Backup Tool v2.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r"""
Beispiele:
  # Normales Backup (D:\ → automatisch "Karte_D")
  python ds_save_backup.py

  # Eigenes Label fuer die SD-Karte
  python ds_save_backup.py --label "Hauptkarte"

  # Zweite SD-Karte (anderes Laufwerk, eigenes Label)
  python ds_save_backup.py --source E:\ --label "Zweitkarte"

  # Dry-Run (nichts schreiben, nur anzeigen)
  python ds_save_backup.py --dry-run

  # Alle Backups aller SD-Karten auflisten
  python ds_save_backup.py --list

  # Nur eine bestimmte SD-Karte auflisten
  python ds_save_backup.py --list --label "Hauptkarte"

  # keep-versions SD-weit setzen (alle Spiele auf dieser Karte)
  python ds_save_backup.py --set-keep --sd "Karte_D" --versions 8

  # keep-versions fuer ein bestimmtes Spiel setzen
  python ds_save_backup.py --set-keep --sd "Karte_D" --game "Pokemon Platin" --versions 15

  # Spielstand interaktiv zuruecksetzen (zeigt alle Versionen zur Auswahl)
  python ds_save_backup.py --restore --sd "Hauptkarte" --game "Pokemon Platin"

  # Spielstand direkt auf eine bestimmte Version zuruecksetzen (Index 0 = aelteste)
  python ds_save_backup.py --restore --sd "Hauptkarte" --game "Pokemon Platin" --version-index 2

  # Restore simulieren ohne zu schreiben
  python ds_save_backup.py --restore --sd "Hauptkarte" --game "Pokemon Platin" --dry-run
        """
    )

    parser.add_argument("--source",
                        type=Path, default=DEFAULT_SOURCE_DIR, metavar="PFAD",
                        help="Quellpfad der SD-Karte (Standard: D:\\)")
    parser.add_argument("--backup-dir",
                        type=Path, default=DEFAULT_BACKUP_DIR, metavar="PFAD",
                        help="Basis-Backup-Verzeichnis")
    parser.add_argument("--label",
                        type=str, default=None, metavar="NAME",
                        help="Name/Label der SD-Karte (wird als Unterordner verwendet)")
    parser.add_argument("--dry-run",
                        action="store_true",
                        help="Simuliert ohne zu schreiben")
    parser.add_argument("--keep-versions",
                        type=int, default=DEFAULT_KEEP_VERSIONS, metavar="N",
                        help=f"Globaler Fallback fuer Versionszahl (Standard: {DEFAULT_KEEP_VERSIONS})")
    parser.add_argument("--list",
                        action="store_true",
                        help="Zeigt alle vorhandenen Backups an")

    # Unterbefehl: keep-versions konfigurieren
    parser.add_argument("--set-keep",
                        action="store_true",
                        help="Setzt keep_versions (benoetigt --sd und --versions)")
    parser.add_argument("--sd",
                        type=str, default=None, metavar="NAME",
                        help="SD-Karten-Label fuer --set-keep")
    parser.add_argument("--game",
                        type=str, default=None, metavar="SPIEL",
                        help="Spielname fuer --set-keep (ohne: SD-Default wird gesetzt)")
    parser.add_argument("--versions",
                        type=int, default=None, metavar="N",
                        help="Neue Versionszahl fuer --set-keep")

    # Unterbefehl: Restore
    parser.add_argument("--restore",
                        action="store_true",
                        help="Stellt eine Backup-Version auf die SD-Karte zurueck (benoetigt --sd und --game)")
    parser.add_argument("--version-index",
                        type=int, default=None, metavar="N",
                        help="Index der Backup-Version fuer --restore (0 = aelteste). Ohne Angabe: interaktive Auswahl.")

    args = parser.parse_args()

    print_header()

    # -- keep-versions setzen --
    if args.set_keep:
        if not args.sd or args.versions is None:
            parser.error("--set-keep benoetigt --sd NAME und --versions N")
        set_keep_versions(args.backup_dir, args.sd, args.game, args.versions)
        return

    # -- Restore --
    if args.restore:
        if not args.sd or not args.game:
            parser.error("--restore benoetigt --sd NAME und --game SPIELNAME")
        if not args.source.exists():
            print(colorize(f"\n  x Quellverzeichnis nicht gefunden: {args.source}", Colors.RED))
            print(colorize("    Ist die SD-Karte eingelegt?", Colors.YELLOW))
            sys.exit(1)
        restore_save(
            source_dir=args.source,
            base_backup_dir=args.backup_dir,
            sd_id=args.sd,
            game_name=args.game,
            version_index=args.version_index,
            dry_run=args.dry_run,
        )
        return

    # -- Backups auflisten --
    if args.list:
        list_backups(args.backup_dir, sd_filter=args.label)
        return

    # -- Normaler Backup-Lauf --
    source_dir = args.source

    if not source_dir.exists():
        print(colorize(f"\n  x Quellverzeichnis nicht gefunden: {source_dir}", Colors.RED))
        print(colorize("    Ist die SD-Karte eingelegt?", Colors.YELLOW))
        sys.exit(1)

    sd_id = get_sd_card_id(source_dir, args.label)

    if sd_id is None:
        print(colorize(
            "\n  x  Diese SD-Karte hat noch kein Label!\n",
            Colors.RED
        ))
        print(
            "  Beim ersten Einstecken einer neuen Karte einmalig vergeben:\n"
            f"    {colorize('python ds_save_backup.py --label \"MeinKartenName\"', Colors.CYAN)}\n"
            "\n"
            "  Das Label wird als ds_card_id.txt auf der SD gespeichert\n"
            "  und kuenftig automatisch erkannt - einmalige Eingabe genuegt.\n"
            "\n"
            "  Abbruch, um versehentliche Doppelsicherungen zu verhindern."
        )
        sys.exit(1)

    sd_backup_dir = resolve_sd_backup_dir(args.backup_dir, sd_id)

    print(f"\n  Quelle      : {colorize(str(source_dir), Colors.CYAN)}")
    print(f"  SD-Label    : {colorize(sd_id, Colors.YELLOW)}")
    print(f"  Backup-Pfad : {colorize(str(sd_backup_dir), Colors.CYAN)}")
    if args.dry_run:
        print(f"  Modus       : {colorize('DRY-RUN (kein Schreiben)', Colors.MAGENTA)}")

    stats = backup_saves(
        source_dir=source_dir,
        base_backup_dir=args.backup_dir,
        sd_id=sd_id,
        dry_run=args.dry_run,
        global_keep_versions=args.keep_versions,
    )

    print_summary(stats, sd_backup_dir, args.dry_run)


if __name__ == "__main__":
    main()
