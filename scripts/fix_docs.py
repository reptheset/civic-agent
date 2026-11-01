"""Copies your documents into data/my_docs and points the saved profile at them."""
import json
import shutil
from pathlib import Path

f = Path("data/my_profile.json")
d = json.loads(f.read_text())
for doc in d["documents"]:
    while True:
        raw = input(f"\nDrag your {doc['doc_type']} file here, then press Enter: ")
        src = Path(raw.strip().strip("'\"").replace("\\ ", " ")).expanduser()
        if src.is_file():
            dest = Path("data/my_docs") / f"{doc['doc_type']}{src.suffix.lower()}"
            shutil.copy(src, dest)
            doc["path"], doc["filename"] = str(dest.resolve()), dest.name
            print(f"  Copied to {dest}")
            break
        print(f"  Not found: {src}  -- try dragging it again")
f.write_text(json.dumps(d, indent=2))
print("\nCheck:")
for doc in d["documents"]:
    print(f"  {doc['doc_type']}: exists = {Path(doc['path']).exists()}")
