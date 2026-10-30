"""Quote plain YAML scalars that contain ': ' (a common authoring mistake in scenario files).

    python -m tools.yaml_quote_fix scenarios/*/scenario.yaml
"""

import re
import sys
from pathlib import Path

LINE = re.compile(r"^(\s*(?:- )?[A-Za-z_][\w]*:\s)(.+)$")


def fix_text(text: str) -> tuple[str, int]:
    out, n = [], 0
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            key, val = m.group(1), m.group(2)
            v = val.strip()
            plain = not v.startswith(('"', "'", "{", "[", ">", "|", "&", "*", "!"))
            if plain and ": " in v and not v.endswith(":"):
                v = '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
                line = key + v
                n += 1
        out.append(line)
    return "\n".join(out) + "\n", n


def main() -> None:
    for p in sys.argv[1:]:
        path = Path(p)
        new, n = fix_text(path.read_text(encoding="utf-8"))
        if n:
            path.write_text(new, encoding="utf-8")
        print(f"{path}: {n} satır tırnaklandı")


if __name__ == "__main__":
    main()
