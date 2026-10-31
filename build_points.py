"""
build_points.py

Reads the cleaned survey export (clean_positions_survey_export.csv), cleans
the language and building names, and writes three files for the Leaflet map
(mapScript.js) to plot markers from:

    data/plotting_data/student_points.csv
    data/plotting_data/staff_points.csv
    data/plotting_data/faculty_points.csv

Each file has a header row and four columns:

    Id,Language,Latitude,Longitude
    1009,english,42.817312,-73.929871
    1009,german,42.817255,-73.930012

Id (4 digits) is the same for every row that comes from the same survey
response. For the n-th response (n = its row number in the export, 3 digits):

    student: 1n  (response 9  -> 1009)
    staff:   2n  (response 78 -> 2078)
    faculty: 3n

One row (one map marker) for each language, in each building, of each
survey response:

    N_student = sum over students of  l * (w + 1)   (work buildings + residence)
    N_staff   = sum over staff    of  l * w
    N_faculty = sum over faculty  of  l * w
    N_p       = N_student + N_staff + N_faculty

    l = number of languages in the response (after cleaning)
    w = number of work buildings in the response (Work1)

Language check: a language is plotted only if it is on CLI_LANGUAGES (the
CLI language list). Any other language is left out of the map and shown in
the language report, so you can write a LANGUAGE_NAME_FIXES entry for it.
Language names are written to the csv files in lowercase.

Building names are matched to OpenStreetMap with OSM_NAME_FIXES
(survey answer -> OSM building name, "housenumber street" address, or OSM
way ID). Points are placed at random inside the building outline.

A point is left out for one reason only: its language is checked first, then
its building. Running the script prints three reports:
    1. Building report: buildings left out, and points left out for each
    2. Language report: languages left out, and points left out for each
    3. N_p check:       points plotted + points left out vs. N_p

If the point counts don't add up, no files are written.

Run with:  python build_points.py
Requires:  pip install pandas osmnx
"""

from collections import Counter
from pathlib import Path
import random
import sys

import osmnx as ox
import pandas as pd
from shapely.geometry import Point

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

INPUT_PATH = Path("data/raw/clean_positions_survey_export.csv")
OUT_DIR = Path("data/plotting_data")

OUTPUT_COLUMNS = ["Id", "Language", "Latitude", "Longitude"]

# Column names in clean_positions_survey_export.csv (its first header row).
# Qualtrics uses the name "Q1" twice (the consent question, then the position
# question), and pandas renames the second one "Q1.1".
POSITION_COL = "Q1.1"       # "Position - Selected Choice": student/staff/faculty
WORK_COL = "Q1a"            # "Where do you mainly work on campus", comma-separated if several
RESIDENCE_COL = "Q1b"       # "Where do you reside on campus if you are student"
LANG_COLUMNS = [f"Q4 Languages specify_{i}_TEXT" for i in range(13, 23)]  # Language 1-10

# Position -> first digit of the Id, e.g. student response 9 -> 1009
POSITION_PREFIX = {"student": 1, "staff": 2, "faculty": 3}

# Number of survey responses per position (counted by hand). Only used to
# warn you if the export doesn't contain what you expect.
EXPECTED_RESPONSES = {"student": 321, "staff": 104, "faculty": 99}

PLACE_NAME = "Union College, Schenectady, New York, USA"  # same as notebook

# How far outside the official campus boundary to look for buildings.
# Raise this if off-campus buildings still show up in the NO Match report.
CAMPUS_BUFFER_METERS = 400

# Last resort for buildings that aren't in OSM at all (or have no name or
# address there): name -> (lat, lon) of the building's center.
# The key must be the name the script searches for (the "searched for"
# value in the NO Match report). Pins are scattered in a small circle.
MANUAL_LOCATIONS = {
    # "Human Resources": (42.8170, -73.9280),
}
MANUAL_RADIUS_DEGREES = 0.0001  # roughly 8-11 m

# The notebook doesn't seed random, so its points change on every run.
# A fixed seed keeps the map stable between rebuilds. Set to None to match
# the notebook's behavior exactly.
RANDOM_SEED = 42

# If a respondent lists the same language twice (e.g. "mandarin" and
# "chinese (mandarin)", which both clean to "mandarin"), count it once.
# l_k is then the number of DIFFERENT languages in response k.
DROP_DUPLICATE_LANGUAGES = True

