"""A valid 40-node folding tree, and the finding codes it needs.

This is the mango tree sketched in section 7 of
``docs/proposals/unified-decision-tree-engine.md``, written out in full. It
exists as a module rather than a test helper because the beta designer and
the dry-run report both need one tree that is known to compile, and a fixture
that only pytest can import is a fixture they cannot use.

Nothing here touches a database. ``MANGO_KNOWN_CODES`` stands in for the
finding catalogue: pass it to the compiler as ``known_codes``.

What the tree does, in order:

  1. picks the vigour index from soil texture and size class, into ``vars``
  2. checks that index against its size band            -> ``ndvi_low``
  3. counts NDMI, SMI and CWSI votes, two of three      -> ``dry``
  4. checks NDRE                                        -> ``nutrient_low``
  5. checks BSI                                         -> ``cover_open``
  6. checks seven-day rain                              -> ``dry_spell``
  7. switches on three weather-risk scores              -> the pest findings
  8. checks heat, salinity, a scouting signal, the block baseline and the
     growth stage
  9. stops, and the fold turns whatever was registered into one card

The "two of three" count is a branch tree, not arithmetic: the node kinds
have no expression language on purpose (section 4.2), so agreement is
counted by which node the walk is standing on.
"""

from __future__ import annotations

from typing import Any

# The finding codes this tree declares. Session 1 owns the real catalogue;
# this is the set of codes it has to contain for the mango tree to publish.
MANGO_KNOWN_CODES: frozenset[str] = frozenset(
    {
        "ndvi_low",
        "dry",
        "dry_spell",
        "nutrient_low",
        "cover_open",
        "pest_high",
        "pest_med",
        "mildew_high",
        "fly_high",
        "heat_stress",
        "salinity_high",
        "scout_confirmed_pest",
        "block_declining",
        "stage_sensitive",
        # Present in the catalogue but not registered by this tree, so a test
        # can tell "unknown code" apart from "not declared by this tree".
        "frost_risk",
    }
)


def _index(code: str, key: str = "mean") -> dict[str, str]:
    return {"source": "indices", "index_code": code, "key": key}


def _param(name: str) -> dict[str, str]:
    return {"source": "params", "name": name}


def _var(name: str) -> dict[str, str]:
    return {"source": "vars", "name": name}


def _risk(code: str) -> dict[str, str]:
    return {"source": "weather_risk", "risk_code": code, "field": "score"}


