#!/usr/bin/env python3
"""
Albion Online - Universal Strict Market Packet Extractor (V3 - DB Integrated)
Powered by items.json:
- Exact in-game localized names
- Exact in-game weights
- Strict 28-day history correlation (No cross-contamination)
- Exact fee separation
"""

import os
import sys
import json
import csv
import re
import argparse

QUALITY_NAMES = {
    1: "Normal",
    2: "Good",
    3: "Outstanding",
    4: "Excellent",
    5: "Masterpiece"
}

def parse_meta(item_str):
    tier = 0
    enchant = 0
    m = re.match(r"^T(\d+)_", item_str)
    if m:
        tier = int(m.group(1))
    if "@" in item_str:
        try:
            enchant = int(item_str.split("@")[1])
        except Exception:
            enchant = 0
    return tier, enchant

def load_master_db(db_path):
    if not db_path or not os.path.exists(db_path):
        print(f"[!] Warning: Master DB '{db_path}' not found.")
        return {}, {}

    print(f"[*] Loading Master DB from '{db_path}'...")
    try:
        with open(db_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            index_to_unique = {int(k): v for k, v in data.get("index_to_unique", {}).items()}
            items = data.get("items", {})
            print(f"[+] Loaded {len(items):,} items and {len(index_to_unique):,} index mappings.")
            return index_to_unique, items
    except Exception as e:
        print(f"[!] Error loading Master DB: {e}")
        return {}, {}

def main():
    parser = argparse.ArgumentParser(description="Albion Online Market Packet Analyzer")
    parser.add_argument("input_file", nargs="?", default="Blackmarket_merc_shoes.json", help="Path to packet stream JSON")
    parser.add_argument("-db", "--database", default=None, help="Path to items.json")
    parser.add_argument("-o", "--output_prefix", default=None, help="Output file prefix")
    parser.add_argument("--non-premium", action="store_true", help="Apply Non-Premium market fee")
    args = parser.parse_args()

    input_path = args.input_file
    if not os.path.exists(input_path):
        print(f"[!] Error: File '{input_path}' not found.")
        sys.exit(1)

    # Auto-detect items.json
    db_path = args.database
    if not db_path:
        local_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "items.json")
        if os.path.exists(local_db):
            db_path = local_db
        elif os.path.exists("items.json"):
            db_path = "items.json"

    index_to_unique, items_db = load_master_db(db_path)

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_prefix = args.output_prefix if args.output_prefix else f"{base_name}_summary"
    output_csv = f"{output_prefix}.csv"
    output_json = f"{output_prefix}.json"

    tax_rate = 0.08 if args.non_premium else 0.04
    setup_fee = 0.025
    sell_order_total_fee = tax_rate + setup_fee

    print(f"[*] Parsing packet stream '{input_path}'...")
    with open(input_path, "r", encoding="utf-8") as f:
        try:
            packets = json.load(f)
        except Exception as e:
            print(f"[!] Invalid JSON format: {e}")
            sys.exit(1)

    market_db = {}
    fname = os.path.basename(input_path).lower()
    is_black_market = ("blackmarket" in fname) or ("_bm" in fname) or fname.startswith("bm")
    seen_order_ids = set()
    req_81_82_map = {}
    req_95_map = {}
    fallback_canonical_cache = {}

    def get_entry(item_type: str, quality_num: int, explicit_tier=None, explicit_enchant=None):
        key = (item_type, quality_num)
        if key not in market_db:
            tier, enchant = parse_meta(item_type)
            if explicit_tier:
                tier = explicit_tier
            if explicit_enchant is not None:
                enchant = explicit_enchant

            # Lookup display name and weight from items.json
            base_type = item_type.split("@")[0]
            db_item = items_db.get(item_type) or items_db.get(base_type) or {}
            
            display_name = db_item.get("name") or item_type
            weight = float(db_item.get("weight", 0.0))

            market_db[key] = {
                "item_name": display_name,
                "item_type": item_type,
                "base_item": base_type,
                "tier": tier,
                "enchantment": enchant,
                "quality_id": quality_num,
                "quality_name": QUALITY_NAMES.get(quality_num, f"Q{quality_num}"),
                "weight": weight,
                "market_type": "Royal Marketplace",
                "lowest_sell_price": None,
                "net_sell_payout": None,
                "total_sell_stock": 0,
                "sell_order_count": 0,
                "highest_buy_order": None,
                "total_buy_demand": 0,
                "buy_order_count": 0,
                "history_28d_volume": 0,
                "history_28d_turnover": 0.0,
                "history_28d_avg_price": 0.0,
                "daily_volume_velocity": 0.0,
                "days_of_supply": None,
                "price_deviation_pct": None,
                "liquidity_status": "NO DATA",
                "sell_orders": [],
                "buy_orders": []
            }
        return market_db[key]

    # PASS 1: MAP REQUESTS
    for pkt in packets:
        kind = pkt.get("kind")
        code = pkt.get("code")
        params = pkt.get("params", {})

        if kind == "REQUEST" and code in (81, 82):
            req_id = params.get("255", {}).get("value")
            item_list = params.get("8", {}).get("value", [])
            tier_str = params.get("7", {}).get("value")
            raw_name = params.get("3", {}).get("value", "")
            enchant_str = params.get("10", {}).get("value", "0")

            if req_id is not None and item_list:
                item_num = item_list[0]
                req_81_82_map[req_id] = item_num

                if tier_str and raw_name:
                    canonical = f"T{tier_str}_{raw_name.upper()}"
                    if enchant_str and str(enchant_str) not in ("0", ""):
                        canonical += f"@{enchant_str}"
                    fallback_canonical_cache[item_num] = canonical

        if kind == "REQUEST" and code == 95:
            req_id = params.get("255", {}).get("value")
            item_num = params.get("1", {}).get("value")
            quality = params.get("2", {}).get("value", 1)
            timescale = params.get("3", {}).get("value", 0)
            if req_id is not None:
                req_95_map[req_id] = {
                    "item_num": item_num,
                    "quality": quality,
                    "timescale": timescale
                }

    # PASS 2: PROCESS LIVE ORDERS
    for pkt in packets:
        kind = pkt.get("kind")
        code = pkt.get("code")
        params = pkt.get("params", {})

        if kind == "RESPONSE" and code in (81, 82):
            resp_id = params.get("255", {}).get("value")
            item_num = req_81_82_map.get(resp_id)

            for p_val in params.values():
                val = p_val.get("value", [])
                if isinstance(val, list):
                    for entry_str in val:
                        if isinstance(entry_str, str) and entry_str.startswith("{"):
                            try:
                                o = json.loads(entry_str)
                            except Exception:
                                continue

                            order_id = o.get("Id")
                            if order_id and order_id in seen_order_ids:
                                continue
                            if order_id:
                                seen_order_ids.add(order_id)

                            item_type = o.get("ItemTypeId")
                            if not item_type:
                                continue

                            if item_num:
                                fallback_canonical_cache[item_num] = item_type

                            buyer_name = o.get("BuyerName", "")
                            if buyer_name == "@BLACK_MARKET":
                                is_black_market = True

                            quality = o.get("QualityLevel", 1)
                            tier = o.get("Tier")
                            enchant = o.get("EnchantmentLevel", 0)
                            unit_price = o.get("UnitPriceSilver", 0) / 10000.0
                            amount = o.get("Amount", 0)
                            auction_type = o.get("AuctionType")

                            entry = get_entry(item_type, quality, tier, enchant)

                            if auction_type == "offer":
                                entry["sell_order_count"] += 1
                                entry["total_sell_stock"] += amount
                                if entry["lowest_sell_price"] is None or unit_price < entry["lowest_sell_price"]:
                                    entry["lowest_sell_price"] = unit_price
                                entry["sell_orders"].append({
                                    "id": order_id,
                                    "unit_price": unit_price,
                                    "amount": amount,
                                    "seller": o.get("SellerName"),
                                    "expires": o.get("Expires")
                                })

                            elif auction_type == "request" or buyer_name == "@BLACK_MARKET":
                                entry["buy_order_count"] += 1
                                entry["total_buy_demand"] += amount
                                if entry["highest_buy_order"] is None or unit_price > entry["highest_buy_order"]:
                                    entry["highest_buy_order"] = unit_price
                                entry["buy_orders"].append({
                                    "id": order_id,
                                    "unit_price": unit_price,
                                    "amount": amount,
                                    "buyer": buyer_name,
                                    "expires": o.get("Expires")
                                })

    # PASS 3: MATCH 28-DAY HISTORY (Strict Resolution)
    for pkt in packets:
        kind = pkt.get("kind")
        code = pkt.get("code")
        params = pkt.get("params", {})

        if kind == "RESPONSE" and code == 95:
            resp_id = params.get("255", {}).get("value")
            req_info = req_95_map.get(resp_id)

            if not req_info or req_info["timescale"] != 2:
                continue

            quality = req_info["quality"]
            item_num = req_info["item_num"]

            # Strict item matching via items_db index mapping
            item_type = index_to_unique.get(item_num)
            if not item_type and item_num in fallback_canonical_cache:
                item_type = fallback_canonical_cache[item_num]

            if not item_type:
                continue

            volumes = params.get("0", {}).get("value", [])
            silver_raw = params.get("1", {}).get("value", [])

            tot_vol = sum(v for v in volumes if v > 0)
            tot_silver = sum(s / 10000.0 for v, s in zip(volumes, silver_raw) if v > 0)

            rec = get_entry(item_type, quality)
            rec["history_28d_volume"] = tot_vol
            rec["history_28d_turnover"] = round(tot_silver, 2)
            if tot_vol > 0:
                rec["history_28d_avg_price"] = round(tot_silver / tot_vol, 2)
                rec["daily_volume_velocity"] = round(tot_vol / 28.0, 1)

    # PASS 4: COMPUTE METRICS
    final_rows = []
    for rec in market_db.values():
        rec["market_type"] = "Caerleon Black Market" if is_black_market else "Royal Marketplace"

        sell_p = rec["lowest_sell_price"]
        stock = rec["total_sell_stock"]
        daily_v = rec["daily_volume_velocity"]
        avg_p = rec["history_28d_avg_price"]

        if sell_p is not None:
            rec["net_sell_payout"] = round(sell_p * (1.0 - sell_order_total_fee), 2)

        if daily_v > 0 and stock > 0:
            rec["days_of_supply"] = round(stock / daily_v, 1)

        if sell_p and avg_p and avg_p > 0:
            rec["price_deviation_pct"] = round(((sell_p - avg_p) / avg_p) * 100.0, 1)

        if daily_v >= 50.0:
            rec["liquidity_status"] = "VERY HIGH"
        elif daily_v >= 5.0:
            rec["liquidity_status"] = "MEDIUM"
        elif daily_v > 0.0:
            rec["liquidity_status"] = "LOW"
        else:
            rec["liquidity_status"] = "ILLIQUID" if stock > 0 else "NO DATA"

        if stock > 0 or rec["total_buy_demand"] > 0 or rec["history_28d_volume"] > 0:
            final_rows.append(rec)

    final_rows.sort(key=lambda x: (x["item_name"], x["tier"], x["enchantment"], x["quality_id"]))

    grouped_json = {}
    for r in final_rows:
        itype = r["item_type"]
        if itype not in grouped_json:
            grouped_json[itype] = {
                "item_name": r["item_name"],
                "item_type": itype,
                "base_item": r["base_item"],
                "tier": r["tier"],
                "enchantment": r["enchantment"],
                "weight": r["weight"],
                "market_type": r["market_type"],
                "qualities": {}
            }
        grouped_json[itype]["qualities"][r["quality_name"]] = r

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(grouped_json, f, indent=2)

    fieldnames = [
        "item_name", "item_type", "tier", "enchantment", "quality_name", "weight", "market_type",
        "lowest_sell_price", "net_sell_payout", "total_sell_stock", "sell_order_count",
        "highest_buy_order", "total_buy_demand", "buy_order_count",
        "history_28d_volume", "daily_volume_velocity", "days_of_supply",
        "history_28d_avg_price", "price_deviation_pct", "history_28d_turnover", "liquidity_status"
    ]

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in final_rows:
            writer.writerow(r)

    print(f"[+] Output Clean CSV:  {output_csv}")
    print(f"[+] Output Clean JSON: {output_json}")

if __name__ == "__main__":
    main()