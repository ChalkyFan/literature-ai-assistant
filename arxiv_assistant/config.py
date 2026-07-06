"""Project configuration"""

ARXIV_CATEGORIES = [
    "cond-mat.str-el",
    "cond-mat.mtrl-sci",
]

KEYWORDS = [
    "strongly correlated",
    "strong correlation",
    "Hubbard model",
    "Mott insulator",
    "Mott transition",
    "heavy fermion",
    "quantum critical",
    "strange metal",
    "non-Fermi liquid",
    "bad metal",
    "quantum phase transition",
    "high-Tc",
    "high temperature superconduct",
    "cuprate",
    "unconventional superconduct",
    "pairing mechanism",
    "pseudogap",
    "charge density wave",
    "strip order",
    "pair density wave",
    "ARPES",
    "angle-resolved photoemission",
    "neutron scattering",
    "scanning tunneling microscopy",
    "STM",
    "STS",
    "transport measurement",
    "resistivity",
    "Hall effect",
    "magnetotransport",
    "specific heat",
    "thermal conductivity",
    "optical conductivity",
    "Raman scattering",
    "X-ray scattering",
    "resonant inelastic X-ray",
    "RIXS",
    "muon spin rotation",
    "frustrated magnet",
    "spin liquid",
    "quantum spin liquid",
    "kitaev material",
    "iridate",
    "ruthenate",
    "nickelate",
    "iron-based superconduct",
    "FeTe",
    "kagome",
    "triangular lattice",
    "honeycomb lattice",
]

DB_PATH = "data/literature.db"
PAPERS_DIR = "papers"
REPORTS_DIR = "reports"

ARXIV_BATCH_SIZE = 200
MAX_RESULTS_PER_DAY = 50

WEB_HOST = "0.0.0.0"
WEB_PORT = 8080
