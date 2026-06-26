"""Fix syntax errors in backtest.py."""
with open("backtest.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix the bad list comprehension on line ~126
import re
# Replace the broken line (has nested if/else which is invalid)
content = content.replace(
    'all_dates = sorted(set(d for d in all_dates if start_dt <= d.to_pydatetime() if hasattr(d, "to_pydatetime") else d))',
    "all_dates = sorted(set(d for d in all_dates))"
)

# Also remove the duplicate all_dates line
lines = content.split("\n")
filtered = []
for i, line in enumerate(lines):
    # Skip the faulty line entirely
    if "if hasattr(d, " in line and "to_pydatetime" in line:
        continue
    filtered.append(line)
content = "\n".join(filtered)

with open("backtest.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Fixed backtest.py")