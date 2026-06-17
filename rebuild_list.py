"""Replace NIFTY500_FALLBACK with a deduped, trimmed version (~500 symbols)."""
import re

with open('nse_swing_scanner.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find NIFTY500_FALLBACK = [ section
start_marker = 'NIFTY500_FALLBACK = ['
start_pos = content.find(start_marker)
if start_pos == -1:
    print("ERROR: NIFTY500_FALLBACK not found!")
    exit(1)

# Find the closing bracket matching this opening
bracket_start = content.find('[', start_pos)
depth = 0
end_pos = bracket_start
for i in range(bracket_start, len(content)):
    if content[i] == '[':
        depth += 1
    elif content[i] == ']':
        depth -= 1
        if depth == 0:
            end_pos = i + 1
            break

print(f"NIFTY500_FALLBACK spans from pos {start_pos} to {end_pos}")

# Extract all symbols from the list
list_text = content[bracket_start:end_pos]
symbols = re.findall(r'"([A-Z0-9.-]+\.NS)"', list_text)
print(f"Found {len(symbols)} symbols total")

# Deduplicate while preserving order, then trim to first ~500
seen = set()
unique_symbols = []
for s in symbols:
    if s not in seen:
        seen.add(s)
        unique_symbols.append(s)

print(f"After dedup: {len(unique_symbols)} unique symbols")

# Keep only first ~500
trimmed = unique_symbols[:500]
print(f"Trimmed to: {len(trimmed)} symbols")

# Find the "Additional Nifty500" marker - that's where we want to cut
additional_marker = '# Additional Nifty500 liquid stocks'
additional_pos = content.find(additional_marker, start_pos)
if additional_pos > 0:
    cut_start = additional_pos
    print(f"Cutting from 'Additional Nifty500' marker at pos {cut_start}")
else:
    # Just cut after the first 500 symbols
    cut_start = start_pos + len(start_marker) + 1
    # Find the right spot - after the Midcap section
    lines = content[start_pos:end_pos].split('\n')
    # Count lines of symbols
    line_count = 0
    for line in lines:
        if '"' in line and '.NS' in line:
            line_count += 1
    
    # Cut after the original 343 symbols
    # The original symbols are about 7 lines (5 symbols each)
    # Original list had ~144 symbols in the "core" sections
    # Let's find a more natural cut point - after NIFTY MIDCAP 100
    midcap_marker = '# NIFTY MIDCAP 100'
    midcap_pos = content.find(midcap_marker, start_pos)
    if midcap_pos > 0:
        # Count lines from midcap marker
        after_midcap = content[midcap_pos:end_pos]
        lines_in = after_midcap.split('\n')
        # Count symbol lines (with commas)
        sym_count = 0
        cut_line_idx = 0
        for idx, line in enumerate(lines_in):
            if '".NS"' in line or line.strip().endswith('.NS",'):
                sym_count += 1
                if sym_count >= 50:  # add ~50 stocks from midcap (total ~195)
                    cut_line_idx = idx
                    break
        
        # Find the character position in the full content
        cut_start = midcap_pos
        for i in range(cut_line_idx + 1):
            cut_start += len(lines_in[i]) + 1  # +1 for newline
            
        print(f"Cutting after Midcap section at pos {cut_start}")
    else:
        cut_start = start_pos + len(start_marker) + 1

# Build new content
before = content[:start_pos]
after_list_start = content[bracket_start:end_pos]

# The original list header + first 500 unique symbols as a comma-separated block
new_list_start = start_marker + '\n'

# Format: batch of 10 symbols per line for readability
new_symbol_lines = []
batch_size = 10
for i in range(0, len(trimmed), batch_size):
    batch = trimmed[i:i+batch_size]
    line = '    ' + ','.join(f'"{s}"' for s in batch) + ','
    new_symbol_lines.append(line)
new_list_text = '\n'.join(new_symbol_lines) + '\n]\n'

after = content[end_pos:]

new_content = before + new_list_start + new_list_text + after

with open('nse_swing_scanner.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"Written new file: {len(new_content)} chars (was {len(content)})")
print("Done!")