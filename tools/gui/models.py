"""Curated UI families, not a claim of compatibility with a selected artifact."""

REASONING_LEVELS = ("auto", "low", "medium", "xhigh")
SPECULATIVE_MODES = {
    "off": {"label": "Off", "file_field": None, "options_id": None},
    "mtp": {"label": "MTP", "file_field": "mtp_model", "options_id": "mtp-options"},
    "dflash2": {"label": "DFlash2", "file_field": "dflash_model", "options_id": None},
}
MODEL_FAMILIES = {
    "generic": {
        "label": "Other / existing configuration",
        "speculative": ("off", "mtp", "dflash2"),
        "reasoning_effort": REASONING_LEVELS,
        "defaults": {},
        "hint": "Choose options supported by your model. Gufo checks artifact compatibility when loading.",
    },
    "qwen38_flash_next": {
        "label": "Qwen3.8-Flash-Next",
        "speculative": ("off", "mtp"),
        "reasoning_effort": REASONING_LEVELS,
        "defaults": {"think": "on", "reasoning_effort": "auto", "temperature": 1.0,
                     "top_p": 0.95, "top_k": 20, "min_p": 0.0},
        "hint": "MTP needs a matching shared Q8_0 sidecar. Gufo checks projector compatibility when loading.",
    },
    "qwen38_27b": {
        "label": "Qwen3.8-27B",
        "speculative": ("off", "dflash2"),
        "reasoning_effort": REASONING_LEVELS,
        "defaults": {"think": "auto", "reasoning_effort": "auto"},
        "hint": "DFlash2 needs a matching draft and uses Gufo's adaptive defaults. Sampling remains editable.",
    },
}


def validate_model_settings(settings):
    family = MODEL_FAMILIES[settings["model_family"]]
    if settings["speculative"] not in family["speculative"]:
        raise ValueError(f"{family['label']} does not support {settings['speculative']} speculative decoding.")
    if settings["reasoning_effort"] not in family["reasoning_effort"]:
        raise ValueError(f"Unsupported reasoning level for {family['label']}.")
