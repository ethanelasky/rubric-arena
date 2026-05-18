#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


RUBRIC = {
    "rubric_version": "1.0",
    "id": "usemo_2020_p1",
    "description": "Classify the positive integers representable by the lcm expression.",
    "points": 7,
    "combinator": "one_of",
    "guidelines": [
        "The source rubric has three official partial-credit routes: 2-adic valuations, factoring, and general p-adic lcm divisibility.",
        "0 points for only stating that the even positive integers are the answer.",
        "0 points for only stating WLOG gcd(x,y,z)=1.",
        "A complete solution earns 7 points regardless of route.",
    ],
    "children": [
        {
            "id": "usemo_2020_p1.complete",
            "description": "Complete solution proving both construction and impossibility.",
            "points": 7,
            "selection_signal": "the paper gives a complete proof of both directions",
            "satisfied_when": "all",
            "children": [
                {"id": "usemo_2020_p1.complete.even_construction", "description": "Proves every even positive integer is attainable."},
                {"id": "usemo_2020_p1.complete.odd_impossible", "description": "Proves no odd positive integer is attainable."},
            ],
        },
        {
            "id": "usemo_2020_p1.partial_v2",
            "description": "Partial credit on the 2-adic valuation route.",
            "points": 2,
            "selection_signal": "the paper has even construction and at least one substantial valuation case but is incomplete",
            "combinator": "sum",
            "children": [
                {"id": "usemo_2020_p1.partial_v2.even_construction", "description": "Gives a valid construction for every even positive integer.", "points": 1},
                {"id": "usemo_2020_p1.partial_v2.substantial_case", "description": "Uses 2-adic or prime-adic valuations and resolves at least one substantial odd-impossibility case.", "points": 1},
            ],
        },
        {
            "id": "usemo_2020_p1.partial_factoring",
            "description": "Partial credit on the pairwise-gcd factoring route.",
            "points": 2,
            "selection_signal": "the paper has even construction and pairwise-gcd factoring but is incomplete",
            "combinator": "sum",
            "children": [
                {"id": "usemo_2020_p1.partial_factoring.even_construction", "description": "Gives a valid construction for every even positive integer.", "points": 1},
                {"id": "usemo_2020_p1.partial_factoring.pairwise_gcd_factoring", "description": "Uses substantive pairwise-gcd factorization beyond merely saying WLOG gcd(x,y,z)=1.", "points": 1},
            ],
        },
        {
            "id": "usemo_2020_p1.partial_general_vp",
            "description": "Partial credit on the general prime-adic lcm-divisibility route.",
            "points": 2,
            "selection_signal": "the paper has even construction and the key lcm divisibility claim but is incomplete",
            "combinator": "sum",
            "children": [
                {"id": "usemo_2020_p1.partial_general_vp.even_construction", "description": "Gives a valid construction for every even positive integer.", "points": 1},
                {"id": "usemo_2020_p1.partial_general_vp.lcm_divisibility", "description": "States or derives lcm(x,z) divides lcm(x,y)=lcm(y,z), or an equivalent primewise maximum condition.", "points": 1},
            ],
        },
        {"id": "usemo_2020_p1.no_progress", "description": "No score-bearing progress under the source rubric.", "points": 0, "selection_signal": "none of the above applies"},
    ],
}

EXPECTED_PHRASES = [
    "§4.1 Rubric for USEMO1",
    "0 points for stating that even integers are the only solutions",
    "1 point for the construction for even integers",
    "resolving at least one substantial case",
    "factoring pairwise greatest common divisors",
    "lcm(x, z) | lcm(x, y) = lcm(y, z)",
    "7 points for a complete solution",
]


def extract_text(pdf_path: Path) -> str:
    with tempfile.NamedTemporaryFile(suffix='.txt') as out:
        subprocess.run(['pdftotext', str(pdf_path), out.name], check=True)
        return Path(out.name).read_text(errors='replace')


def main() -> None:
    parser = argparse.ArgumentParser(description='Create the USEMO 2020 P1 rubric fixture from the report PDF.')
    parser.add_argument('pdf', type=Path, help='Path to report-usemo-2020.pdf')
    parser.add_argument('--output', type=Path, default=Path('data/usemo_2020/rubrics/usemo_2020_p1.rubric.json'))
    args = parser.parse_args()

    text = extract_text(args.pdf)
    missing = [phrase for phrase in EXPECTED_PHRASES if phrase not in text]
    if missing:
        raise SystemExit('PDF text did not contain expected rubric phrases: ' + repr(missing))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(RUBRIC, indent=2, ensure_ascii=False) + '\n')
    print(f'wrote {args.output}')
    print('validated expected USEMO1 rubric phrases in PDF text')


if __name__ == '__main__':
    main()
