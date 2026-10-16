"""Generate Questie corrections for an AzerothCore server running mod-individual-progression.

The stock AzerothCore corrections in Database/AzerothCore/ describe an unmodified AzerothCore and
deliberately leave mod-individual-progression out (EXCLUDED_MODULE_NAMES). This tool layers a
server's own data on top of them: it reads a HeidiSQL export of the live acore_world database and
writes Database/IndividualProgression/, which loads after Database/AzerothCore/ and only holds what
that server does differently (vanilla quest levels, objectives, givers and spawns, the module's own
quests and NPCs, and other custom content on the server).

How each part is found:
- Quests: the AzerothCore quest validators run against the live export with the stock AzerothCore
  corrections merged in, so every mismatch left is something only the live server has. Quests that
  Questie does not know at all and that a player can start get a full entry.
- NPCs, objects and items: the AzerothCore generators run once against the AzerothCore source and once
  against the live export. Entries that differ (or are new) on the live server are kept.

Usage (from the repository root, about 30 minutes):
    python tools/generate_ip_overlay.py --acore-source D:/azerothcore-wotlk \
        --live-dump D:/azerothcore-live-dump/acore_world.sql --work-dir D:/questie-ip-work \
        --map-difficulty-dbc D:/azerothcore-wotlk/env/dist/bin/dbc/MapDifficulty.dbc

Quest IDs given with --skip-quest-range (default 90000-99999, a server owner's test quests) are left out.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from generate_acore_quest_corrections import build_module_text, validate_lua_fragment  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "Database" / "IndividualProgression"
QUEST_FIX_FILES = [
    "Database/Corrections/classicQuestFixes.lua",
    "Database/Corrections/tbcQuestFixes.lua",
    "Database/Corrections/wotlkQuestFixes.lua",
]
GENERATORS = {
    # name: (script, extra arguments, output file)
    "npc": ("generate_acore_npc_corrections.py", ["--include-missing-npcs"], "IndividualProgressionNPCCorrections.lua"),
    "object": ("generate_acore_object_corrections.py", ["--include-missing-objects"], "IndividualProgressionObjectCorrections.lua"),
    "item": ("generate_acore_item_corrections.py", ["--include-missing-items"], "IndividualProgressionItemCorrections.lua"),
}
MAP_DIFFICULTY_GENERATORS = {"npc", "object"}
ENTRY_START = re.compile(r"^(\s*)\[(\d+)\] = \{\s*$")
MAX_BATCH_BYTES = 128 * 1024
MAX_BATCH_ENTRIES = 500


def run(args):
    print("  $", " ".join(str(arg) for arg in args), flush=True)
    subprocess.run([str(arg) for arg in args], check=True, cwd=REPO_ROOT)


# --- the live export as an AzerothCore source tree ---------------------------------------------

def link_source_code(source: Path, acore_source: Path):
    """The generators also read C++ sources (Wintergrasp's scripted spawns): link <live>/src to the
    server's AzerothCore src (a directory junction on Windows, a symlink elsewhere)."""
    link = source / "src"
    if link.exists():
        return
    target = (acore_source / "src").resolve()
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def split_live_dump(dump: Path, work_dir: Path, acore_source: Path) -> Path:
    """Write each table of a HeidiSQL/mysqldump export to <work>/live-source/data/sql/base/db_world,
    the layout the AzerothCore tools read. Skipped when the split is newer than the export."""
    source = work_dir / "live-source"
    tables_dir = source / "data" / "sql" / "base" / "db_world"
    (source / "data" / "sql" / "updates" / "db_world").mkdir(parents=True, exist_ok=True)
    link_source_code(source, acore_source)
    stamp = tables_dir / ".split-from"
    if stamp.exists() and stamp.stat().st_mtime >= dump.stat().st_mtime:
        return source
    tables_dir.mkdir(parents=True, exist_ok=True)
    start = re.compile(r"^(?:CREATE TABLE(?: IF NOT EXISTS)?|INSERT INTO|REPLACE INTO) `(\w+)`")
    current, handle, seen = None, None, set()
    with dump.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            match = start.match(line)
            if match and match.group(1) != current:
                current = match.group(1)
                if handle:
                    handle.close()
                handle = (tables_dir / f"{current}.sql").open("a" if current in seen else "w", encoding="utf-8")
                seen.add(current)
            if handle:
                handle.write(line)
    if handle:
        handle.close()
    stamp.write_text(str(dump), encoding="utf-8")
    print(f"Split {len(seen)} tables from {dump}")
    return source


# --- quests ------------------------------------------------------------------------------------

def stock_quest_fix_files(work_dir: Path):
    """The stock AzerothCore quest corrections as `return {...}` files the validators can merge."""
    text = (REPO_ROOT / "Database/AzerothCore/AzerothCoreQuestCorrections.lua").read_text(encoding="utf-8")
    files = []
    for name in ("relationCorrections", "metadataCorrections"):
        match = re.search(rf"^    local {name} = \{{\n(.*?)^    \}}\n", text, re.M | re.S)
        if not match:
            raise ValueError(f"{name} not found in AzerothCoreQuestCorrections.lua")
        path = work_dir / f"stock_{name}.lua"
        path.write_text("return {\n" + match.group(1) + "}\n", encoding="utf-8")
        files.append(path)
    return files


def drop_quest_entries(fragment: str, skip):
    """Remove `[id] = {...},` entries whose quest ID is in skip from a suggestion fragment."""
    kept, skipping = [], False
    for line in fragment.splitlines():
        match = ENTRY_START.match(line)
        if match:
            skipping = int(match.group(2)) in skip
        if not skipping:
            kept.append(line)
        if skipping and line.strip() == "},":
            skipping = False
    return "\n".join(kept) + "\n"


def lua_string(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "") + '"'


def lua_list(values):
    return "{" + ",".join(str(value) for value in values) + "}"


def new_quest_entries(live_source: Path, skip):
    """{quest: field lines} for quests a player can start on the live server but Questie lacks."""
    import validate_acore_quest_metadata as metadata

    questie_text = (REPO_ROOT / "Database/Wotlk/wotlkQuestDB.lua").read_text(encoding="utf-8")
    known = {int(quest) for quest in re.findall(r"^\[(\d+)\] = ", questie_text, re.M)}
    quests = metadata.load_acore_sql_table(live_source, "quest_template")
    addons = metadata.load_acore_sql_table(live_source, "quest_template_addon")
    starters, enders = {}, {}
    for table, kind, target in (("creature_queststarter", 0, starters), ("gameobject_queststarter", 1, starters),
                                ("creature_questender", 0, enders), ("gameobject_questender", 1, enders)):
        for giver, quest in load_pairs(live_source, table):
            target.setdefault(quest, ([], []))[kind].append(giver)
    item_starts = {}
    for row in metadata.load_acore_sql_table(live_source, "item_template", key_column="entry").values():
        if int(row.get("startquest") or 0):
            item_starts.setdefault(int(row["startquest"]), []).append(int(row["entry"]))

    entries = {}
    for quest_id in sorted(set(quests) - known):
        row = quests[quest_id]
        level, min_level = int(row["QuestLevel"]), int(row["MinLevel"])
        startable = quest_id in starters or quest_id in item_starts
        if quest_id in skip or not startable or min_level > 80 or not row["LogTitle"] \
                or row["LogTitle"].startswith("<"):
            continue
        addon = addons.get(quest_id, {})
        creature_start, object_start = starters.get(quest_id, ([], []))
        creature_end, object_end = enders.get(quest_id, ([], []))
        started = "{%s,%s,%s}" % (lua_list(creature_start) if creature_start else "nil",
                                   lua_list(object_start) if object_start else "nil",
                                   lua_list(item_starts[quest_id]) if quest_id in item_starts else "nil")
        finished = "{%s,%s}" % (lua_list(creature_end) if creature_end else "nil",
                                 lua_list(object_end) if object_end else "nil")
        creatures = [int(row[f"RequiredNpcOrGo{i}"]) for i in range(1, 5) if int(row[f"RequiredNpcOrGo{i}"]) > 0]
        objects = [-int(row[f"RequiredNpcOrGo{i}"]) for i in range(1, 5) if int(row[f"RequiredNpcOrGo{i}"]) < 0]
        items = [int(row[f"RequiredItemId{i}"]) for i in range(1, 7) if int(row[f"RequiredItemId{i}"]) > 0]
        objectives = "{%s,%s,%s}" % (
            "{" + ",".join("{%d}" % c for c in creatures) + "}" if creatures else "nil",
            "{" + ",".join("{%d}" % o for o in objects) + "}" if objects else "nil",
            "{" + ",".join("{%d}" % i for i in items) + "}" if items else "nil")
        text = row["LogDescription"] or row["QuestCompletionLog"] or ""
        lines = [f"    [questKeys.name] = {lua_string(row['LogTitle'])},",
                 f"    [questKeys.startedBy] = {started},",
                 f"    [questKeys.finishedBy] = {finished},",
                 f"    [questKeys.requiredLevel] = {min_level},",
                 f"    [questKeys.questLevel] = {level},",
                 f"    [questKeys.requiredRaces] = {int(row['AllowableRaces'])},"]
        if int(addon.get("AllowableClasses") or 0):
            lines.append(f"    [questKeys.requiredClasses] = {int(addon['AllowableClasses'])},")
        if text:
            lines.append(f"    [questKeys.objectivesText] = {{{lua_string(text)}}},")
        if creatures or objects or items:
            lines.append(f"    [questKeys.objectives] = {objectives},")
        if int(row.get("StartItem") or 0):
            lines.append(f"    [questKeys.sourceItemId] = {int(row['StartItem'])},")
        previous = int(addon.get("PrevQuestID") or 0)
        if previous > 0:
            lines.append(f"    [questKeys.preQuestSingle] = {{{previous}}},")
        lines.append(f"    [questKeys.zoneOrSort] = {int(row['QuestSortID'])},")
        if int(addon.get("NextQuestID") or 0):
            lines.append(f"    [questKeys.nextQuestInChain] = {int(addon['NextQuestID'])},")
        if int(row.get("Flags") or 0):
            lines.append(f"    [questKeys.questFlags] = {int(row['Flags'])},")
        if int(addon.get("SpecialFlags") or 0) & 1:
            lines.append("    [questKeys.specialFlags] = 1,")
        entries[quest_id] = lines
        print(f"  new quest {quest_id} {row['LogTitle']}")
    return entries


def add_new_quests(fragment: str, new_quests):
    """Complete the validator's entries for quests Questie lacks with the fields it leaves out (givers,
    zone, races); a quest it has no entry for gets a whole one. One entry per quest, so nothing it
    found is overwritten."""
    lines = fragment.splitlines()
    index = 0
    while index < len(lines):
        match = ENTRY_START.match(lines[index])
        quest_id = match and int(match.group(2))
        if quest_id in new_quests:
            end = next(i for i in range(index + 1, len(lines)) if lines[i].strip() == "},")
            present = set(re.findall(r"\[questKeys\.(\w+)\]", "\n".join(lines[index:end])))
            indent = match.group(1) + "    "
            extra = [indent + field.strip() for field in new_quests.pop(quest_id)
                     if re.search(r"\[questKeys\.(\w+)\]", field).group(1) not in present]
            lines[end:end] = extra
            index = end + len(extra)
        index += 1
    for quest_id, fields in sorted(new_quests.items()):
        lines += [f"[{quest_id}] = {{", *fields, "},", ""]
    return "\n".join(lines) + "\n"


def load_pairs(source: Path, table: str):
    """(id, quest) rows of a quest starter/ender table."""
    path = source / "data" / "sql" / "base" / "db_world" / f"{table}.sql"
    if not path.exists():
        return []
    return [(int(a), int(b)) for a, b in re.findall(r"\((\d+),\s*(\d+)\)", path.read_text(encoding="utf-8"))]


def build_quests(args, live_source: Path, work_dir: Path, skip):
    fixes = [*QUEST_FIX_FILES, *stock_quest_fix_files(work_dir)]
    relations = work_dir / "quest_relations.lua"
    metadata = work_dir / "quest_metadata.lua"
    for script, output in (("validate_acore_quest_relations.py", relations), ("validate_acore_quest_metadata.py", metadata)):
        if not (args.reuse and output.exists()):
            run([sys.executable, TOOLS_DIR / script, "--acore-source", live_source, "--quest-fixes", *fixes,
                 "--suggest-lua", output, "--report", output.with_suffix(".json"), "--limit", "0"])
    relation_text = drop_quest_entries(relations.read_text(encoding="utf-8"), skip)
    metadata_text = drop_quest_entries(metadata.read_text(encoding="utf-8"), skip)
    metadata_text = add_new_quests(metadata_text, new_quest_entries(live_source, skip))
    validate_lua_fragment(relation_text, "relations")
    validate_lua_fragment(metadata_text, "metadata")
    text = build_module_text(relation_text, metadata_text)
    text = text.replace(
        "-- Generated from tools/reports/acore_relation_suggestions.lua and tools/reports/acore_metadata_suggestions.lua.\n"
        "-- Regenerate this file from the validators when AzerothCore quest data changes.",
        "-- Generated by tools/generate_ip_overlay.py from a live server export: only what that server\n"
        "-- (mod-individual-progression) does differently from the stock AzerothCore corrections.")
    text = text.replace("-- AzerothCore quest relation parity.", "-- Live server quest relations.")
    text = text.replace("-- AzerothCore quest metadata parity.", "-- Live server quest metadata.")
    validate_lua_fragment(text, "quest overlay")
    output = OUTPUT_DIR / "IndividualProgressionQuestCorrections.lua"
    output.write_text(text, encoding="utf-8")
    count = len(re.findall(r"^\s*\[\d+\] = \{$", text, re.M))
    print(f"Wrote {output} ({count} quest entries)")


# --- NPCs, objects, items ----------------------------------------------------------------------

def parse_module(path: Path):
    """(header lines, batch preamble lines, {id: entry text}) of a generated correction module."""
    lines = path.read_text(encoding="utf-8").splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith("QuestieCompat.RegisterCorrection("))
    header = lines[:first]
    returns = next(i for i in range(first, len(lines)) if lines[i].strip() == "return {")
    preamble = lines[first:returns + 1]
    entries, index = {}, returns + 1
    while index < len(lines):
        match = ENTRY_START.match(lines[index])
        if match:
            end = next(i for i in range(index + 1, len(lines)) if lines[i] == match.group(1) + "},")
            entries[int(match.group(2))] = "\n".join(lines[index:end + 1])
            index = end + 1
        else:
            index += 1
    return header, preamble, entries


