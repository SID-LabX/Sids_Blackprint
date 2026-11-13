# Sid's Blackprint

A brief description of what this project does.

## Contributing

We welcome contributions! Please review [CONTRIBUTING.md](CONTRIBUTING.md) and note that all contributors must sign our [Contributor License Agreement (CLA)](CLA.md) before pull requests can be merged.

## License

This project is licensed under the terms of the [PROPRIETARY SOURCE-AVAILABLE LICENSE](LICENSE).

---

### Complete Glossary of Every Metric in Your Sheet csv.

Here is what every column in summary means, how it is calculated, and how to use it for trading:

---

#### 1. Identity & Location
* **`item_name`**: The localized in-game display name (e.g. `Adept's Mercenary Shoes`).
* **`item_type`**: The internal game ID (e.g. `T4_SHOES_LEATHER_SET1`).
* **`tier`**: The item tier (e.g. `4` = Tier 4).
* **`enchantment`**: The enchantment level (`0` = flat, `1` = .1 green, `2` = .2 blue, `3` = .3 purple, `4` = .4 gold).
* **`quality_name`**: Item quality from 1 to 5 (`Normal`, `Good`, `Outstanding`, `Excellent`, `Masterpiece`). Higher quality gives minor item power bonuses.
* **`market_type`**: Displays whether the data was captured at the **Caerleon Black Market** (system-generated loot buyer) or a **Royal Marketplace** (player-to-player city market).

---

#### 2. Live Supply (Sell Orders)
* **`lowest_sell_price`**: The absolute cheapest price an item is currently listed for sale. This is what you would pay if you clicked "Buy Now".
* **`net_sell_payout`**: The actual silver you receive after the game deducts market taxes and listing setup fees:
  $$\text{net\_sell\_payout} = \text{lowest\_sell\_price} \times (1 - \text{fee\_rate})$$
  *(Default: 4% tax + 2.5% setup fee for Premium = 6.5% total deduction).*
* **`total_sell_stock`**: The total count of all items of this quality currently sitting in active sell orders on the market.
* **`sell_order_count`**: How many separate sell listings make up that stock (e.g. 2,802 shoes spread across 19 different player listings).

---

#### 3. Live Demand (Buy Orders / Black Market Requests)
* **`highest_buy_order`**: The highest price currently offered by a buyer.
  * *At the Black Market:* This is what the Black Market system will **instantly pay you** right now if you sell to it directly.
  * *At Royal Markets:* The top price a player will pay for an instant sell.
* **`total_buy_demand`**: The total number of items buyers are waiting to buy at buy-order prices.
* **`buy_order_count`**: The number of open buy orders currently waiting.

---

#### 4. Historical Turnover & Velocity (28-Day Data)
* **`history_28d_volume`**: The total number of units that **actually sold** in this market over the last 28 days.
* **`history_28d_turnover`**: The total silver exchanged for this item over the last 28 days:
  $$\text{history\_28d\_turnover} = \sum (\text{Sold Units} \times \text{Sold Price})$$
* **`history_28d_avg_price`**: The volume-weighted average price over the last 28 days:
  $$\text{history\_28d\_avg\_price} = \frac{\text{history\_28d\_turnover}}{\text{history\_28d\_volume}}$$
* **`daily_volume_velocity`**: The average sales rate per day over the 28-day window:
  $$\text{daily\_volume\_velocity} = \frac{\text{history\_28d\_volume}}{28}$$
  *(e.g., `1,465.3/d` means ~1,465 pairs of Good T4 Mercenary Shoes are consumed every 24 hours).*

---

#### 5. Financial Indicators
* **`days_of_supply`**: How many days it will take for the current market stock to sell out at the current sales velocity:
  $$\text{days\_of\_supply} = \frac{\text{total\_sell\_stock}}{\text{daily\_volume\_velocity}}$$
  * **`< 2.0 days` (Low Supply):** Prices will likely rise or hold firm because items sell faster than they are restocked.
  * **`> 15.0 days` (Oversupplied):** There is too much stock sitting on the market; expect price cuts or undercuts.
* **`price_deviation_pct`**: The percentage difference between the current lowest sell listing and the 28-day historical average price.
* **`liquidity_status`**: A rating of how quickly and easily you can sell the item without crashing the price:
  * **`VERY HIGH`**: Sells $\ge 50$ units per day (fast cash, safe to transport in bulk).
  * **`MEDIUM`**: Sells $5 - 49$ units per day.
  * **`LOW`**: Sells $1 - 4$ units per day (slow to move).
  * **`ILLIQUID`**: Has current stock listed, but 0 recorded sales over the last 28 days.
  * **`NO DATA`**: No orders and no sales history logged.