def mango_folding_tree() -> dict[str, Any]:
    """A fresh copy of the valid tree, safe for a caller to mutate."""
    nodes: dict[str, Any] = {
        # --- 1. pick the vigour index -------------------------------------
        "root": {
            "label_en": "Sandy soil?",
            "condition": {
                "tree": {
                    "op": "in",
                    "left": {"source": "block", "field": "soil_texture"},
                    "values": ["sandy", "sandy_loam"],
                }
            },
            "on_match": "a_set_savi",
            "on_miss": "a_size",
        },
        "a_size": {
            "label_en": "Large canopy?",
            "condition": {
                "tree": {
                    "op": "ge",
                    "left": {
                        "source": "crop_attribute",
                        "code": "canopy_diameter_m",
                        "key": "value",
                    },
                    "right": _param("large_canopy_m"),
                }
            },
            "on_match": "a_set_savi_large",
            "on_miss": "a_set_ndvi",
        },
        "a_set_savi": {
            "label_en": "Use SAVI on sand",
            "set": {"index_used": "savi", "band_low": _param("savi_band_low")},
            "next": "b_band",
        },
        "a_set_savi_large": {
            "label_en": "Use SAVI on a large canopy",
            "set": {"index_used": "savi", "band_low": _param("savi_band_low_large")},
            "next": "b_band",
        },
        "a_set_ndvi": {
            "label_en": "Use NDVI",
            "set": {"index_used": "ndvi", "band_low": _param("ndvi_band_low")},
            "next": "b_band",
        },
        # --- 2. the band check --------------------------------------------
        "b_band": {
            "label_en": "Which index was picked",
            "condition": {"tree": {"op": "eq", "left": _var("index_used"), "right": "savi"}},
            "on_match": "b_band_savi",
            "on_miss": "b_band_ndvi",
        },
        "b_band_savi": {
            "label_en": "SAVI below its band",
            "condition": {"tree": {"op": "lt", "left": _index("savi"), "right": _var("band_low")}},
            "on_match": "b_reg_ndvi_low",
            "on_miss": "c_ndmi",
        },
        "b_band_ndvi": {
            "label_en": "NDVI below its band",
            "condition": {"tree": {"op": "lt", "left": _index("ndvi"), "right": _var("band_low")}},
            "on_match": "b_reg_ndvi_low",
            "on_miss": "c_ndmi",
        },
        "b_reg_ndvi_low": {
            "label_en": "Vigour is below the band",
            "register": {"code": "ndvi_low", "severity": "warning"},
            "next": "c_ndmi",
        },
        # --- 3. two of three water signals agree ---------------------------
        "c_ndmi": {
            "label_en": "NDMI below band",
            "condition": {
                "tree": {"op": "lt", "left": _index("ndmi"), "right": _param("ndmi_low")}
            },
            "on_match": "c1_smi",
            "on_miss": "c0_smi",
        },
        "c1_smi": {
            "label_en": "SMI below band, one vote already",
            "condition": {"tree": {"op": "lt", "left": _index("smi"), "right": _param("smi_low")}},
            "on_match": "c_reg_dry",
            "on_miss": "c1_cwsi",
        },
        "c0_smi": {
            "label_en": "SMI below band, no vote yet",
            "condition": {"tree": {"op": "lt", "left": _index("smi"), "right": _param("smi_low")}},
            "on_match": "c1_cwsi_b",
            "on_miss": "d_ndre",
        },
        "c1_cwsi": {
            "label_en": "CWSI above band, NDMI voted",
            "condition": {
                "tree": {"op": "gt", "left": _index("cwsi"), "right": _param("cwsi_high")}
            },
            "on_match": "c_reg_dry",
            "on_miss": "d_ndre",
        },
        "c1_cwsi_b": {
            "label_en": "CWSI above band, SMI voted",
            "condition": {
                "tree": {"op": "gt", "left": _index("cwsi"), "right": _param("cwsi_high")}
            },
            "on_match": "c_reg_dry",
            "on_miss": "d_ndre",
        },
        "c_reg_dry": {
            "label_en": "Two of three water signals agree",
            "register": {"code": "dry", "severity": "warning"},
            "next": "d_ndre",
        },
        # --- 4. nitrogen ---------------------------------------------------
        "d_ndre": {
            "label_en": "NDRE below band",
            "condition": {
                "tree": {"op": "lt", "left": _index("ndre"), "right": _param("ndre_low")}
            },
            "on_match": "d_reg_nutrient",
            "on_miss": "e_bsi",
        },
        "d_reg_nutrient": {
            "label_en": "Leaf nitrogen is low",
            "register": {"code": "nutrient_low", "severity": "warning"},
            "next": "e_bsi",
        },
        # --- 5. bare ground ------------------------------------------------
        "e_bsi": {
            "label_en": "BSI above band",
            "condition": {"tree": {"op": "gt", "left": _index("bsi"), "right": _param("bsi_high")}},
            "on_match": "e_reg_cover",
            "on_miss": "e2_rain",
        },
        "e_reg_cover": {
            "label_en": "Bare ground increased",
            "register": {"code": "cover_open", "severity": "info"},
            "next": "e2_rain",
        },
        # --- 6. seven-day rain ---------------------------------------------
        "e2_rain": {
            "label_en": "Seven-day rain below band",
            "condition": {
                "tree": {
                    "op": "lt",
                    "left": {
                        "source": "weather",
                        "scope": "past_7d",
                        "field": "precipitation_mm_total",
                    },
                    "right": _param("rain_7d_low"),
                }
            },
            "on_match": "e2_reg_dryspell",
            "on_miss": "f_pest",
        },
        "e2_reg_dryspell": {
            "label_en": "No rain for a week",
            "register": {"code": "dry_spell", "severity": "info"},
            "next": "f_pest",
        },
        # --- 7. the three weather risks ------------------------------------
        "f_pest": {
            "label_en": "Anthracnose pressure",
            "switch": {
                "on": _risk("anthracnose"),
                "cases": [
                    {"ge": 70, "go": "f_reg_pest_high"},
                    {"ge": 40, "go": "f_reg_pest_med"},
                ],
                "default": "g_mildew",
            },
        },
        "f_reg_pest_high": {
            "label_en": "Anthracnose pressure is high",
            "register": {"code": "pest_high", "severity": "critical"},
            "next": "g_mildew",
        },
        "f_reg_pest_med": {
            "label_en": "Anthracnose pressure is building",
            "register": {"code": "pest_med", "severity": "warning"},
            "next": "g_mildew",
        },
        "g_mildew": {
            "label_en": "Powdery mildew pressure",
            "switch": {
                "on": _risk("powdery_mildew"),
                "cases": [{"ge": 60, "go": "g_reg_mildew_high"}],
                "default": "h_fly",
            },
        },
        "g_reg_mildew_high": {
            "label_en": "Powdery mildew pressure is high",
            "register": {"code": "mildew_high", "severity": "critical"},
            "next": "h_fly",
        },
        "h_fly": {
            "label_en": "Fruit fly pressure",
            "switch": {
                "on": _risk("fruit_fly"),
                "cases": [{"ge": 65, "go": "h_reg_fly_high"}],
                "default": "i_heat",
            },
        },
        "h_reg_fly_high": {
            "label_en": "Fruit fly pressure is high",
            "register": {"code": "fly_high", "severity": "critical"},
            "next": "i_heat",
        },
        # --- 8. heat, salt, scouting, trend, stage -------------------------
        "i_heat": {
            "label_en": "Canopy temperature above band",
            "condition": {
                "tree": {
                    "op": "gt",
                    "left": {"source": "weather_index", "index_code": "lst", "key": "mean"},
                    "right": _param("lst_high"),
                }
            },
            "on_match": "i_reg_heat",
            "on_miss": "j_salt",
        },
        "i_reg_heat": {
            "label_en": "Canopy is running hot",
            "register": {"code": "heat_stress", "severity": "warning"},
            "next": "j_salt",
        },
        "j_salt": {
            "label_en": "Salinity class is high",
            "condition": {
                "tree": {
                    "op": "in",
                    "left": {"source": "block", "field": "salinity_class"},
                    "values": ["high", "very_high"],
                }
            },
            "on_match": "j_reg_salt",
            "on_miss": "k_scout",
        },
        "j_reg_salt": {
            "label_en": "Salinity is high",
            "register": {"code": "salinity_high", "severity": "warning"},
            "next": "k_scout",
        },
        "k_scout": {
            "label_en": "A scout confirmed a pest",
            "condition": {
                "tree": {
                    "op": "eq",
                    "left": {"source": "signals", "code": "pest_sighting", "key": "value_text"},
                    "right": "confirmed",
                }
            },
            "on_match": "k_reg_scout",
            "on_miss": "l_trend",
        },
        "k_reg_scout": {
            "label_en": "A scout saw the pest",
            "register": {"code": "scout_confirmed_pest", "severity": "critical"},
            "next": "l_trend",
        },
        "l_trend": {
            "label_en": "Block below its own baseline",
            "condition": {
                "tree": {
                    "op": "lt",
                    "left": _index("ndvi", "baseline_deviation"),
                    "right": _param("baseline_drop"),
                }
            },
            "on_match": "l_reg_decline",
            "on_miss": "m_stage",
        },
        "l_reg_decline": {
            "label_en": "The block is declining",
            "register": {"code": "block_declining", "severity": "info"},
            "next": "m_stage",
        },
        "m_stage": {
            "label_en": "Growth stage",
            "switch": {
                "on": {"source": "block", "field": "growth_stage"},
                "cases": [
                    {"eq": "flowering", "go": "m_reg_flowering"},
                    {"eq": "fruit_set", "go": "m_reg_fruit_set"},
                ],
                "default": "n_stop",
            },
        },
        "m_reg_flowering": {
            "label_en": "Flowering, so the block is sensitive",
            "register": {"code": "stage_sensitive", "severity": "info"},
            "next": "n_stop",
        },
        "m_reg_fruit_set": {
            "label_en": "Fruit set, so the block is sensitive",
            "register": {"code": "stage_sensitive", "severity": "info"},
            "next": "n_stop",
        },
        # --- 9. the fold ---------------------------------------------------
        "n_stop": {"label_en": "Fold the findings into one card", "stop": True},
    }

    return {
        "code": "mango_folding_v1",
        "name_en": "Mango, folded",
        "name_ar": "المانجو، مطوية",
        "description_en": "One mango tree that registers findings and folds them into one card.",
        "scope": "cell",
        "crop_paths": ["mango"],
        "root": "root",
        "nodes": nodes,
        "country_codes": ["EG"],
        "parameters": {
            "large_canopy_m": {"type": "number", "default": 4.0},
            "savi_band_low": {"type": "number", "default": 0.30},
            "savi_band_low_large": {"type": "number", "default": 0.35},
            "ndvi_band_low": {"type": "number", "default": 0.45},
            "ndmi_low": {"type": "number", "default": 0.15},
            "smi_low": {"type": "number", "default": 0.25},
            "cwsi_high": {"type": "number", "default": 0.60},
            "ndre_low": {"type": "number", "default": 0.20},
            "bsi_high": {"type": "number", "default": 0.10},
            "rain_7d_low": {"type": "number", "default": 2.0},
            "lst_high": {"type": "number", "default": 38.0},
            "baseline_drop": {"type": "number", "default": -0.10},
        },
        "registers": [
            "ndvi_low",
            "dry",
            "dry_spell",
            "nutrient_low",
            "cover_open",
            "pest_high",
            "pest_med",
            "mildew_high",
            "fly_high",
            "heat_stress",
            "salinity_high",
            "scout_confirmed_pest",
            "block_declining",
            "stage_sensitive",
        ],
        "combinations": [
            {
                "codes": ["ndvi_low", "cover_open"],
                "action_type": "scout",
                "status": "issue",
                "text_en": (
                    "Vigour dropped and bare ground increased. Likely missing "
                    "trees, not a weak canopy."
                ),
                "text_ar": "انخفضت الحيوية وزادت الأرض العارية. الأرجح أشجار مفقودة لا ضعف مجموع خضري.",
            },
            {
                "codes": ["ndvi_low", "dry"],
                "action_type": "irrigate",
                "status": "alert",
                "text_en": (
                    "Vigour and leaf water both dropped. Water shortage is the "
                    "fix. Irrigate first."
                ),
                "text_ar": "انخفضت الحيوية وماء الورقة معاً. نقص الماء هو السبب. اسقِ أولاً.",
            },
            {
                "codes": ["ndvi_low", "nutrient_low"],
                "action_type": "fertilize",
                "status": "alert",
                "text_en": "Vigour and leaf nitrogen both dropped. Feed before scouting.",
                "text_ar": "انخفضت الحيوية والنيتروجين معاً. سمّد قبل الكشف الميداني.",
            },
            {
                "codes": ["ndvi_low", "dry", "nutrient_low"],
                "action_type": "irrigate",
                "status": "alert",
                "text_en": "Both water and nitrogen are short. Irrigate first, then feed.",
                "text_ar": "الماء والنيتروجين كلاهما ناقص. اسقِ أولاً ثم سمّد.",
            },
            {
                "codes": ["ndvi_low", "pest_high"],
                "action_type": "spray",
                "status": "alert",
                "text_en": "Vigour dropped and anthracnose pressure is high. Treat now.",
                "text_ar": "انخفضت الحيوية وضغط الأنثراكنوز مرتفع. عالج الآن.",
            },
        ],
    }
