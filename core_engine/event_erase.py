#!/usr/bin/env python3
import json
import os
import sys

if len(sys.argv) < 2:
    print("Usage: python event_erase.py <your_file.json>")
    sys.exit(1)

input_file = sys.argv[1]

if not os.path.exists(input_file):
    print(f"[!] Error: File '{input_file}' not found.")
    sys.exit(1)

base_name, ext = os.path.splitext(input_file)
output_file = f"{base_name}_clean{ext}"

print(f"[*] Reading '{os.path.basename(input_file)}'...")

try:
    with open(input_file, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read().strip()
        
    # Auto-repair truncated sniffer files (missing closing brackets)
    if content and not content.endswith("]"):
        last_bracket = content.rfind("}")
        if last_bracket != -1:
            content = content[:last_bracket + 1] + "\n]"
            
    packets = json.loads(content)
except Exception as e:
    print(f"[!] Critical: Failed to parse '{input_file}': {e}")
    sys.exit(1)

total_packets = len(packets)
if not isinstance(packets, list):
    print("[!] Unexpected format: Top-level is not a list of packets.")
    sys.exit(1)

# Drop EVENT packets (keep only REQUEST and RESPONSE)
cleaned_packets = [
    pkt for pkt in packets 
    if isinstance(pkt, dict) and pkt.get("kind", "").upper() != "EVENT"
]

kept_count = len(cleaned_packets)
deleted_count = total_packets - kept_count

print(f"[+] Total Packets: {total_packets:,} | Dropped Events: {deleted_count:,} | Kept: {kept_count:,}")

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(cleaned_packets, f, indent=2)

print(f"[+] Clean stream written to -> {os.path.basename(output_file)}")