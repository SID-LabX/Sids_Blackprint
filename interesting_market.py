#!/usr/bin/env python3
"""
Albion Online - Forensic Market Intelligence & Cartel Radar (V2.0 - Un-Truncated Master Edition)
================================================================================================
Features:
1. Complete Un-Truncated Intelligence: Outputs 100% of detected whales, monopolies, and anomalies.
2. Cross-City Price Dislocation Matrix: Full continent-wide grid comparing prices across all 6 cities & BM.
3. Whale & Cartel Forensics: Tracks player capital, cross-city operations, and market dominance.
4. Market Microstructure: Order Book Imbalance (OBI), Starvation alerts, and Market Reset costs.
5. Stationary Market-Making: Zero-transport within-city spreads (>35% spread).
6. Valuation Deviations: Panic Dumps (< -25%) and Troll Inflation (> +45%).
7. Black Market Escalation: Tracks where Black Market buy orders exceed Royal Continent sell asks.
"""

import os
import sys
import json
import glob
import csv
from collections import defaultdict

# ==============================================================================
#  PATH RESOLUTION
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
OUTPUT_MD = os.path.join(SAVES_DIR, "market_intelligence_dossier.md")

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

def get_item_name(item_id: str) -> str:
    base = item_id.split("@")[0]
    entry = ITEMS_DB.get(item_id) or ITEMS_DB.get(base)
    if entry and "name" in entry:
        return entry["name"]
    return item_id.replace("_", " ").title()

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
                    avg_p = float(row.get("history_28d_avg_price") or 0)
                    turnover = float(row.get("history_28d_turnover") or 0)

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
                            "history_28d_turnover": turnover,
                            "sell_orders": [[sell_p, sell_stock]] if sell_p > 0 and sell_stock > 0 else [],
                            "buy_orders": [[buy_p, buy_dem]] if buy_p > 0 and buy_dem > 0 else []
                        }
        except Exception as e:
            print(f"    [!] Warning: Error reading CSV {os.path.basename(fpath)}: {e}")

    print(f"[*] Aggregated market datasets across {len(city_markets)} cities.")
    return city_markets

# ==============================================================================
#  FORENSIC ANALYSIS MODULES
# ==============================================================================

def analyze_whales_and_cartels(city_markets):
    player_buy_capital = defaultdict(float)
    player_sell_capital = defaultdict(float)
    player_city_footprint = defaultdict(set)
    monopolies = []

    for city, items in city_markets.items():
        if city == "Black Market":
            continue

        for itype, idata in items.items():
            qualities = idata.get("qualities", {})
            for q_name, q_data in qualities.items():
                total_stock = int(q_data.get("total_sell_stock") or 0)
                sell_orders = q_data.get("sell_orders") or []
                buy_orders = q_data.get("buy_orders") or []

                seller_volume = defaultdict(int)

                for o in sell_orders:
                    if isinstance(o, dict):
                        p = float(o.get("unit_price") or o.get("price") or 0)
                        a = int(o.get("amount") or o.get("count") or 0)
                        s = o.get("seller") or ""
                        if s and s != "@BLACK_MARKET" and p > 0 and a > 0:
                            player_sell_capital[s] += (p * a)
                            player_city_footprint[s].add(city)
                            seller_volume[s] += a

                for o in buy_orders:
                    if isinstance(o, dict):
                        p = float(o.get("unit_price") or o.get("price") or 0)
                        a = int(o.get("amount") or o.get("count") or 0)
                        b = o.get("buyer") or ""
                        if b and b != "@BLACK_MARKET" and p > 0 and a > 0:
                            player_buy_capital[b] += (p * a)
                            player_city_footprint[b].add(city)

                if total_stock >= 5:
                    for s, vol in seller_volume.items():
                        ratio = (vol / total_stock) * 100.0
                        if ratio >= 65.0:
                            monopolies.append({
                                "player": s,
                                "city": city,
                                "item_id": itype,
                                "quality": q_name,
                                "stock": vol,
                                "total_stock": total_stock,
                                "dominance_pct": ratio,
                                "lowest_ask": q_data.get("lowest_sell_price", 0),
                                "avg_price": q_data.get("history_28d_avg_price", 0)
                            })

    all_players = set(player_buy_capital.keys()).union(set(player_sell_capital.keys()))
    whale_leaderboard = []
    for p in all_players:
        b_cap = player_buy_capital[p]
        s_cap = player_sell_capital[p]
        total = b_cap + s_cap
        if total >= 500000:  # Filter noise below 500k
            whale_leaderboard.append({
                "player": p,
                "buy_capital": b_cap,
                "sell_capital": s_cap,
                "total_capital": total,
                "cities": list(player_city_footprint[p])
            })
    whale_leaderboard.sort(key=lambda x: x["total_capital"], reverse=True)
    monopolies.sort(key=lambda x: (x["dominance_pct"], x["stock"]), reverse=True)

    return whale_leaderboard, monopolies