def write_overlay_module(path: Path, header, preamble, entries, source_note):
    out = [line for line in header if not line.startswith("-- ")]
    while out and out[-1] == "":
        out.pop()
    out += ["", f"-- Generated by tools/generate_ip_overlay.py ({source_note}) from a live server export:",
            "-- only entries that server (mod-individual-progression) has differently from the stock",
            "-- AzerothCore corrections in Database/AzerothCore/.", ""]
    batch, size = [], 0

    def flush():
        if batch:
            out.extend([*preamble, *batch, "    }", "end)", ""])
            batch.clear()

    for entry_id in sorted(entries):
        entry = entries[entry_id] + "\n"
        if batch and (size + len(entry) > MAX_BATCH_BYTES or len(batch) >= MAX_BATCH_ENTRIES):
            flush()
            size = 0
        batch.append(entry)
        size += len(entry)
    flush()
    text = "\n".join(out)
    validate_lua_fragment(text, str(path))
    path.write_text(text, encoding="utf-8")


def questie_values(name, ids_fields):
    """{id: {field: Lua text}} of Questie's own values (database plus its expansion fixes), for
    entries the stock AzerothCore corrections change but the live server has as Questie does."""
    import importlib
    if name == "item":
        module = importlib.import_module("generate_acore_item_corrections")
        keys = module.parse_item_keys(REPO_ROOT / "Database/Wotlk/wotlkItemDB.lua")
        values = module.load_effective_questie_items(REPO_ROOT, keys)
        def fmt(field, value):
            return module.format_lua_value(value)
    else:
        module = importlib.import_module(f"generate_acore_{name}_corrections")
        parse_keys, load = ((module.parse_npc_keys, module.load_effective_questie_npcs) if name == "npc"
                            else (module.parse_object_keys, module.load_effective_questie_objects))
        keys = parse_keys(REPO_ROOT / f"Database/Wotlk/wotlk{'Npc' if name == 'npc' else 'Object'}DB.lua")
        fields = {field for wanted in ids_fields.values() for field in wanted}
        values = load(REPO_ROOT, keys, fields)
        zone_names = module.parse_zone_id_names(REPO_ROOT, module.parse_zone_maps(REPO_ROOT, None))
        def fmt(field, value):
            return module.format_lua_field_value(field, value, zone_names)
    result = {}
    for entry_id, wanted in ids_fields.items():
        own = values.get(entry_id) or {}
        result[entry_id] = {field: ("nil" if own.get(field) is None else fmt(field, own[field])) for field in wanted}
    return result


