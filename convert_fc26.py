import csv

input_file = "fc26_players_raw.csv"
output_file = "fc26_players_mgl.csv"

POSITION_MAP = {
    "GK": "GK",
    "CB": "CB",
    "LB": "LB",
    "RB": "RB",
    "LWB": "LWB",
    "RWB": "RWB",
    "CDM": "CDM",
    "LDM": "CDM",
    "RDM": "CDM",
    "CM": "CM",
    "LCM": "CM",
    "RCM": "CM",
    "CAM": "CAM",
    "LAM": "CAM",
    "RAM": "CAM",
    "LM": "LM",
    "RM": "RM",
    "LW": "LW",
    "RW": "RW",
    "LF": "CF",
    "RF": "CF",
    "CF": "CF",
    "ST": "ST",
    "LS": "ST",
    "RS": "ST",
}

def clean_number(value):
    if not value:
        return 0
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return 0

with open(input_file, "r", encoding="utf-8-sig", newline="") as infile:
    reader = csv.DictReader(infile)

    with open(output_file, "w", encoding="utf-8", newline="") as outfile:
        fieldnames = [
            "fc27_id",
            "name",
            "fc27_club",
            "nationality",
            "position",
            "overall",
            "pace",
            "shooting",
            "passing",
            "dribbling",
            "defending",
            "physical",
        ]

        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()

        count = 0

        for row in reader:
            positions = (row.get("player_positions") or "").split(",")

            primary_position = ""
            for pos in positions:
                pos = pos.strip().upper()
                if pos in POSITION_MAP:
                    primary_position = POSITION_MAP[pos]
                    break

            writer.writerow({
                "fc27_id": str(row.get("player_id", "")).strip(),
                "name": (row.get("long_name") or row.get("short_name") or "").strip(),
                "fc27_club": (row.get("club_name") or "").strip(),
                "nationality": (row.get("nationality_name") or "").strip(),
                "position": primary_position,
                "overall": clean_number(row.get("overall")),
                "pace": clean_number(row.get("pace")),
                "shooting": clean_number(row.get("shooting")),
                "passing": clean_number(row.get("passing")),
                "dribbling": clean_number(row.get("dribbling")),
                "defending": clean_number(row.get("defending")),
                "physical": clean_number(row.get("physic")),
            })

            count += 1

print(f"Converted {count} players.")
print(f"Created: {output_file}")