"""
Fixes for cleaning building names that are not in OpenStreetMap (OSM):

FORMAT: "Building name not in OSM": "Replacement name, address, or way id in OSM",
"""
OSM_NAME_FIXES = {
    "Karp Hall": "Humanities Building",
    "Lippman Hall": "Social Sciences Building",
    "ISEC building": "Integrated Science and Engineering Complex",
    "Sorum": "Green House",
    "Reamer Campus Center": "Murray and Ruth Reamer Campus Center",
    "Richmond House": "Richmond Hall",
    "Messa": "Wold Hall",
    "Olin Center": "F W Olin Center",
    "Hickok House (Gamma Phi Beta)": "Hickok House",
    "Wold Center": "Peter Irving Wold Center",
    "Davidson North (Kappa Alpha)": "Davidson House",
    "Wold": "Peter Irving Wold Center",
    "Green/Harris": "Green House",
    "Breazzano": "Orange House",
    "17 South Lane": "Human Resources",
    "Golub": "Golub House",
    "Fero House (Alpha Delta Phi)": "Fero House",
    "Facilities Services (check also the buildings where you usually work)": "Stephen J Potter Testing Laboratory",
    "20, 22 Union Ave": "20 Union Avenue",
    "Feigenbaum Hall": "Feigenbaum Center for Visual Arts",
    "Potter North (Chi Psi)": "Potter House",
    "Davidson South (Sigma Phi)": "Davidson House",
    "Abbe Carriage House": "Abbe Hall",
    "Yulman Theater": "Morton and Helen Yulman Theater",
    "Campus Security": "645 Nott Street",
    "Grant Hall & O’Brien Center": "Grant Hall (Admissions & Financial Aid)",
    "Becker Career Center": "Stanley R Becker Career Center",
    "Potter South (Delta Phi Epsilon)": "Potter House",
    "Edwards House (Theta Delta Chi)": "Edwards House",
    "Raymond North (Sigma Delta Tau)": "Raymond House",
    "Beuth": "Beuth House",
    "Dining Services (check also building where you usually or frequently work)": "Murray and Ruth Reamer Campus Center",
    "Peschel Computer Center": "Stanley G Peschel Computer Center",
    "219 Seward Pl (The Multicultural Greek Council)": 1206496965, # this building has no adress in OpenStreetMap, replace it with the way id
    "36 Union": 1246726844, # this building has no adress in OpenStreetMap, replace it with the way id
    "Alumni Gym": "Alumni Gymnasium",
    "Kennedy Community Center": "257 Park Place",
    "Williams Center for Campus Community Safety/645 Nott": "645 Nott Street",
    "Henle Dance Pavillion": "Henle Dance Pavilion",
    "Rathskeller": "Old Chapel",
    "Community Service House": "257 Park Place"
}


