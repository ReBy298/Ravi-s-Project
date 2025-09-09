#!/usr/bin/env python3
"""
tableau_xml_to_bossstyle_ai.py
---------------------------------
Reads a Tableau datasource XML, narrows context for a given table, and uses an LLM
(Azure OpenAI or OpenAI) to produce:
  - <Table>_columns_boss_style.txt      (boss-style YAML-like spec for columns)
  - <Table>_partition.m                 (Power Query M partition block, via AI prompt)
  - context.json                        (narrowed JSON context sent to the LLM)

It also validates that the model covered ALL columns found in the Tableau XML.
If there are omissions, it retries up to 2 times with feedback listing missing columns.

USAGE (Azure OpenAI):
  export AZURE_OPENAI_API_KEY="..."
  export AZURE_OPENAI_ENDPOINT="https://<your-endpoint>.cognitiveservices.azure.com"
  export AZURE_OPENAI_API_VERSION="2024-12-01-preview"

  python tableau_xml_to_bossstyle_ai.py \
    --input /path/to/datasource.xml \
    --out-dir ./out \
    --provider azure \
    --model gpt-5-mini \
    --prompt-file ./prompt.txt \
    --table Orders

USAGE (OpenAI non-Azure):
  export OPENAI_API_KEY="..."
  python tableau_xml_to_bossstyle_ai.py \
    --input /path/to/datasource.xml \
    --out-dir ./out \
    --provider openai \
    --model gpt-4o-mini \
    --prompt-file ./prompt.txt \
    --table Orders
"""
import argparse, json, os, re, sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# -------------------------------
# XML parsing & context narrowing
# -------------------------------
def parse_tableau_xml(xml_path: str) -> Dict[str, Any]:
    """Parse Tableau datasource XML into a lightweight dict structure."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # connection info (server, db)
    named_conn = root.find(".//named-connections/named-connection/connection")
    conn_info = {}
    if named_conn is not None:
        for k in ("server", "dbname", "class", "authentication"):
            v = named_conn.attrib.get(k)
            if v:
                conn_info[k] = v

    # relations: list of (name, table, type)
    relations = []
    for rel in root.findall(".//relation[@type='table']"):
        relations.append({
            "name": rel.attrib.get("name"),
            "table": rel.attrib.get("table"),
            "connection": rel.attrib.get("connection"),
            "type": rel.attrib.get("type"),
        })

    # metadata records (columns)
    md_records = []
    for rec in root.findall(".//metadata-records/metadata-record[@class='column']"):
        md = {
            "remote_name": (rec.findtext("remote-name") or ""),
            "local_name": (rec.findtext("local-name") or ""),
            "parent_name": (rec.findtext("parent-name") or ""),
            "local_type": (rec.findtext("local-type") or ""),
            "aggregation": (rec.findtext("aggregation") or ""),
            "precision": (rec.findtext("precision") or ""),
            "width": (rec.findtext("width") or ""),
            "contains_null": (rec.findtext("contains-null") or ""),
            "ordinal": (rec.findtext("ordinal") or ""),
        }
        md_records.append(md)

    # object graph: objects and relationships
    objects = []
    for obj in root.findall(".//object-graph/objects/object"):
        objects.append({
            "caption": obj.attrib.get("caption"),
            "id": obj.attrib.get("id"),
        })

    relationships = []
    for rel in root.findall(".//object-graph/relationships/relationship"):
        eq = rel.find("./expression[@op='=']")
        if eq is None: 
            continue
        parts = eq.findall("./expression")
        if len(parts) != 2:
            continue
        left_op = parts[0].attrib.get("op", "")
        right_op = parts[1].attrib.get("op", "")
        left_ep = rel.find("./first-end-point")
        right_ep = rel.find("./second-end-point")
        relationships.append({
            "left": left_op, "right": right_op,
            "left_object_id": left_ep.attrib.get("object-id") if left_ep is not None else None,
            "right_object_id": right_ep.attrib.get("object-id") if right_ep is not None else None
        })

    return {
        "connection": conn_info,
        "relations": relations,
        "metadata_records": md_records,
        "objects": objects,
        "relationships": relationships,
    }

def narrow_context_for_table(ctx: Dict[str, Any], table_name: str) -> Dict[str, Any]:
    """Keep only info for the requested table + any relationships touching it."""
    parent_tag = f"[{table_name}]"
    md = [r for r in ctx.get("metadata_records", []) if r.get("parent_name") == parent_tag]

    # object id -> caption
    id2cap = {o["id"]: o["caption"] for o in ctx.get("objects", []) if o.get("id") and o.get("caption")}
    rels = []
    for r in ctx.get("relationships", []):
        # resolve (table.col) = (table.col)
        def _split_col(op: str) -> Tuple[Optional[str], Optional[str]]:
            # op may be "[Region]" etc. We only have column name; table comes from endpoint object
            col = op.strip("[]") if op else None
            return (None, col)

        lt, lc = _split_col(r.get("left"))
        rt, rc = _split_col(r.get("right"))
        left_tab = id2cap.get(r.get("left_object_id"))
        right_tab = id2cap.get(r.get("right_object_id"))
        rels.append({
            "left_table": left_tab, "left_column": lc,
            "right_table": right_tab, "right_column": rc
        })

    # filter only rels involving this table
    rels = [x for x in rels if x["left_table"] == table_name or x["right_table"] == table_name]

    # keep a small connection dict
    conn = ctx.get("connection", {})
    return {
        "table": table_name,
        "connection": {"server": conn.get("server"), "dbname": conn.get("dbname"), "class": conn.get("class")},
        "metadata_records": md,
        "relationships_touching_table": rels,
    }

# -------------------------------
# Required columns extraction
# -------------------------------
def extract_required_columns(narrowed_ctx: Dict[str, Any], table_name: str) -> List[str]:
    cols = []
    for rec in (narrowed_ctx.get("metadata_records") or []):
        name = (rec.get("local_name") or "").strip("[]").strip()
        if name:
            cols.append(name)
    return sorted(set(cols), key=str.lower)

def parse_boss_names(boss_text: str) -> set:
    names = set()
    for ln in (boss_text or "").splitlines():
        m = re.match(r'^\s*-\s*name\s*:\s*(.+)$', ln)
        if m:
            names.add(m.group(1).strip().strip("'\""))
        m2 = re.match(r'^\s*column\s+([A-Za-z0-9_\-\[\]\. ]+)', ln)
        if m2:
            names.add(m2.group(1).strip().strip("'\""))
    return names

# -------------------------------
# Prompt building
# -------------------------------
def load_prompts(prompt_path: str) -> Dict[str, str]:
    """
    Reads a prompt file that may contain sections:
      ### COLUMNS_PROMPT
      ### PARTITION_PROMPT
    If sections not found, entire file is treated as COLUMNS_PROMPT.
    """
    text = Path(prompt_path).read_text(encoding="utf-8")
    parts = {}
    cur = None
    buf = []
    for ln in text.splitlines():
        hdr = ln.strip().upper()
        if hdr == "### COLUMNS_PROMPT":
            if cur:
                parts[cur] = "\n".join(buf).strip()
                buf = []
            cur = "COLUMNS"
            continue
        if hdr == "### PARTITION_PROMPT":
            if cur:
                parts[cur] = "\n".join(buf).strip()
                buf = []
            cur = "PARTITION"
            continue
        buf.append(ln)
    if cur:
        parts[cur] = "\n".join(buf).strip()
    if "COLUMNS" not in parts:
        parts["COLUMNS"] = text.strip()
    return parts

def build_columns_prompt(table_name: str, narrowed_ctx: Dict[str, Any], template: str) -> Tuple[str, List[str]]:
    req_cols = extract_required_columns(narrowed_ctx, table_name)
    payload = {
        "table": table_name,
        "metadata_records": narrowed_ctx.get("metadata_records"),
        "relationships_touching_table": narrowed_ctx.get("relationships_touching_table"),
        "connection": narrowed_ctx.get("connection"),
    }
    out = template
    out = out.replace("{table_name}", table_name)
    out = out.replace("{context_json}", json.dumps(payload, indent=2))
    out = out.replace("{required_columns_list}", "- " + "\n- ".join(req_cols))
    return out, req_cols

def build_partition_prompt(table_name: str, narrowed_ctx: Dict[str, Any], template: str) -> str:
    conn = narrowed_ctx.get("connection") or {}
    server = conn.get("server") or "<SERVER_NAME>"
    dbname = conn.get("dbname") or "<DATABASE_NAME>"
    payload = {
        "table": table_name,
        "connection": {"server": server, "dbname": dbname},
    }
    out = template
    out = out.replace("{table_name}", table_name)
    out = out.replace("{server}", server)
    out = out.replace("{dbname}", dbname)
    out = out.replace("{context_json}", json.dumps(payload, indent=2))
    return out

# -------------------------------
# LLM calls
# -------------------------------
def call_openai_chat(provider: str, model: str, system_prompt: str, user_prompt: str) -> str:
    if provider == "azure":
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            # some Azure deployments only accept default temperature
            max_completion_tokens=4096,
        )
        return (resp.choices[0].message.content or "").strip()
    else:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=2048,
        )
        return (resp.choices[0].message.content or "").strip()

# -------------------------------
# Main
# -------------------------------
def main():
    ap = argparse.ArgumentParser(description="Generate boss-style columns and M partition via LLM from Tableau XML.")
    ap.add_argument("--input", required=True, help="Path to Tableau datasource XML")
    ap.add_argument("--out-dir", required=True, help="Output directory")
    ap.add_argument("--table", required=True, help="Target table name, e.g., Orders")
    ap.add_argument("--provider", choices=["openai", "azure"], required=True, help="LLM provider")
    ap.add_argument("--model", required=True, help="Model or deployment name")
    ap.add_argument("--prompt-file", required=True, help="Path to prompt file (supports sections)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Parse XML and narrow context
    ctx = parse_tableau_xml(args.input)
    narrowed = narrow_context_for_table(ctx, args.table)

    # Save context for debugging
    Path(out_dir / "context.json").write_text(json.dumps(narrowed, indent=2), encoding="utf-8")

    # 2) Load prompts
    parts = load_prompts(args.prompt_file)
    columns_template = parts.get("COLUMNS", "")
    partition_template = parts.get("PARTITION", "").strip()
    if not partition_template:
        # sensible default if not provided
        partition_template = (
            "You are a Power Query M expert.\n"
            "Goal: produce the import partition block for table '{table_name}'.\n"
            "Use a Sql.Databases source with the server and database from context.\n"
            "STRICT OUTPUT FORMAT (exactly this structure):\n"
            "partition {table_name} = m\n"
            "  mode: import\n"
            "  source =\n"
            "    let\n"
            "      Source = Sql.Databases(\"{server}\"),\n"
            "      srcSource = Source{{[Name=\"{dbname}\"]}}[Data],\n"
            "      {table_name}_object = srcSource{{[Item=\"{table_name}\",Schema=\"dbo\"]}}[Data]\n"
            "    in\n"
            "      {table_name}_object\n"
            "\n"
            "CONTEXT:\n"
            "{context_json}\n"
            "Return ONLY the partition block, no prose."
        )

    # 3) Build & call LLM for columns
    system_prompt_cols = "You are a Power BI semantic model expert. Respond with boss-style YAML only."
    user_prompt_cols, required_cols = build_columns_prompt(args.table, narrowed, columns_template)
    boss_out = call_openai_chat(args.provider, args.model, system_prompt_cols, user_prompt_cols)

    # Quality loop: ensure all columns present; retry up to 2 times if missing
    got = parse_boss_names(boss_out)
    miss = sorted(set(required_cols) - got)
    retries = 0
    while miss and retries < 2:
        feedback = (
            user_prompt_cols +
            "\n\nIMPORTANT: You omitted the following required columns. "
            "Regenerate the full boss-style list covering ALL columns exactly once, "
            "no extras, no omissions:\n- " + "\n- ".join(miss)
        )
        boss_out = call_openai_chat(args.provider, args.model, system_prompt_cols, feedback)
        got = parse_boss_names(boss_out)
        miss = sorted(set(required_cols) - got)
        retries += 1

    # 4) Build & call LLM for partition
    system_prompt_part = "You are a Power Query M and Power BI semantic model expert. Respond with the partition block only."
    user_prompt_part = build_partition_prompt(args.table, narrowed, partition_template)
    part_out = call_openai_chat(args.provider, args.model, system_prompt_part, user_prompt_part)

    # 5) Write files
    (out_dir / f"{args.table}_columns_boss_style.txt").write_text(boss_out + "\n", encoding="utf-8")
    (out_dir / f"{args.table}_partition.m").write_text(part_out + "\n", encoding="utf-8")

    print("Done.")
    print(" -", out_dir / f"{args.table}_columns_boss_style.txt")
    print(" -", out_dir / f"{args.table}_partition.m")
    print(" -", out_dir / "context.json")

if __name__ == "__main__":
    main()
