#!/usr/bin/env python3
"""
Albion Online - Industrial Refining & Supply-Chain Engine (V3.3 - Production Verified)
=====================================================================================
Fixes & Enhancements:
- 28-Day Price Anchor: Resolved JSON key mismatch ('history_28d_avg_price') to eliminate ghost sell spikes.
- True Hauling Weight Guard: Verifies procurement payload weight (raw materials + catalysts) to prevent mount overload.
- Tight Budget Optimization: Uses binary-search batch sizing to fully deploy capital without budget waste.
- Unidirectional Corridor Routing: Eliminates backward procurement loops across cities.
- Embedded Data Weight Ingestion: Directly reads item weight metadata from market summary files.
- Complete Stone Refining Support: Accurately maps enchanted rocks to flat stone block outputs.
"""

import os
import sys
import json
import glob
import math
import csv

# ==============================================================================
#  ALBION GAME ENGINE BALANCE CONSTANTS
# ==============================================================================

TAX_PREMIUM_SALES     = 0.040   # 4.0% sales tax with Premium
TAX_PREMIUM_SETUP     = 0.025   # 2.5% listing setup fee with Premium
TAX_NON_PREM_SALES    = 0.080   # 8.0% sales tax without Premium
TAX_NON_PREM_SETUP    = 0.025   # 2.5% listing setup fee without Premium
TAX_INSTANT_FILL_PREM = 0.040   # 4.0% flat tax on filling buy orders (Premium)
TAX_INSTANT_FILL_NP   = 0.080   # 8.0% flat tax on filling buy orders (Non-Premium)

BONUS_BASE_ROYAL_CITY = 18.0    # Base +18% production bonus in Royal Cities
BONUS_LOCAL_REFINING  = 40.0    # +40% specialty city refining bonus (Total: 58%)
BONUS_FOCUS_BOOST     = 59.0    # Focus adds +59% to the production bonus pool

NUTRITION_FACTOR      = 0.1125  # Nutrition consumed = item_value * 0.1125
MAX_DAILY_VOLUME_SHARE= 0.35    # Max 35% of daily volume to prevent market crashes
MAX_PRICE_OVERHANG_RATIO = 1.25 # Max 25% above 28d avg price (Filters artificial walls)
MAX_STOCK_CONSUMPTION_RATIO = 0.80 # Never assume >80% of a city's total stock can be bought

REFINING_SPECIALTY = {
    "LEATHER":    {"city": "Martlock",      "raw_prefix": "HIDE",  "refined_prefix": "LEATHER"},
    "METALBAR":   {"city": "Thetford",      "raw_prefix": "ORE",   "refined_prefix": "METALBAR"},
    "PLANKS":     {"city": "Fort Sterling", "raw_prefix": "WOOD",  "refined_prefix": "PLANKS"},
    "CLOTH":      {"city": "Lymhurst",      "raw_prefix": "FIBER", "refined_prefix": "CLOTH"},
    "STONEBLOCK": {"city": "Bridgewatch",   "raw_prefix": "ROCK",  "refined_prefix": "STONEBLOCK"}
}

ROYAL_RING = ["Martlock", "Bridgewatch", "Lymhurst", "Fort Sterling", "Thetford"]
RAW_RATIO_BY_TIER = {2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 5, 8: 5}
BASE_ITEM_VALUES  = {2: 8, 3: 16, 4: 32, 5: 64, 6: 128, 7: 256, 8: 512}

def get_shortest_royal_corridor(city_a, city_b):
    if city_a == city_b:
        return [city_a]
    if city_a not in ROYAL_RING or city_b not in ROYAL_RING:
        return [city_a, city_b]

    i = ROYAL_RING.index(city_a)
    j = ROYAL_RING.index(city_b)
    n = len(ROYAL_RING)

    cw_dist = (j - i) % n
    ccw_dist = (i - j) % n

    if cw_dist <= ccw_dist:
        return [ROYAL_RING[(i + step) % n] for step in range(cw_dist + 1)]
    else:
        return [ROYAL_RING[(i - step) % n] for step in range(ccw_dist + 1)]

def get_allowed_sourcing_cities(refining_city, dest_city, mode="CORRIDOR"):
    if mode == "GLOBAL":
        return None
    if dest_city in ["Caerleon", "Black Market"]:
        if refining_city in ROYAL_RING:
            idx = ROYAL_RING.index(refining_city)
            return [refining_city, ROYAL_RING[(idx - 1) % 5], ROYAL_RING[(idx + 1) % 5]]
        return [refining_city]

    corridor = get_shortest_royal_corridor(refining_city, dest_city)
    if len(corridor) > 2 and dest_city in corridor:
        return [c for c in corridor if c != dest_city]
    return corridor