"""
Language names from:
https://certifiedlanguages.com/wp-content/uploads/2024/12/CLIs-Language-List-Translations-1.pdf
(CLI "Language List - Translation Services"; the PDF notes the list is subject to change.)

NOTE:
-> names for languages with variants were added
-> any slashes are split to two distinct languages
-> extra names for less common or unspoken languages

FORMAT: "Language name",
"""
CLI_LANGUAGES = [
    "Afrikaans",
    "Albanian",
    "Amharic",
    "Arabic",
    "Armenian",
    "Armenian (Eastern)",
    "Armenian (Western)",
    "Azerbaijani",
    "Azerbaijani (Azeri)",
    "Bassa",
    "Belarusian",
    "Bengali",
    "Bosnian",
    "Braille",
    "Bulgarian",
    "Burmese",
    "Cambodian", 
    "Cambodian (Khmer)",
    "Cape Verde Creole",
    "Cebuano",
    "Chinese",
    "Chinese (Simplified)",
    "Chinese (Traditional)",
    "Chuukese",
    "Croatian",
    "Czech",
    "Danish",
    "Dari",
    "Dutch",
    "English",
    "Estonian",
    "Farsi (Persian)",
    "Finnish",
    "Flemmish",
    "French",
    "French (Canada)",
    "French (France)",
    "Fulani",
    "Georgian",
    "German",
    "German (Swiss)",
    "Greek",
    "Gujarati",
    "Haitian Creole",
    "Hakha Chin",
    "Hakka",
    "Hakka (Chinese)",
    "Hebrew",
    "Hindi",
    "Hmong",
    "Hungarian",
    "Icelandic",
    "Igbo",
    "Ibo",
    "Ilocano",
    "Ilonggo",
    "Ilonggo (Hiligaynon)",
    "Indonesian",
    "Italian",
    "Japanese",
    "Javanese",
    "Kannada",
    "Karen",
    "Kazakh",
    "Kinyarwanda",
    "Kirundi",
    "Korean",
    "Kurdish",
    "Kurdish (Kurmanji dialect)",
    "Kurdish (Sorani dialect)",
    "Kyrgyz",
    "Kirgiz",
    "Lao",
    "Lao (Laotian)",
    "Latvian",
    "Lithuanian",
    "Macedonian",
    "Malay",
    "Malay (Malaysian)",
    "Mandinka",
    "Marathi",
    "Marshallese",
    "Mien",
    "Mongolian",
    "Montenegrin",
    "Navajo",
    "Nepali",
    "Norwegian",
    "Oromo",
    "Pashto",
    "Polish",
    "Portuguese",
    "Portuguese (Brazil)",
    "Portuguese (Portugal)",
    "Punjabi",
    "Rohingya",
    "Romanian",
    "Romanian (Moldavan)",
    "Russian",
    "Serbian",
    "Slovak",
    "Slovenian",
    "Somali",
    "Spanish",
    "Spanish (Castilian)",
    "Spanish (Latin American)",
    "Spanish (other varieties)",
    "Swahili",
    "Swedish",
    "Tagalog",
    "Tamil",
    "Telugu",
    "Thai",
    "Tibetan",
    "Tigrinya",
    "Turkish",
    "Ukrainian",
    "Urdu",
    "Uzbek",
    "Vietnamese",
    "Wolof",
    "Yoruba",

    # Extras
    "Latin",
    "American Sign Language",
    "Irish",
    "Ancient Greek",
    "Yiddish",
    "Fijian",
    "Sanskrit",
    "Aramaic",
    "Chinese (Mandarin)",
    "Chinese (Cantonese)",
    "Chinese (Toisanese)",
    "Chinese (Fuzhou dialect)",
    "Chinese (Hokkien)",
    "Malayalam",
    "Ottoman",
    "Tok Pisin",
    "Toki Pona",
    "Twi",
    "Welsh",
    "Akkadian",
    "Assamese",
    "Bambara",
    "Basque",
    "Bikol",
    "Chewa",
    "Classical Hebrew",
    "Belizian Creole",
    "Hawaiian",
    "Japanese Sign Language",
    "Tem",
    "Luganda",
    "Morse Code",
    "Nahuatl",
    "Odia",
    "Classical Persian",
    "Pig Latin",
    "Quechua",
    "Serer",
    "Siraiki",
    "Chimwiini",
    "Soninke",
    "Sumerian",
    "Ugaritic"
]

# Compared case-insensitively: cleaned answers are lowercased, so we compare
# against the lowercase version of each name on the list.
VALID_LANGUAGES = {name.lower() for name in CLI_LANGUAGES}

