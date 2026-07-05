from pathlib import Path

path = Path('pages/recommendation.html')
text = path.read_text(encoding='utf-8')
old = 'return TABLE_LABELS[tableId] || tableId.replace(/_/g, " ").replace(/\x08\\w/g, (chr) => chr.toUpperCase());'
new = 'return TABLE_LABELS[tableId] || tableId.replace(/_/g, " ").replace(/\\b\\w/g, (chr) => chr.toUpperCase());'
if old not in text:
    print('Old string not found. \n---\n' + repr(text[text.find('function normalizeTableName'):text.find('function classifyTableDemand')+30]))
    raise SystemExit(1)
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('patched')
