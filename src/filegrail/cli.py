"""Command line interface. Standard library only, no runtime dependencies.

The tool does several distinct things, and they are commands rather than flags.
`--doctor` and `--explain` were modes wearing an option's clothes: each one
ignored most of the other options, and every pair of them was mutually
exclusive, which is exactly the shape subcommands exist to express.

`filegrail <path>` still scans, with no command word, because that is the thing
people do ninety per cent of the time and making them type `scan` for it would
be ceremony.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from . import __version__
from .analysis import analyse
from .casereport import render_case
from .doctor import survey
from .filters import FAMILIES, UnknownType, describe, selection
from .htmlreport import render_html
from .identify import extract
from .pronom import registry
from .report import (
    render_compare,
    render_doctor,
    render_explain,
    render_json,
    render_json_compare,
    render_json_doctor,
    render_json_explain,
    render_text,
    render_timeline,
)
from .scan import ScanCoverage, Unsearched, scan
from .theme import detect

if TYPE_CHECKING:  # only for the signatures; the scan brings the real thing
    from .analysis import Case
    from .identify import Identifier
    from .models import FileRecord

COMMANDS = (
    "scan",
    "image",
    "photo",
    "explain",
    "compare",
    "doctor",
    "menu",
    "clean",
    "mcp",
    "help",
)


# --- parsers -----------------------------------------------------------------


def _common() -> argparse.ArgumentParser:
    """Options every command understands."""
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("-j", "--json", action="store_true", help="Output machine-readable JSON.")
    colour = shared.add_mutually_exclusive_group()
    colour.add_argument(
        "--color",
        "--colour",
        dest="colour",
        action="store_true",
        default=None,
        help="Force styled output even when not writing to a terminal.",
    )
    colour.add_argument(
        "--no-color",
        "--no-colour",
        dest="colour",
        action="store_false",
        help="Disable ANSI colors.",
    )
    return shared


def _profile() -> argparse.ArgumentParser:
    """The option for reading a machine that is not this one.

    Every source that answers *how did this arrive* lives under a home
    directory, and the readers have always taken one as an argument. Offering
    it here is what turns `what does my machine remember about my files` into
    `here is a mounted profile, reconstruct what its machine remembered`.
    """
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--home",
        type=Path,
        metavar="DIR",
        help="Read browser, shell and desktop history from this user profile "
        "instead of the current one, e.g. a mounted image.",
    )
    return shared


def _redaction() -> argparse.ArgumentParser:
    """The option for output that is about to leave the machine.

    A parent rather than a member of `_common()` because it belongs to the
    commands that render evidence and to no others: `doctor` prints which
    sources exist, `clean` prints file names and the blocks taken out of them,
    and neither can carry a credential. An option that does nothing is worse
    than an absent one - it reads as a promise.
    """
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--redact", action="store_true", help="Redact credentials before printing.")
    return shared


def build_parser() -> argparse.ArgumentParser:
    """The scan parser, which is also what a bare path is parsed with."""
    parser = argparse.ArgumentParser(
        prog="filegrail scan",
        parents=[_common(), _profile(), _redaction()],
        description="Analyze a file or directory and report where its files came from.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        type=Path,
        help="File or directory to examine (default: current directory).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Open every file: its full detail with every decoded field, and the full pivot lists.",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Print the report as one self-contained HTML page, to redirect to a file.",
    )
    parser.add_argument(
        "--graphml",
        action="store_true",
        help="Export the evidence graph as GraphML. Enables --pivots.",
    )
    parser.add_argument(
        "--graph-csv",
        action="store_true",
        help="Export one evidence-backed graph relationship per CSV row. Enables --pivots.",
    )
    parser.add_argument(
        "--case-jsonld",
        dest="case_jsonld",
        action="store_true",
        help="Export the evidence graph as CASE/UCO JSON-LD, keeping the evidence on each "
        "relationship and recording which tool produced it. Enables --pivots.",
    )
    parser.add_argument(
        "-o",
        "--out",
        dest="out",
        type=Path,
        metavar="FILE",
        help="Write the report to this file instead of standard output.",
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="Stop at the summary, the key findings and a one-line index of the files.",
    )
    parser.add_argument(
        "--timeline",
        action="store_true",
        help="Emit one chronological line per event instead of grouping by file.",
    )
    parser.add_argument(
        "--unknown-only", action="store_true", help="List only files nothing was found for."
    )
    parser.add_argument(
        "--pivots",
        action="store_true",
        help="List the emails, domains, addresses, hashes and coordinates found "
        "in metadata and in the text of supported documents.",
    )
    # The flag was `--identify` up to 0.17.1. A saved command keeps working; it
    # stays out of the help so that the option has one name to learn.
    parser.add_argument("--identify", dest="pivots", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--cluster",
        action="store_true",
        help="Group the files by the authors and cameras more than one of them names.",
    )
    parser.add_argument(
        "--content",
        action="store_true",
        help="Pivots from the text of supported documents only. Turns --pivots on by itself.",
    )
    parser.add_argument(
        "--meta",
        action="store_true",
        help="Pivots from provenance and metadata only, no document text opened. "
        "Turns --pivots on by itself.",
    )
    parser.add_argument(
        "--hash", action="store_true", dest="hash_files", help="Compute SHA-256 for each file."
    )
    parser.add_argument(
        "--type",
        dest="families",
        action="append",
        default=[],
        metavar="NAME",
        help=f"Only these kinds of file: {', '.join(sorted(FAMILIES))}.",
    )
    parser.add_argument(
        "--ext",
        dest="extensions",
        action="append",
        default=[],
        metavar="LIST",
        help="Only these extensions, e.g. --ext jpg,pdf.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap the list of files with no evidence found; 0 for all "
        f"(default: all, or {BRIEF_LIMIT} under --brief).",
    )
    parser.add_argument(
        "--no-recurse", action="store_true", help="Do not descend into subdirectories."
    )
    parser.add_argument(
        "--no-skip",
        action="store_true",
        help="Read the directories a scan normally leaves alone, such as "
        "build output, caches and vendored copies.",
    )
    parser.add_argument(
        "--no-shell-history", action="store_true", help="Skip shell history correlation."
    )
    parser.add_argument(
        "--no-archives",
        action="store_true",
        help="Do not give an archive's origin to the files inside it.",
    )
    parser.add_argument("--version", action="version", version=f"filegrail {__version__}")
    return parser


def _explain_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filegrail explain",
        parents=[_common(), _profile(), _redaction()],
        description="Show the evidence behind what filegrail says about one file.",
    )
    parser.add_argument("path", type=Path, help="The file to explain.")
    return parser


def _compare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filegrail compare",
        parents=[_common(), _profile(), _redaction()],
        description="Compare what two files record about themselves and how each arrived.",
    )
    parser.add_argument("left", type=Path, help="The first file.")
    parser.add_argument("right", type=Path, help="The second file.")
    return parser


def _image_parser(
    *, prog: str = "filegrail image", legacy: bool = False
) -> argparse.ArgumentParser:
    # Imported here so the default in the help text is the one the analyser
    # uses, without the cost of loading the photo readers to build any other
    # parser.
    from .photo import IMAGE_BUDGET, LINKED_IMAGE_BUDGET

    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Legacy alias for filegrail image. Build a Digital Image Examination Report."
            if legacy
            else "Build a Digital Image Examination Report for still images."
        ),
    )
    parser.add_argument("path", type=Path, help="Image or directory to examine.")
    parser.add_argument(
        "-o",
        "--out",
        required=True,
        type=Path,
        metavar="FILE",
        help=(
            "Write the digital image examination report to this HTML file; working images "
            "and analytical outputs go to a directory beside it."
        ),
    )
    parser.add_argument(
        "--redact",
        action="store_true",
        help="Redact text and omit every pixel-bearing preview and diagnostic.",
    )
    parser.add_argument(
        "--case", metavar="REF", help="Case reference to head the report's title block."
    )
    parser.add_argument(
        "--examiner", metavar="NAME", help="Examiner to name in the report's title block."
    )
    parser.add_argument(
        "--no-recurse", action="store_true", help="Do not descend into subdirectories."
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        dest="hash_files",
        help="Accepted for compatibility; SHA-256 is always recorded for every image.",
    )
    parser.add_argument(
        "--embed",
        action="store_true",
        help=(
            "Carry working images and analytical outputs inside the page, subject to the "
            "image budget. Without it they are written to a directory beside the page, "
            "which keeps the HTML small and lets a browser load only what is on screen."
        ),
    )
    parser.add_argument(
        "--image-budget",
        type=_megabytes,
        metavar="MB",
        help=(
            "Megabytes of working images and analytical outputs one report may produce "
            f"(default: {LINKED_IMAGE_BUDGET // (1024 * 1024)}, or "
            f"{IMAGE_BUDGET // (1024 * 1024)} with --embed, where the images have to fit "
            "in a page a browser can open; 0 for no limit). Images past it keep "
            "every fact read from them and lose only their pictures."
        ),
    )
    parser.add_argument("--version", action="version", version=f"filegrail {__version__}")
    return parser


def _photo_parser() -> argparse.ArgumentParser:
    return _image_parser(prog="filegrail photo", legacy=True)


def _megabytes(value: str) -> int:
    """A size in whole megabytes, which cannot be negative."""
    try:
        size = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number of megabytes: {value}") from None
    if size < 0:
        raise argparse.ArgumentTypeError("a budget cannot be negative")
    return size


def _doctor_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="filegrail doctor",
        parents=[_common(), _profile()],
        description="Report which evidence sources this machine has, and how far back they reach.",
    )


def _clean_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filegrail clean",
        parents=[_common()],
        description=(
            "Write copies of files with their metadata removed. The originals are never modified."
        ),
    )
    parser.add_argument("path", nargs="?", default=".", type=Path, help="File or directory.")
    parser.add_argument(
        "--out",
        dest="out",
        type=Path,
        metavar="DIR",
        help="Where to write the cleaned copies. Required unless --check, "
        "and never the source directory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Write nothing. Report what would be removed and what a reader "
        "would still find, and exit 1 if any copy would not come out clean.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace a file already at the destination path.",
    )
    parser.add_argument(
        "--type",
        dest="families",
        action="append",
        default=[],
        metavar="NAME",
        help=f"Only these kinds of file: {', '.join(sorted(FAMILIES))}.",
    )
    parser.add_argument(
        "--ext",
        dest="extensions",
        action="append",
        default=[],
        metavar="LIST",
        help="Only these extensions, e.g. --ext jpg,png.",
    )
    parser.add_argument(
        "--no-recurse", action="store_true", help="Do not descend into subdirectories."
    )
    return parser


def _menu_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filegrail menu",
        parents=[_common()],
        description="Choose what to run from a list instead of remembering flags.",
    )
    parser.add_argument("path", nargs="?", default=".", type=Path, help="Where to start.")
    return parser


def _mcp_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filegrail mcp",
        description=(
            "Serve FileGrail to an AI agent over the Model Context Protocol, on standard "
            "input and output. Read-only."
        ),
    )
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        default=[],
        metavar="DIR",
        help="A directory the agent may examine; repeatable (default: the current directory).",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Also read browser, shell and desktop history. Off by default: an agent "
        "usually sends what it receives to a remote model.",
    )
    parser.add_argument(
        "--home",
        type=Path,
        metavar="DIR",
        help="Read the history from this user profile instead of the current one. "
        "Implies --profile.",
    )
    return parser


PARSERS = {
    "scan": build_parser,
    "image": _image_parser,
    "photo": _photo_parser,
    "explain": _explain_parser,
    "compare": _compare_parser,
    "doctor": _doctor_parser,
    "menu": _menu_parser,
    "clean": _clean_parser,
    "mcp": _mcp_parser,
}


# --- dispatch ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    given = sys.argv[1:] if argv is None else list(argv)

    # A bare run introduces the tool rather than scanning the current directory.
    # Starting an unasked-for scan of wherever the shell happens to be is a
    # surprise, and in a home directory an expensive one.
    if not given:
        from .about import render

        print(render(detect()))
        return 0

    if given[0] in COMMANDS:
        command, rest = given[0], given[1:]
    else:
        command, rest = "scan", given

    if command == "help":
        return _help(rest)
    return {
        "scan": _scan,
        "image": _image,
        "photo": _image,
        "explain": _explain,
        "compare": _compare,
        "doctor": _doctor,
        "menu": _menu,
        "clean": _clean,
        "mcp": _mcp,
    }[command](rest)


def _mcp(rest: list[str]) -> int:
    from .mcp import Server, serve

    args = _mcp_parser().parse_args(rest)
    home = _home(args)
    if isinstance(home, int):
        return home
    roots = args.root or [Path.cwd()]
    for root in roots:
        if not root.is_dir():
            return _missing(root)
    server = Server(roots, profile=args.profile or home is not None, home=home)
    serve(server, sys.stdin.buffer, sys.stdout.buffer)
    return 0


def _help(rest: list[str]) -> int:
    """`filegrail help <command>`, and the landing screen without one."""
    if not rest:
        from .about import render

        print(render(detect()))
        return 0

    name = rest[0]
    if name not in PARSERS:
        print(f"filegrail: no such command: {name}", file=sys.stderr)
        print(f"filegrail: try one of: {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    PARSERS[name]().print_help()
    return 0


#: How many unexplained files `--brief` lists before it says how many are left.
#: `--brief` is the flag for somebody scanning a large tree, and it is the only
#: place the default report shortens anything.
BRIEF_LIMIT = 25


def _limit(args: argparse.Namespace) -> int:
    """How much of the `no evidence found` list to print.

    All of it, unless asked otherwise. A report that hides part of a list it
    already has makes somebody run the tool twice for data it had the first
    time, which is the same objection that put every decoded field on screen
    by default.
    """
    if args.limit is not None:
        return int(args.limit)
    return BRIEF_LIMIT if args.brief else 0


def _missing(path: Path) -> int:
    print(f"filegrail: no such file or directory: {path}", file=sys.stderr)
    return 2


def _home(args: argparse.Namespace) -> Path | None | int:
    """Resolve `--home`, refusing a profile that is not there.

    A mistyped path would otherwise read as an answer: every source comes back
    empty, and a run that found nothing because it looked in the wrong place is
    indistinguishable from one that found nothing because there was nothing to
    find. That confusion is the exact thing `doctor` exists to prevent, so it
    is not one to introduce here.
    """
    if args.home is None:
        return None
    if not args.home.is_dir():
        return _missing(args.home)
    return Path(args.home).resolve()


def _scan(rest: list[str]) -> int:
    args = build_parser().parse_args(rest)
    outputs = [
        args.json,
        args.html,
        args.graphml,
        args.graph_csv,
        args.case_jsonld,
        args.timeline,
    ]
    if sum(outputs) > 1:
        print(
            "filegrail: --json, --html, --graphml, --graph-csv, --case-jsonld and "
            "--timeline are separate outputs; choose one",
            file=sys.stderr,
        )
        return 2
    root = args.path.resolve()
    if not root.exists():
        return _missing(args.path)

    home = _home(args)
    if isinstance(home, int):
        return home

    try:
        suffixes = selection(args.families, args.extensions)
    except UnknownType as unknown:
        print(f"filegrail: {unknown}", file=sys.stderr)
        return 2

    stats: dict[str, int] = {}
    missed = Unsearched()
    coverage = ScanCoverage()
    records = scan(
        root,
        recursive=not args.no_recurse,
        hash_files=args.hash_files,
        use_shell_history=not args.no_shell_history,
        follow_archives=not args.no_archives,
        suffixes=suffixes,
        home=home,
        stats=stats,
        skip_names=not args.no_skip,
        unsearched=missed,
        coverage=coverage,
    )

    if args.unknown_only:
        records = [record for record in records if not record.evidence]
    if args.redact:
        records = [record.redacted() for record in records]

    base = root if root.is_dir() else root.parent
    theme = detect(colour=args.colour)

    # `--content` or `--meta` without `--pivots` would pay for the search and
    # then print a count of what it found. Naming a corpus is asking to be
    # shown it. Both corpora are read unless one was asked for alone.
    listed = (
        args.pivots
        or args.content
        or args.meta
        or args.graphml
        or args.graph_csv
        or args.case_jsonld
    )
    content = listed and (args.content or not args.meta)
    metadata = listed and (args.meta or not args.content)
    output_format = (
        "json"
        if args.json
        else "graphml"
        if args.graphml
        else "graph-csv"
        if args.graph_csv
        else "case-jsonld"
        if args.case_jsonld
        else "html"
        if args.html
        else "timeline"
        if args.timeline
        else "text"
    )
    run: dict[str, object] = {
        "output": output_format,
        "home": str(home or Path.home()),
        "recursive": not args.no_recurse,
        "hash": args.hash_files,
        "shell_history": not args.no_shell_history,
        "archives": not args.no_archives,
        "skip_named_directories": not args.no_skip,
        "pivots": listed,
        "content": content,
        "metadata": metadata,
        "cluster": args.cluster,
        "unknown_only": args.unknown_only,
        "redacted": args.redact,
        "format_registry": registry().describe(),
        "filters": {
            "types": list(args.families),
            "extensions": list(args.extensions),
            "effective_suffixes": sorted(suffixes) if suffixes is not None else None,
        },
    }
    coverage_document = coverage.to_dict()

    written = args.out.resolve() if args.out else None
    if args.json:
        report = render_json(
            records,
            base,
            identify=listed,
            content=content,
            metadata=metadata,
            cluster=args.cluster,
            home=home,
            unsearched=missed,
            run=run,
            coverage=coverage_document,
        )
    elif args.case_jsonld:
        from .caseexport import render_case_jsonld
        from .graph import build_graph

        graph = build_graph(records, extract(records, content=content, metadata=metadata))
        report = render_case_jsonld(
            graph,
            records,
            root=root,
            moment=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            run=run,
        )
    elif args.graphml or args.graph_csv:
        from .graph import build_graph
        from .graph_export import render_graph_csv, render_graph_meta, render_graphml

        graph = build_graph(records, extract(records, content=content, metadata=metadata))
        if args.graphml:
            report = render_graphml(graph, run=run, coverage=coverage_document)
        else:
            report = render_graph_csv(graph)
            # An edge list has no row the scan itself belongs in, so what the
            # scan was goes in a file of its own beside it. Without a file to
            # write beside, `--json` is where to read it.
            if written is not None:
                beside = written.with_name(written.name + ".meta.json")
                try:
                    beside.write_text(render_graph_meta(run, coverage_document), encoding="utf-8")
                except OSError as error:
                    print(f"filegrail: cannot write {beside}: {error}", file=sys.stderr)
                    return 2
    elif args.html:
        case, found = _case(records, base, home, content=content, metadata=metadata, listed=listed)
        report = render_html(
            case,
            verbose=args.verbose,
            identifiers=found,
            content=content,
            metadata=metadata,
            home=home,
            unsearched=missed,
            filtered=describe(args.families, args.extensions),
            redacted=args.redact,
            output=written,
        )
    elif args.timeline:
        report = render_timeline(records, base, theme=theme, home=home)
    elif root.is_dir():
        case, found = _case(records, base, home, content=content, metadata=metadata, listed=listed)
        report = render_case(
            case,
            theme=theme,
            verbose=args.verbose,
            brief=args.brief,
            limit=_limit(args),
            identifiers=found,
            content=content,
            cluster=args.cluster,
            home=home,
            unsearched=missed,
            filtered=describe(args.families, args.extensions),
        )
    else:
        report = render_text(
            records,
            base,
            verbose=args.verbose,
            brief=args.brief,
            limit=_limit(args),
            stats=stats,
            theme=theme,
            filtered=describe(args.families, args.extensions),
            identify=listed,
            content=content,
            metadata=metadata,
            cluster=args.cluster,
            home=home,
            unsearched=missed,
        )
    return _emit(
        report,
        written,
        exact=args.json or args.graphml or args.graph_csv or args.case_jsonld or args.html,
    )


def _image(rest: list[str]) -> int:
    args = _image_parser().parse_args(rest)
    root = args.path.resolve()
    if not root.exists():
        return _missing(args.path)

    from .photo import PHOTO_SUFFIXES, analyse_photos
    from .photohtml import render_photo_html

    if root.is_file() and root.suffix.lower() not in PHOTO_SUFFIXES:
        print(f"filegrail: unsupported image: {args.path}", file=sys.stderr)
        return 2

    output = args.out.resolve()
    images = None if args.embed else output.with_name(f"{output.stem}.files")
    staging = _photo_asset_work_path(images, "tmp") if images is not None else None
    backup = _photo_asset_work_path(images, "bak") if images is not None else None
    excluded = {output}
    excluded.update(path for path in (images, staging, backup) if path is not None)
    records = scan(
        root,
        recursive=not args.no_recurse,
        # Image identity is evidence, independent of how the report transports
        # its working pixels. Every report therefore records the digest.
        hash_files=True,
        follow_archives=False,
        suffixes=PHOTO_SUFFIXES,
        exclude_paths=excluded,
    )
    from .photo import IMAGE_BUDGET, LINKED_IMAGE_BUDGET

    default = IMAGE_BUDGET if args.embed else LINKED_IMAGE_BUDGET
    budget = default if args.image_budget is None else args.image_budget * 1024 * 1024 or None
    collection = analyse_photos(records, root, redact=args.redact, budget=budget)
    if not collection.photos:
        print(f"filegrail: no supported images found in {args.path}", file=sys.stderr)
        return 2

    if images is None:
        report = render_photo_html(
            collection, output=output, case=args.case, examiner=args.examiner
        )
        return _emit_atomic(report, output)

    assert staging is not None and backup is not None
    try:
        _prepare_photo_asset_stage(images, staging, backup)
        report = render_photo_html(
            collection,
            output=output,
            assets=staging,
            asset_url=images.name,
            case=args.case,
            examiner=args.examiner,
        )
    except OSError as error:
        _remove_path(staging)
        print(f"filegrail: cannot write {images}: {error}", file=sys.stderr)
        return 2
    return _emit_photo_bundle(
        report,
        output,
        assets=images,
        staging=staging,
        backup=backup,
        keep_assets=not args.redact,
    )


def _emit(report: str, out: Path | None, *, exact: bool = False) -> int:
    """The report, to the file it was asked for or to standard output.

    `exact` is for output another program reads: JSON, GraphML, the CSV edge
    list and the HTML report. Each of those declares that it is UTF-8, and a
    console that cannot encode a character must not be allowed to change what
    the document says it contains - a `?` in the middle of a file name is a
    changed value, and in XML it is a file no parser will open. Piping a scan
    on a console that is not UTF-8 is ordinary on Windows, and it used to
    produce a corrupt document and an exit code of 0.
    """
    said = report if report.endswith("\n") else report + "\n"
    if out is None:
        if exact:
            sys.stdout.buffer.write(said.encode("utf-8"))
            sys.stdout.buffer.flush()
            return 0
        # A terminal that cannot show a character in a file name still gets
        # the report, with that character replaced, rather than a traceback.
        try:
            sys.stdout.write(said)
        except UnicodeEncodeError:
            encoding = sys.stdout.encoding or "ascii"
            sys.stdout.buffer.write(said.encode(encoding, "replace"))
        sys.stdout.flush()
        return 0
    try:
        out.write_text(said, encoding="utf-8")
    except OSError as error:
        print(f"filegrail: cannot write {out}: {error}", file=sys.stderr)
        return 2
    return 0


def _emit_atomic(report: str, out: Path) -> int:
    """Write a complete report beside its destination, then replace in one step."""
    temporary: Path | None = None
    try:
        temporary = _write_report_temporary(report, out)
        os.replace(temporary, out)
    except OSError as error:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
        print(f"filegrail: cannot write {out}: {error}", file=sys.stderr)
        return 2
    return 0


def _write_report_temporary(report: str, out: Path) -> Path:
    """Write and fsync a report beside its destination without publishing it."""
    said = report if report.endswith("\n") else report + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=out.parent,
        prefix=f".{out.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(said)
        handle.flush()
        os.fsync(handle.fileno())
    return temporary


def _photo_asset_work_path(assets: Path, role: str) -> Path:
    return assets.with_name(f".{assets.name}.{role}")


def _remove_path(path: Path) -> None:
    """Remove one exact report-owned path without following a directory symlink."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _prepare_photo_asset_stage(assets: Path, staging: Path, backup: Path) -> None:
    """Recover an interrupted swap and create an empty sidecar staging directory."""
    _remove_path(staging)
    if backup.exists() or backup.is_symlink():
        if not assets.exists() and not assets.is_symlink():
            os.replace(backup, assets)
        else:
            _remove_path(backup)
    staging.mkdir(parents=True)