"""
Fixes for cleaning language names that are not in LANGUAGE_LIST:

FORMAT: "Language name not in LANGUAGE_LIST": "Replacement name in LANGUAGE_LIST",
"""
LANGUAGE_NAME_FIXES = {
    "asl": "American Sign Language",
    "american sign": "American Sign Language",
    "american sigb language": "American Sign Language",
    "asl (rudimentary)": "American Sign Language",
    "sign language": "American Sign Language",
    "some asl": "American Sign Language",

    "modern greek": "Greek",
    "greek. έλα ρε": "Greek",

    "classical greek": "Ancient Greek",

    "mandarin": "Chinese (Mandarin)",
    "chinese (mandarin)": "Chinese (Mandarin)",
    "mandarin chinese": "Chinese (Mandarin)",
    "chinese/mandarin": "Chinese (Mandarin)",
    "mandarin fluent": "Chinese (Mandarin)",

    "cantonese chinese": "Chinese (Cantonese)",
    "canatonse": "Chinese (Cantonese)",
    "cantonese": "Chinese (Cantonese)",

    "toisan chinese": "Chinese (Toisanese)",

    "dieleict fuzhou": "Chinese (Fuzhou dialect)",

    "hokkien": "Chinese (Hokkien)",

    "french français": "French",
    "french, 2 terms different ages, knowledge poor": "French",
    "french, been taking since 6th grade, am a french major at union.": "French",

    "hebrew עברית": "Hebrew",
    "modern hebrew": "Hebrew",
    "some hebrew": "Hebrew",

    "russian русский": "Russian",

    "yiddish אידיש": "Yiddish",

    "bangla": "Bengali",
    "bangladesh": "Bengali",

    "deutsch": "German",
    "german, 2 years high school, knowledge poor": "German",
    "german: ich liebe lese jeden tag.": "German",

    "brazilian portuguese": "Portuguese (Brazil)",
    "portuguese (brazilian)": "Portuguese (Brazil)",

    "português": "Portuguese",

    "englisch": "English",
    "english fluent": "English",
    "english, native": "English",
    "english, native speaker": "English",
    "english. hi i’m speaking in english whaddup.": "English",
    "english: i am glad to be participating in this survey!": "English",
    "englisj": "English",

    "khmer": "Cambodian",

    "swiss german": "German (Swiss)",

    "tok pisin (png)": "Tok Pisin",

    "arabic (classical, msa)": "Arabic",
    "عربي": "Arabic",

    "bahasa indonesia": "Indonesian",

    "belarussian": "Belarusian",

    "chichewa/nyanja": "Chewa",
    
    "criolo": "Cape Verde Creole",

    "espanol": "Spanish",
    "español. hola soy un estudiante de union college.": "Spanish",
    "some spanish": "Spanish",

    "hawai'ian": "Hawaiian",

    "irish/gaelic": "Irish",

    "italian: mi piace fare lunghe passeggiate la sera.": "Italian",

    "kotokoli": "Tem",

    "nederlands": "Dutch",

    "náhuatl": "Nahuatl",

    "odisha": "Odia",

    "persian": "Farsi (Persian)",
    "farsi": "Farsi (Persian)",
    "persian (classical)": "Farsi (Persian)",

    "sereer": "Serer",

    "somali mimi": "Chimwiini",

    "studied japanese": "Japanese",
    "日本語": "Japanese",

    "swedish, 1 term middle school, knowledge poor": "Swedish",

    "turkish. nasılsın": "Turkish",

    "ukrainain": "Ukrainian",

    "urdu (or punjabi?)": "Urdu",

    "vi2tnam": "Vietnamese",
    "vietnamese native": "Vietnamese",

    "한국어": "Korean"
}

# ---------------------------------------------------------------------------
# Random points (copied from the notebook)
# ---------------------------------------------------------------------------

def generate_random_points_in_polygon(polygon, num_points):
    """Generates random points that strictly fall inside a polygon."""
    points = []
    min_x, min_y, max_x, max_y = polygon.bounds

    # Keep searching until we find the requested number of internal points
    while len(points) < num_points:
        random_point = Point(
            random.uniform(min_x, max_x), random.uniform(min_y, max_y)
        )
        if polygon.contains(random_point):
            points.append(random_point)

    return points

# ---------------------------------------------------------------------------
# Reading and cleaning
# ---------------------------------------------------------------------------

def read_survey(path: Path) -> pd.DataFrame:
    # dtype=str keeps every column as text (so .str works even on an empty
    # column); blank cells stay blank (NaN), like in the original script.
    # utf-8-sig drops the invisible byte-order mark at the start of the file,
    # which would otherwise be glued onto the first column name.
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()

    needed = ["Progress", POSITION_COL, WORK_COL, RESIDENCE_COL, *LANG_COLUMNS]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        sys.exit(f"{path} is missing columns: {missing}\n"
                 f"Columns found: {list(df.columns)}\n"
                 "Fix the column names in the Settings section.")

    # Qualtrics puts two extra header rows under the column names (the full
    # question text, then {"ImportId": ...}). Skip every row at the top until
    # Progress is a number, which real responses always have.
    is_response = pd.to_numeric(df["Progress"], errors="coerce").notna()
    skip = int(is_response.to_numpy().argmax()) if is_response.any() else 0
    df = df.iloc[skip:].reset_index(drop=True)

    print(f"Read {len(df)} survey responses from {path} "
          f"(skipped {skip} extra header rows)")
    return df


def clean_positions(df: pd.DataFrame) -> pd.DataFrame:
    df[POSITION_COL] = df[POSITION_COL].str.strip().str.lower()
    bad = df[~df[POSITION_COL].isin(POSITION_PREFIX)]
    if len(bad):
        values = sorted({str(v) for v in bad[POSITION_COL]})
        sys.exit(f"{len(bad)} responses have a position that isn't "
                 f"student/staff/faculty: {values}")
    return df


