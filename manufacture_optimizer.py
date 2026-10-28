#!/usr/bin/env python3
"""
Albion Online - Industrial Manufacturing & Supply-Chain Engine (V9.0 - Outlands & Black Zone Edition)
====================================================================================================
Features:
- Full Black Zone (Outlands) Hideout & HQ bonus solver (Zone Quality 1-6 + Power Core bonuses).
- Synchronized Joint Batch Simulator: Solves raw + lower-tier catalyst returns together without desync.
- Logistics Hub Guard: Restricts procurement to <= 2 cities or direct corridor travel.
- Dual-Leg Mount Cargo Limits: Tracks both heavy raw material haul & finished equipment transport.
- Black Market Reality Anchors: Caps instant dumps and ladder listings by actual 28-day velocity & depth.
- Separate Station Usage Fees (Refining vs Crafting vs BZ Hideout Tribute).
"""

import glob
import json
import math
import os
import sys

# ==============================================================================
#  ALBION GAME ENGINE BALANCE CONSTANTS
# ==============================================================================

# 1. TAXES & TRANSACTION FEES
TAX_PREMIUM_SALES     = 0.040   # 4.0% sales tax with Premium
TAX_PREMIUM_SETUP     = 0.025   # 2.5% listing setup fee with Premium
TAX_NON_PREM_SALES    = 0.080   # 8.0% sales tax without Premium
TAX_NON_PREM_SETUP    = 0.025   # 2.5% listing setup fee without Premium
TAX_INSTANT_FILL_PREM = 0.040   # 4.0% flat tax on filling buy orders (Premium)
TAX_INSTANT_FILL_NP   = 0.080   # 8.0% flat tax on filling buy orders (Non-Premium)

# 2. PRODUCTION BONUSES
BONUS_BASE_ROYAL_CITY = 18.0    # Base 18% production bonus in Royal Cities
BONUS_LOCAL_REFINING  = 40.0    # +40% local city refining bonus (Total: 58%)
BONUS_LOCAL_CRAFTING  = 15.0    # +15% local city crafting bonus (Total: 33%)
BONUS_FOCUS_BOOST     = 59.0    # Focus adds +59% to the production bonus pool

# Black Zone Hideout Bonus Scale by Zone Quality (Level 1 to 6)
# Format: {ZoneQuality: Base_Bonus_Pct}
BZ_HO_BONUS_TABLE = {
    1: 20.0,
    2: 25.0,
    3: 32.0,
    4: 40.0,
    5: 48.0,
    6: 58.0
}
BZ_HQ_EXTRA_BONUS = 7.0         # Additional bonus if Hideout is an approved Headquarters

# 3. STATION NUTRITION & ITEM VALUES
NUTRITION_FACTOR      = 0.1125  # Nutrition consumed = item_value * 0.1125
RAW_RATIO_BY_TIER     = {2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 5, 8: 5}
BASE_ITEM_VALUES      = {2: 8, 3: 16, 4: 32, 5: 64, 6: 128, 7: 256, 8: 512}

# 4. SPECIALTY CITY MAPPING
REFINING_BONUS_CITIES = {
    "ORE": "Thetford",         "METALBAR": "Thetford",
    "WOOD": "Fort Sterling",   "PLANKS": "Fort Sterling",
    "FIBER": "Lymhurst",       "CLOTH": "Lymhurst",
    "HIDE": "Martlock",        "LEATHER": "Martlock",
    "ROCK": "Bridgewatch",     "STONEBLOCK": "Bridgewatch"
}

CRAFTING_BONUS_MAP = {
    "Thetford":      ["BOW", "NATURESTAFF", "FIRESTAFF", "ARMOR_LEATHER", "HEAD_CLOTH"],
    "Fort Sterling": ["HAMMER", "SPEAR", "HOLYSTAFF", "ARMOR_PLATE", "SHOES_CLOTH"],
    "Lymhurst":      ["SWORD", "BOW", "ARCANESTAFF", "HEAD_LEATHER", "SHOES_LEATHER"],
    "Bridgewatch":   ["CROSSBOW", "DAGGER", "CURSESTAFF", "ARMOR_PLATE", "ARMOR_CLOTH"],
    "Martlock":      ["AXE", "QUARTERSTAFF", "FROSTSTAFF", "SHOES_PLATE", "SHIELD", "OFF"]
}

