#!/usr/bin/env python3
"""
Albion Online - Cross-City Arbitrage & Black Market Scanner (V8 - High-Tier Enabled & DB Linked)
Fixes:
- Correct path to items.json (true weights now active)
- Allows 1-unit high-value snipes for expensive T7/T8 gear
- Dynamic velocity scaling (no longer blinds itself to items with < 6/d velocity)
- CLI configurable filters (--min-roi, --min-profit)
"""

import os
import sys
import json
import glob
import argparse

BASE_DIR = r"C:\Users\SID\Desktop\albion"
SAVES_DIR = os.path.join(BASE_DIR, "saves_here")
ITEMS_DB_PATH = os.path.join(BASE_DIR, "items.json")
OUTPUT_MD = os.path.join(SAVES_DIR, "best_trades.md")

TAX_SELL_ORDER = 0.065   # 2.5% setup fee + 4% sales tax (Premium)
TAX_INSTANT_FILL = 0.04  # 4% sales tax (0% setup fee)

def load_weights_db():
    if not os.path.exists(ITEMS_DB_PATH):
        print(f"[!] Warning: '{ITEMS_DB_PATH}' not found. Weight fallbacks will be used.")
        return {}
    try:
        with open(ITEMS_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            items = data.get("items", {})
            weights = {k: float(v.get("weight", 1.0)) for k, v in items.items()}
            print(f"[*] Loaded {len(weights):,} exact item weights from items.json")
            return weights
    except Exception as e:
        print(f"[!] Error loading items.json: {e}")
        return {}

WEIGHTS_DB = load_weights_db()

def get_item_weight(item_type: str) -> float:
    base = item_type.split("@")[0]
    return WEIGHTS_DB.get(item_type) or WEIGHTS_DB.get(base) or 1.5

def detect_city_name(filename, market_type=""):
    fn = os.path.basename(filename).lower()
    if "bm" in fn or "black" in fn or "blackmarket" in fn or market_type == "Caerleon Black Market":
        return "Black Market"
    elif "thetford" in fn:
        return "Thetford"
    elif "fortsterling" in fn or "fort_sterling" in fn:
        return "Fort Sterling"
    elif "lymhurst" in fn:
        return "Lymhurst"
    elif "bridgewatch" in fn:
        return "Bridgewatch"
    elif "martlock" in fn:
        return "Martlock"
    elif "caerlon" in fn or "caerleon" in fn:
        return "Caerleon Royal"
    return os.path.basename(filename).split('_')[0].capitalize()

def parse_ladder(q_data, ladder_type="sell"):
    if not isinstance(q_data, dict):
        return []

    ladder = []
    keys = ["sell_orders", "sell_ladder"] if ladder_type == "sell" else ["buy_orders", "buy_ladder"]

    for k in keys:
        val = q_data.get(k)
        if val and isinstance(val, list):
            for entry in val:
                p, a = 0, 0
                if isinstance(entry, dict):
                    p = entry.get("unit_price") or entry.get("price") or 0
                    a = entry.get("amount") or entry.get("count") or 0
                elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    p = entry[0] or 0
                    a = entry[1] or 0
                else:
                    continue
                try:
                    p = int(p)
                    a = int(a)
                except (ValueError, TypeError):
                    continue
                if p > 0 and a > 0:
                    ladder.append([p, a])
            if ladder:
                break

    if not ladder:
        if ladder_type == "sell":
            lp = q_data.get("lowest_sell_price") or 0
            stock = q_data.get("total_sell_stock") or 0
            if lp and stock:
                ladder.append([int(lp), int(stock)])
        else:
            hb = q_data.get("highest_buy_order") or 0
            demand = q_data.get("total_buy_demand") or 0
            if hb and demand:
                ladder.append([int(hb), int(demand)])

    ladder.sort(key=lambda x: x[0], reverse=(ladder_type == "buy"))
    return ladder

def walk_instant_dump(sell_ladder, buy_ladder, min_unit_profit=200, min_marginal_roi=0.08):
    """
    Matches buy orders against sell orders lot-by-lot.
    Stops when individual marginal profit falls below acceptable threshold.
    """
    s_idx, b_idx = 0, 0
    s_ladder = [list(x) for x in sell_ladder]
    b_ladder = [list(x) for x in buy_ladder]

    matched_qty = 0
    total_buy_cost = 0.0
    total_net_payout = 0.0

    while s_idx < len(s_ladder) and b_idx < len(b_ladder):
        ask_p, ask_qty = s_ladder[s_idx]
        bid_p, bid_qty = b_ladder[b_idx]

        net_payout_per_u = round(bid_p * (1.0 - TAX_INSTANT_FILL), 2)
        marginal_profit = net_payout_per_u - ask_p

        if marginal_profit < min_unit_profit or (marginal_profit / ask_p) < min_marginal_roi:
            break

        trade_qty = min(ask_qty, bid_qty)
        if trade_qty <= 0:
            break

        total_buy_cost += ask_p * trade_qty
        total_net_payout += net_payout_per_u * trade_qty
        matched_qty += trade_qty

        s_ladder[s_idx][1] -= trade_qty
        b_ladder[b_idx][1] -= trade_qty

        if s_ladder[s_idx][1] == 0:
            s_idx += 1
        if b_ladder[b_idx][1] == 0:
            b_idx += 1

    total_profit = total_net_payout - total_buy_cost
    return matched_qty, total_buy_cost, total_net_payout, total_profit

def walk_sell_order_buy(sell_ladder, target_qty, max_allowed_buy_price=None):
    taken = 0
    total_cost = 0.0
    for price, amt in sell_ladder:
        if max_allowed_buy_price and price > max_allowed_buy_price:
            break
        take = min(amt, target_qty - taken)
        total_cost += price * take
        taken += take
        if taken >= target_qty:
            break

    vwap = (total_cost / taken) if taken > 0 else 0.0
    return taken, total_cost, vwap

def main():
    parser = argparse.ArgumentParser(description="Albion Arbitrage & Squeeze Scanner V8")
    parser.add_argument("--min-roi", type=float, default=12.0, help="Minimum ROI percentage (Default: 12.0%%)")
    parser.add_argument("--min-profit", type=float, default=15000.0, help="Minimum total trade profit (Default: 15,000s)")
    args = parser.parse_args()

    lines = []
    def out(text=""):
        print(text)
        lines.append(text)

    out("=" * 115)
    out(f"       ALBION DUAL-ENGINE ARBITRAGE & SQUEEZE SCANNER (V8 - HIGH-TIER ENABLED)")
    out(f"       Filters: Min ROI >= {args.min_roi:.1f}% | Min Profit >= {args.min_profit:,.0f}s")
    out("=" * 115)

    json_files = glob.glob(os.path.join(SAVES_DIR, "*_summary.json"))
    if not json_files:
        print(f"[!] No '*_summary.json' files found in '{SAVES_DIR}'.")
        sys.exit(1)

    out(f"[*] Scanning {len(json_files)} market datasets:")
    city_markets = {}
    for fpath in json_files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
                first_item = next(iter(data.values())) if data else {}
                m_type = first_item.get("market_type", "") if isinstance(first_item, dict) else ""
                city = detect_city_name(fpath, m_type)
                
                if city not in city_markets:
                    city_markets[city] = data
                else:
                    city_markets[city].update(data)
                out(f"    - [{city}] -> {os.path.basename(fpath)}")
        except Exception as e:
            out(f"    [!] Error reading {os.path.basename(fpath)}: {e}")

    royal_trades = []
    squeeze_trades = []
    bm_instant_trades = []
    bm_order_trades = []
    seen_routes = set()

    all_items = set()
    for market in city_markets.values():
        all_items.update(market.keys())

    for itype in all_items:
        weight = get_item_weight(itype)

        for q_name in ["Normal", "Good", "Outstanding", "Excellent", "Masterpiece"]:
            source_sellers = []
            for city, market in city_markets.items():
                if city == "Black Market":
                    continue
                q_data = market.get(itype, {}).get("qualities", {}).get(q_name)
                if not q_data:
                    continue

                sell_ladder = parse_ladder(q_data, "sell")
                stock = q_data.get("total_sell_stock") or 0
                if sell_ladder and stock > 0:
                    source_sellers.append({
                        "city": city,
                        "sell_ladder": sell_ladder,
                        "lowest_ask": sell_ladder[0][0],
                        "stock": stock,
                        "item_name": q_data.get("item_name") or itype,
                        "tier": f"T{q_data.get('tier', 4)}.{q_data.get('enchantment', 0)}"
                    })

            # -------------------------------------------------------------
            # BLACK MARKET ENGINES
            # -------------------------------------------------------------
            if "Black Market" in city_markets:
                bm_q = city_markets["Black Market"].get(itype, {}).get("qualities", {}).get(q_name)
                if bm_q:
                    bm_ask_ladder = parse_ladder(bm_q, "sell")
                    bm_bid_ladder = parse_ladder(bm_q, "buy")
                    bm_velocity = float(bm_q.get("daily_volume_velocity") or 0.0)
                    bm_avg_price = float(bm_q.get("history_28d_avg_price") or 0.0)

                    # A. Real Instant Dump (Instant Cash)
                    if bm_bid_ladder:
                        for s in source_sellers:
                            matched_qty, total_buy_cost, total_net_payout, total_profit = walk_instant_dump(
                                s["sell_ladder"], bm_bid_ladder
                            )

                            if matched_qty >= 1 and total_profit >= args.min_profit:
                                avg_buy = total_buy_cost / matched_qty
                                avg_net_payout = total_net_payout / matched_qty
                                avg_bid = avg_net_payout / (1.0 - TAX_INSTANT_FILL)
                                net_per_u = total_profit / matched_qty
                                roi = (net_per_u / avg_buy) * 100 if avg_buy > 0 else 0

                                if roi >= args.min_roi:
                                    bm_instant_trades.append({
                                        "item": s["item_name"],
                                        "tier": s["tier"],
                                        "quality": q_name,
                                        "from_city": s["city"],
                                        "buy_price": avg_buy,
                                        "bm_bid": avg_bid,
                                        "net_profit": net_per_u,
                                        "roi": roi,
                                        "weight_kg": weight,
                                        "silver_per_kg": net_per_u / weight if weight > 0 else 0,
                                        "safe_qty": matched_qty,
                                        "total_profit": total_profit
                                    })

                    # B. BM Order Book Runs (Batch Hauls)
                    if bm_ask_ladder and bm_avg_price > 0:
                        bm_top_ask = bm_ask_ladder[0][0]
                        realistic_bm_ask = min(bm_top_ask, bm_avg_price * 1.15)
                        net_ask = realistic_bm_ask * (1.0 - TAX_SELL_ORDER)

                        for s in source_sellers:
                            # Dynamic safe load calculation: handles low-velocity items properly
                            if bm_velocity >= 5.0:
                                target_vol = min(s["stock"], max(1, int(bm_velocity * 0.35)), 60)
                            else:
                                target_vol = min(s["stock"], 2)

                            if target_vol < 1:
                                continue

                            max_buy_price = net_ask / (1.0 + (args.min_roi / 100.0))
                            actual_qty, total_buy_cost, vwap_buy = walk_sell_order_buy(
                                s["sell_ladder"], target_vol, max_allowed_buy_price=max_buy_price
                            )

                            if actual_qty >= 1:
                                total_net_payout = net_ask * actual_qty
                                total_order_profit = total_net_payout - total_buy_cost
                                net_per_u = total_order_profit / actual_qty
                                roi = (net_per_u / vwap_buy) * 100 if vwap_buy > 0 else 0

                                if total_order_profit >= args.min_profit and roi >= args.min_roi:
                                    bm_order_trades.append({
                                        "item": s["item_name"],
                                        "tier": s["tier"],
                                        "quality": q_name,
                                        "from_city": s["city"],
                                        "buy_price": vwap_buy,
                                        "bm_ask": realistic_bm_ask,
                                        "net_profit": net_per_u,
                                        "roi": roi,
                                        "velocity": bm_velocity,
                                        "weight_kg": weight,
                                        "silver_per_kg": net_per_u / weight if weight > 0 else 0,
                                        "safe_qty": actual_qty,
                                        "total_profit": total_order_profit
                                    })

            # -------------------------------------------------------------
            # ROYAL MARKET ENGINES
            # -------------------------------------------------------------
            for s in source_sellers:
                for dest_city, market in city_markets.items():
                    if dest_city in (s["city"], "Black Market"):
                        continue
                    
                    route_key = (itype, q_name, s["city"], dest_city)
                    if route_key in seen_routes:
                        continue

                    dest_q = market.get(itype, {}).get("qualities", {}).get(q_name)
                    if not dest_q:
                        continue

                    dest_ask_ladder = parse_ladder(dest_q, "sell")
                    if not dest_ask_ladder:
                        continue

                    dest_top_ask = dest_ask_ladder[0][0]
                    dest_stock = int(dest_q.get("total_sell_stock") or 0)
                    dest_vel = float(dest_q.get("daily_volume_velocity") or 0.0)
                    dest_avg = float(dest_q.get("history_28d_avg_price") or 0.0)

                    if dest_top_ask and dest_avg > 0:
                        deviation = ((dest_top_ask - dest_avg) / dest_avg) * 100.0

                        # SQUEEZE SNIPER
                        if deviation > 50.0 and dest_stock <= 5:
                            exploit_sell_price = round(min(dest_top_ask - 1, dest_avg * 1.35), 0)
                            net_payout = exploit_sell_price * (1.0 - TAX_SELL_ORDER)

                            target_qty = min(s["stock"], 3)
                            actual_qty, total_buy_cost, vwap_buy = walk_sell_order_buy(
                                s["sell_ladder"], target_qty, max_allowed_buy_price=net_payout - 2000
                            )

                            if actual_qty >= 1:
                                total_profit = (net_payout * actual_qty) - total_buy_cost
                                net_per_u = total_profit / actual_qty
                                roi = (net_per_u / vwap_buy) * 100 if vwap_buy > 0 else 0

                                if roi >= 25.0 and total_profit >= 10000:
                                    seen_routes.add(route_key)
                                    squeeze_trades.append({
                                        "item": s["item_name"],
                                        "tier": s["tier"],
                                        "quality": q_name,
                                        "from": s["city"],
                                        "to": dest_city,
                                        "buy_price": vwap_buy,
                                        "troll_ask": dest_top_ask,
                                        "exploit_sell": exploit_sell_price,
                                        "net_profit": net_per_u,
                                        "roi": roi,
                                        "safe_qty": actual_qty,
                                        "total_profit": total_profit
                                    })

                        # STANDARD ROYAL FLIP
                        elif deviation <= 35.0:
                            net_payout_per_u = dest_top_ask * (1.0 - TAX_SELL_ORDER)
                            target_load = min(s["stock"], max(1, int(dest_vel * 0.40)), 40)

                            max_allowed_buy = net_payout_per_u / (1.0 + (args.min_roi / 100.0))
                            actual_qty, total_buy_cost, vwap_buy = walk_sell_order_buy(
                                s["sell_ladder"], target_load, max_allowed_buy_price=max_allowed_buy
                            )

                            if actual_qty >= 1:
                                total_profit = (net_payout_per_u * actual_qty) - total_buy_cost
                                net_per_u = total_profit / actual_qty
                                roi = (net_per_u / vwap_buy) * 100 if vwap_buy > 0 else 0

                                if total_profit >= args.min_profit and roi >= args.min_roi:
                                    seen_routes.add(route_key)
                                    royal_trades.append({
                                        "item": s["item_name"],
                                        "tier": s["tier"],
                                        "quality": q_name,
                                        "from": s["city"],
                                        "to": dest_city,
                                        "buy_price": vwap_buy,
                                        "sell_price": dest_top_ask,
                                        "net_profit": net_per_u,
                                        "roi": roi,
                                        "velocity": dest_vel,
                                        "weight_kg": weight,
                                        "silver_per_kg": net_per_u / weight if weight > 0 else 0,
                                        "safe_qty": actual_qty,
                                        "total_profit": total_profit
                                    })

    # -------------------------------------------------------------
    # TABLES WITH TRANSPORT DENSITY & TOTAL WEIGHT
    # -------------------------------------------------------------
    total_found = len(squeeze_trades) + len(bm_instant_trades) + len(bm_order_trades) + len(royal_trades)

    if squeeze_trades:
        squeeze_trades.sort(key=lambda x: x["total_profit"], reverse=True)
        out("\n" + "=" * 130)
        out("  🚨 PREDATOR SQUEEZE & SHORTAGE ALERTS")
        out("=" * 130)
        out(f"{'Item':<26} | {'Tier':<4} | {'Quality':<7} | {'Route':<15} | {'Buy VWAP':>8} | {'Post @':>8} | {'Net/u':>8} | {'ROI%':>5} | {'Load':>5} | {'Tot Wt':>7} | {'s/kg':>7} | {'Profit':>11}")
        out("-" * 130)
        for t in squeeze_trades[:10]:
            route_str = f"{t['from'][:4]} -> {t['to'][:4]}"
            tot_w = t['safe_qty'] * t.get('weight_kg', 1.5)
            s_kg = t.get('silver_per_kg', 0)
            out(f"{t['item']:<26} | {t['tier']:<4} | {t['quality'][:7]:<7} | {route_str:<15} | {t['buy_price']:>8,.0f} | {t['exploit_sell']:>8,.0f} | {t['net_profit']:>+8,.0f} | {t['roi']:>4.1f}% | {t['safe_qty']:>4}u | {tot_w:>5.1f}kg | {s_kg:>7,.0f} | {t['total_profit']:>+10,.0f}s")

    if bm_instant_trades:
        bm_instant_trades.sort(key=lambda x: x["total_profit"], reverse=True)
        out("\n" + "=" * 130)
        out("  🔥 TOP BLACK MARKET INSTANT-DUMP FLIPS")
        out("=" * 130)
        out(f"{'Item':<26} | {'Tier':<4} | {'Quality':<7} | {'Buy From':<12} | {'Buy VWAP':>8} | {'BM Bid':>8} | {'Net/u':>8} | {'ROI%':>5} | {'Load':>5} | {'Tot Wt':>7} | {'s/kg':>7} | {'Profit':>11}")
        out("-" * 130)
        for t in bm_instant_trades[:12]:
            tot_w = t['safe_qty'] * t.get('weight_kg', 1.5)
            s_kg = t.get('silver_per_kg', 0)
            out(f"{t['item']:<26} | {t['tier']:<4} | {t['quality'][:7]:<7} | {t['from_city']:<12} | {t['buy_price']:>8,.0f} | {t['bm_bid']:>8,.0f} | {t['net_profit']:>+8,.0f} | {t['roi']:>4.1f}% | {t['safe_qty']:>4}u | {tot_w:>5.1f}kg | {s_kg:>7,.0f} | {t['total_profit']:>+10,.0f}s")

    if bm_order_trades:
        bm_order_trades.sort(key=lambda x: x["total_profit"], reverse=True)
        out("\n" + "=" * 130)
        out("  💰 TOP BLACK MARKET ORDER-BOOK RUNS")
        out("=" * 130)
        out(f"{'Item':<26} | {'Tier':<4} | {'Quality':<7} | {'Buy From':<12} | {'Buy VWAP':>8} | {'BM Ask':>8} | {'Net/u':>8} | {'ROI%':>5} | {'Load':>5} | {'Tot Wt':>7} | {'s/kg':>7} | {'Profit':>11}")
        out("-" * 130)
        for t in bm_order_trades[:12]:
            tot_w = t['safe_qty'] * t.get('weight_kg', 1.5)
            s_kg = t.get('silver_per_kg', 0)
            out(f"{t['item']:<26} | {t['tier']:<4} | {t['quality'][:7]:<7} | {t['from_city']:<12} | {t['buy_price']:>8,.0f} | {t['bm_ask']:>8,.0f} | {t['net_profit']:>+8,.0f} | {t['roi']:>4.1f}% | {t['safe_qty']:>4}u | {tot_w:>5.1f}kg | {s_kg:>7,.0f} | {t['total_profit']:>+10,.0f}s")

    if royal_trades:
        royal_trades.sort(key=lambda x: x["total_profit"], reverse=True)
        out("\n" + "=" * 130)
        out("  🛡️ TOP SAFE ROYAL-TO-ROYAL RUNS")
        out("=" * 130)
        out(f"{'Item':<26} | {'Tier':<4} | {'Quality':<7} | {'Route':<15} | {'Buy VWAP':>8} | {'Sell':>8} | {'Net/u':>8} | {'ROI%':>5} | {'Load':>5} | {'Tot Wt':>7} | {'s/kg':>7} | {'Profit':>11}")
        out("-" * 130)
        for t in royal_trades[:15]:
            route_str = f"{t['from'][:4]} -> {t['to'][:4]}"
            tot_w = t['safe_qty'] * t.get('weight_kg', 1.5)
            s_kg = t.get('silver_per_kg', 0)
            out(f"{t['item']:<26} | {t['tier']:<4} | {t['quality'][:7]:<7} | {route_str:<15} | {t['buy_price']:>8,.0f} | {t['sell_price']:>8,.0f} | {t['net_profit']:>+8,.0f} | {t['roi']:>4.1f}% | {t['safe_qty']:>4}u | {tot_w:>5.1f}kg | {s_kg:>7,.0f} | {t['total_profit']:>+10,.0f}s")

    if total_found == 0:
        out(f"\n[-] No opportunities matched the current criteria (ROI >= {args.min_roi}%, Profit >= {args.min_profit:,.0f}s).")
        out("    Tip: Try running with '--min-roi 10 --min-profit 10000' to surface lower-margin trades.")

    out("=" * 130 + "\n")

    try:
        with open(OUTPUT_MD, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[+] Report saved to: {OUTPUT_MD}\n")
    except Exception as e:
        print(f"[!] Warning: Could not save report: {e}")

if __name__ == "__main__":
    main()