# ==============================================================================
#  PATH RESOLUTION & DATA INGESTION
# ==============================================================================

POSSIBLE_BASE_DIRS = [
    r"C:\Users\birun\Desktop\albion",
    os.path.dirname(os.path.abspath(__file__)),
    os.getcwd()
]
BASE_DIR = next((d for d in POSSIBLE_BASE_DIRS if os.path.exists(d)), os.getcwd())

POSSIBLE_SAVES_DIRS = [
    os.path.join(BASE_DIR, "saves_here"),
    os.path.join(os.getcwd(), "saves_here"),
    BASE_DIR,
    os.getcwd()
]
SAVES_DIR = next((d for d in POSSIBLE_SAVES_DIRS if os.path.exists(d) and len(glob.glob(os.path.join(d, "*_summary.*"))) > 0), POSSIBLE_SAVES_DIRS[0])
OUTPUT_MD = os.path.join(SAVES_DIR, "refining_plan.md")

DB_CANDIDATES = [
    os.path.join(BASE_DIR, "items.json"),
    os.path.join(BASE_DIR, "items_db.json"),
    os.path.join(os.getcwd(), "items.json"),
    os.path.join(os.getcwd(), "items_db.json")
]
ITEMS_DB_PATH = next((p for p in DB_CANDIDATES if os.path.exists(p)), None)