REFINED_PATTERNS = ["_METALBAR", "_LEATHER", "_PLANKS", "_CLOTH", "_STONEBLOCK"]
ROYAL_RING = ["Martlock", "Bridgewatch", "Lymhurst", "Fort Sterling", "Thetford"]

# ==============================================================================
#  DATA INGESTION & PATH RESOLUTION
# ==============================================================================

POSSIBLE_BASE_DIRS = [
    r"C:\Users\SID\Desktop\albion",
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
OUTPUT_MD = os.path.join(SAVES_DIR, "manufacturing_plan.md")

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
    if "ARMOR" in item_id:
        return 7.5
    if "HEAD" in item_id or "HELMET" in item_id:
        return 2.5
    if "SHOES" in item_id:
        return 2.5
    if "LEATHER" in item_id or "HIDE" in item_id:
        return 0.76 if tier >= 5 else 0.51
    return 1.5

def detect_city_name(filename, market_type=""):
    fn = os.path.basename(filename).lower()
    if "bm" in fn or "black" in fn or "blackmarket" in fn or market_type == "Caerleon Black Market":
        return "Black Market"
    for c in ["Thetford", "Fort Sterling", "Lymhurst", "Bridgewatch", "Martlock", "Caerleon"]:
        if c.lower().replace(" ", "") in fn.replace("_", "").replace(" ", ""):
            return c
    return os.path.basename(filename).split('_')[0].capitalize()

def load_all_market_summaries():
    json_files = glob.glob(os.path.join(SAVES_DIR, "*_summary.json"))
    if not json_files:
        json_files = glob.glob("*_summary.json")

    if not json_files:
        print(f"[!] Error: No '*_summary.json' files found in '{SAVES_DIR}'.")
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
            print(f"    [!] Error loading {os.path.basename(fpath)}: {e}")

    for c in sorted(city_markets.keys()):
        print(f"    [+] Indexed [{c}] ({len(city_markets[c]):,} items)")
    return city_markets

# ==============================================================================
#  MATHEMATICAL SOLVERS (JOINT RECYCLING & RRR)
# ==============================================================================

def calculate_rrr(base_bonus_pct, is_focus=False, daily_bonus_pct=0, hideout_bonus_pct=0):
    total_bonus = base_bonus_pct + daily_bonus_pct + hideout_bonus_pct
    if is_focus:
        total_bonus += BONUS_FOCUS_BOOST
    bonus_fraction = total_bonus / 100.0
    return bonus_fraction / (1.0 + bonus_fraction)

def simulate_crafting_seed(target_equipment, craft_rrr, items_per_craft=1):
    """
    Reverse-solves for single material pool crafting.
    """
    if target_equipment <= 0:
        return 0
    if craft_rrr <= 0:
        return target_equipment * items_per_craft

    seed = max(items_per_craft, int(target_equipment * items_per_craft * (1.0 - craft_rrr)))
    while True:
        produced = 0
        curr = seed
        while curr >= items_per_craft:
            batches = curr // items_per_craft
            produced += batches
            returned = math.floor(batches * items_per_craft * craft_rrr)
            leftover = curr % items_per_craft
            curr = leftover + returned
            if returned == 0:
                break
        if produced >= target_equipment:
            return seed
        seed += 1

def simulate_joint_refine_materials(target_refined_units, ref_rrr, raw_ratio, lower_ratio=1):
    """
    CRITICAL FIX: Synchronized dual-resource simulation.
    Refining consumes raw_ratio * N and lower_ratio * N in strict unison.
    """
    if target_refined_units <= 0:
        return 0, 0
    if ref_rrr <= 0:
        return target_refined_units * raw_ratio, target_refined_units * lower_ratio

    crafts_needed = target_refined_units
    seed_crafts = max(1, int(crafts_needed * (1.0 - ref_rrr)))

    while True:
        produced = 0
        curr_raw = seed_crafts * raw_ratio
        curr_low = seed_crafts * lower_ratio

        while curr_raw >= raw_ratio and curr_low >= lower_ratio:
            batches = min(curr_raw // raw_ratio, curr_low // lower_ratio)
            produced += batches

            ret_raw = math.floor(batches * raw_ratio * ref_rrr)
            ret_low = math.floor(batches * lower_ratio * ref_rrr)

            left_raw = curr_raw - (batches * raw_ratio)
            left_low = curr_low - (batches * lower_ratio)

            curr_raw = left_raw + ret_raw
            curr_low = left_low + ret_low

            if ret_raw == 0 and ret_low == 0:
                break

        if produced >= target_refined_units:
            return seed_crafts * raw_ratio, seed_crafts * lower_ratio
        seed_crafts += 1

# ==============================================================================
#  ORDER-BOOK DEPTH WALKING
# ==============================================================================

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

        sell_orders = q_data.get("sell_orders", [])
        for o in sell_orders:
            p, a = 0, 0
            if isinstance(o, dict):
                p = o.get("unit_price") or o.get("price") or 0
                a = o.get("amount") or o.get("count") or 0
            elif isinstance(o, (list, tuple)) and len(o) >= 2:
                p, a = o[0], o[1]
            if p > 0 and a > 0:
                all_lots.append({"city": city, "price": float(p), "amount": int(a)})

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

# ==============================================================================
#  USER CONFIGURATION PROMPT
# ==============================================================================

def prompt_user_config():
    print("\n" + "=" * 90)
    print("   ALBION INDUSTRIAL SUPPLY-CHAIN & MANUFACTURING ENGINE (V9.0 - OUTLANDS EDITION)")
    print("=" * 90)

    p_in = input("[1] Active PREMIUM Account? (Y/N) [Default: Y]: ").strip().upper()
    is_premium = (p_in != "N")
    tax_sales = TAX_PREMIUM_SALES if is_premium else TAX_NON_PREM_SALES
    tax_setup = TAX_PREMIUM_SETUP if is_premium else TAX_NON_PREM_SETUP
    tax_sell_order = tax_sales + tax_setup
    tax_instant_fill = TAX_INSTANT_FILL_PREM if is_premium else TAX_INSTANT_FILL_NP

    f_budget_in = input("[2] FOCUS BUDGET to spend [0 for No Focus | Default: 0]: ").strip()
    focus_budget = int(f_budget_in) if f_budget_in.isdigit() else 0

    focus_mode = "AUTO"
    if focus_budget > 0:
        print("    -> Focus Allocation Target:")
        print("       [1] Auto-Allocate (Highest profit efficiency)")
        print("       [2] Refining ONLY | [3] Crafting ONLY | [4] Force BOTH")
        m_in = input("       Select [1-4, Default: 1]: ").strip()
        if m_in == "2": focus_mode = "REFINE_ONLY"
        elif m_in == "3": focus_mode = "CRAFT_ONLY"
        elif m_in == "4": focus_mode = "BOTH"

    # Production Location (Royal vs Caerleon vs Black Zone Outlands)
    print("\n[3] Primary CRAFTING LOCATION:")
    print("    [1] Royal Cities (Local City Bonus +15%)")
    print("    [2] Caerleon (Base 18% - Heavy Red Zone Focus)")
    print("    [3] Black Zone Hideout (Outlands)")
    loc_in = input("    Choose [1-3, Default: 1]: ").strip()
    location_mode = "ROYAL"
    bz_quality = 1
    is_hq = False
    if loc_in == "2":
        location_mode = "CAERLEON"
    elif loc_in == "3":
        location_mode = "BLACK_ZONE"
        zq_in = input("    -> Black Zone Quality Level (1 to 6) [Default: 4]: ").strip()
        bz_quality = int(zq_in) if zq_in in ("1","2","3","4","5","6") else 4
        hq_in = input("    -> Is this an approved Headquarters (HQ)? (Y/N) [Default: Y]: ").strip().upper()
        is_hq = (hq_in != "N")

    # Logistics Hub Restriction
    print("\n[4] SOURCING LOGISTICS RESTRICTION:")
    print("    [1] Max 2 Cities (Realistic player transport route) [Default]")
    print("    [2] Single Hub Only (All materials bought in 1 city)")
    print("    [3] Global (Free market hopping - Theoretical)")
    src_in = input("    Choose [1-3, Default: 1]: ").strip()
    sourcing_mode = "DUAL_HUB"
    if src_in == "2": sourcing_mode = "SINGLE_HUB"
    elif src_in == "3": sourcing_mode = "GLOBAL"

    w_in = input("\n[5] Max MOUNT CARRY WEIGHT in kg [e.g. 800 (Ox), 2500 (T6 Ox), 0 for No Limit]: ").strip()
    try:
        max_weight = float(w_in) if w_in else 0.0
    except ValueError:
        max_weight = 0.0

    b_in = input("[6] Maximum SILVER INVESTMENT BUDGET [Default: 5,000,000 | 0 for Unlimited]: ").strip()
    try:
        max_budget = float(b_in) if b_in else 5000000.0
    except ValueError:
        max_budget = 5000000.0

    fee_ref_in = input("[7] Refining Station Fee per 100 nutrition [Default: 500]: ").strip()
    refine_fee_per_100 = float(fee_ref_in) if fee_ref_in else 500.0

    fee_craft_in = input("[8] Crafting Station Fee per 100 nutrition (Enter 0 for BZ Hideout) [Default: 1200]: ").strip()
    craft_fee_per_100 = float(fee_craft_in) if fee_craft_in else 1200.0

    profit_in = input("[9] Minimum NET PROFIT threshold to display [Default: 100000]: ").strip()
    min_profit = float(profit_in) if profit_in else 100000.0

    print("=" * 90 + "\n")
    return {
        "is_premium": is_premium,
        "tax_sell_order": tax_sell_order,
        "tax_instant_fill": tax_instant_fill,
        "focus_budget": focus_budget,
        "focus_mode": focus_mode,
        "location_mode": location_mode,
        "bz_quality": bz_quality,
        "is_hq": is_hq,
        "sourcing_mode": sourcing_mode,
        "max_weight": max_weight,
        "max_budget": max_budget,
        "refine_fee_per_100": refine_fee_per_100,
        "craft_fee_per_100": craft_fee_per_100,
        "min_profit": min_profit
    }

# ==============================================================================
#  PIECEWISE CRAFTING & SUPPLY CHAIN SOLVER
# ==============================================================================

def solve_manufacturing_route(item_id, target_batch, expected_rev_per_u, sell_path, baseline_q, db_meta,
                               crafting_info, upgrade_info, city_markets, config, focus_strat, allowed_cities=None):
    use_ref_focus = focus_strat in ('BOTH', 'REFINE_ONLY')
    use_craft_focus = focus_strat in ('BOTH', 'CRAFT_ONLY')

    # Determine Crafting Location and Bonus
    if config["location_mode"] == "BLACK_ZONE":
        crafting_city = f"BZ Hideout (Q{config['bz_quality']}{' HQ' if config['is_hq'] else ''})"
        base_craft_bonus = BZ_HO_BONUS_TABLE.get(config["bz_quality"], 40.0)
        if config["is_hq"]:
            base_craft_bonus += BZ_HQ_EXTRA_BONUS
    elif config["location_mode"] == "CAERLEON":
        crafting_city = "Caerleon"
        base_craft_bonus = BONUS_BASE_ROYAL_CITY
    else:
        crafting_city = "Caerleon"
        base_craft_bonus = BONUS_BASE_ROYAL_CITY
        for c_name, cat_list in CRAFTING_BONUS_MAP.items():
            if any(k in item_id for k in cat_list):
                crafting_city = c_name
                base_craft_bonus = BONUS_BASE_ROYAL_CITY + BONUS_LOCAL_CRAFTING
                break

    craft_rrr = calculate_rrr(base_craft_bonus, use_craft_focus)
    materials_plan = []
    total_production_cost = 0.0
    total_focus_used = 0
    total_inbound_weight = 0.0

    if use_craft_focus:
        base_craft_focus = crafting_info.get("focus", 0)
        total_focus_used += base_craft_focus * target_batch

    for req in crafting_info["resources"]:
        mat_id = req["item"]
        mat_ratio = req["count"]
        is_artifact = ("ARTEFACT" in mat_id or "TOKEN" in mat_id)

        if is_artifact:
            needed_art = target_batch * mat_ratio
            acq, cost, alloc = walk_multi_city_asks(mat_id, needed_art, city_markets, allowed_cities=allowed_cities)
            if acq < needed_art:
                return None
            w_art = get_item_weight(mat_id) * needed_art
            total_inbound_weight += w_art
            total_production_cost += cost
            materials_plan.append({
                "item": mat_id,
                "type": "ARTIFACT",
                "needed": needed_art,
                "cost": cost,
                "alloc": alloc,
                "path": "Direct Buy"
            })
        else:
            seed_refined = simulate_crafting_seed(target_batch, craft_rrr, items_per_craft=mat_ratio)
            acq_ref, cost_ref, alloc_ref = walk_multi_city_asks(mat_id, seed_refined, city_markets, allowed_cities=allowed_cities)

            # Check Refining Feasibility
            ref_db = ITEMS_DB.get(mat_id)
            ref_recipe = ref_db.get("crafting", {}).get("resources", []) if ref_db else []
            can_refine = len(ref_recipe) >= 2 and any(p in mat_id for p in REFINED_PATTERNS)

            refining_feasible = False
            raw_cost_total = 0.0
            raw_alloc_details = []
            ref_city = "Martlock"

            if can_refine:
                res_type = next((k for k in REFINING_BONUS_CITIES if k in mat_id), "LEATHER")
                ref_city = REFINING_BONUS_CITIES.get(res_type, "Martlock")

                if config["location_mode"] == "BLACK_ZONE":
                    ref_bonus = BZ_HO_BONUS_TABLE.get(config["bz_quality"], 40.0)
                    if config["is_hq"]: ref_bonus += BZ_HQ_EXTRA_BONUS
                    ref_city = crafting_city
                else:
                    ref_bonus = BONUS_BASE_ROYAL_CITY + BONUS_LOCAL_REFINING

                ref_rrr = calculate_rrr(ref_bonus, use_ref_focus)

                raw_elem = ref_recipe[0]
                low_elem = ref_recipe[1]
                needed_raw, needed_low = simulate_joint_refine_materials(seed_refined, ref_rrr, raw_elem["count"], low_elem["count"])

                acq_raw, c_raw, a_raw = walk_multi_city_asks(raw_elem["item"], needed_raw, city_markets, allowed_cities=allowed_cities)
                acq_low, c_low, a_low = walk_multi_city_asks(low_elem["item"], needed_low, city_markets, allowed_cities=allowed_cities)

                if acq_raw >= needed_raw and acq_low >= needed_low:
                    tier_char = 4
                    if len(mat_id) >= 2 and mat_id[1].isdigit():
                        tier_char = int(mat_id[1])
                    ench_val = int(mat_id.split("@")[1]) if "@" in mat_id else 0
                    base_v = BASE_ITEM_VALUES.get(tier_char, 32) * (2 ** ench_val)
                    ref_nut = base_v * NUTRITION_FACTOR * seed_refined
                    ref_fee = (ref_nut / 100.0) * config["refine_fee_per_100"]

                    raw_cost_total = c_raw + c_low + ref_fee
                    refining_feasible = True
                    raw_alloc_details = [
                        {"ingredient": raw_elem["item"], "needed": needed_raw, "cost": c_raw, "alloc": a_raw},
                        {"ingredient": low_elem["item"], "needed": needed_low, "cost": c_low, "alloc": a_low}
                    ]

            # Choose optimal sourcing branch
            if refining_feasible and (acq_ref < seed_refined or raw_cost_total < cost_ref):
                chosen_cost = raw_cost_total
                f_tag = " + Focus" if use_ref_focus else ""
                path_str = f"Refine Raw @ {ref_city} (RRR: {ref_rrr*100:.1f}%{f_tag})"
                chosen_alloc = raw_alloc_details
                for ing in raw_alloc_details:
                    total_inbound_weight += get_item_weight(ing["ingredient"]) * ing["needed"]
                if use_ref_focus:
                    base_ref_focus = ref_db.get("crafting", {}).get("focus", 0)
                    total_focus_used += base_ref_focus * seed_refined
            elif acq_ref >= seed_refined:
                chosen_cost = cost_ref
                path_str = "Buy Refined Directly"
                chosen_alloc = alloc_ref
                total_inbound_weight += get_item_weight(mat_id) * seed_refined
            else:
                return None

            materials_plan.append({
                "item": mat_id,
                "type": "REFINED",
                "needed": seed_refined,
                "cost": chosen_cost,
                "alloc": chosen_alloc,
                "path": path_str,
                "best_refine_city": ref_city
            })
            total_production_cost += chosen_cost

    # Station Crafting Fees
    tier_num = db_meta.get("tier", 4)
    ench_num = int(item_id.split("@")[1]) if "@" in item_id else 0
    item_v = db_meta.get("item_value") or (BASE_ITEM_VALUES.get(tier_num, 32) * (2 ** ench_num) * 4)

    nutrition_craft = item_v * NUTRITION_FACTOR * target_batch
    craft_fee = (nutrition_craft / 100.0) * config["craft_fee_per_100"]
    total_production_cost += craft_fee

    if config["max_budget"] > 0 and total_production_cost > config["max_budget"]:
        return None

    # Cargo Weight Guard
    unit_w = get_item_weight(item_id)
    total_equipment_weight = target_batch * unit_w
    max_route_weight = max(total_inbound_weight, total_equipment_weight)

    if config["max_weight"] > 0 and max_route_weight > config["max_weight"]:
        return None

    total_rev = expected_rev_per_u * target_batch
    profit = total_rev - total_production_cost
    roi = (profit / total_production_cost) * 100.0 if total_production_cost > 0 else 0
    s_per_f = (profit / total_focus_used) if total_focus_used > 0 else 0
    s_per_kg = (profit / max_route_weight) if max_route_weight > 0 else 0

    return {
        "item_id": item_id,
        "item_name": db_meta.get("name", item_id),
        "baseline_quality": baseline_q.get("quality_name", "Normal"),
        "tier": f"T{tier_num}.{ench_num}",
        "batch_size": target_batch,
        "revenue": total_rev,
        "cost": total_production_cost,
        "profit": profit,
        "roi": roi,
        "focus_used": total_focus_used,
        "silver_per_focus": s_per_f,
        "focus_strategy": focus_strat,
        "max_haul_weight": max_route_weight,
        "silver_per_kg": s_per_kg,
        "sell_path": sell_path,
        "crafting_city": crafting_city,
        "craft_rrr": craft_rrr * 100.0,
        "materials": materials_plan
    }

# ==============================================================================
#  MAIN DRIVER
# ==============================================================================

def main():
    config = prompt_user_config()
    city_markets = load_all_market_summaries()

    if "Black Market" not in city_markets:
        print("[!] Critical: No 'Black Market' summary found in 'saves_here'.")
        sys.exit(1)

    bm_items = city_markets["Black Market"]
    budget = config["focus_budget"]
    plans = []

    print(f"[*] Solving Multivariable DAG across {len(bm_items)} Black Market targets...")

    for item_id, item_data in bm_items.items():
        base_id = item_id.split("@")[0]
        db_meta = ITEMS_DB.get(item_id) or ITEMS_DB.get(base_id)
        if not db_meta:
            continue

        crafting_info = db_meta.get("crafting")
        upgrade_info = None

        if "@" in item_id:
            elvl = item_id.split("@")[1]
            ench_dict = ITEMS_DB.get(base_id, {}).get("enchantments", {}).get(elvl, {})
            crafting_info = ench_dict.get("crafting") or crafting_info
            upgrade_info = ench_dict.get("upgrade_with_runes")

        if not crafting_info or not crafting_info.get("resources"):
            continue

        qualities = item_data.get("qualities", {})
        baseline_q = qualities.get("Normal") or qualities.get("Good")
        if not baseline_q:
            continue

        bm_bid = baseline_q.get("highest_buy_order") or 0
        bm_ask = baseline_q.get("lowest_sell_price") or 0
        bm_demand = baseline_q.get("total_buy_demand") or 0
        bm_vel = baseline_q.get("daily_volume_velocity") or 0.0

        horizons = []

        # 1. Instant Buy Order Dump (Controlled for Liquidity)
        if bm_bid > 0 and bm_demand > 0:
            filled_units, gross_val = walk_market_bids(baseline_q, max_qty=bm_demand)
            # Safe absorption throttle: Do not dump more than 40% of 1 day's velocity in one haul
            max_safe_dump = max(1, int(bm_vel * 0.40)) if bm_vel >= 2.0 else 2
            safe_units = min(filled_units, max_safe_dump, 15)
            if safe_units > 0:
                payout_per_u = (gross_val / filled_units) * (1.0 - config["tax_instant_fill"])
                horizons.append({
                    "batch_size": safe_units,
                    "revenue_per_u": payout_per_u,
                    "path": f"Instant Fill BM Buy Order ({baseline_q.get('quality_name', 'Normal')})"
                })

        # 2. Sell Order Ladder with 28-day Overhang Anchor
        if bm_ask > 0 and (bm_vel >= 1.0 or bm_demand == 0):
            avg_28d = float(baseline_q.get("history_28d_avg_price") or 0)
            effective_ask = bm_ask
            if avg_28d > 0 and bm_ask > (avg_28d * 1.25):
                effective_ask = avg_28d * 1.10

            safe_batch = max(1, min(int(bm_vel * 0.35), 15))
            horizons.append({
                "batch_size": safe_batch,
                "revenue_per_u": effective_ask * (1.0 - config["tax_sell_order"]),
                "path": f"List on BM Sell Ladder ({baseline_q.get('quality_name', 'Normal')})"
            })

        # Hub Filtering Setup
        candidate_hub_sets = [None]
        if config["sourcing_mode"] == "SINGLE_HUB":
            candidate_hub_sets = [[c] for c in ROYAL_RING]
        elif config["sourcing_mode"] == "DUAL_HUB":
            candidate_hub_sets = [
                [ROYAL_RING[i], ROYAL_RING[(i+1)%5]] for i in range(5)
            ]

        for h in horizons:
            target_batch = h["batch_size"]
            expected_rev = h["revenue_per_u"]
            sell_path = h["path"]

            strategies_to_test = ['NONE'] if budget == 0 else (
                [config["focus_mode"]] if config["focus_mode"] != "AUTO" else ['BOTH', 'REFINE_ONLY', 'CRAFT_ONLY', 'NONE']
            )

            best_solution = None

            for hub_set in candidate_hub_sets:
                for strat in strategies_to_test:
                    plan = solve_manufacturing_route(
                        item_id, target_batch, expected_rev, sell_path, baseline_q,
                        db_meta, crafting_info, upgrade_info, city_markets, config,
                        strat, allowed_cities=hub_set
                    )
                    if not plan:
                        continue

                    if budget > 0 and plan["focus_used"] > budget:
                        f_per_u = plan["focus_used"] / target_batch
                        scaled = int(budget // f_per_u)
                        if scaled >= 1:
                            plan = solve_manufacturing_route(
                                item_id, scaled, expected_rev, sell_path, baseline_q,
                                db_meta, crafting_info, upgrade_info, city_markets, config,
                                strat, allowed_cities=hub_set
                            )

                    if plan and plan["focus_used"] <= budget:
                        if best_solution is None or plan["profit"] > best_solution["profit"]:
                            best_solution = plan

            if best_solution and best_solution["profit"] >= config["min_profit"]:
                best_solution["velocity"] = bm_vel
                if bm_vel >= 10.0:
                    best_solution["liquidity_badge"] = "🟢 HIGH VELOCITY (Fast Turnover)"
                elif bm_vel >= 1.0:
                    best_solution["liquidity_badge"] = "🟡 MODERATE (1-3 Days to Sell)"
                else:
                    best_solution["liquidity_badge"] = "🔴 LOW VELOCITY (Illiquid Warning)"
                plans.append(best_solution)

    plans.sort(key=lambda x: x["profit"], reverse=True)

    lines = []
    def out(text=""):
        print(text)
        lines.append(text)

    out("\n" + "=" * 135)
    out(f"       ALBION INDUSTRIAL SUPPLY-CHAIN & MANUFACTURING REPORT (V9.0 - OUTLANDS EDITION)")
    out(f"       Target: [{'BLACK ZONE HIDEOUT' if config['location_mode']=='BLACK_ZONE' else config['location_mode']}] | Sourcing: {config['sourcing_mode']} | Focus: {budget:,}")
    out("=" * 135)

    if not plans:
        out("\n[-] No manufacturing routes met your profit, cargo weight, and hub constraints.")
    else:
        for idx, p in enumerate(plans[:5], 1):
            out(f"\n[OPPORTUNITY #{idx}]: {p['batch_size']}x {p['item_name']} ({p['tier']})")
            out(f"  • Quality Anchor:      Guaranteed at '{p['baseline_quality']}' (Higher rolls = pure free profit)")
            out(f"  • Focus Allocation:    Strategy [{p['focus_strategy']}] -> Consumes {p['focus_used']:,} Focus")
            if p["focus_used"] > 0:
                out(f"  • Focus Efficiency:    {p['silver_per_focus']:>12,.0f} silver / Focus Point")
            out(f"  • Liquidity Status:    {p['liquidity_badge']} (BM Velocity: {p['velocity']:.1f}/day)")
            out(f"  • Total Net Revenue:   {p['revenue']:>12,.0f} silver ({p['sell_path']})")
            out(f"  • Total Cost:          {p['cost']:>12,.0f} silver")
            out(f"  • NET PROFIT:          {p['profit']:>+12,.0f} silver (Net ROI: {p['roi']:.1f}%)")
            out(f"  • Max Haul Weight:     {p['max_haul_weight']:>8.1f} kg ({p['silver_per_kg']:,.0f} s/kg)")
            out(f"  • Crafting Location:   [{p['crafting_city']}] (RRR: {p['craft_rrr']:.1f}%)")
            out("  -------------------------------------------------------------------------------------------------")
            out("  INDUSTRIAL STEP-BY-STEP EXECUTION PLAN:")

            # Consolidate Procurement
            city_shopping = {}
            for m in p["materials"]:
                if m["type"] == "ARTIFACT" or "Buy Refined" in m["path"]:
                    for lot in m["alloc"]:
                        c = lot["city"]
                        key = (c, m["item"])
                        city_shopping.setdefault(key, {"amount": 0, "cost": 0.0, "prices": []})
                        city_shopping[key]["amount"] += lot["amount"]
                        city_shopping[key]["cost"] += lot["cost"]
                        city_shopping[key]["prices"].append(lot["unit_price"])
                else:
                    for ing in m["alloc"]:
                        for lot in ing["alloc"]:
                            c = lot["city"]
                            key = (c, ing["ingredient"])
                            city_shopping.setdefault(key, {"amount": 0, "cost": 0.0, "prices": []})
                            city_shopping[key]["amount"] += lot["amount"]
                            city_shopping[key]["cost"] += lot["cost"]
                            city_shopping[key]["prices"].append(lot["unit_price"])

            grouped_by_city = {}
            for (c, item_name), data in city_shopping.items():
                grouped_by_city.setdefault(c, []).append({
                    "item": item_name,
                    "amount": data["amount"],
                    "cost": data["cost"],
                    "vwap": data["cost"] / data["amount"] if data["amount"] > 0 else 0,
                    "min_p": min(data["prices"]),
                    "max_p": max(data["prices"])
                })

            out("\n  STEP 1: PROCUREMENT (Consolidated Shopping List):")
            for city, buy_list in grouped_by_city.items():
                out(f"    • Travel to [{city}]:")
                for itm in buy_list:
                    p_str = f"@ {itm['vwap']:,.0f}s" if itm["min_p"] == itm["max_p"] else f"(VWAP: {itm['vwap']:,.0f}s | Range: {itm['min_p']:,.0f}s - {itm['max_p']:,.0f}s)"
                    out(f"        - Buy {itm['amount']:,}x {itm['item']} {p_str} -> Subtotal: {itm['cost']:,.0f}s")

            has_refining = any("Refine Raw" in m["path"] for m in p["materials"])
            if has_refining:
                out("\n  STEP 2: REFINING LEG:")
                for m in p["materials"]:
                    if "Refine Raw" in m["path"]:
                        out(f"    • Transport materials to [{m['best_refine_city']}]:")
                        out(f"        - Process batch: Yields {m['needed']:,}x {m['item']} ({m['path']})")
            else:
                out("\n  STEP 2: REFINING LEG:\n    • Skip (All materials procured refined directly).")

            out(f"\n  STEP 3: CRAFTING LEG [{p['crafting_city']}]:")
            out(f"    • Transport ingredients to [{p['crafting_city']}]:")
            out(f"        - Craft {p['batch_size']:,}x {p['item_name']} at Station (Local RRR: {p['craft_rrr']:.1f}%)")

            out(f"\n  STEP 4: CASH OUT [Caerleon Black Market]:")
            out(f"    • Haul {p['batch_size']:,} equipment to Caerleon:")
            out(f"        - {p['sell_path']}")
            out(f"        - Net Silver Inflow: {p['revenue']:,.0f}s (Net Profit: {p['profit']:>+,.0f}s)")
            out("=" * 135)

    try:
        with open(OUTPUT_MD, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\n[+] Production plan written to: {OUTPUT_MD}")
    except Exception as e:
        print(f"[!] Warning: Could not save report: {e}")

if __name__ == "__main__":
    main()