def _emit_photo_bundle(
    report: str,
    out: Path,
    *,
    assets: Path,
    staging: Path,
    backup: Path,
    keep_assets: bool,
) -> int:
    """Publish linked HTML and its complete sidecar set as one recoverable swap."""
    temporary: Path | None = None
    old_moved = False
    new_installed = False
    report_installed = False
    try:
        temporary = _write_report_temporary(report, out)
        if assets.exists() or assets.is_symlink():
            os.replace(assets, backup)
            old_moved = True
        if keep_assets:
            os.replace(staging, assets)
            new_installed = True
        else:
            _remove_path(staging)
        os.replace(temporary, out)
        report_installed = True
        temporary = None
        if old_moved:
            _remove_path(backup)
    except OSError as error:
        if not report_installed:
            if new_installed:
                try:
                    _remove_path(assets)
                except OSError:
                    pass
            if old_moved and (backup.exists() or backup.is_symlink()):
                try:
                    os.replace(backup, assets)
                except OSError:
                    pass
        for path in (temporary, staging):
            if path is not None:
                try:
                    _remove_path(path)
                except OSError:
                    pass
        print(f"filegrail: cannot replace report bundle {out}: {error}", file=sys.stderr)
        return 2
    return 0


def _case(
    records: list[FileRecord],
    base: Path,
    home: Path | None,
    *,
    content: bool,
    metadata: bool,
    listed: bool,
) -> tuple[Case, list[Identifier] | None]:
    """The scan read as a case, with its pivots when they were asked for."""
    found = extract(records, content=content, metadata=metadata) if listed else None
    return analyse(records, base, survey=survey(home), identifiers=found), found