def add_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Id = (1, 2 or 3 for student/staff/faculty) followed by the 3-digit
    response number n, e.g. response 78 from staff -> 2078."""
    if len(df) > 999:
        sys.exit(f"{len(df)} responses won't fit a 3-digit response number n.")
    df = df.reset_index(drop=True)
    n = pd.Series(range(1, len(df) + 1))
    df["Id"] = df[POSITION_COL].map(POSITION_PREFIX) * 1000 + n
    return df


def clean_languages(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase and trim every language answer, then apply
    LANGUAGE_NAME_FIXES (whole-answer replacements; empty for now).
    Whether a language is on the CLI list is checked later, in place_points."""
    for heading in LANG_COLUMNS:
        df[heading] = df[heading].str.lower().str.strip()
        if LANGUAGE_NAME_FIXES:
            df[heading] = df[heading].replace(LANGUAGE_NAME_FIXES)
            df[heading] = df[heading].str.lower().str.strip()
    return df

# ---------------------------------------------------------------------------
# One response: its languages (l) and buildings (w, or w + 1 for students)
# ---------------------------------------------------------------------------

# Building names that contain a comma themselves (e.g. "20, 22 Union Ave").
# These must not be split apart when separating multiple Work1 answers.
NAMES_WITH_COMMAS = [name for name in OSM_NAME_FIXES if "," in name]


def split_work_answer(answer) -> list:
    """Split a multi-select work answer on commas, keeping names that
    contain commas (like "20, 22 Union Ave") in one piece.
    A blank answer gives an empty list (w = 0)."""
    if not isinstance(answer, str):
        return []

    for name in NAMES_WITH_COMMAS:
        answer = answer.replace(name, name.replace(",", "\0"))
    parts = [part.replace("\0", ",").strip() for part in answer.split(",")]
    return [part for part in parts if part]


def has_residence(residence) -> bool:
    return isinstance(residence, str) and residence.strip() != ""


def languages_of(row) -> list:
    """The cleaned languages in one response (length l)."""
    languages = [row[h] for h in LANG_COLUMNS
                 if isinstance(row[h], str) and row[h] != ""]
    if DROP_DUPLICATE_LANGUAGES:
        languages = list(dict.fromkeys(languages))  # keeps order
    return languages


def buildings_of(row) -> list:
    """The buildings in one response.
    Students: residence + work buildings (w + 1).  Staff/faculty: work (w)."""
    work = split_work_answer(row[WORK_COL])
    if row[POSITION_COL] == "student" and has_residence(row[RESIDENCE_COL]):
        return [row[RESIDENCE_COL].strip()] + work
    return work  # staff/faculty, or a student with no residence answer


def to_osm_name(survey_name: str):
    """Survey name -> OSM name, address, or way ID (int)."""
    return OSM_NAME_FIXES.get(survey_name, survey_name)

# ---------------------------------------------------------------------------
# N: the expected number of points
# ---------------------------------------------------------------------------

def count_expected_points(df: pd.DataFrame) -> pd.DataFrame:
    """l, w, residence and l * (buildings) for every response, counted
    straight from the columns. Deliberately separate from build_requests(),
    so the two can check each other. Indexed by Id."""
    langs = df[LANG_COLUMNS].where(df[LANG_COLUMNS].ne(""))
    listed = langs.notna().sum(axis=1)
    l = langs.nunique(axis=1) if DROP_DUPLICATE_LANGUAGES else listed

    student = df[POSITION_COL] == "student"
    w = df[WORK_COL].apply(lambda answer: len(split_work_answer(answer)))
    r = (student & df[RESIDENCE_COL].apply(has_residence)).astype(int)

    counts = pd.DataFrame({
        "position": df[POSITION_COL].values,
        "l": l.values,
        "w": w.values,
        "r": r.values,
        "student": student.values,
        "repeats": (listed - l).values,
    }, index=df["Id"].values)
    counts["points"] = counts["l"] * (counts["w"] + counts["r"])
    return counts

# ---------------------------------------------------------------------------
# Buildings: OpenStreetMap side
# ---------------------------------------------------------------------------

