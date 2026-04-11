#!/usr/bin/env python3
"""Build a non-destructive partial TomatoWUR dataset bundle for Pointcept.

The Pointcept ``TomatoWURCSV`` dataset loader only reads ``file_name`` and
``sem_seg_file_name`` from the split JSON files. This script scans partial
point-cloud and label CSV trees, validates that they match, splits plants into
train/val/test groups, and writes a new ``ann_versions/<name>/`` bundle that
contains:

* ``annotations/<plant>`` and ``point_clouds/<plant>`` as symlinks or copies
* ``json/train.json``, ``json/val.json``, ``json/test.json``, ``json/all.json``
* split metadata and plant lists for reproducibility

By default the script refuses to write into an existing output directory.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


LABEL_SUFFIX = "_labels.csv"
PARTIAL_TOKEN = "_partial_"


@dataclass(frozen=True)
class SamplePair:
    plant: str
    sample_name: str
    point_cloud_src: Path
    annotation_src: Path
    point_rows: int | None = None
    annotation_rows: int | None = None

    def to_json_entry(self) -> dict[str, str]:
        return {
            "file_name": f"../point_clouds/{self.plant}/{self.sample_name}.csv",
            "sem_seg_file_name": (
                f"../annotations/{self.plant}/{self.sample_name}{LABEL_SUFFIX}"
            ),
        }


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "Create a new ann_versions dataset bundle from partial TomatoWUR CSV "
            "sources without overwriting existing data."
        )
    )
    parser.add_argument(
        "--annotations-root",
        type=Path,
        default=Path("~/annotations_partial").expanduser(),
        help="Root directory containing per-plant partial label CSV folders.",
    )
    parser.add_argument(
        "--point-clouds-root",
        type=Path,
        default=Path("~/point_clouds_partial").expanduser(),
        help="Root directory containing per-plant partial point-cloud CSV folders.",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=script_dir,
        help=(
            "TomatoWUR data root. Used when --output-root is omitted so output is "
            "written to <dataset-root>/ann_versions/<version-name>/."
        ),
    )
    parser.add_argument(
        "--version-name",
        type=str,
        default=None,
        help="Name for the new ann_versions bundle, for example partial-v1.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Explicit output directory. If omitted, --version-name is required.",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.70,
        help="Plant-level train split ratio.",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.15,
        help="Plant-level validation split ratio.",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.15,
        help="Plant-level test split ratio.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used for plant-level shuffling before splitting.",
    )
    parser.add_argument(
        "--materialize-mode",
        choices=("symlink", "copy"),
        default="symlink",
        help="How to expose source plant folders inside the new bundle.",
    )
    parser.add_argument(
        "--skip-row-count-check",
        action="store_true",
        help="Skip validating that every point-cloud CSV and label CSV have equal rows.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the planned split without writing output files.",
    )
    args = parser.parse_args()

    args.annotations_root = args.annotations_root.expanduser().resolve()
    args.point_clouds_root = args.point_clouds_root.expanduser().resolve()
    args.dataset_root = args.dataset_root.expanduser().resolve()

    if args.output_root is None:
        if not args.version_name:
            parser.error("Either --output-root or --version-name must be provided.")
        args.output_root = (
            args.dataset_root / "ann_versions" / args.version_name
        ).resolve()
    else:
        args.output_root = args.output_root.expanduser().resolve()

    validate_ratios(args.train_ratio, args.val_ratio, args.test_ratio, parser)
    return args


def validate_ratios(
    train_ratio: float, val_ratio: float, test_ratio: float, parser: argparse.ArgumentParser
) -> None:
    ratios = (train_ratio, val_ratio, test_ratio)
    if any(r < 0 for r in ratios):
        parser.error("Split ratios must be non-negative.")
    total = sum(ratios)
    if not math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        parser.error(
            f"Split ratios must sum to 1.0, got {total:.6f} "
            f"from train={train_ratio}, val={val_ratio}, test={test_ratio}."
        )


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def sorted_subdirs(root: Path) -> list[Path]:
    if not root.is_dir():
        fail(f"Missing directory: {root}")
    return sorted(path for path in root.iterdir() if path.is_dir())


def count_csv_rows(csv_path: Path) -> int:
    with csv_path.open("rb") as handle:
        line_count = -1
        for line_count, _ in enumerate(handle):
            pass
    return max(line_count, 0)


def discover_pairs(
    annotations_root: Path,
    point_clouds_root: Path,
    check_row_counts: bool,
) -> dict[str, list[SamplePair]]:
    annotation_dirs = sorted_subdirs(annotations_root)
    point_cloud_dirs = sorted_subdirs(point_clouds_root)

    annotation_plants = {path.name for path in annotation_dirs}
    point_cloud_plants = {path.name for path in point_cloud_dirs}
    if annotation_plants != point_cloud_plants:
        missing_annotations = sorted(point_cloud_plants - annotation_plants)
        missing_point_clouds = sorted(annotation_plants - point_cloud_plants)
        details: list[str] = []
        if missing_annotations:
            details.append(
                "plants missing in annotations-root: " + ", ".join(missing_annotations)
            )
        if missing_point_clouds:
            details.append(
                "plants missing in point-clouds-root: " + ", ".join(missing_point_clouds)
            )
        fail("; ".join(details))

    pairs_by_plant: dict[str, list[SamplePair]] = {}
    for plant in sorted(annotation_plants):
        ann_dir = annotations_root / plant
        pc_dir = point_clouds_root / plant

        ann_files = sorted(ann_dir.glob(f"*{LABEL_SUFFIX}"))
        pc_files = sorted(pc_dir.glob("*.csv"))
        ann_map = {
            path.name[: -len(LABEL_SUFFIX)]: path
            for path in ann_files
            if PARTIAL_TOKEN in path.name
        }
        pc_map = {
            path.stem: path
            for path in pc_files
            if PARTIAL_TOKEN in path.stem
        }

        if not ann_map:
            fail(f"No partial annotation CSVs found in {ann_dir}")
        if not pc_map:
            fail(f"No partial point-cloud CSVs found in {pc_dir}")

        if ann_map.keys() != pc_map.keys():
            missing_ann = sorted(pc_map.keys() - ann_map.keys())
            missing_pc = sorted(ann_map.keys() - pc_map.keys())
            details = [f"plant {plant} has mismatched partial files"]
            if missing_ann:
                details.append(
                    "missing annotation files for: " + ", ".join(missing_ann[:10])
                )
            if missing_pc:
                details.append(
                    "missing point-cloud files for: " + ", ".join(missing_pc[:10])
                )
            fail("; ".join(details))

        plant_pairs: list[SamplePair] = []
        for sample_name in sorted(ann_map):
            point_rows = None
            annotation_rows = None
            if check_row_counts:
                point_rows = count_csv_rows(pc_map[sample_name])
                annotation_rows = count_csv_rows(ann_map[sample_name])
                if point_rows != annotation_rows:
                    fail(
                        "Row-count mismatch for "
                        f"{plant}/{sample_name}: point cloud has {point_rows}, "
                        f"annotation has {annotation_rows}"
                    )
            plant_pairs.append(
                SamplePair(
                    plant=plant,
                    sample_name=sample_name,
                    point_cloud_src=pc_map[sample_name],
                    annotation_src=ann_map[sample_name],
                    point_rows=point_rows,
                    annotation_rows=annotation_rows,
                )
            )
        pairs_by_plant[plant] = plant_pairs
    return pairs_by_plant


def allocate_counts(total: int, ratios: dict[str, float]) -> dict[str, int]:
    raw = {name: total * ratio for name, ratio in ratios.items()}
    counts = {name: math.floor(value) for name, value in raw.items()}
    remainder = total - sum(counts.values())
    order = sorted(
        ratios,
        key=lambda name: (raw[name] - counts[name], ratios[name], name),
        reverse=True,
    )
    for name in order[:remainder]:
        counts[name] += 1
    return counts


def split_plants(
    plants: Iterable[str], train_ratio: float, val_ratio: float, test_ratio: float, seed: int
) -> dict[str, list[str]]:
    plant_list = sorted(plants)
    rng = random.Random(seed)
    rng.shuffle(plant_list)

    counts = allocate_counts(
        len(plant_list),
        {"train": train_ratio, "val": val_ratio, "test": test_ratio},
    )

    train_end = counts["train"]
    val_end = train_end + counts["val"]
    split_map = {
        "train": sorted(plant_list[:train_end]),
        "val": sorted(plant_list[train_end:val_end]),
        "test": sorted(plant_list[val_end:]),
    }

    for split_name, split_plants_list in split_map.items():
        if split_plants_list and len(split_plants_list) != counts[split_name]:
            fail(
                f"Internal split error for {split_name}: expected "
                f"{counts[split_name]} plants, got {len(split_plants_list)}"
            )
    return split_map


def build_entries(
    pairs_by_plant: dict[str, list[SamplePair]], plant_names: Iterable[str]
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for plant in sorted(plant_names):
        for pair in pairs_by_plant[plant]:
            entries.append(pair.to_json_entry())
    return entries


def ensure_new_output_root(output_root: Path) -> None:
    if output_root.exists():
        fail(f"Output directory already exists: {output_root}")
    output_root.mkdir(parents=True, exist_ok=False)


def materialize_sources(
    output_root: Path,
    annotations_root: Path,
    point_clouds_root: Path,
    plant_names: Iterable[str],
    mode: str,
) -> None:
    annotations_out = output_root / "annotations"
    point_clouds_out = output_root / "point_clouds"
    annotations_out.mkdir()
    point_clouds_out.mkdir()

    for plant in sorted(plant_names):
        ann_src = annotations_root / plant
        pc_src = point_clouds_root / plant
        ann_dst = annotations_out / plant
        pc_dst = point_clouds_out / plant
        if mode == "symlink":
            ann_dst.symlink_to(ann_src, target_is_directory=True)
            pc_dst.symlink_to(pc_src, target_is_directory=True)
        elif mode == "copy":
            shutil.copytree(ann_src, ann_dst)
            shutil.copytree(pc_src, pc_dst)
        else:
            fail(f"Unsupported materialize mode: {mode}")


def write_json(path: Path, entries: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(entries, indent=4) + "\n")


def write_text_lines(path: Path, lines: Iterable[str]) -> None:
    path.write_text("".join(f"{line}\n" for line in lines))


def write_metadata(
    output_root: Path,
    args: argparse.Namespace,
    split_map: dict[str, list[str]],
    pairs_by_plant: dict[str, list[SamplePair]],
) -> None:
    metadata = {
        "annotations_root": str(args.annotations_root),
        "point_clouds_root": str(args.point_clouds_root),
        "output_root": str(output_root),
        "materialize_mode": args.materialize_mode,
        "seed": args.seed,
        "ratios": {
            "train": args.train_ratio,
            "val": args.val_ratio,
            "test": args.test_ratio,
        },
        "plants_per_split": {name: plants for name, plants in split_map.items()},
        "sample_counts": {
            "all": sum(len(samples) for samples in pairs_by_plant.values()),
            "train": sum(len(pairs_by_plant[plant]) for plant in split_map["train"]),
            "val": sum(len(pairs_by_plant[plant]) for plant in split_map["val"]),
            "test": sum(len(pairs_by_plant[plant]) for plant in split_map["test"]),
        },
        "per_plant_sample_counts": {
            plant: len(samples) for plant, samples in sorted(pairs_by_plant.items())
        },
    }
    (output_root / "metadata.json").write_text(json.dumps(metadata, indent=4) + "\n")


def print_summary(
    output_root: Path,
    split_map: dict[str, list[str]],
    pairs_by_plant: dict[str, list[SamplePair]],
    dry_run: bool,
) -> None:
    print(f"Output root: {output_root}")
    print(f"Plants discovered: {len(pairs_by_plant)}")
    print(f"Samples discovered: {sum(len(samples) for samples in pairs_by_plant.values())}")
    for split_name in ("train", "val", "test"):
        plant_count = len(split_map[split_name])
        sample_count = sum(len(pairs_by_plant[plant]) for plant in split_map[split_name])
        print(f"{split_name}: {plant_count} plants, {sample_count} samples")
    if dry_run:
        print("Dry run only. No files were written.")


def main() -> int:
    args = parse_args()
    pairs_by_plant = discover_pairs(
        annotations_root=args.annotations_root,
        point_clouds_root=args.point_clouds_root,
        check_row_counts=not args.skip_row_count_check,
    )

    split_map = split_plants(
        plants=pairs_by_plant.keys(),
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        seed=args.seed,
    )

    if args.dry_run:
        print_summary(args.output_root, split_map, pairs_by_plant, dry_run=True)
        return 0

    ensure_new_output_root(args.output_root)
    materialize_sources(
        output_root=args.output_root,
        annotations_root=args.annotations_root,
        point_clouds_root=args.point_clouds_root,
        plant_names=pairs_by_plant.keys(),
        mode=args.materialize_mode,
    )

    json_dir = args.output_root / "json"
    json_dir.mkdir()
    write_json(json_dir / "all.json", build_entries(pairs_by_plant, pairs_by_plant.keys()))
    write_json(json_dir / "train.json", build_entries(pairs_by_plant, split_map["train"]))
    write_json(json_dir / "val.json", build_entries(pairs_by_plant, split_map["val"]))
    write_json(json_dir / "test.json", build_entries(pairs_by_plant, split_map["test"]))
    write_text_lines(json_dir / "train_plants.txt", split_map["train"])
    write_text_lines(json_dir / "val_plants.txt", split_map["val"])
    write_text_lines(json_dir / "test_plants.txt", split_map["test"])
    write_metadata(args.output_root, args, split_map, pairs_by_plant)
    print_summary(args.output_root, split_map, pairs_by_plant, dry_run=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
