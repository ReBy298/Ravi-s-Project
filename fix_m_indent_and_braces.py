import re
from pathlib import Path
import argparse

def fix_braces(text: str) -> str:
    # Replace accidental double braces inside M
    return text.replace("{{", "{").replace("}}", "}")

def fix_m_partition_block(text: str, base_indent=2, let_indent=4, body_indent=6, ret_indent=6) -> str:
    """
    Normalizes:
      source =
        let
          <body lines>
        in
          <return>
    Indents are in spaces relative to table block start.
    """
    # Build indent strings
    si  = " " * base_indent          # source line
    li  = " " * (base_indent + let_indent)   # let / in
    bi  = " " * (base_indent + body_indent)  # body lines
    ri  = " " * (base_indent + ret_indent)   # return line

    pattern = re.compile(
        r"(?:^|\n)([ \t]*)source\s*=\s*\n"   # capture table-level indent if needed
        r"([ \t]*)let\s*\n"
        r"(?P<body>[\s\S]*?)"
        r"\n[ \t]*in\s*\n"
        r"[ \t]*(?P<ret>[^\n]+)",
        re.MULTILINE
    )

    def _repl(m: re.Match) -> str:
        raw_body = m.group("body").strip("\n")
        body_lines = []
        for line in raw_body.splitlines():
            s = line.strip()
            if not s:
                continue
            body_lines.append(f"{bi}{s}")
        fixed_body = "\n".join(body_lines)
        return (
            f"\n{si}source =\n"
            f"{li}let\n"
            f"{fixed_body}\n"
            f"{li}in\n"
            f"{ri}{m.group('ret').strip()}"
        )

    return pattern.sub(_repl, fix_braces(text))

def process_file(p: Path, **kw):
    txt = p.read_text(encoding="utf-8")
    fixed = fix_m_partition_block(txt, **kw)
    p.write_text(fixed, encoding="utf-8")
    print(f"[OK] {p}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tables-dir", default="OUT_PBIP/SemanticModel/tables")
    ap.add_argument("--base-indent", type=int, default=2)
    ap.add_argument("--let-indent", type=int, default=2)   # base(2)+2=4
    ap.add_argument("--body-indent", type=int, default=4)  # base(2)+4=6
    ap.add_argument("--ret-indent", type=int, default=4)   # base(2)+4=6
    args = ap.parse_args()

    td = Path(args.tables_dir)
    if not td.exists():
        raise SystemExit(f"Tables dir not found: {td}")

    for f in sorted(td.glob("*.tmdl")):
        process_file(
            f,
            base_indent=args.base_indent,
            let_indent=args.let_indent,
            body_indent=args.body_indent,
            ret_indent=args.ret_indent,
        )

if __name__ == "__main__":
    main()