def get_search_area():
    """Campus boundary from OSM, plus a widened version of it."""
    campus = ox.geocode_to_gdf(PLACE_NAME)
    campus_shape = campus.geometry.iloc[0]

    if campus_shape.geom_type not in ("Polygon", "MultiPolygon"):
        print(f"⚠ OSM returned a {campus_shape.geom_type} (not an outline) for "
              f"{PLACE_NAME!r}. Searching a circle around it instead.")

    utm = campus.estimate_utm_crs()  # a projection in meters, so the buffer is in meters
    widened = campus.to_crs(utm).buffer(CAMPUS_BUFFER_METERS).to_crs(epsg=4326)
    return campus_shape, widened.iloc[0]


def load_building_polygons() -> dict:
    """Returns {name or address: polygon} for buildings on and near campus."""
    campus_shape, search_area = get_search_area()

    print(f"\nDownloading buildings within {CAMPUS_BUFFER_METERS} m of {PLACE_NAME}...")
    buildings = ox.features_from_polygon(search_area, tags={'building': True})
    buildings = buildings.to_crs(epsg=4326)

    # Random points need an area, so skip buildings mapped as single points
    buildings = buildings[buildings.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]

    # On-campus buildings go first, so they win if a name appears twice
    on_campus = buildings.geometry.intersects(campus_shape)
    buildings = (buildings.assign(on_campus=on_campus)
                          .sort_values("on_campus", ascending=False, kind="stable"))

    polygons = {}

    # 1. Match by building name
    if "name" in buildings.columns:
        for name, geom in zip(buildings["name"], buildings.geometry):
            if isinstance(name, str):
                polygons.setdefault(name.strip(), geom)

    # 2. Match by street address, e.g. "645 Nott Street"
    if {"addr:housenumber", "addr:street"} <= set(buildings.columns):
        for number, street, geom in zip(buildings["addr:housenumber"],
                                        buildings["addr:street"],
                                        buildings.geometry):
            if isinstance(number, str) and isinstance(street, str):
                polygons.setdefault(f"{number.strip()} {street.strip()}", geom)

    # 3. Match by OSM way ID, for outlines with no name or address.
    #    Any integer value in OSM_NAME_FIXES is treated as a way ID.
    way_ids = {v for v in OSM_NAME_FIXES.values() if isinstance(v, int)}
    for way_id in way_ids:
        key = ("way", way_id)
        if key in buildings.index:
            polygons[way_id] = buildings.loc[key, "geometry"]

    # 4. Manual locations, only for names not found above
    for name, (lat, lon) in MANUAL_LOCATIONS.items():
        if name in polygons:
            print(f"ℹ MANUAL_LOCATIONS: {name!r} was found in OSM, "
                  "so the manual location is ignored")
        polygons.setdefault(name, Point(lon, lat).buffer(MANUAL_RADIUS_DEGREES))

    print(f"Found {len(buildings)} buildings ({int(on_campus.sum())} on campus), "
          f"{len(polygons)} names/addresses to match against")
    return polygons

# ---------------------------------------------------------------------------
# Points
# ---------------------------------------------------------------------------

def build_requests(df: pd.DataFrame) -> pd.DataFrame:
    """One request per language x building x response."""
    requests = []
    for _, row in df.iterrows():
        languages = languages_of(row)
        for building in buildings_of(row):
            for language in languages:
                requests.append((int(row["Id"]), row[POSITION_COL],
                                 building, language))
    return pd.DataFrame(requests,
                        columns=["Id", "position", "building", "language"])


def place_points(requests: pd.DataFrame, polygons: dict):
    """One random point inside the building for every request, but only if
    (1) its language is on the CLI list and (2) its building matches an OSM
    building. The language is checked first, so each request ends up placed
    or left out for exactly one reason."""
    rows = []
    placed, dropped = Counter(), Counter()

    # 1. Language check: anything not on the CLI list is left out.
    bad = requests[~requests["language"].isin(VALID_LANGUAGES)]
    dropped.update(bad["Id"])
    bad_languages = {language: (len(group), group["Id"].nunique())
                     for language, group in bad.groupby("language")}

    # 2. Building match, for the points whose language passed. Every building
    #    is looked up (even if all its languages failed) so none is hidden.
    unmatched = {}
    for building, group in requests.groupby("building"):
        osm_name = to_osm_name(building)
        polygon = polygons.get(osm_name)
        valid = group[group["language"].isin(VALID_LANGUAGES)]

        if polygon is None:
            unmatched[building] = (osm_name, len(valid), len(group))
            dropped.update(valid["Id"])
            continue

        points = generate_random_points_in_polygon(polygon, len(valid))
        for order, id_, position, language, point in zip(
                valid.index, valid["Id"], valid["position"],
                valid["language"], points):
            # shapely stores (x, y) = (lon, lat)
            rows.append({"order": order,
                         "Id": id_,
                         "position": position,
                         "Language": language,
                         "Latitude": round(point.y, 6),
                         "Longitude": round(point.x, 6)})
            placed[id_] += 1

    return rows, unmatched, bad_languages, placed, dropped


