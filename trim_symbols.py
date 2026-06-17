"""Count bracket depth from the marker to find correct closing bracket."""
with open('nse_swing_scanner.py', 'r', encoding='utf-8') as f:
    content = f.read()

marker = '# Additional Nifty500 liquid stocks'
marker_pos = content.find(marker)
if marker_pos == -1:
    print("ERROR: Marker not found!")
    exit(1)

# Walk backwards from marker to find the opening [ of the list
bracket_depth = 0
closing_pos = marker_pos

# Scan forward from marker, tracking bracket depth
depth = 0
found_first_bracket = False
for i in range(marker_pos, len(content)):
    ch = content[i]
    if ch == '[':
        if not found_first_bracket:
            found_first_bracket = True
        depth += 1
    elif ch == ']':
        depth -= 1
        if found_first_bracket and depth == 0:
            closing_pos = i + 1
            break

print(f"Marker at position {marker_pos}")
print(f"Closing ] at position {closing_pos}")
print(f"Context around close: {repr(content[closing_pos-5:closing_pos+5])}")

# The bloat section goes from marker to (but not including) the closing ]
before = content[:marker_pos]
after = content[closing_pos:]
new_content = before + after

with open('nse_swing_scanner.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"Trimmed. Original: {len(content)} chars, New: {len(new_content)} chars")
print(f"Removed: from line containing 'Additional Nifty500' to closing bracket")