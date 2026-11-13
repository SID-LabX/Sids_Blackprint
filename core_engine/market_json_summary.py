import sys
import os
import json
from collections import defaultdict

def calculate_vwap(orders, target_qty, is_ask=True):
    """
    Calculates Volume-Weighted Average Price (VWAP) for a given batch size.
    is_ask=True  -> Buying from sell orders (sorts cheapest first).
    is_ask=False -> Selling into buy orders (sorts highest bidder first).
    """
    if not orders:
        return "No Orders"
    
    # Sort: asks ascending (lowest price first), bids descending (highest price first)
    sorted_orders = sorted(orders, key=lambda x: x.get('unit_price', 0), reverse=not is_ask)
    
    accumulated_qty = 0
    total_cost = 0.0
    
    for o in sorted_orders:
        qty = o.get('amount', 0)
        price = o.get('unit_price', 0)
        if qty <= 0 or price <= 0:
            continue
            
        take = min(qty, target_qty - accumulated_qty)
        total_cost += take * price
        accumulated_qty += take
        
        if accumulated_qty >= target_qty:
            break
            
    if accumulated_qty < target_qty:
        if accumulated_qty == 0:
            return "0 stock"
        avg_price = total_cost / accumulated_qty
        return f"{avg_price:,.0f}s (only {accumulated_qty}u avl)"
    
    avg_price = total_cost / target_qty
    return f"{avg_price:,.0f}s"

def extract_ladder(orders, is_ask=True, max_levels=10, min_volume_coverage=50):
    """
    Aggregates orders by price (Price x Qty).
    Stops when it has shown enough unique price levels OR covered at least 50 units.
    This guarantees you never get blinded by a 1-unit spike.
    """
    if not orders:
        return "EMPTY"
        
    sorted_orders = sorted(orders, key=lambda x: x.get('unit_price', 0), reverse=not is_ask)
    ladder = defaultdict(int)
    for o in sorted_orders:
        price = o.get('unit_price', 0)
        qty = o.get('amount', 0)
        if qty > 0 and price > 0:
            ladder[price] += qty
            
    ladder_entries = []
    cumulative_volume = 0
    for idx, (price, qty) in enumerate(ladder.items()):
        ladder_entries.append(f"{price:,.0f}s x {qty}")
        cumulative_volume += qty
        # Stop once we have covered at least min_volume_coverage units AND at least 5 price tiers,
        # or reached max_levels
        if (cumulative_volume >= min_volume_coverage and idx >= 4) or idx >= max_levels:
            remaining_orders = len(ladder) - (idx + 1)
            if remaining_orders > 0:
                ladder_entries.append(f"... (+{remaining_orders} more price levels)")
            break
            
    return ", ".join(ladder_entries)

def detect_walls(orders, is_ask=True, threshold_qty=12):
    """
    Detects single industrial orders holding significant supply/demand.
    """
    walls = []
    for o in orders:
        qty = o.get('amount', 0)
        price = o.get('unit_price', 0)
        actor = o.get('seller' if is_ask else 'buyer', 'Unknown')
        if qty >= threshold_qty:
            walls.append(f"{qty} units @ {price:,.0f}s by '{actor}'")
    return walls

def process_market_json(input_path, output_path=None):
    if not os.path.exists(input_path):
        print(f"Error: File '{input_path}' not found.")
        sys.exit(1)
        
    if output_path is None:
        base_name = os.path.splitext(input_path)[0]
        output_path = f"{base_name}_summary.md"

    print(f"[*] Reading and parsing: {input_path} ...")
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        sys.exit(1)

    lines = []
    city_name = os.path.basename(input_path).split('_')[0].capitalize()
    lines.append(f"# COMPACT L2 MARKET DEPTH DOSSIER: {city_name.upper()}")
    lines.append(f"*Extracted order-book depth with real slippage curves (VWAP) & Wall detection.*\n")

    item_count = 0
    variant_count = 0

    for item_type, item_info in data.items():
        item_name = item_info.get('item_name', item_type)
        qualities = item_info.get('qualities', {})
        
        has_printed_header = False

        for quality_name, q_data in qualities.items():
            sell_orders = q_data.get('sell_orders', [])
            buy_orders = q_data.get('buy_orders', [])
            velocity = q_data.get('daily_volume_velocity', 0) or 0
            turnover = q_data.get('history_28d_turnover', 0) or 0
            total_sell_stock = q_data.get('total_sell_stock', 0) or 0
            total_buy_demand = q_data.get('total_buy_demand', 0) or 0

            # Only skip if totally dead across all metrics
            if velocity == 0 and total_sell_stock == 0 and total_buy_demand == 0 and turnover == 0:
                continue

            if not has_printed_header:
                lines.append(f"\n---")
                lines.append(f"## {item_name} (`{item_type}`)")
                has_printed_header = True
                item_count += 1

            variant_count += 1
            avg_price = q_data.get('history_28d_avg_price', 0) or 0
            days_supply = q_data.get('days_of_supply', 'N/A')

            # Compute Slippage VWAP
            buy_vwap_5 = calculate_vwap(sell_orders, 5, is_ask=True)
            buy_vwap_10 = calculate_vwap(sell_orders, 10, is_ask=True)
            buy_vwap_20 = calculate_vwap(sell_orders, 20, is_ask=True)
            buy_vwap_50 = calculate_vwap(sell_orders, 50, is_ask=True)

            dump_vwap_5 = calculate_vwap(buy_orders, 5, is_ask=False)
            dump_vwap_10 = calculate_vwap(buy_orders, 10, is_ask=False)
            dump_vwap_20 = calculate_vwap(buy_orders, 20, is_ask=False)

            # L2 Order Ladders
            ask_ladder = extract_ladder(sell_orders, is_ask=True)
            bid_ladder = extract_ladder(buy_orders, is_ask=False)

            # Detect Walls
            sell_walls = detect_walls(sell_orders, is_ask=True, threshold_qty=12)
            buy_walls = detect_walls(buy_orders, is_ask=False, threshold_qty=12)

            lines.append(f"\n### Quality: {quality_name} (Tier {q_data.get('tier', 0)}.{q_data.get('enchantment', 0)})")
            lines.append(f"- **Liquidity:** Velocity: **{velocity:,.1f}/d** | Stock: {total_sell_stock} | 28d Avg Price: {avg_price:,.0f}s | Supply Life: {days_supply}d")
            lines.append(f"- **Real Sell Ladder (Asks):** {ask_ladder}")
            lines.append(f"- **Real Buy Ladder (Bids):** {bid_ladder}")
            lines.append(f"- **Buy Slippage (VWAP):** 5u: `{buy_vwap_5}` | 10u: `{buy_vwap_10}` | 20u: `{buy_vwap_20}` | 50u: `{buy_vwap_50}`")
            lines.append(f"- **Dump Slippage (VWAP):** 5u: `{dump_vwap_5}` | 10u: `{dump_vwap_10}` | 20u: `{dump_vwap_20}`")
            
            if sell_walls:
                lines.append(f"- **⚠️ Supply Walls Detected:** {'; '.join(sell_walls)}")
            if buy_walls:
                lines.append(f"- **🛡️ Buy Walls Detected:** {'; '.join(buy_walls)}")

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    print(f"[✓] Completed successfully!")
    print(f"    - Parsed {item_count} items ({variant_count} quality variants).")
    print(f"    - Saved compact dossier to: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python json_summary.py <input_market_file.json> [output_summary.md]")
        sys.exit(1)
        
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    process_market_json(input_file, output_file)