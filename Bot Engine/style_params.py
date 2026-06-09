# style_params.py
# V4 Configuration for Trading Styles (Pip Distances)

# We define the offset limits to control exit mechanics.
# Note: Values are in PIPS. (e.g. 2 pips = 20 points in MT5 usually)

STYLE_PARAMS = {
    "SCALPING": {
        "max_virtual_sl_pips": 20,
        "max_virtual_tp_pips": 40,
        "be_offset_pips": 2,      # Break-even lock distance
        "trail_start_pips": 15,   # When to start trailing
        "trail_dist_pips": 10     # Distance of trailing behind price
    },
    "INTRADAY": {
        "max_virtual_sl_pips": 50,
        "max_virtual_tp_pips": 100,
        "be_offset_pips": 5,
        "trail_start_pips": 40,
        "trail_dist_pips": 20
    },
    "SWING": {
        "max_virtual_sl_pips": 150,
        "max_virtual_tp_pips": 300,
        "be_offset_pips": 15,
        "trail_start_pips": 100,
        "trail_dist_pips": 50
    }
}

def get_style_params(style: str, symbol: str = None) -> dict:
    """Returns the parameters for the given style, defaulting to INTRADAY if unknown."""
    style_upper = style.upper()
    return STYLE_PARAMS.get(style_upper, STYLE_PARAMS["INTRADAY"])