def load_items_db():
    if not ITEMS_DB_PATH:
        return {}
    try:
        with open(ITEMS_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("items", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}

ITEMS_DB = load_items_db()
EXTRACTED_ITEM_WEIGHTS = {}

def get_item_weight(item_id: str) -> float:
    base = item_id.split("@")[0]
    if item_id in EXTRACTED_ITEM_WEIGHTS:
        return EXTRACTED_ITEM_WEIGHTS[item_id]
    if base in EXTRACTED_ITEM_WEIGHTS:
        return EXTRACTED_ITEM_WEIGHTS[base]

    db_entry = ITEMS_DB.get(item_id) or ITEMS_DB.get(base)
    if db_entry and "weight" in db_entry:
        return float(db_entry["weight"])

    tier = 4
    if len(item_id) >= 2 and item_id[1].isdigit():
        tier = int(item_id[1])
    if "STONEBLOCK" in item_id or "ROCK" in item_id:
        return 0.5 * (2 ** (tier - 4)) if tier >= 4 else 0.3
    if "LEATHER" in item_id or "HIDE" in item_id:
        return 0.76 if tier >= 5 else (0.51 if tier == 4 else 0.34)
    return 0.5

def detect_city_name(filename, market_type=""):
    fn = os.path.basename(filename).lower()
    if "bm" in fn or "black" in fn or "blackmarket" in fn or market_type == "Caerleon Black Market":
        return "Black Market"
    for c in ["Thetford", "Fort Sterling", "Lymhurst", "Bridgewatch", "Martlock", "Caerleon", "Caerlon"]:
        if c.lower().replace(" ", "") in fn.replace("_", "").replace(" ", ""):
            return "Caerleon" if "caerl" in c.lower() else c
    return os.path.basename(filename).split('_')[0].capitalize()

def load_all_market_summaries():
    json_files = glob.glob(os.path.join(SAVES_DIR, "*_summary.json"))
    csv_files = glob.glob(os.path.join(SAVES_DIR, "*_summary.csv"))

    if not json_files and not csv_files:
        json_files = glob.glob("*_summary.json")
        csv_files = glob.glob("*_summary.csv")

    if not json_files and not csv_files:
        print(f"\n[!] Error: No '*_summary.json' or '*_summary.csv' files found in '{SAVES_DIR}'.")
        sys.exit(1)

    city_markets = {}

    for fpath in json_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                first_item = next(iter(data.values())) if data else {}
                m_type = first_item.get("market_type", "") if isinstance(first_item, dict) else ""
                city = detect_city_name(fpath, m_type)

                if city not in city_markets:
                    city_markets[city] = {}
                for itype, idata in data.items():
                    if "weight" in idata and itype not in EXTRACTED_ITEM_WEIGHTS:
                        try:
                            EXTRACTED_ITEM_WEIGHTS[itype] = float(idata["weight"])
                        except (ValueError, TypeError):
                            pass

                    if itype not in city_markets[city]:
                        city_markets[city][itype] = idata
                    else:
                        city_markets[city][itype]["qualities"].update(idata.get("qualities", {}))
        except Exception as e:
            print(f"    [!] Warning: Error reading JSON {os.path.basename(fpath)}: {e}")

    for fpath in csv_files:
        city = detect_city_name(fpath)
        if city not in city_markets:
            city_markets[city] = {}
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    itype = row.get("item_type")
                    if not itype:
                        continue
                    q_name = row.get("quality_name", "Normal")
                    sell_p = float(row.get("lowest_sell_price") or 0)
                    sell_stock = int(float(row.get("total_sell_stock") or 0))
                    buy_p = float(row.get("highest_buy_order") or 0)
                    buy_dem = int(float(row.get("total_buy_demand") or 0))
                    vel = float(row.get("daily_volume_velocity") or 0)
                    avg_p = float(row.get("history_28d_avg_price") or row.get("avg_price_28d") or row.get("price_avg_28d") or 0)

                    if itype not in city_markets[city]:
                        city_markets[city][itype] = {"qualities": {}}

                    if q_name not in city_markets[city][itype]["qualities"]:
                        city_markets[city][itype]["qualities"][q_name] = {
                            "lowest_sell_price": sell_p,
                            "total_sell_stock": sell_stock,
                            "highest_buy_order": buy_p,
                            "total_buy_demand": buy_dem,
                            "daily_volume_velocity": vel,
                            "history_28d_avg_price": avg_p,
                            "sell_orders": [[sell_p, sell_stock]] if sell_p > 0 and sell_stock > 0 else [],
                            "buy_orders": [[buy_p, buy_dem]] if buy_p > 0 and buy_dem > 0 else []
                        }
        except Exception as e:
            print(f"    [!] Warning: Error reading CSV {os.path.basename(fpath)}: {e}")

    print(f"[*] Aggregated market datasets across {len(city_markets)} cities:")
    for c in sorted(city_markets.keys()):
        print(f"    - [{c}] ({len(city_markets[c]):,} items indexed)")
    return city_markets

# ==============================================================================
#  REFINING MATH & ALGORITHMIC SOURCING
# ==============================================================================

def calculate_rrr(base_bonus_pct, is_focus=False):
    total_bonus = base_bonus_pct
    if is_focus:
        total_bonus += BONUS_FOCUS_BOOST
    bonus_fraction = total_bonus / 100.0
    return bonus_fraction / (1.0 + bonus_fraction)

def simulate_reverse_starting_materials(target_units, return_rate, ratio=1):
    if target_units <= 0:
        return 0
    if return_rate <= 0:
        return target_units * ratio

    seed = max(ratio, int(target_units * ratio * (1.0 - return_rate)))
    while True:
        produced = 0
        curr = seed
        while curr >= ratio:
            batches = curr // ratio
            produced += batches
            returned = math.floor(batches * ratio * return_rate)
            leftover = curr % ratio
            curr = leftover + returned
            if returned == 0:
                break
        if produced >= target_units:
            return seed
        seed += 1

def walk_multi_city_asks(item_id, target_qty, city_markets, allowed_cities=None, excluded_cities=None):
    excluded_cities = excluded_cities or ["Black Market"]
    all_lots = []

    for city, items in city_markets.items():
        if city in excluded_cities:
            continue
        if allowed_cities and city not in allowed_cities:
            continue

        q_data = items.get(item_id, {}).get("qualities", {}).get("Normal") or items.get(item_id, {}).get("qualities", {}).get("Good")
        if not q_data:
            qualities = items.get(item_id, {}).get("qualities", {})
            if qualities:
                q_data = next(iter(qualities.values()))

        if not q_data:
            continue

        total_stock = q_data.get("total_sell_stock", 999999)
        max_takeable = max(10, int(total_stock * MAX_STOCK_CONSUMPTION_RATIO))

        sell_orders = q_data.get("sell_orders") or q_data.get("sell_ladder") or []
        city_lot_cum = 0
        for o in sell_orders:
            p, a = 0, 0
            if isinstance(o, dict):
                p = o.get("unit_price") or o.get("price") or 0
                a = o.get("amount") or o.get("count") or 0
            elif isinstance(o, (list, tuple)) and len(o) >= 2:
                p, a = o[0], o[1]
            if p > 0 and a > 0:
                take_a = min(a, max(0, max_takeable - city_lot_cum))
                if take_a > 0:
                    all_lots.append({"city": city, "price": float(p), "amount": int(take_a)})
                    city_lot_cum += take_a

    all_lots.sort(key=lambda x: x["price"])

    acquired = 0
    total_cost = 0.0
    allocation = []

    for lot in all_lots:
        if acquired >= target_qty:
            break
        take = min(lot["amount"], target_qty - acquired)
        cost = take * lot["price"]
        total_cost += cost
        acquired += take
        allocation.append({
            "city": lot["city"],
            "unit_price": lot["price"],
            "amount": take,
            "cost": cost
        })

    return acquired, total_cost, allocation

def walk_market_bids(q_data, max_qty=999999):
    buy_orders = q_data.get("buy_orders") or q_data.get("buy_ladder") or []
    ladder = []
    for o in buy_orders:
        if isinstance(o, dict):
            p = o.get("unit_price") or o.get("price") or 0
            a = o.get("amount") or o.get("count") or 0
        elif isinstance(o, (list, tuple)) and len(o) >= 2:
            p, a = o[0], o[1]
        else:
            continue
        if p > 0 and a > 0:
            ladder.append((float(p), int(a)))
    ladder.sort(key=lambda x: x[0], reverse=True)

    filled = 0
    gross_payout = 0.0
    for p, a in ladder:
        if filled >= max_qty:
            break
        take = min(a, max_qty - filled)
        gross_payout += take * p
        filled += take

    return filled, gross_payout

def build_refining_recipes_for_item(refined_id):
    base = refined_id.split("@")[0]
    ench = int(refined_id.split("@")[1]) if "@" in refined_id else 0

    parts = base.split("_")
    if len(parts) < 2:
        return []

    tier_str = parts[0]
    if not (tier_str.startswith("T") and tier_str[1:].isdigit()):
        return []
    tier = int(tier_str[1:])
    if tier < 3 or tier > 8:
        return []

    res_token = parts[1]
    res_type = None
    for r_key, meta in REFINING_SPECIALTY.items():
        if res_token == meta["refined_prefix"]:
            res_type = r_key
            break

    if not res_type:
        return []

    raw_prefix = REFINING_SPECIALTY[res_type]["raw_prefix"]
    refined_prefix = REFINING_SPECIALTY[res_type]["refined_prefix"]
    raw_count = RAW_RATIO_BY_TIER.get(tier, 2)
    lower_tier = tier - 1

    # Stone blocks: Each craft consumes raw_count rocks and (mult) lower blocks, producing (mult) blocks
    if res_type == "STONEBLOCK":
        recipes = []
        lower_refined_id = f"T{lower_tier}_{refined_prefix}" if lower_tier >= 2 else None
        # Flat rock (mult = 1)
        recipes.append((res_type, tier, 0, f"T{tier}_{raw_prefix}", raw_count, lower_refined_id, 1, 1))
        # Enchanted rock alternatives: .1 yields 2 blocks, .2 yields 4, .3 yields 8, .4 yields 16
        for rock_ench, mult in [(1, 2), (2, 4), (3, 8), (4, 16)]:
            raw_id = f"T{tier}_{raw_prefix}_LEVEL{rock_ench}@{rock_ench}"
            recipes.append((res_type, tier, rock_ench, raw_id, raw_count, lower_refined_id, mult, mult))
        return recipes

    if ench == 0:
        raw_item_id = f"T{tier}_{raw_prefix}"
        lower_refined_id = f"T{lower_tier}_{refined_prefix}" if lower_tier >= 2 else None
    else:
        raw_item_id = f"T{tier}_{raw_prefix}_LEVEL{ench}@{ench}"
        if lower_tier == 3:
            lower_refined_id = f"T3_{refined_prefix}"
        else:
            lower_refined_id = f"T{lower_tier}_{refined_prefix}_LEVEL{ench}@{ench}"

    return [(res_type, tier, ench, raw_item_id, raw_count, lower_refined_id, 1, 1)]

# ==============================================================================
#  PROMPT CONFIGURATION
# ==============================================================================

def prompt_user_config():
    print("\n" + "=" * 95)
    print("   ALBION REFINING & INDUSTRIAL SUPPLY-CHAIN ENGINE (V3.3 - PRODUCTION VERIFIED)")
    print("=" * 95)

    p_in = input("[1] Do you have ACTIVE PREMIUM? (Y/N) [Default: N]: ").strip().upper()
    is_premium = (p_in == "Y")
    tax_sales = TAX_PREMIUM_SALES if is_premium else TAX_NON_PREM_SALES
    tax_setup = TAX_PREMIUM_SETUP if is_premium else TAX_NON_PREM_SETUP
    tax_sell_order = tax_sales + tax_setup
    tax_instant_fill = TAX_INSTANT_FILL_PREM if is_premium else TAX_INSTANT_FILL_NP

    f_budget_in = input("[2] Enter your FOCUS BUDGET to spend [0 for No Focus | Default: 0]: ").strip()
    focus_budget = int(f_budget_in) if f_budget_in.isdigit() else 0

    days_in = input("[3] Target HOLDING/SELLOUT HORIZON in DAYS [Default: 1.0]: ").strip()
    try:
        holding_days = float(days_in) if days_in else 1.0
        if holding_days <= 0: holding_days = 1.0
    except ValueError:
        holding_days = 1.0

    b_in = input("[4] Maximum SILVER INVESTMENT BUDGET [Default: 2000000]: ").strip()
    try:
        max_budget = float(b_in) if b_in else 2000000.0
        if max_budget <= 0: max_budget = 2000000.0
    except ValueError:
        max_budget = 2000000.0

    s_in = input("[5] Sourcing Mode: [1] Linear Ring Corridor (Connected) [Default] | [2] Global (Any City): ").strip()
    sourcing_mode = "GLOBAL" if s_in == "2" else "CORRIDOR"

    w_in = input("[6] Max MOUNT CARGO WEIGHT in kg [e.g. 350 (Horse), 800 (Ox), 2500 (T6 Ox) | Press Enter for No Limit]: ").strip()
    try:
        max_weight = float(w_in) if w_in else 0.0
    except ValueError:
        max_weight = 0.0

    fee_in = input("[7] Refining Station Fee per 100 nutrition [Default: 500]: ").strip()
    refine_fee_per_100 = float(fee_in) if fee_in else 500.0

    profit_in = input("[8] Minimum Net Profit threshold to display [Default: 10000]: ").strip()
    min_profit = float(profit_in) if profit_in else 10000.0

    roi_in = input("[9] Minimum Net ROI % threshold [Default: 8.0]: ").strip()
    min_roi = float(roi_in) if roi_in else 8.0

    print("=" * 95 + "\n")
    return {
        "is_premium": is_premium,
        "tax_sell_order": tax_sell_order,
        "tax_instant_fill": tax_instant_fill,
        "focus_budget": focus_budget,
        "holding_days": holding_days,
        "max_budget": max_budget,
        "sourcing_mode": sourcing_mode,
        "max_weight": max_weight,
        "refine_fee_per_100": refine_fee_per_100,
        "min_profit": min_profit,
        "min_roi": min_roi
    }

# ==============================================================================
#  ROUTE SOLVER WITH BINARY SEARCH BUDGET PACKING
# ==============================================================================

def evaluate_batch(current_units, refined_id, recipe_tuple, dest_mode, dest_price, dest_gross, q_data, city_markets, config, specialty_city, allowed_cities, ref_rrr):
    res_type, tier, ench, raw_id, raw_ratio, lower_id, lower_ratio, block_mult = recipe_tuple

    crafts = max(1, current_units // block_mult)
    actual_output_units = crafts * block_mult

    # 1. MOUNT WEIGHT GUARD: Check RAW hauling weight as well as output weight
    raw_w = get_item_weight(raw_id)
    low_w = get_item_weight(lower_id) if lower_id else 0.0
    out_w = get_item_weight(refined_id)

    needed_raw = simulate_reverse_starting_materials(crafts, ref_rrr, ratio=raw_ratio)
    needed_lower = simulate_reverse_starting_materials(crafts, ref_rrr, ratio=lower_ratio) if lower_id else 0

    haul_in_w = (needed_raw * raw_w) + (needed_lower * low_w)
    haul_out_w = actual_output_units * out_w
    max_leg_weight = max(haul_in_w, haul_out_w)

    if config["max_weight"] > 0 and max_leg_weight > config["max_weight"]:
        return None, "OVERWEIGHT"

    acq_raw, cost_raw, alloc_raw = walk_multi_city_asks(raw_id, needed_raw, city_markets, allowed_cities=allowed_cities)
    if acq_raw < needed_raw:
        return None, "NO_STOCK_RAW"

    cost_lower = 0.0
    alloc_lower = []
    if lower_id and needed_lower > 0:
        acq_low, cost_low, alloc_low = walk_multi_city_asks(lower_id, needed_lower, city_markets, allowed_cities=[specialty_city])
        if acq_low < needed_lower:
            acq_low, cost_low, alloc_low = walk_multi_city_asks(lower_id, needed_lower, city_markets, allowed_cities=allowed_cities)
            if acq_low < needed_lower:
                return None, "NO_STOCK_LOWER"
        cost_lower = cost_low
        alloc_lower = alloc_low

    ench_mult = (2 ** ench)
    base_val = BASE_ITEM_VALUES.get(tier, 32) * ench_mult
    nutrition = base_val * NUTRITION_FACTOR * actual_output_units
    station_fee = (nutrition / 100.0) * config["refine_fee_per_100"]

    total_cost = cost_raw + cost_lower + station_fee
    if config["max_budget"] > 0 and total_cost > config["max_budget"]:
        return None, "OVERBUDGET"

    if dest_mode == "INSTANT_BUY_ORDER":
        filled, gross = walk_market_bids(q_data, max_qty=actual_output_units)
        if filled < actual_output_units:
            return None, "INSUFFICIENT_BUY_DEMAND"
        net_revenue = gross * (1.0 - config["tax_instant_fill"])
    else:
        net_revenue = (dest_price * actual_output_units) * (1.0 - config["tax_sell_order"])

    net_profit = net_revenue - total_cost
    roi = (net_profit / total_cost) * 100.0 if total_cost > 0 else 0.0
    silver_per_kg = (net_profit / max_leg_weight) if max_leg_weight > 0 else 0

    solution = {
        "refined_id": refined_id,
        "res_type": res_type,
        "tier_str": f"T{tier}.{ench}",
        "batch_size": actual_output_units,
        "refining_city": specialty_city,
        "ref_rrr": ref_rrr * 100.0,
        "dest_mode": dest_mode,
        "dest_price": dest_price,
        "revenue": net_revenue,
        "cost": total_cost,
        "profit": net_profit,
        "roi": roi,
        "weight": max_leg_weight,
        "silver_per_kg": silver_per_kg,
        "raw_id": raw_id,
        "needed_raw": needed_raw,
        "cost_raw": cost_raw,
        "alloc_raw": alloc_raw,
        "lower_id": lower_id,
        "needed_lower": needed_lower,
        "cost_lower": cost_lower,
        "alloc_lower": alloc_lower,
        "station_fee": station_fee
    }
    return solution, "OK"

def solve_refining_route(refined_id, recipe_tuple, target_units, dest_city, dest_mode, dest_price, dest_gross, q_data, city_markets, config, use_focus, execution_note=""):
    res_type = recipe_tuple[0]
    specialty_city = REFINING_SPECIALTY[res_type]["city"]
    ref_rrr = calculate_rrr(BONUS_BASE_ROYAL_CITY + BONUS_LOCAL_REFINING, use_focus)
    allowed_cities = get_allowed_sourcing_cities(specialty_city, dest_city, mode=config["sourcing_mode"])

    low = 5
    high = target_units
    best_candidate = None

    sol, status = evaluate_batch(high, refined_id, recipe_tuple, dest_mode, dest_price, dest_gross, q_data, city_markets, config, specialty_city, allowed_cities, ref_rrr)
    if sol and sol["profit"] >= config["min_profit"] and sol["roi"] >= config["min_roi"]:
        sol.update({"dest_city": dest_city, "use_focus": use_focus, "execution_note": execution_note})
        return sol

    while low <= high:
        mid = (low + high) // 2
        sol, status = evaluate_batch(mid, refined_id, recipe_tuple, dest_mode, dest_price, dest_gross, q_data, city_markets, config, specialty_city, allowed_cities, ref_rrr)
        if sol:
            if sol["profit"] >= config["min_profit"] and sol["roi"] >= config["min_roi"]:
                best_candidate = sol
                low = mid + 1
            else:
                high = mid - 1
        else:
            high = mid - 1

    if best_candidate:
        best_candidate.update({
            "dest_city": dest_city,
            "use_focus": use_focus,
            "execution_note": execution_note
        })
        return best_candidate

    return None

# ==============================================================================
#  MAIN EXECUTION PIPELINE
# ==============================================================================

def main():
    config = prompt_user_config()
    city_markets = load_all_market_summaries()

    all_items = set()
    for m in city_markets.values():
        all_items.update(m.keys())

    refined_candidates = []
    for itype in all_items:
        recipes = build_refining_recipes_for_item(itype)
        for r in recipes:
            refined_candidates.append((itype, r))

    budget_str = f"{config['max_budget']:,.0f} silver" if config["max_budget"] > 0 else "UNLIMITED"
    print(f"\n[*] Identified {len(refined_candidates)} strictly validated refineable recipe pathways.")
    print(f"[*] Solving with Reality Anchors active | Sourcing: {config['sourcing_mode']} | Hard Cap: {budget_str}...\n")

    plans = []

    for refined_id, recipe_tuple in refined_candidates:
        res_type, tier, ench, raw_id, raw_ratio, lower_id, lower_ratio, block_mult = recipe_tuple

        for city, c_data in city_markets.items():
            q_data = c_data.get(refined_id, {}).get("qualities", {}).get("Normal")
            if not q_data:
                continue

            sell_p = float(q_data.get("lowest_sell_price") or 0)
            stock = int(float(q_data.get("total_sell_stock") or 0))
            vel = float(q_data.get("daily_volume_velocity") or 0)
            hb = float(q_data.get("highest_buy_order") or 0)
            demand = int(float(q_data.get("total_buy_demand") or 0))

            avg_28d = float(
                q_data.get("history_28d_avg_price") 
                or q_data.get("avg_price_28d") 
                or q_data.get("price_avg_28d") 
                or 0
            )

            # Channel 1: Instant Dump into Buy Orders
            if hb > 0 and demand > 0:
                filled, gross_payout = walk_market_bids(q_data, max_qty=demand)
                if filled >= 5:
                    p = solve_refining_route(
                        refined_id, recipe_tuple, filled, city, "INSTANT_BUY_ORDER",
                        hb, gross_payout, q_data, city_markets, config, use_focus=(config["focus_budget"] > 0)
                    )
                    if p:
                        plans.append(p)

            # Channel 2: Sell Order Ladder (With Reality Anchor & FIFO Aggregator)
            if sell_p > 0:
                if hb > 0 and sell_p > (hb * 2.2):
                    continue

                effective_sell_price = sell_p
                note = ""
                if avg_28d > 0 and sell_p > (avg_28d * MAX_PRICE_OVERHANG_RATIO):
                    effective_sell_price = avg_28d * 1.15
                    note = f" (Anchored from {sell_p:,.0f}s spike to {effective_sell_price:,.0f}s)"

                holding_mult = config["holding_days"]
                daily_absorbable = vel * MAX_DAILY_VOLUME_SHARE if vel >= 1.0 else 5.0
                target_batch = max(5, int(daily_absorbable * holding_mult))

                sell_orders = q_data.get("sell_orders") or q_data.get("sell_ladder") or []
                if sell_orders and not note:
                    first_o = sell_orders[0]
                    lowest_ask = first_o[0] if isinstance(first_o, (list, tuple)) else first_o.get("unit_price", 0)

                    total_qty_at_lowest = sum(
                        (o[1] if isinstance(o, (list, tuple)) else o.get("amount", 0))
                        for o in sell_orders
                        if abs((o[0] if isinstance(o, (list, tuple)) else o.get("unit_price", 0)) - lowest_ask) < 0.001
                    )

                    wall_threshold = max(100, int(vel * 0.20)) if vel > 0 else 200
                    if total_qty_at_lowest >= wall_threshold and lowest_ask > 1:
                        effective_sell_price = lowest_ask - 1.0
                        note = f" (Undercuts {total_qty_at_lowest:,}u wall by 1s)"

                p = solve_refining_route(
                    refined_id, recipe_tuple, target_batch, city, "SELL_ORDER_LADDER",
                    effective_sell_price, effective_sell_price * target_batch, q_data, city_markets, config,
                    use_focus=(config["focus_budget"] > 0), execution_note=note
                )
                if p:
                    plans.append(p)

    plans.sort(key=lambda x: x["profit"], reverse=True)

    lines = []
    def out(text=""):
        print(text)
        lines.append(text)

    out("\n" + "=" * 135)
    out(f"       ALBION REFINING & INDUSTRIAL SUPPLY-CHAIN REPORT (V3.3 - PRODUCTION VERIFIED)")
    out(f"       Mode: {'ACTIVE PREMIUM (4% Tax)' if config['is_premium'] else 'NON-PREMIUM (8% Tax + 2.5% Setup)'} | Sourcing: {config['sourcing_mode']} | Budget: {budget_str}")
    out("=" * 135)

    if not plans:
        out("\n[-] No refining routes matched your criteria within the configured budget and corridor constraints.")
    else:
        out(f"{'Resource Output':<24} | {'Tier':<5} | {'Refine @':<13} | {'Sell To':<14} | {'Channel':<13} | {'Yield':>6} | {'Total Cost':>11} | {'Net Profit':>11} | {'ROI%':>6} | {'s/kg':>7}")
        out("-" * 135)
        for p in plans[:20]:
            chan = "Instant Dump" if p["dest_mode"] == "INSTANT_BUY_ORDER" else "Sell Order"
            out(f"{p['refined_id']:<24} | {p['tier_str']:<5} | {p['refining_city']:<13} | {p['dest_city']:<14} | {chan:<13} | {p['batch_size']:>5}u | {p['cost']:>10,.0f}s | {p['profit']:>+10,.0f}s | {p['roi']:>5.1f}% | {p['silver_per_kg']:>7,.0f}")

        out("\n" + "=" * 135)
        out(f"  🚀 TOP STEP-BY-STEP REFINING EXECUTION PLANS (BUDGET: {budget_str})")
        out("=" * 135)

        for idx, p in enumerate(plans[:5], 1):
            chan_str = "Instant Fill Buy Orders" if p["dest_mode"] == "INSTANT_BUY_ORDER" else f"List on Sell Ladder @ {p['dest_price']:,.0f}s{p['execution_note']}"
            red_zone_warn = " ⚠️ [RED ZONE TRANSPORT - LETHAL FULL LOOT ZONE]" if p["dest_city"] in ["Caerleon", "Black Market"] else ""

            out(f"\n[REFINING PLAN #{idx}]: {p['batch_size']:,}x {p['refined_id']} ({p['tier_str']}){red_zone_warn}")
            out(f"  • Destination Market:  [{p['dest_city']}] via {chan_str}")
            out(f"  • Total Net Revenue:   {p['revenue']:>12,.0f} silver")
            out(f"  • Total Sourcing Cost: {p['cost']:>12,.0f} silver (Includes {p['station_fee']:,.0f}s station usage fee)")
            out(f"  • NET PROFIT:          {p['profit']:>+12,.0f} silver (Net ROI: {p['roi']:.1f}%)")
            out(f"  • Max Haul Weight:     {p['weight']:>8.1f} kg ({p['silver_per_kg']:,.0f} s/kg)")
            out(f"  • Refining Bonus City: [{p['refining_city']}] (Local RRR: {p['ref_rrr']:.1f}%)")
            out("  -------------------------------------------------------------------------------------------------")
            out("  EXECUTION STEP-BY-STEP ITINERARY:")

            city_shopping = {}
            for lot in p["alloc_raw"]:
                c = lot["city"]
                key = (c, p["raw_id"])
                city_shopping.setdefault(key, {"amount": 0, "cost": 0.0, "prices": []})
                city_shopping[key]["amount"] += lot["amount"]
                city_shopping[key]["cost"] += lot["cost"]
                city_shopping[key]["prices"].append(lot["unit_price"])

            for lot in p["alloc_lower"]:
                c = lot["city"]
                key = (c, p["lower_id"])
                city_shopping.setdefault(key, {"amount": 0, "cost": 0.0, "prices": []})
                city_shopping[key]["amount"] += lot["amount"]
                city_shopping[key]["cost"] += lot["cost"]
                city_shopping[key]["prices"].append(lot["unit_price"])

            grouped = {}
            for (c, item_name), data in city_shopping.items():
                grouped.setdefault(c, []).append({
                    "item": item_name,
                    "amount": data["amount"],
                    "cost": data["cost"],
                    "vwap": data["cost"] / data["amount"] if data["amount"] > 0 else 0,
                    "min_p": min(data["prices"]),
                    "max_p": max(data["prices"])
                })

            out("\n  STEP 1: PROCUREMENT (Consolidated Shopping List):")
            for city, items in grouped.items():
                out(f"    • Travel to [{city}]:")
                for itm in items:
                    p_str = f"@ {itm['vwap']:,.0f}s" if itm["min_p"] == itm["max_p"] else f"(VWAP: {itm['vwap']:,.0f}s | Range: {itm['min_p']:,.0f}s - {itm['max_p']:,.0f}s)"
                    out(f"        - Buy {itm['amount']:,}x {itm['item']} {p_str} -> Subtotal: {itm['cost']:,.0f}s")

            out(f"\n  STEP 2: REFINING LEG [{p['refining_city']}]:")
            out(f"    • Haul materials to [{p['refining_city']}] Station:")
            out(f"        - Refine {p['needed_raw']:,}x {p['raw_id']}" + (f" + {p['needed_lower']:,}x {p['lower_id']}" if p['lower_id'] else ""))
            out(f"        - Yield with {p['ref_rrr']:.1f}% RRR: {p['batch_size']:,}x {p['refined_id']}")

            out(f"\n  STEP 3: TRANSPORT & CASH OUT [{p['dest_city']}]:")
            out(f"    • Haul {p['batch_size']:,} refined resources to [{p['dest_city']}]:")
            out(f"        - {chan_str}")
            out(f"        - Collect Net Silver: {p['revenue']:,.0f}s (Net Profit: {p['profit']:>+,.0f}s)")
            out("=" * 135)

    try:
        with open(OUTPUT_MD, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\n[+] Reality-anchored refining plan saved to: {OUTPUT_MD}\n")
    except Exception as e:
        print(f"[!] Warning: Could not save report: {e}")

if __name__ == "__main__":
    main()