def _one(path: Path, home: Path | None = None) -> FileRecord | None:
    """Scan exactly one file, for the commands that take one."""
    resolved = path.resolve()
    if not resolved.is_file():
        return None
    found = scan(resolved, home=home)
    return found[0] if found else None


def _explain(rest: list[str]) -> int:
    args = _explain_parser().parse_args(rest)
    home = _home(args)
    if isinstance(home, int):
        return home

    record = _one(args.path, home)
    if record is None:
        print(f"filegrail: explain takes one file: {args.path}", file=sys.stderr)
        return 2
    if args.redact:
        record = record.redacted()

    if args.json:
        print(render_json_explain(record, home))
        return 0

    print(render_explain(record, theme=detect(colour=args.colour), home=home))
    return 0


def _compare(rest: list[str]) -> int:
    args = _compare_parser().parse_args(rest)
    home = _home(args)
    if isinstance(home, int):
        return home

    # Built one at a time rather than as a pair, so that "this one is missing"
    # is answered before the next line rather than after both are read.
    pair: list[FileRecord] = []
    for path in (args.left, args.right):
        record = _one(path, home)
        if record is None:
            print(f"filegrail: compare takes two files: {path}", file=sys.stderr)
            return 2
        pair.append(record.redacted() if args.redact else record)
    left, right = pair

    if args.json:
        print(render_json_compare(left, right, home))
        return 0

    from .compare import compare

    print(render_compare(left, right, compare(left, right), theme=detect(colour=args.colour)))
    return 0