def revert_entries(name, stock, stock_only):
    """Entries that set the stock-corrected fields back to Questie's own values."""
    key_name = {"npc": "npcKeys", "object": "objectKeys", "item": "itemKeys"}[name]
    field_re = re.compile(rf"\[{key_name}\.(\w+)\]")
    wanted = {entry_id: field_re.findall(stock[entry_id]) for entry_id in stock_only}
    values = questie_values(name, wanted)
    entries = {}
    for entry_id, fields in values.items():
        lines = [f"        [{entry_id}] = {{"]
        for field, text in fields.items():
            if text == "nil":
                # Questie has nothing here: an empty table clears a stock spawn list or source list.
                text = "{}" if field in ("spawns", "waypoints", "npcDrops", "objectDrops", "itemDrops", "vendors") else None
            if text is not None:
                lines.append(f"            [{key_name}.{field}] = {text},")
        lines.append("        },")
        if len(lines) > 2:
            entries[entry_id] = "\n".join(lines)
    return entries


def build_generated(args, live_source: Path, work_dir: Path, name):
    script, extra, output_name = GENERATORS[name]
    outputs = {}
    for label, source in (("stock", args.acore_source), ("live", live_source)):
        output = work_dir / f"{name}_{label}.lua"
        command = [sys.executable, TOOLS_DIR / script, "--acore-source", source, "--output", output,
                   "--report", work_dir / f"{name}_{label}.md", *extra]
        if name in MAP_DIFFICULTY_GENERATORS and args.map_difficulty_dbc:
            command += ["--map-difficulty-dbc", args.map_difficulty_dbc]
        if not (args.reuse and output.exists()):
            run(command)
        outputs[label] = parse_module(output)
    header, preamble, live = outputs["live"]
    _, _, stock = outputs["stock"]
    changed = {entry_id: text for entry_id, text in live.items() if stock.get(entry_id) != text}
    stock_only = sorted(set(stock) - set(live))
    reverted = revert_entries(name, stock, stock_only)
    write_overlay_module(OUTPUT_DIR / output_name, header, preamble, {**changed, **reverted}, script)
    print(f"Wrote {output_name}: {len(changed)} changed entries and {len(reverted)} set back to Questie's own data")


