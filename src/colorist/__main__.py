# SPDX-License-Identifier: MIT
"""Command line entry point for local QC and consistency normalization."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def _check_python_floor(version_info=None) -> None:
    """Stop before third-party imports on unsupported Python versions."""
    active = sys.version_info if version_info is None else version_info
    if tuple(active[:2]) < (3, 11):
        version = ".".join(str(part) for part in active[:3])
        raise SystemExit(
            f"colorist requires Python 3.11 or newer; running Python {version}"
        )


_check_python_floor()

from colorist.tools import PreflightError, preflight
from colorist.cuts import confirm_cut_proposal, write_cut_proposal
from colorist.render import ConvertParams
from colorist.workflow import run_consistency, run_qc


_EXIT_CODES = {"PASS": 0, "FAIL": 2, "INDETERMINATE": 3, "ERROR": 4}
_ENCODINGS = (
    "slog3_sgamut3cine",
    "logc3ei800_awg3",
    "logc4_awg4",
    "vlog_vgamut",
    "clog3_cgamut",
)


def _add_input_declaration_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--input-range", choices=("full", "limited"))
    command.add_argument("--input-matrix", help="declared FFmpeg input matrix name")
    command.add_argument("--input-transfer", default="bt709")
    command.add_argument("--input-primaries", default="bt709")
    command.add_argument(
        "--confirm-metadata-override",
        action="store_true",
        help="use the declaration after an input metadata conflict is shown",
    )


def _input_params(args: argparse.Namespace) -> ConvertParams | None:
    if args.input_range is None and args.input_matrix is None:
        return None
    if args.input_range is None or args.input_matrix is None:
        raise ValueError("--input-range and --input-matrix must be supplied together")
    return ConvertParams(
        range=args.input_range,
        matrix=args.input_matrix,
        transfer=args.input_transfer,
        primaries=args.input_primaries,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m colorist")
    commands = parser.add_subparsers(dest="command", required=True)

    qc = commands.add_parser(
        "qc", help="verify an existing delivery against an expected profile"
    )
    qc.add_argument("file", type=Path)
    qc.add_argument(
        "--preset",
        required=True,
        help="explicit gate preset; shipped presets are provisional",
    )
    qc.add_argument("--deliver", required=True, help="expected delivery profile")
    qc.add_argument(
        "--source-reference",
        type=Path,
        help=(
            "distinct pre-grade source used to measure grade-introduced clipping; "
            "sampled spatial rank correspondence is checked before comparison, and "
            "missing or failed evidence is INDETERMINATE"
        ),
    )
    qc.add_argument(
        "--encoding",
        choices=_ENCODINGS,
        help="source-reference log encoding; omit for display-referred Rec.709",
    )
    qc.add_argument(
        "--out",
        required=True,
        type=Path,
        help="explicit run directory for reports, masks, and optional review PNGs",
    )
    qc.add_argument(
        "--mask-review",
        action="store_true",
        help="write opt-in source-mask contact sheets under the run directory",
    )
    _add_input_declaration_arguments(qc)

    consistency = commands.add_parser(
        "consistency", help="normalize white balance and exposure across a cut list"
    )
    consistency.add_argument("file", type=Path)
    consistency.add_argument("--cuts", required=True, type=Path)
    consistency.add_argument(
        "--preset",
        required=True,
        help="explicit gate preset; shipped presets are provisional",
    )
    consistency.add_argument(
        "--deliver",
        required=True,
        help="delivery profile to encode; consistency always renders one",
    )
    consistency.add_argument(
        "--encoding",
        choices=_ENCODINGS,
        help="source log encoding; omit for display-referred Rec.709 passthrough",
    )
    consistency.add_argument("--workdir", type=Path)
    consistency.add_argument(
        "--out",
        required=True,
        type=Path,
        help="explicit run directory for reports, masks, and optional review PNGs",
    )
    consistency.add_argument(
        "--mask-review",
        action="store_true",
        help="write opt-in source-mask contact sheets under the run directory",
    )
    consistency.add_argument(
        "--approve-short-shots",
        action="store_true",
        help="allow automatic correction below 3 frames; gates remain indeterminate",
    )
    _add_input_declaration_arguments(consistency)

    propose = commands.add_parser(
        "propose-cuts", help="write a scored, non-authoritative complete cut proposal"
    )
    propose.add_argument("file", type=Path)
    propose.add_argument("--out", required=True, type=Path)
    propose.add_argument("--threshold", type=float, default=10.0)
    propose.add_argument("--min-shot", type=int, default=12)

    confirm = commands.add_parser(
        "confirm-cuts", help="confirm a reviewed proposal as an authoritative cut list"
    )
    confirm.add_argument("proposal", type=Path)
    confirm.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    # Every command below shells out to ffmpeg. Resolving the binaries proves
    # only that some file exists at that path, so check the version and the
    # capabilities before any of them touches a frame. --help never reaches
    # here, so the install-verification command stays lightweight.
    try:
        preflight()
    except (PreflightError, FileNotFoundError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return _EXIT_CODES["ERROR"]
    if args.command == "propose-cuts":
        try:
            proposal = write_cut_proposal(
                args.file,
                args.out,
                threshold=args.threshold,
                min_shot=args.min_shot,
            )
        except Exception as error:
            print(f"{type(error).__name__}: {error}", file=sys.stderr)
            return _EXIT_CODES["ERROR"]
        print(f"PROPOSED {proposal}")
        print("Review the scored boundaries, then run confirm-cuts; this file is not applied.")
        return 0
    if args.command == "confirm-cuts":
        try:
            cutlist = confirm_cut_proposal(args.proposal, args.out)
        except Exception as error:
            print(f"{type(error).__name__}: {error}", file=sys.stderr)
            return _EXIT_CODES["ERROR"]
        print(f"CONFIRMED {cutlist}")
        return 0
    try:
        input_params = _input_params(args)
    except ValueError as error:
        parser.error(str(error))
    if args.command == "qc":
        if args.source_reference is None and (
            args.encoding is not None
            or input_params is not None
            or args.confirm_metadata_override
        ):
            parser.error(
                "--encoding and input declarations require --source-reference for qc"
            )
    # Any exception that escapes a workflow (for example an --out that names an
    # existing regular file, which fails before or inside the workflow's own
    # error handler) must still print a clean ERROR and exit 4, never a raw
    # traceback with exit 1, to honor the documented exit-code contract.
    try:
        if args.command == "qc":
            result = run_qc(
                args.file,
                args.preset,
                args.deliver,
                report_dir=args.out,
                source_reference=args.source_reference,
                curve_gamut=args.encoding,
                input_params=input_params,
                confirm_metadata_override=args.confirm_metadata_override,
                mask_review=args.mask_review,
            )
        else:
            result = run_consistency(
                args.file,
                args.cuts,
                args.preset,
                args.deliver,
                args.workdir or args.out,
                curve_gamut=args.encoding,
                input_params=input_params,
                confirm_metadata_override=args.confirm_metadata_override,
                report_dir=args.out,
                mask_review=args.mask_review,
                approve_short_shots=args.approve_short_shots,
            )
    except Exception as error:  # noqa: BLE001 - the CLI's last-resort ERROR gate
        print("ERROR")
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return _EXIT_CODES["ERROR"]
    print(result.state)
    if result.error:
        print(result.error, file=sys.stderr)
    return _EXIT_CODES[result.state]


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess
    raise SystemExit(main())