def _clean(rest: list[str]) -> int:
    """Write cleaned copies, and say what came out and what did not.

    The exit code answers one question: would every copy come out clean? A file
    nothing here can strip does not make a dirty copy and does not count; a
    copy the readers can still see a block in does, in both modes, because a
    check that disagreed with the run it is checking would be worth nothing.
    """
    args = _clean_parser().parse_args(rest)
    from .clean import clean_file
    from .report import render_clean, render_json_clean
    from .scan import iter_files

    if not args.path.exists():
        print(f"filegrail: {args.path} does not exist", file=sys.stderr)
        return 2
    if args.out is None and not args.check:
        print("filegrail: clean needs --out, or --check to write nothing", file=sys.stderr)
        return 2

    source = args.path.resolve()
    destination = args.out.resolve() if args.out is not None else None
    # Writing into the tree being read would make the run depend on the order
    # it happened to walk in, and a second run would clean its own output.
    if destination is not None and (
        destination == source or (source.is_dir() and destination.is_relative_to(source))
    ):
        print("filegrail: --out must be outside the directory being cleaned", file=sys.stderr)
        return 2

    try:
        suffixes = selection(args.families, args.extensions)
    except UnknownType as unknown:
        print(f"filegrail: {unknown}", file=sys.stderr)
        return 2

    if destination is not None and not args.check:
        # Not under --check: a mode that writes nothing does not get to leave a
        # directory behind as the one trace that it ran.
        destination.mkdir(parents=True, exist_ok=True)
    # The copies mirror the tree, so `below` is the directory the walk started
    # from. A single file has no tree above it and keeps its own name.
    below = source if source.is_dir() else source.parent
    results = [
        clean_file(path, destination, below=below, overwrite=args.overwrite, write=not args.check)
        for path in iter_files(source, recursive=not args.no_recurse, suffixes=suffixes)
    ]
    unclean = 1 if any(item.remaining for item in results) else 0

    if args.json:
        print(render_json_clean(results, source, destination, check=args.check))
        return unclean
    print(
        render_clean(
            results, source, destination, theme=detect(colour=args.colour), check=args.check
        )
    )
    return unclean


def _doctor(rest: list[str]) -> int:
    args = _doctor_parser().parse_args(rest)
    from .doctor import survey

    home = _home(args)
    if isinstance(home, int):
        return home

    found = survey(home)
    if args.json:
        print(render_json_doctor(found, home))
        return 0
    print(render_doctor(found, detect(colour=args.colour), home=home))
    return 0


def _menu(rest: list[str]) -> int:
    """Hand over to the interactive front end, if there is a terminal for it."""
    args = _menu_parser().parse_args(rest)
    from . import menu

    if not menu.available():
        print(
            "filegrail: menu needs a terminal; it cannot be piped or redirected.",
            file=sys.stderr,
        )
        return 2
    if not args.path.exists():
        return _missing(args.path)
    return menu.run(args.path, execute=main)


if __name__ == "__main__":
    raise SystemExit(main())
