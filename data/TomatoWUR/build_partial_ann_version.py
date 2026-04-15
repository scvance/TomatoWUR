#!/usr/bin/env python3
"""Build a non-destructive TomatoWUR CSV bundle for Pointcept.

The Pointcept ``TomatoWURCSV`` dataset loader only reads ``file_name`` and
``sem_seg_file_name`` from the split JSON files. This script scans point-cloud
and label CSV trees, validates that they match, splits plants or sequences into
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


@dataclass(frozen=True)
class PairingMismatch:
    annotation_only: tuple[str, ...] = ()
    point_cloud_only: tuple[str, ...] = ()

    @property
    def has_mismatch(self) -> bool:
        return bool(self.annotation_only or self.point_cloud_only)


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "Create a new ann_versions dataset bundle from TomatoWUR CSV "
            "sources without overwriting existing data."
        )
    )
    parser.add_argument(
        "--annotations-root",
        type=Path,
        default=Path("~/annotations_partial").expanduser(),
        help="Root directory containing per-plant label CSV folders.",
    )
    parser.add_argument(
        "--point-clouds-root",
        type=Path,
        default=Path("~/point_clouds_partial").expanduser(),
        help="Root directory containing per-plant point-cloud CSV folders.",
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
        "--sample-name-contains",
        type=str,
        default=None,
        help=(
            "Optional substring filter applied to matched sample stems. Use "
            "this to restrict discovery to names such as '_partial_' or 'traj'."
        ),
    )
    parser.add_argument(
        "--pairing-mode",
        choices=("strict", "intersection"),
        default="strict",
        help=(
            "How to handle per-plant stem mismatches between annotations and "
            "point clouds. 'strict' fails, 'intersection' keeps only common stems."
        ),
    )
    parser.add_argument(
        "--split-unit",
        choices=("plant", "sequence"),
        default="plant",
        help=(
            "Unit used for train/val/test assignment. 'sequence' keeps all "
            "frames sharing the same prefix before --sequence-delimiter together."
        ),
    )
    parser.add_argument(
        "--sequence-delimiter",
        type=str,
        default="_sensor_",
        help=(
            "Delimiter used to derive a sequence key from a sample stem when "
            "--split-unit=sequence, for example '_sensor_' or '_partial_'."
        ),
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.70,
        help="Train split ratio applied at the selected split unit.",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.15,
        help="Validation split ratio applied at the selected split unit.",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.15,
        help="Test split ratio applied at the selected split unit.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed used for split-unit shuffling before splitting.",
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
    if args.split_unit == "sequence" and not args.sequence_delimiter:
        parser.error("--sequence-delimiter must be non-empty when --split-unit=sequence.")
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
    sample_name_contains: str | None,
    pairing_mode: str,
) -> tuple[dict[str, list[SamplePair]], dict[str, PairingMismatch]]:
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
    pairing_mismatches: dict[str, PairingMismatch] = {}
    for plant in sorted(annotation_plants):
        ann_dir = annotations_root / plant
        pc_dir = point_clouds_root / plant

        ann_files = sorted(ann_dir.glob(f"*{LABEL_SUFFIX}"))
        pc_files = sorted(pc_dir.glob("*.csv"))
        ann_map: dict[str, Path] = {}
        for path in ann_files:
            sample_name = path.name[: -len(LABEL_SUFFIX)]
            if sample_name_contains and sample_name_contains not in sample_name:
                continue
            ann_map[sample_name] = path
        pc_map: dict[str, Path] = {}
        for path in pc_files:
            sample_name = path.stem
            if sample_name_contains and sample_name_contains not in sample_name:
                continue
            pc_map[sample_name] = path

        if not ann_map:
            fail(f"No annotation CSVs matched in {ann_dir}")
        if not pc_map:
            fail(f"No point-cloud CSVs matched in {pc_dir}")

        ann_names = set(ann_map)
        pc_names = set(pc_map)
        mismatch = PairingMismatch(
            annotation_only=tuple(sorted(ann_names - pc_names)),
            point_cloud_only=tuple(sorted(pc_names - ann_names)),
        )
        if mismatch.has_mismatch:
            if pairing_mode == "strict":
                details = [f"plant {plant} has mismatched CSV stems"]
                if mismatch.annotation_only:
                    details.append(
                        "annotation-only stems: "
                        + ", ".join(mismatch.annotation_only[:10])
                    )
                if mismatch.point_cloud_only:
                    details.append(
                        "point-cloud-only stems: "
                        + ", ".join(mismatch.point_cloud_only[:10])
                    )
                fail("; ".join(details))
            pairing_mismatches[plant] = mismatch
            sample_names = sorted(ann_names & pc_names)
            if not sample_names:
                fail(
                    f"plant {plant} has no shared CSV stems after applying "
                    f"pairing-mode={pairing_mode}"
                )
        else:
            sample_names = sorted(ann_map)

        plant_pairs: list[SamplePair] = []
        for sample_name in sample_names:
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
    return pairs_by_plant, pairing_mismatches


def sequence_name_from_sample(sample_name: str, sequence_delimiter: str) -> str:
    if sequence_delimiter not in sample_name:
        fail(
            f"Sample {sample_name!r} does not contain the sequence delimiter "
            f"{sequence_delimiter!r} required for --split-unit=sequence."
        )
    return sample_name.rsplit(sequence_delimiter, 1)[0]


def build_split_units(
    pairs_by_plant: dict[str, list[SamplePair]],
    split_unit: str,
    sequence_delimiter: str,
) -> dict[str, list[SamplePair]]:
    if split_unit == "plant":
        return {plant: list(pairs) for plant, pairs in sorted(pairs_by_plant.items())}
    if split_unit == "sequence":
        pairs_by_unit: dict[str, list[SamplePair]] = {}
        for plant in sorted(pairs_by_plant):
            for pair in pairs_by_plant[plant]:
                unit_name = sequence_name_from_sample(
                    pair.sample_name, sequence_delimiter
                )
                pairs_by_unit.setdefault(unit_name, []).append(pair)
        return {
            unit_name: sorted(pairs, key=lambda pair: pair.sample_name)
            for unit_name, pairs in sorted(pairs_by_unit.items())
        }
    fail(f"Unsupported split unit: {split_unit}")


def frame_index_from_sample(sample_name: str, sequence_delimiter: str) -> int:
    if sequence_delimiter not in sample_name:
        fail(
            f"Sample {sample_name!r} does not contain the sequence delimiter "
            f"{sequence_delimiter!r} required for trajectory manifests."
        )
    frame_suffix = sample_name.rsplit(sequence_delimiter, 1)[1]
    if not frame_suffix.isdigit():
        fail(
            f"Sample {sample_name!r} has non-numeric frame suffix {frame_suffix!r} "
            f"after delimiter {sequence_delimiter!r}."
        )
    return int(frame_suffix)


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


def split_names(
    names: Iterable[str], train_ratio: float, val_ratio: float, test_ratio: float, seed: int
) -> dict[str, list[str]]:
    name_list = sorted(names)
    rng = random.Random(seed)
    rng.shuffle(name_list)

    counts = allocate_counts(
        len(name_list),
        {"train": train_ratio, "val": val_ratio, "test": test_ratio},
    )

    train_end = counts["train"]
    val_end = train_end + counts["val"]
    split_map = {
        "train": sorted(name_list[:train_end]),
        "val": sorted(name_list[train_end:val_end]),
        "test": sorted(name_list[val_end:]),
    }

    for split_name, split_plants_list in split_map.items():
        if split_plants_list and len(split_plants_list) != counts[split_name]:
            fail(
                f"Internal split error for {split_name}: expected "
                f"{counts[split_name]} units, got {len(split_plants_list)}"
            )
    return split_map


def build_entries(
    pairs_by_unit: dict[str, list[SamplePair]], unit_names: Iterable[str]
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for unit_name in sorted(unit_names):
        for pair in pairs_by_unit[unit_name]:
            entries.append(pair.to_json_entry())
    return entries


def plants_for_units(
    pairs_by_unit: dict[str, list[SamplePair]], unit_names: Iterable[str]
) -> list[str]:
    return sorted(
        {
            pair.plant
            for unit_name in unit_names
            for pair in pairs_by_unit[unit_name]
        }
    )


def count_samples_for_units(
    pairs_by_unit: dict[str, list[SamplePair]], unit_names: Iterable[str]
) -> int:
    return sum(len(pairs_by_unit[unit_name]) for unit_name in unit_names)


def selected_pairs(
    pairs_by_unit: dict[str, list[SamplePair]], unit_names: Iterable[str]
) -> list[SamplePair]:
    return [
        pair
        for unit_name in sorted(unit_names)
        for pair in pairs_by_unit[unit_name]
    ]


def trajectory_manifests_supported(
    pairs_by_unit: dict[str, list[SamplePair]],
    unit_names: Iterable[str],
    sequence_delimiter: str,
) -> bool:
    pairs = selected_pairs(pairs_by_unit, unit_names)
    if not pairs:
        return False
    with_delimiter = [sequence_delimiter in pair.sample_name for pair in pairs]
    if all(with_delimiter):
        return True
    if any(with_delimiter):
        missing = sorted(
            pair.sample_name for pair in pairs if sequence_delimiter not in pair.sample_name
        )
        fail(
            "Cannot mix trajectory and non-trajectory sample names when generating "
            f"trajectory manifests. Missing delimiter {sequence_delimiter!r} in: "
            + ", ".join(missing[:10])
        )
    return False


def build_trajectory_entries(
    pairs_by_unit: dict[str, list[SamplePair]],
    unit_names: Iterable[str],
    sequence_delimiter: str,
) -> list[dict[str, object]]:
    pairs = selected_pairs(pairs_by_unit, unit_names)
    grouped: dict[str, list[SamplePair]] = {}
    for pair in pairs:
        sequence_id = sequence_name_from_sample(pair.sample_name, sequence_delimiter)
        grouped.setdefault(sequence_id, []).append(pair)

    trajectory_entries: list[dict[str, object]] = []
    for sequence_id in sorted(grouped):
        sequence_pairs = sorted(
            grouped[sequence_id],
            key=lambda pair: (frame_index_from_sample(pair.sample_name, sequence_delimiter), pair.sample_name),
        )
        frame_indices = [
            frame_index_from_sample(pair.sample_name, sequence_delimiter)
            for pair in sequence_pairs
        ]
        if len(frame_indices) != len(set(frame_indices)):
            fail(
                f"Sequence {sequence_id} has duplicate frame indices derived from "
                f"delimiter {sequence_delimiter!r}."
            )
        frames = []
        for pair in sequence_pairs:
            entry = pair.to_json_entry()
            frames.append(
                {
                    "frame_name": pair.sample_name,
                    "frame_index": frame_index_from_sample(
                        pair.sample_name, sequence_delimiter
                    ),
                    "file_name": entry["file_name"],
                    "sem_seg_file_name": entry["sem_seg_file_name"],
                }
            )
        trajectory_entries.append(
            {
                "plant": sequence_pairs[0].plant,
                "sequence_id": sequence_id,
                "num_frames": len(frames),
                "frames": frames,
            }
        )
    return trajectory_entries


def write_trajectory_jsons(
    json_dir: Path,
    pairs_by_unit: dict[str, list[SamplePair]],
    split_map: dict[str, list[str]],
    sequence_delimiter: str,
) -> tuple[dict[str, str], dict[str, int], dict[str, int]]:
    if not trajectory_manifests_supported(
        pairs_by_unit, pairs_by_unit.keys(), sequence_delimiter
    ):
        return {}, {}, {}

    manifest_files: dict[str, str] = {}
    trajectory_counts_per_split: dict[str, int] = {}
    per_trajectory_frame_counts: dict[str, int] = {}
    for split_name, unit_names in {
        "all": list(pairs_by_unit.keys()),
        "train": split_map["train"],
        "val": split_map["val"],
        "test": split_map["test"],
    }.items():
        trajectory_entries = build_trajectory_entries(
            pairs_by_unit, unit_names, sequence_delimiter
        )
        file_name = f"{split_name}_trajectories.json"
        write_json(json_dir / file_name, trajectory_entries)
        manifest_files[split_name] = file_name
        trajectory_counts_per_split[split_name] = len(trajectory_entries)
        for entry in trajectory_entries:
            per_trajectory_frame_counts[str(entry["sequence_id"])] = int(
                entry["num_frames"]
            )
    return manifest_files, trajectory_counts_per_split, per_trajectory_frame_counts


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
    pairs_by_unit: dict[str, list[SamplePair]],
    pairing_mismatches: dict[str, PairingMismatch],
    trajectory_manifest_files: dict[str, str],
    trajectory_counts_per_split: dict[str, int],
    per_trajectory_frame_counts: dict[str, int],
) -> None:
    metadata = {
        "annotations_root": str(args.annotations_root),
        "point_clouds_root": str(args.point_clouds_root),
        "output_root": str(output_root),
        "materialize_mode": args.materialize_mode,
        "sample_name_contains": args.sample_name_contains,
        "pairing_mode": args.pairing_mode,
        "split_unit": args.split_unit,
        "sequence_delimiter": args.sequence_delimiter,
        "trajectory_sequence_delimiter": args.sequence_delimiter,
        "seed": args.seed,
        "ratios": {
            "train": args.train_ratio,
            "val": args.val_ratio,
            "test": args.test_ratio,
        },
        "units_per_split": {name: units for name, units in split_map.items()},
        "plants_per_split": {
            name: plants_for_units(pairs_by_unit, units)
            for name, units in split_map.items()
        },
        "unit_counts": {
            "all": len(pairs_by_unit),
            "train": len(split_map["train"]),
            "val": len(split_map["val"]),
            "test": len(split_map["test"]),
        },
        "sample_counts": {
            "all": count_samples_for_units(pairs_by_unit, pairs_by_unit.keys()),
            "train": count_samples_for_units(pairs_by_unit, split_map["train"]),
            "val": count_samples_for_units(pairs_by_unit, split_map["val"]),
            "test": count_samples_for_units(pairs_by_unit, split_map["test"]),
        },
        "per_plant_sample_counts": {
            plant: len(samples) for plant, samples in sorted(pairs_by_plant.items())
        },
        "per_unit_sample_counts": {
            unit_name: len(samples)
            for unit_name, samples in sorted(pairs_by_unit.items())
        },
        "trajectory_manifest_files": trajectory_manifest_files,
        "per_split_trajectory_counts": trajectory_counts_per_split,
        "per_trajectory_frame_counts": per_trajectory_frame_counts,
        "pairing_mismatches": {
            plant: {
                "annotation_only_count": len(mismatch.annotation_only),
                "point_cloud_only_count": len(mismatch.point_cloud_only),
                "annotation_only_preview": list(mismatch.annotation_only[:10]),
                "point_cloud_only_preview": list(mismatch.point_cloud_only[:10]),
            }
            for plant, mismatch in sorted(pairing_mismatches.items())
        },
    }
    (output_root / "metadata.json").write_text(json.dumps(metadata, indent=4) + "\n")


def print_summary(
    output_root: Path,
    split_map: dict[str, list[str]],
    pairs_by_plant: dict[str, list[SamplePair]],
    pairs_by_unit: dict[str, list[SamplePair]],
    pairing_mismatches: dict[str, PairingMismatch],
    trajectory_counts_per_split: dict[str, int],
    split_unit: str,
    pairing_mode: str,
    dry_run: bool,
) -> None:
    print(f"Output root: {output_root}")
    print(f"Split unit: {split_unit}")
    print(f"Plants discovered: {len(pairs_by_plant)}")
    print(f"Split units discovered: {len(pairs_by_unit)}")
    print(
        f"Samples discovered: {count_samples_for_units(pairs_by_unit, pairs_by_unit.keys())}"
    )
    if trajectory_counts_per_split:
        print(
            "Trajectory manifests: "
            f"{trajectory_counts_per_split.get('all', 0)} sequences total"
        )
    if pairing_mismatches:
        annotation_only_total = sum(
            len(mismatch.annotation_only) for mismatch in pairing_mismatches.values()
        )
        point_cloud_only_total = sum(
            len(mismatch.point_cloud_only) for mismatch in pairing_mismatches.values()
        )
        print(
            "Pairing mismatches: "
            f"{len(pairing_mismatches)} plants, dropped "
            f"{annotation_only_total} annotation-only and "
            f"{point_cloud_only_total} point-cloud-only samples using "
            f"pairing-mode={pairing_mode}"
        )
    for split_name in ("train", "val", "test"):
        unit_count = len(split_map[split_name])
        plant_count = len(plants_for_units(pairs_by_unit, split_map[split_name]))
        sample_count = count_samples_for_units(pairs_by_unit, split_map[split_name])
        if split_unit == "plant":
            print(f"{split_name}: {unit_count} plants, {sample_count} samples")
        else:
            print(
                f"{split_name}: {unit_count} sequences, {plant_count} plants, "
                f"{sample_count} samples"
            )
    if dry_run:
        print("Dry run only. No files were written.")


def main() -> int:
    args = parse_args()
    pairs_by_plant, pairing_mismatches = discover_pairs(
        annotations_root=args.annotations_root,
        point_clouds_root=args.point_clouds_root,
        check_row_counts=not args.skip_row_count_check,
        sample_name_contains=args.sample_name_contains,
        pairing_mode=args.pairing_mode,
    )
    pairs_by_unit = build_split_units(
        pairs_by_plant=pairs_by_plant,
        split_unit=args.split_unit,
        sequence_delimiter=args.sequence_delimiter,
    )

    split_map = split_names(
        names=pairs_by_unit.keys(),
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        seed=args.seed,
    )

    if args.dry_run:
        print_summary(
            args.output_root,
            split_map,
            pairs_by_plant,
            pairs_by_unit,
            pairing_mismatches,
            {},
            args.split_unit,
            args.pairing_mode,
            dry_run=True,
        )
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
    write_json(json_dir / "all.json", build_entries(pairs_by_unit, pairs_by_unit.keys()))
    write_json(json_dir / "train.json", build_entries(pairs_by_unit, split_map["train"]))
    write_json(json_dir / "val.json", build_entries(pairs_by_unit, split_map["val"]))
    write_json(json_dir / "test.json", build_entries(pairs_by_unit, split_map["test"]))
    write_text_lines(json_dir / "train_units.txt", split_map["train"])
    write_text_lines(json_dir / "val_units.txt", split_map["val"])
    write_text_lines(json_dir / "test_units.txt", split_map["test"])
    write_text_lines(
        json_dir / "train_plants.txt",
        plants_for_units(pairs_by_unit, split_map["train"]),
    )
    write_text_lines(
        json_dir / "val_plants.txt",
        plants_for_units(pairs_by_unit, split_map["val"]),
    )
    write_text_lines(
        json_dir / "test_plants.txt",
        plants_for_units(pairs_by_unit, split_map["test"]),
    )
    (
        trajectory_manifest_files,
        trajectory_counts_per_split,
        per_trajectory_frame_counts,
    ) = write_trajectory_jsons(
        json_dir=json_dir,
        pairs_by_unit=pairs_by_unit,
        split_map=split_map,
        sequence_delimiter=args.sequence_delimiter,
    )
    write_metadata(
        args.output_root,
        args,
        split_map,
        pairs_by_plant,
        pairs_by_unit,
        pairing_mismatches,
        trajectory_manifest_files,
        trajectory_counts_per_split,
        per_trajectory_frame_counts,
    )
    print_summary(
        args.output_root,
        split_map,
        pairs_by_plant,
        pairs_by_unit,
        pairing_mismatches,
        trajectory_counts_per_split,
        args.split_unit,
        args.pairing_mode,
        dry_run=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