def write_loader():
    files = ["IndividualProgressionQuestCorrections.lua", *(GENERATORS[name][2] for name in GENERATORS)]
    present = [name for name in files if (OUTPUT_DIR / name).exists()]
    lines = ['<Ui xmlns="http://www.blizzard.com/wow/ui/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             'xsi:schemaLocation="http://www.blizzard.com/wow/ui/ ..\\FrameXML\\UI.xsd">',
             '    <Script>QuestieLoader:StampLoadBoundary("Database/IndividualProgression/IndividualProgression.xml")</Script>',
             "",
             "    <!-- A live server's own data (mod-individual-progression); registered after Database/AzerothCore",
             "         so these corrections are applied last. Generated by tools/generate_ip_overlay.py. -->"]
    lines += [f'    <Script file="{name}"/>' for name in present]
    lines += ["</Ui>", ""]
    (OUTPUT_DIR / "IndividualProgression.xml").write_text("\n".join(lines), encoding="utf-8")


def stamp_toc_version(dump: Path):
    """Questie recompiles its database when the TOC version changes: suffix it with the export's date
    (10.0.1-335-ip20261016) so new corrections are picked up after each regeneration."""
    import datetime
    stamp = datetime.date.fromtimestamp(dump.stat().st_mtime).strftime("%Y%m%d")
    toc = REPO_ROOT / "Questie-335.toc"
    text = toc.read_bytes().decode("utf-8")
    text = re.sub(r"^(## Version: [\d.]+-335)(?:-ip\d+)?", rf"\g<1>-ip{stamp}", text, flags=re.M)
    text = re.sub(r"^(## Title: Questie-335\|cFF00FF00 v[\d.]+-335)(?:-ip\d+)?", rf"\g<1>-ip{stamp}", text, flags=re.M)
    toc.write_bytes(text.encode("utf-8"))
    print(f"Questie-335.toc version suffix: -ip{stamp}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--acore-source", required=True, type=Path, help="AzerothCore source tree the server is built from")
    parser.add_argument("--live-dump", required=True, type=Path, help="HeidiSQL/mysqldump export of the live acore_world")
    parser.add_argument("--work-dir", required=True, type=Path, help="Folder for the split export and intermediate files")
    parser.add_argument("--map-difficulty-dbc", type=Path, help="The server's MapDifficulty.dbc (NPC and object generators)")
    parser.add_argument("--skip-quest-range", nargs=2, type=int, default=(90000, 99999), metavar=("FIRST", "LAST"))
    parser.add_argument("--only", nargs="+", choices=["quest", *GENERATORS], help="Rebuild only these parts")
    parser.add_argument("--reuse", action="store_true", help="Reuse generator outputs already in --work-dir")
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    live_source = split_live_dump(args.live_dump, args.work_dir, args.acore_source)
    skip = set(range(args.skip_quest_range[0], args.skip_quest_range[1] + 1))
    parts = args.only or ["quest", *GENERATORS]
    if "quest" in parts:
        build_quests(args, live_source, args.work_dir, skip)
    for name in GENERATORS:
        if name in parts:
            build_generated(args, live_source, args.work_dir, name)
    write_loader()
    stamp_toc_version(args.live_dump)


if __name__ == "__main__":
    main()