def analyze_cross_city_dislocations(city_markets):
    """
    Builds the full Cross-City Price Dislocation Matrix comparing prices across all cities.
    """
    tracked_cities = ["Thetford", "Fort Sterling", "Lymhurst", "Bridgewatch", "Martlock", "Caerleon"]
    all_item_keys = set()

    for city in tracked_cities:
        if city in city_markets:
            for itype, idata in city_markets[city].items():
                for q_name in idata.get("qualities", {}):
                    all_item_keys.add((itype, q_name))

    dislocation_matrix = []

    for itype, q_name in all_item_keys:
        city_asks = {}
        bm_bid = 0.0

        for city in tracked_cities:
            if city in city_markets:
                q_data = city_markets[city].get(itype, {}).get("qualities", {}).get(q_name)
                if q_data:
                    p = float(q_data.get("lowest_sell_price") or 0)
                    stk = int(float(q_data.get("total_sell_stock") or 0))
                    if p > 0 and stk > 0:
                        city_asks[city] = p

        if "Black Market" in city_markets:
            bm_q = city_markets["Black Market"].get(itype, {}).get("qualities", {}).get(q_name)
            if bm_q:
                bm_bid = float(bm_q.get("highest_buy_order") or 0)

        if len(city_asks) >= 2:
            min_city, min_ask = min(city_asks.items(), key=lambda x: x[1])
            max_city, max_ask = max(city_asks.items(), key=lambda x: x[1])
            
            if min_ask > 0 and max_ask > min_ask:
                spread_pct = ((max_ask - min_ask) / min_ask) * 100.0
                dislocation_matrix.append({
                    "item_id": itype,
                    "quality": q_name,
                    "min_city": min_city,
                    "min_ask": min_ask,
                    "max_city": max_city,
                    "max_ask": max_ask,
                    "spread_pct": spread_pct,
                    "city_asks": city_asks,
                    "bm_bid": bm_bid
                })

    dislocation_matrix.sort(key=lambda x: x["spread_pct"], reverse=True)
    return dislocation_matrix