def check_point_count(expected: pd.DataFrame, placed: Counter, dropped: Counter) -> list:
    """For every response: placed + dropped must equal l * (buildings).
    Returns the responses that don't add up (should be empty)."""
    problems = []
    for id_, n in expected["points"].items():
        p, d = placed.get(id_, 0), dropped.get(id_, 0)
        if p + d != n:
            problems.append((id_, int(n), p, d))
    for id_ in (set(placed) | set(dropped)) - set(expected.index):
        problems.append((id_, 0, placed.get(id_, 0), dropped.get(id_, 0)))
    return problems


def save_points(points: pd.DataFrame) -> dict:
    """Write student_points.csv, staff_points.csv and faculty_points.csv
    (each with a header row, even if a file ends up with no points)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = {}
    for position in POSITION_PREFIX:
        path = OUT_DIR / f"{position}_points.csv"
        subset = points[points["position"] == position]
        subset[OUTPUT_COLUMNS].to_csv(path, index=False)
        saved[position] = (path, len(subset))
    return saved

# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def building_report(unmatched: dict):
    print("\n" + "=" * 70)
    print("BUILDING REPORT")
    print("=" * 70)
    if not unmatched:
        print("✓ Every building was matched. No points left out.")
        return
    print("⚠ Buildings NOT in OpenStreetMap (left out of the map):")
    for building, (osm_name, lost, total) in sorted(
            unmatched.items(), key=lambda x: (-x[1][1], -x[1][2])):
        if isinstance(osm_name, int):
            searched = f" (searched for way {osm_name})"
        else:
            searched = f" (searched for {osm_name!r})" if osm_name != building else ""
        extra = ""
        if total > lost:
            extra = (f" (+{total - lost} more points here were already left out "
                     "for an unrecognized language)")
        print(f"   {building!r}{searched}: {lost} points left out{extra}")
    print(f"   Total: {len(unmatched)} buildings, "
          f"{sum(lost for _, lost, _ in unmatched.values())} points left out")


def language_report(bad_languages: dict):
    print("\n" + "=" * 70)
    print("LANGUAGE REPORT")
    print("=" * 70)
    if not bad_languages:
        print("✓ Every language is on the CLI list. No points left out.")
        return
    print("⚠ Languages NOT in CLI_LANGUAGES (left out of the map):")
    for language, (points, responses) in sorted(
            bad_languages.items(), key=lambda x: (-x[1][0], x[0])):
        plural = "response" if responses == 1 else "responses"
        print(f"   {language!r}: {points} points left out "
              f"({responses} {plural})")
    print(f"   Total: {len(bad_languages)} languages, "
          f"{sum(p for p, _ in bad_languages.values())} points left out")


def np_report(expected: pd.DataFrame, dropped: Counter, saved: dict,
              n_bad_language: int, n_bad_building: int):
    print("\n" + "=" * 70)
    print("N_p CHECK")
    print("=" * 70)

    # Responses per position (I, J, K, R) vs. what you counted by hand
    counts = expected["position"].value_counts()
    R = len(expected)
    print(f"Responses: R = {R}  "
          f"(I = {counts.get('student', 0)} students, "
          f"J = {counts.get('staff', 0)} staff, "
          f"K = {counts.get('faculty', 0)} faculty)")
    for position, n in EXPECTED_RESPONSES.items():
        if counts.get(position, 0) != n:
            print(f"⚠ Expected {n} {position} responses, found {counts.get(position, 0)}")
    if R != sum(EXPECTED_RESPONSES.values()):
        print(f"⚠ Expected R = {sum(EXPECTED_RESPONSES.values())} responses, found {R}")

    dropped_by_position = Counter()
    for id_, n in dropped.items():
        dropped_by_position[expected.loc[id_, "position"]] += n

    print(f"\n   {'':10}{'expected N':>12}{'plotted':>10}{'left out':>10}   file")
    total_expected = total_plotted = total_dropped = 0
    for position in POSITION_PREFIX:
        n_expected = int(expected.loc[expected["position"] == position, "points"].sum())
        n_plotted = saved[position][1]
        n_dropped = dropped_by_position[position]
        total_expected += n_expected
        total_plotted += n_plotted
        total_dropped += n_dropped
        print(f"   {position:10}{n_expected:>12}{n_plotted:>10}{n_dropped:>10}   "
              f"{saved[position][0]}")
    print(f"   {'N_p':10}{total_expected:>12}{total_plotted:>10}{total_dropped:>10}")

    print(f"\n✓ N_p check passed: {total_plotted} plotted + {total_dropped} left out "
          f"= {total_plotted + total_dropped} = N_p ({total_expected})")
    print(f"   Left out = {n_bad_language} (language not on the CLI list) "
          f"+ {n_bad_building} (building with no OSM match)")

    no_residence = int((expected["student"] & (expected["r"] == 0)).sum())
    if no_residence:
        print(f"ℹ {no_residence} student responses have no residence answer, "
              "so they have w buildings instead of w + 1")
    zero = int((expected["points"] == 0).sum())
    if zero:
        print(f"ℹ {zero} responses have no languages or no buildings, "
              "so they add no points")
    repeats = int(expected["repeats"].sum())
    if repeats:
        print(f"ℹ {repeats} repeated languages within a response were counted once "
              "(DROP_DUPLICATE_LANGUAGES)")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not INPUT_PATH.exists():
        sys.exit(f"Can't find {INPUT_PATH}. Check INPUT_PATH in the Settings section.")

    if RANDOM_SEED is not None:
        random.seed(RANDOM_SEED)

    # 1. Read, clean, and give every response its Id
    df = read_survey(INPUT_PATH)
    df = clean_positions(df)
    df = add_ids(df)
    df = clean_languages(df)

    # 2. Expected number of points N_p, counted straight from the columns
    expected = count_expected_points(df)
    n_p = int(expected["points"].sum())

    # 3. One request per language x building x response
    requests = build_requests(df)

    # 4. One random point per request, inside its building, if its language
    #    is on the CLI list
    polygons = load_building_polygons()

    # Check the fix list itself: every OSM name / way ID must exist in OSM
    for survey_name, osm_name in OSM_NAME_FIXES.items():
        if osm_name not in polygons:
            if isinstance(osm_name, int):
                print(f"⚠ OSM_NAME_FIXES: {survey_name!r} -> way {osm_name}, "
                      f"but that way isn't a building within "
                      f"{CAMPUS_BUFFER_METERS} m of campus")
            else:
                print(f"⚠ OSM_NAME_FIXES: {survey_name!r} -> {osm_name!r}, "
                      f"but no OSM building is named {osm_name!r}")

    rows, unmatched, bad_languages, placed, dropped = place_points(requests, polygons)
    n_written, n_dropped = len(rows), sum(dropped.values())

    # 5. N_p check: stop BEFORE saving if any point is unaccounted for
    problems = check_point_count(expected, placed, dropped)
    if problems or n_written + n_dropped != n_p:
        print(f"\n✗ N_p check FAILED: expected {n_p} points, "
              f"got {n_written} written + {n_dropped} left out "
              f"= {n_written + n_dropped}")
        for id_, n, p, d in problems[:20]:
            print(f"   Id {id_}: expected {n}, got {p} written + {d} left out")
        if len(problems) > 20:
            print(f"   ... and {len(problems) - 20} more responses")
        sys.exit(f"No files were written to {OUT_DIR}.")

    # 6. Save the three csv files, rows in Id (response) order
    points = pd.DataFrame(rows, columns=["order", "Id", "position", *OUTPUT_COLUMNS[1:]])
    points = points.sort_values("order", kind="stable")
    saved = save_points(points)

    # 7. Reports
    building_report(unmatched)
    language_report(bad_languages)
    np_report(expected, dropped, saved,
              n_bad_language=sum(p for p, _ in bad_languages.values()),
              n_bad_building=sum(lost for _, lost, _ in unmatched.values()))


if __name__ == "__main__":
    main()
