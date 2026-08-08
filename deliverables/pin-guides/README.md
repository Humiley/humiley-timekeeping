# Signing-PIN guides (personalised, bilingual EN/VN)

One letterhead letter per employee explaining how to set up their electronic signing PIN.
Generated from `generate_pin_guides.py`.

## Regenerate for the current roster
```bash
export HUMILEY_BRAND_SKILL=/path/to/humiley-brand      # the skill with scripts/fill_letter.py
python3 generate_pin_guides.py                          # uses the portal's built-in seed roster
python3 generate_pin_guides.py --csv employees.csv      # or your own CSV (columns: name,title,dept)
```
Export `employees.csv` from the portal's employee list (Excel/CSV export) to produce a letter
for every current employee by name.