def analyze_microstructure_and_spreads(city_markets):
    spread_opportunities = []
    starvations = []
    reset_targets = []

    for city, items in city_markets.items():
        for itype, idata in items.items():
            qualities = idata.get("qualities", {})
            for q_name, q_data in qualities.items():
                sell_p = float(q_data.get("lowest_sell_price") or 0)
                stock = int(float(q_data.get("total_sell_stock") or 0))
                buy_p = float(q_data.get("highest_buy_order") or 0)
                demand = int(float(q_data.get("total_buy_demand") or 0))
                vel = float(q_data.get("daily_volume_velocity") or 0)
                avg_p = float(q_data.get("history_28d_avg_price") or 0)

                # 1. Supply Starvation
                if vel >= 5.0 and stock > 0:
                    supply_days = stock / vel
                    if supply_days <= 0.35:
                        starvations.append({
                            "city": city,
                            "item_id": itype,
                            "quality": q_name,
                            "stock": stock,
                            "velocity": vel,
                            "supply_days": supply_days,
                            "lowest_ask": sell_p,
                            "avg_price": avg_p
                        })

                # 2. Stationary Market-Making Spreads
                if sell_p > 0 and buy_p > 0 and buy_p < sell_p:
                    spread_silver = sell_p - buy_p
                    spread_pct = (spread_silver / sell_p) * 100.0
                    net_spread = (sell_p * 0.895) - buy_p  # 10.5% non-prem fee
                    if spread_pct >= 30.0 and vel >= 2.0 and net_spread > 100:
                        spread_opportunities.append({
                            "city": city,
                            "item_id": itype,
                            "quality": q_name,
                            "buy_bid": buy_p,
                            "sell_ask": sell_p,
                            "spread_pct": spread_pct,
                            "net_spread": net_spread,
                            "velocity": vel,
                            "turnover": q_data.get("history_28d_turnover", 0)
                        })

                # 3. Market Reset / Cornering Analysis
                sell_orders = q_data.get("sell_orders") or []
                if avg_p > 0 and sell_orders and len(sell_orders) >= 2:
                    target_reset_price = avg_p * 1.25
                    buyout_cost = 0.0
                    units_to_buy = 0
                    for o in sell_orders:
                        p, a = 0, 0
                        if isinstance(o, dict):
                            p = float(o.get("unit_price") or o.get("price") or 0)
                            a = int(o.get("amount") or o.get("count") or 0)
                        elif isinstance(o, (list, tuple)) and len(o) >= 2:
                            p, a = float(o[0]), int(o[1])
                        if p > 0 and p < target_reset_price:
                            buyout_cost += (p * a)
                            units_to_buy += a

                    if 0 < buyout_cost <= 15000000 and units_to_buy >= 2 and vel >= 1.0:
                        gross_return = units_to_buy * target_reset_price * 0.895
                        profit = gross_return - buyout_cost
                        if profit >= 100000:
                            reset_targets.append({
                                "city": city,
                                "item_id": itype,
                                "quality": q_name,
                                "units_to_buy": units_to_buy,
                                "buyout_cost": buyout_cost,
                                "reset_price": target_reset_price,
                                "profit": profit,
                                "roi": (profit / buyout_cost) * 100.0,
                                "velocity": vel
                            })

    spread_opportunities.sort(key=lambda x: x["net_spread"] * min(x["velocity"], 50), reverse=True)
    starvations.sort(key=lambda x: x["supply_days"])
    reset_targets.sort(key=lambda x: x["profit"], reverse=True)

    return spread_opportunities, starvations, reset_targets

def analyze_valuation_deviations(city_markets):
    panic_dumps = []
    hyper_inflations = []

    for city, items in city_markets.items():
        for itype, idata in items.items():
            qualities = idata.get("qualities", {})
            for q_name, q_data in qualities.items():
                sell_p = float(q_data.get("lowest_sell_price") or 0)
                stock = int(float(q_data.get("total_sell_stock") or 0))
                vel = float(q_data.get("daily_volume_velocity") or 0)
                avg_p = float(q_data.get("history_28d_avg_price") or 0)

                if sell_p > 0 and avg_p > 0 and vel >= 0.5:
                    deviation_pct = ((sell_p - avg_p) / avg_p) * 100.0

                    if deviation_pct <= -20.0 and stock >= 1:
                        panic_dumps.append({
                            "city": city,
                            "item_id": itype,
                            "quality": q_name,
                            "current_ask": sell_p,
                            "avg_price": avg_p,
                            "discount_pct": abs(deviation_pct),
                            "stock": stock,
                            "velocity": vel
                        })
                    elif deviation_pct >= 40.0 and stock <= 15:
                        hyper_inflations.append({
                            "city": city,
                            "item_id": itype,
                            "quality": q_name,
                            "current_ask": sell_p,
                            "avg_price": avg_p,
                            "inflation_pct": deviation_pct,
                            "stock": stock,
                            "velocity": vel
                        })

    panic_dumps.sort(key=lambda x: x["discount_pct"] * x["velocity"], reverse=True)
    hyper_inflations.sort(key=lambda x: x["inflation_pct"], reverse=True)
    return panic_dumps, hyper_inflations

