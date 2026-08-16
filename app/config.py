"""Central configuration: valid domain values and source reliability weights.

Source reliability weights per the PRD (Weather, Regulatory Compliance,
Geopolitical Risk). Port Congestion has no weight specified in the PRD;
0.6 is an explicit engineering assumption (lowest of the four, since no
reliability signal was given for it) documented in the README.
"""

VALID_RISK_SIGNALS = frozenset({"low", "medium", "high"})

SOURCE_RELIABILITY: dict[str, float] = {
    "Weather": 0.9,
    "Regulatory Compliance": 0.8,
    "Geopolitical Risk": 0.7,
    "Port Congestion": 0.6,
}

VALID_SOURCES = frozenset(SOURCE_RELIABILITY.keys())
