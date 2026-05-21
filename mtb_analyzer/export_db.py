import sqlite3
from datetime import datetime


def export_db(race_configs: list, rider_groups: list, output_path: str) -> None:
    """Write all race data to a SQLite database for the frontend SPA."""
    con = sqlite3.connect(output_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

        CREATE TABLE IF NOT EXISTS races (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            slug         TEXT UNIQUE,
            name         TEXT NOT NULL,
            date         TEXT,
            uci_category TEXT,
            category     TEXT
        );

        CREATE TABLE IF NOT EXISTS riders (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id          INTEGER NOT NULL REFERENCES races(id),
            first_name       TEXT,
            last_name        TEXT,
            corrected_name   TEXT,
            country          TEXT,
            birth_year       TEXT,
            start_nr         TEXT,
            uci_id           TEXT,
            uci_rank         INTEGER,
            uci_points       INTEGER,
            team             TEXT,
            category         TEXT,
            match_confidence INTEGER,
            xcodata_slug     TEXT,
            race_name        TEXT
        );

        CREATE TABLE IF NOT EXISTS race_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rider_id    INTEGER NOT NULL REFERENCES riders(id),
            xco_race_id TEXT,
            race_name   TEXT,
            date        TEXT,
            location    TEXT,
            rank        INTEGER,
            time        TEXT,
            cat         TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_riders_race    ON riders(race_id);
        CREATE INDEX IF NOT EXISTS idx_results_rider  ON race_results(rider_id);
    """)

    con.execute("INSERT OR REPLACE INTO meta VALUES ('generated_at', ?)",
                (datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),))

    for race_cfg, riders in zip(race_configs, rider_groups):
        slug = race_cfg.get("output", "").removesuffix(".html")
        cur = con.execute(
            "INSERT OR REPLACE INTO races (slug, name, date, uci_category, category) VALUES (?,?,?,?,?)",
            (slug, race_cfg.get("name", ""), race_cfg.get("date", ""),
             race_cfg.get("uci_category", ""), race_cfg.get("category", "")),
        )
        race_id = cur.lastrowid

        for rider in riders:
            cur2 = con.execute(
                """INSERT INTO riders
                   (race_id, first_name, last_name, corrected_name, country,
                    birth_year, start_nr, uci_id, uci_rank, uci_points,
                    team, category, match_confidence, xcodata_slug, race_name)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (race_id, rider.first_name, rider.last_name,
                 rider.corrected_name, rider.country, rider.birth_year,
                 rider.start_nr, rider.uci_id, rider.uci_rank,
                 rider.uci_points, rider.team, rider.category,
                 rider.match_confidence, rider.xcodata_slug, rider.race_name),
            )
            rider_id = cur2.lastrowid

            for res in rider.race_results:
                con.execute(
                    """INSERT INTO race_results
                       (rider_id, xco_race_id, race_name, date, location, rank, time, cat)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (rider_id, str(res.get("race_id", "")), res.get("race_name", ""),
                     res.get("date", ""), res.get("location", ""),
                     res.get("rank"), res.get("time", ""), res.get("cat", "")),
                )

    con.commit()
    con.close()