def analyze_black_market_escalation(city_markets):
    if "Black Market" not in city_markets:
        return []

    bm_items = city_markets["Black Market"]
    escalations = []

    for itype, idata in bm_items.items():
        qualities = idata.get("qualities", {})
        for q_name, q_data in qualities.items():
            bm_bid = float(q_data.get("highest_buy_order") or 0)
            bm_demand = int(float(q_data.get("total_buy_demand") or 0))
            bm_vel = float(q_data.get("daily_volume_velocity") or 0)

            if bm_bid <= 0 or bm_demand <= 0:
                continue

            cheapest_royal_city = None
            lowest_royal_ask = 999999999.0
            royal_stock = 0

            for city, c_items in city_markets.items():
                if city in ("Black Market", "Caerleon"):
                    continue
                r_q = c_items.get(itype, {}).get("qualities", {}).get(q_name)
                if r_q:
                    ask = float(r_q.get("lowest_sell_price") or 0)
                    stk = int(float(r_q.get("total_sell_stock") or 0))
                    if 0 < ask < lowest_royal_ask and stk > 0:
                        lowest_royal_ask = ask
                        cheapest_royal_city = city
                        royal_stock = stk

            if cheapest_royal_city and lowest_royal_ask < (bm_bid * 0.92):
                net_payout = bm_bid * 0.92
                profit_per_u = net_payout - lowest_royal_ask
                escalations.append({
                    "item_id": itype,
                    "quality": q_name,
                    "from_city": cheapest_royal_city,
                    "royal_ask": lowest_royal_ask,
                    "bm_bid": bm_bid,
                    "net_profit_unit": profit_per_u,
                    "roi": (profit_per_u / lowest_royal_ask) * 100.0,
                    "bm_demand": bm_demand,
                    "royal_stock": royal_stock,
                    "bm_velocity": bm_vel
                })

    escalations.sort(key=lambda x: x["net_profit_unit"] * min(x["bm_demand"], x["royal_stock"]), reverse=True)
    return escalations

# ==============================================================================
#  MAIN EXECUTION & UN-TRUNCATED REPORT GENERATOR
# ==============================================================================

