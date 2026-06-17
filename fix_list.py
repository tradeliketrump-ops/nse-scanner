"""Safely trim the bloated NIFTY500_FALLBACK list."""
import re

with open('nse_swing_scanner.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find NIFTY500_FALLBACK = [ section
start_marker = 'NIFTY500_FALLBACK = ['
start_pos = content.find(start_marker)
if start_pos == -1:
    print("ERROR: NIFTY500_FALLBACK not found!")
    exit(1)

# Find the FIRST line starting with ']' after the Additional marker
additional_marker = '# Additional Nifty500 liquid stocks'
additional_pos = content.find(additional_marker, start_pos)
if additional_pos == -1:
    print("ERROR: 'Additional Nifty500' marker not found!")
    exit(1)

# Find the closing ] that's on its own line
closing_pos = content.find('\n]\n', additional_pos)
if closing_pos == -1:
    print("ERROR: closing ] line not found!")
    exit(1)

closing_pos += 3  # include the \n]\n

print(f"Start: {start_pos}, Additional: {additional_pos}, Closing: {closing_pos}")

# Extract all symbols BEFORE the "Additional" marker
list_before_additional = content[start_pos:additional_pos]
symbols_before = list_before_additional.replace('"', '').replace('.NS', '').replace(',', ' ').split()
symbols_before = [s for s in symbols_before if s and not s.startswith('#') and s.isupper() and not any(c.isdigit() for c in s[:2])]
print(f"Symbols before Additional: {len(symbols_before)}")

# Now build new list: only content before "Additional" marker + closing ]
new_list_part = content[start_pos:additional_pos] + '\n]\n'
before = content[:start_pos]
after = content[closing_pos:]

new_content = before + new_list_part + after

with open('nse_swing_scanner.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"Written. Original: {len(content)} chars, New: {len(new_content)} chars")
print("Done!")