----

# JSON glossary

Here is the complete glossary for the fields found in `summary.json` file, broken down by section.

---

### 1. Root & Header Fields
These define the overall identity of the item for the entire JSON object:

* **`item_type`**: The internal system ID used by Albion's game files (e.g., `"T4_SHOES_LEATHER_SET1"`).
* **`item_name`**: The human-readable in-game display name (e.g., `"Adept's Mercenary Shoes"`).
* **`base_item`**: The un-enchanted core item type (strips any `@1`, `@2`, etc., suffix).
* **`tier`**: The equipment tier number (`4` = Tier 4 / Adept).
* **`enchantment`**: The enchantment level (`0` = flat, `1` = .1, `2` = .2, `3` = .3, `4` = .4).
* **`market_type`**: The market location (`"Caerleon Black Market"` or `"Royal Marketplace"`).
* **`qualities`**: A dictionary containing up to 5 sub-objects, keyed by quality name: `"Normal"`, `"Good"`, `"Outstanding"`, `"Excellent"`, and `"Masterpiece"`.

---

### 2. Quality Node Fields
Inside each quality object (e.g., `qualities -> "Good"`), you get the summary indicators plus the two deep-order lists:

* **`quality_id`**: The numeric index used by the game engine for quality:
  * `1` = Normal
  * `2` = Good
  * `3` = Outstanding
  * `4` = Excellent
  * `5` = Masterpiece
* **`quality_name`**: The display name matching `quality_id`.
* **`lowest_sell_price`**: The cheapest price currently available to buy instantly on the market.
* **`net_sell_payout`**: What you actually take home after paying taxes and setup fees if you list at `lowest_sell_price`.
* **`total_sell_stock`**: Total units currently listed for sale across all sell orders of this quality.
* **`sell_order_count`**: The number of individual active sell orders currently listed.
* **`highest_buy_order`**: The top price any buyer (or the Black Market) will pay you right now on an instant sell.
* **`total_buy_demand`**: Total units buyers are waiting to purchase via active buy orders.
* **`buy_order_count`**: The number of open buy orders currently waiting.
* **`history_28d_volume`**: Total units actually purchased over the last 28 days.
* **`history_28d_turnover`**: Total silver volume spent on this item over the last 28 days.
* **`history_28d_avg_price`**: The volume-weighted average price over the last 28 days (`turnover / volume`).
* **`daily_volume_velocity`**: Average units sold per 24-hour day (`28d_volume / 28`).
* **`days_of_supply`**: Estimated days until current listed stock sells out at the current sales rate (`total_sell_stock / daily_volume_velocity`).
* **`price_deviation_pct`**: How far above or below the current lowest sell price is compared to the 28-day historical average.
* **`liquidity_status`**: Speed of turnover rating (`"VERY HIGH"`, `"MEDIUM"`, `"LOW"`, `"ILLIQUID"`, `"NO DATA"`).

---

### 3. Detailed Live Order Book Lists (`sell_orders` & `buy_orders`)
This is the exclusive depth data that only exists in your JSON (and had to be omitted from the flat CSV)!

#### Inside `sell_orders` (Player listings waiting to be bought):
```json
{
  "id": 9172144872,
  "unit_price": 2834.0,
  "amount": 1,
  "seller": "Kingdefeated",
  "expires": "2026-10-04T17:17:43.279392"
}
```
* **`id`**: The unique global transaction ID assigned to this order by Albion’s servers.
* **`unit_price`**: The price per single shoe in silver (converted from Albion’s internal $10,000\times$ integer format).
* **`amount`**: How many units this seller has remaining at this exact price.
* **`seller`**: The in-game character name of the seller who listed the order.
* **`expires`**: The exact UTC timestamp when this listing will automatically expire and return the items to the seller's mailbox if unsold (standard player listings last 30 days).

---

#### Inside `buy_orders` (Buy orders waiting to purchase items):
```json
{
  "id": 9247286437,
  "unit_price": 2528.0,
  "amount": 22,
  "buyer": "@BLACK_MARKET",
  "expires": "3026-01-14T10:57:39.038783"
}
```
* **`id`**: The unique global transaction ID of the buy order.
* **`unit_price`**: What the buyer will pay per unit for an instant sell.
* **`amount`**: How many units the buyer is willing to absorb at this price.
* **`buyer`**: 
  * If it says **`"@BLACK_MARKET"`**, this is an official system-generated demand order created by the game engine to supply mob drops in dungeons and chests.
  * If it shows a character name, it is a player-placed buy order.
* **`expires`**: The expiration date:
  * Note the year **`3026`** on `@BLACK_MARKET` orders! The game sets system orders 1,000 years into the future so they never expire until filled.