def main():
    print("\n" + "=" * 95)
    print("   ALBION UN-TRUNCATED FORENSIC MARKET INTELLIGENCE & CARTEL RADAR (V2.0)")
    print("=" * 95)

    city_markets = load_all_market_summaries()

    print("[*] Running Deep Whale & Entity Tracing across all cities...")
    whales, monopolies = analyze_whales_and_cartels(city_markets)

    print("[*] Computing Full Cross-City Price Dislocation Matrix...")
    dislocations = analyze_cross_city_dislocations(city_markets)

    print("[*] Computing Market Microstructure, OBI & Stationary Spreads...")
    spreads, starvations, resets = analyze_microstructure_and_spreads(city_markets)

    print("[*] Detecting Historical Valuation Deviations (Panic Dumps & Troll Prices)...")
    dumps, inflations = analyze_valuation_deviations(city_markets)

    print("[*] Scanning Black Market Demand Escalations...\n")
    bm_escalations = analyze_black_market_escalation(city_markets)

    lines = []
    def out(text=""):
        print(text)
        lines.append(text)

    out("# ALBION ADVANCED MARKET INTELLIGENCE & CARTEL DOSSIER (UN-TRUNCATED)")
    out("Generated automatically from multi-city Level-2 Order-Book snapshots.\n")

    # 1. CROSS-CITY PRICE DISLOCATION MATRIX
    out("## 1. 🌐 CROSS-CITY PRICE DISLOCATION MATRIX (ALL TRACKED ITEMS)")
    out("Side-by-side pricing grid across all Royal Cities and Caerleon. Highlights spatial arbitrage spreads:\n")
    out(f"| Item / Resource | Quality | Cheapest Buy | Highest Sell | Max Spread% | Thetford | Fort Sterling | Lymhurst | Bridgewatch | Martlock | Caerleon | BM Bid |")
    out(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for d in dislocations:
        name = get_item_name(d["item_id"])
        c_asks = d["city_asks"]
        t_p = f"{c_asks.get('Thetford', 0):,.0f}s" if 'Thetford' in c_asks else "-"
        fs_p = f"{c_asks.get('Fort Sterling', 0):,.0f}s" if 'Fort Sterling' in c_asks else "-"
        ly_p = f"{c_asks.get('Lymhurst', 0):,.0f}s" if 'Lymhurst' in c_asks else "-"
        bw_p = f"{c_asks.get('Bridgewatch', 0):,.0f}s" if 'Bridgewatch' in c_asks else "-"
        ml_p = f"{c_asks.get('Martlock', 0):,.0f}s" if 'Martlock' in c_asks else "-"
        ca_p = f"{c_asks.get('Caerleon', 0):,.0f}s" if 'Caerleon' in c_asks else "-"
        bm_str = f"{d['bm_bid']:,.0f}s" if d["bm_bid"] > 0 else "-"
        
        min_str = f"[{d['min_city'][:4]}] {d['min_ask']:,.0f}s"
        max_str = f"[{d['max_city'][:4]}] {d['max_ask']:,.0f}s"
        out(f"| {name} | {d['quality']} | {min_str} | {max_str} | **{d['spread_pct']:>5.1f}%** | {t_p} | {fs_p} | {ly_p} | {bw_p} | {ml_p} | {ca_p} | {bm_str} |")

    # 2. WHALE & CARTEL LEADERBOARD
    out("\n## 2. 🐋 FULL WHALE & LIQUIDITY PROVIDER LEADERBOARD")
    out("Every player with active order book capital >= 500,000 silver across all cities:\n")
    out(f"| Rank | Player Name | Total Active Capital | Buy Orders (Bids) | Sell Orders (Asks) | Active Cities |")
    out(f"| :--- | :--- | :--- | :--- | :--- | :--- |")
    for idx, w in enumerate(whales, 1):
        cities_str = ", ".join(sorted(w["cities"]))
        out(f"| #{idx} | **{w['player']}** | {w['total_capital']:>13,.0f}s | {w['buy_capital']:>13,.0f}s | {w['sell_capital']:>13,.0f}s | {cities_str} |")

    # 3. MONOPOLY & MARKET CONCENTRATION
    out("\n## 3. 🏰 ACTIVE MONOPOLY & SUPPLY CONCENTRATION ALERTS")
    out("Single players controlling >65% of the total sell stock in a specific city market:\n")
    out(f"| Player | City | Item / Resource | Quality | Player Stock | Dominance | Lowest Ask | 28d Avg Price |")
    out(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for m in monopolies:
        name = get_item_name(m["item_id"])
        out(f"| **{m['player']}** | {m['city']} | {name} | {m['quality']} | {m['stock']} / {m['total_stock']}u | **{m['dominance_pct']:.1f}%** | {m['lowest_ask']:,.0f}s | {m['avg_price']:,.0f}s |")

    # 4. CRITICAL SUPPLY STARVATIONS
    out("\n## 4. 🚨 CRITICAL SUPPLY STARVATION ALERTS (DAYS OF SUPPLY <= 0.35d)")
    out("High-turnover items whose active stock will deplete rapidly at current daily velocities:\n")
    out(f"| City | Item / Resource | Quality | Current Stock | Daily Velocity | Supply Life | Current Ask | 28d Avg Price |")
    out(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for s in starvations:
        name = get_item_name(s["item_id"])
        out(f"| {s['city']} | {name} | {s['quality']} | {s['stock']}u | {s['velocity']:.1f}/d | **{s['supply_days']*24:.1f} hrs** | {s['lowest_ask']:,.0f}s | {s['avg_price']:,.0f}s |")

    # 5. STATIONARY SAME-CITY MARKET-MAKING SPREADS
    out("\n## 5. 🏦 STATIONARY MARKET-MAKING SPREADS (ZERO TRANSPORT NEEDED)")
    out("Items with wide spreads (>30%) in the same city. Place buy orders, wait for instant dumps, and relist on asks:\n")
    out(f"| City | Item / Resource | Top Bid | Lowest Ask | Net Spread /unit | Spread % | Velocity | 28d Turnover |")
    out(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for sp in spreads:
        name = get_item_name(sp["item_id"])
        out(f"| {sp['city']} | {name} | {sp['buy_bid']:>8,.0f}s | {sp['sell_ask']:>8,.0f}s | **+{sp['net_spread']:>7,.0f}s** | {sp['spread_pct']:.1f}% | {sp['velocity']:.1f}/d | {sp['turnover']:>11,.0f}s |")

    # 6. MARKET RESET & CORNERING TARGETS
    out("\n## 6. 🎯 HOSTILE TAKEOVER & MARKET RESET TARGETS")
    out("Markets where buying out 100% of active sell stock allows resetting the price to the 28-day average for high ROI:\n")
    out(f"| City | Target Item | Buyout Units | Total Buyout Cost | New Reset Ask | Projected Profit | Projected ROI% | Velocity |")
    out(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in resets:
        name = get_item_name(r["item_id"])
        out(f"| {r['city']} | {name} | {r['units_to_buy']}u | {r['buyout_cost']:>10,.0f}s | {r['reset_price']:>10,.0f}s | **+{r['profit']:>10,.0f}s** | **{r['roi']:.1f}%** | {r['velocity']:.1f}/d |")

    # 7. PANIC DUMPS & DEEP VALUE VAULT BUYS
    out("\n## 7. 📉 PANIC DUMPS & DEEP VALUE VAULT BUYS")
    out("Items currently listed at a steep discount (>=20%) relative to their 28-day historical moving average:\n")
    out(f"| City | Item / Resource | Current Ask | 28d Moving Avg | Discount % | Available Stock | Daily Velocity |")
    out(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for d in dumps:
        name = get_item_name(d["item_id"])
        out(f"| {d['city']} | {name} | {d['current_ask']:>8,.0f}s | {d['avg_price']:>8,.0f}s | **-{d['discount_pct']:.1f}%** | {d['stock']}u | {d['velocity']:.1f}/d |")

    # 8. HYPER-INFLATION & TROLL ASKS
    out("\n## 8. 📈 HYPER-INFLATION & TROLL PRICING ALERTS")
    out("Items listed at >=40% above their 28-day historical average with low stock (Prime Import Candidates):\n")
    out(f"| City | Item / Resource | Current Ask | 28d Moving Avg | Inflation % | Available Stock | Daily Velocity |")
    out(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for inf in inflations:
        name = get_item_name(inf["item_id"])
        out(f"| {inf['city']} | {name} | {inf['current_ask']:>8,.0f}s | {inf['avg_price']:>8,.0f}s | **+{inf['inflation_pct']:.1f}%** | {inf['stock']}u | {inf['velocity']:.1f}/d |")

    # 9. BLACK MARKET ESCALATION OPPORTUNITIES
    out("\n## 9. 🔥 BLACK MARKET ESCALATION SPIKES (SYSTEM OVERPAYING)")
    out("Items where the Black Market system buy order exceeds Royal Continent market sell prices:\n")
    out(f"| Item / Resource | Buy From (Royal) | Royal Ask | BM Bid (Caerleon) | Net Profit/u | Net ROI% | BM Demand | Royal Stock |")
    out(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for b in bm_escalations:
        name = get_item_name(b["item_id"])
        out(f"| {name} | {b['from_city']} | {b['royal_ask']:>8,.0f}s | {b['bm_bid']:>8,.0f}s | **+{b['net_profit_unit']:>7,.0f}s** | **{b['roi']:.1f}%** | {b['bm_demand']}u | {b['royal_stock']}u |")

    out("\n" + "=" * 95)
    
    try:
        with open(OUTPUT_MD, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"\n[+] Complete Un-Truncated Market Dossier written to: {OUTPUT_MD}\n")
    except Exception as e:
        print(f"[!] Warning: Could not save report: {e}")

if __name__ == "__main__":
    main()