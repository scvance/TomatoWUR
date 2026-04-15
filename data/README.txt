This README belongs to the comprehensive TomatoWUR dataset.

Title:
TomatoWUR: an annotated dataset of 3D tomato plants to quantitatively evaluate
segmentation, skeletonisation, and plant trait extraction algorithms for 3D
plant phenotyping

Authors:
Bart M. van Marrewijk, Bolai Xin, Katarina Smolenova, Tim van Daalen,
Gerrit Polder, Gert Kootstra

Corresponding author:
Bart M. van Marrewijk
bart.vanmarrewijk@wur.nl
Greenhouse Horticulture Business Unit, Wageningen University & Research
P.O.Box 644
6700 AP Wageningen
The Netherlands

###############################################################################
Background
###############################################################################

The dataset contains 44 annotated point clouds (semantic and instances),
skeletons describing plant architecture, and manual measurements of:

- stem thickness [m]
- internode length [m]
- leaf angle [degrees]
- phyllotactic angle clockwise [degrees]

For more information see:

1. Data in Brief: publication in progress
2. 3D plant segmentation: comparing a 2D-to-3D segmentation method with
   state-of-the-art 3D segmentation algorithms

###############################################################################
Base dataset layout
###############################################################################

The base dataset is organized into four main directories:

TomatoWUR/
|- ann_versions/
|  |- 0-paper-2Dto3D/
|  |  |- annotations/
|  |  |  |- Harvest_01_PotNr_101/
|  |  |  |  |- Harvest_01_PotNr_101.csv
|  |  |  |  |- Harvest_01_PotNr_101_labels.csv
|  |  |  |  |- Harvest_01_PotNr_101_skeleton.csv
|  |  |  |  `- Harvest_01_PotNr_101_cam_*.png
|  |  `- json/
|  |     |- all.json
|  |     |- manual_measurements_only.json
|  |     |- train.json
|  |     |- val.json
|  |     `- test.json
|- camera_poses/
|  |- 0.json
|  |- ...
|  `- 14.json
|- images/
|  |- Harvest_01_PotNr_101/
|  |- ...
|  `- Harvest_03_PotNr_74/
`- point_clouds/
   |- Harvest_01_PotNr_101.csv
   |- ...
   `- Harvest_03_PotNr_74.csv

###############################################################################
How this repo expects the data
###############################################################################

In this repository, the default configs expect the base dataset to live at:

~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/

More generally, the important paths are:

- root project config:
  ~/2D-to-3D_segmentation/config.yaml
- TomatoWUR package config:
  ~/2D-to-3D_segmentation/TomatoWUR/config.yaml

Those configs resolve the dataset as:

- project_dir: TomatoWUR/data
- project_code: TomatoWUR

So the repo expects:

~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/

If you are running TomatoWUR scripts directly from inside the TomatoWUR folder,
the package-local config uses:

- project_dir: data/
- project_code: TomatoWUR

which resolves to the same dataset inside this repo:

~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/

###############################################################################
File formats
###############################################################################

- Raw images: PNG
- Annotated RGB images: PNG
- Camera calibration: JSON
- Point clouds: CSV with x, y, z, blue, green, red, nx, ny, nz
- Annotated point clouds: CSV
- Annotated skeletons including manual measurements: CSV

###############################################################################
Partial point-cloud training data
###############################################################################

For Pointcept training in this repo, we also used a separate partial-point-cloud
bundle under:

~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/ann_versions/partial-v1/

This bundle is not a destructive rewrite of the base dataset. It is generated
from two external source trees:

- ~/annotations_partial
- ~/point_clouds_partial

The expected source layout is:

~/annotations_partial/
|- Harvest_01_PotNr_101/
|  |- Harvest_01_PotNr_101_partial_0000_labels.csv
|  |- Harvest_01_PotNr_101_partial_0001_labels.csv
|  `- ...
|- Harvest_01_PotNr_145/
`- ...

~/point_clouds_partial/
|- Harvest_01_PotNr_101/
|  |- Harvest_01_PotNr_101_partial_0000.csv
|  |- Harvest_01_PotNr_101_partial_0001.csv
|  `- ...
|- Harvest_01_PotNr_145/
`- ...

Important assumptions:

- plant folder names must match between the two roots
- partial file stems must match between the two roots
- every point-cloud CSV must have the same number of rows as its label CSV

###############################################################################
How partial-v1 was generated
###############################################################################

The script used to generate the partial annotation bundle is:

~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/build_partial_ann_version.py

That script:

- scans the partial point-cloud and label trees
- validates plant names and partial filenames
- optionally validates row counts
- splits at the plant level, not the partial-file level
- writes a new ann_versions/<name>/ bundle with train/val/test JSON files
- stores split metadata and plant lists for reproducibility

To reproduce the exact split used here, run:

python ~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/build_partial_ann_version.py \
  --annotations-root ~/annotations_partial \
  --point-clouds-root ~/point_clouds_partial \
  --version-name partial-v1 \
  --train-ratio 0.8 \
  --val-ratio 0.1 \
  --test-ratio 0.1 \
  --seed 123 \
  --materialize-mode copy

Notes:

- The script refuses to overwrite an existing output directory.
- If ann_versions/partial-v1 already exists, remove or rename it first, or use
  a new version name such as partial-v2.
- The exact split metadata for the current bundle is stored in:
  ~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/ann_versions/partial-v1/metadata.json

The generated bundle contains:

- annotations/<plant>/...
- point_clouds/<plant>/...
- json/train.json
- json/val.json
- json/test.json
- json/all.json
- json/train_plants.txt
- json/val_plants.txt
- json/test_plants.txt
- metadata.json

The current partial-v1 metadata records:

- annotations_root: ~/annotations_partial
- point_clouds_root: ~/point_clouds_partial
- output_root:
  ~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/ann_versions/partial-v1
- materialize_mode: copy
- seed: 123
- ratios: train=0.8, val=0.1, test=0.1
- sample counts: all=1408, train=1120, val=160, test=128

If you need the exact plant membership, use:

- ann_versions/partial-v1/json/train_plants.txt
- ann_versions/partial-v1/json/val_plants.txt
- ann_versions/partial-v1/json/test_plants.txt

###############################################################################
How to use partial-v1 in this repo
###############################################################################

For TomatoWUR scripts that use config.yaml, set:

- data.annot_version: partial-v1

in either:

- ~/2D-to-3D_segmentation/config.yaml
- ~/2D-to-3D_segmentation/TomatoWUR/config.yaml

For Pointcept training and inference in this repo, point the config at:

~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/ann_versions/partial-v1/json/

The PTv3 config used in this repo is:

~/2D-to-3D_segmentation/example_configs/semseg-pt-v3m1-0-base_TOMATOWUR.py

and should reference:

- train.json
- val.json
- test.json

inside the partial-v1 json folder.

###############################################################################
Trajectory-aware bundles for sequential training
###############################################################################

The same builder can also generate trajectory-aware bundles for sequential
experiments where one plant contains multiple ordered partial point clouds.

Expected source layout:

~/TomatoWUR_trajectory/
|- annotations_trajectory_sensor/
|  |- Harvest_01_PotNr_55/
|  |  |- Harvest_01_PotNr_55_traj000_sensor_0000_labels.csv
|  |  |- Harvest_01_PotNr_55_traj000_sensor_0001_labels.csv
|  |  `- ...
|  `- ...
`- point_clouds_trajectory_sensor/
   |- Harvest_01_PotNr_55/
   |  |- Harvest_01_PotNr_55_traj000_sensor_0000.csv
   |  |- Harvest_01_PotNr_55_traj000_sensor_0001.csv
   |  `- ...
   `- ...

Trajectory naming assumptions:

- plant folder names must match between the two roots
- frame stems must match between the two roots
- the frame index is parsed from the suffix after `_sensor_`
- the sequence id is the prefix before `_sensor_`
- example:
  `Harvest_01_PotNr_55_traj000_sensor_0007`
  becomes sequence id:
  `Harvest_01_PotNr_55_traj000`

Recommended split mode for future LSTM experiments:

- `--split-unit plant`

This keeps every trajectory from the same plant in the same split. The script
also supports:

- `--split-unit sequence`

That keeps each trajectory intact, but different trajectories from the same
plant may appear in different splits.

Recommended workflow in Docker:

1. Validate the dataset without writing output:

docker compose -f ~/2D-to-3D_segmentation/docker-compose.yaml run --rm \
  -v /path/to/TomatoWUR_trajectory:/data/TomatoWUR_trajectory \
  interactive python3 /workspace/plant3d/TomatoWUR/data/TomatoWUR/build_partial_ann_version.py \
  --annotations-root /data/TomatoWUR_trajectory/annotations_trajectory_sensor \
  --point-clouds-root /data/TomatoWUR_trajectory/point_clouds_trajectory_sensor \
  --version-name trajectory-sensor-plant \
  --pairing-mode strict \
  --split-unit plant \
  --sequence-delimiter _sensor_ \
  --train-ratio 0.8 \
  --val-ratio 0.1 \
  --test-ratio 0.1 \
  --seed 123 \
  --materialize-mode copy \
  --dry-run

2. If the dry run is clean, remove `--dry-run` and rerun the same command.

Equivalent local command if you prefer the repo virtualenv:

source ~/.virtualenvs/tomato/bin/activate
python ~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/build_partial_ann_version.py \
  --annotations-root ~/TomatoWUR_trajectory/annotations_trajectory_sensor \
  --point-clouds-root ~/TomatoWUR_trajectory/point_clouds_trajectory_sensor \
  --version-name trajectory-sensor-plant \
  --pairing-mode strict \
  --split-unit plant \
  --sequence-delimiter _sensor_ \
  --train-ratio 0.8 \
  --val-ratio 0.1 \
  --test-ratio 0.1 \
  --seed 123 \
  --materialize-mode copy

source ~/.virtualenvs/tomato/bin/activate
python ~/2D-to-3D_segmentation/TomatoWUR/data/TomatoWUR/build_partial_ann_version.py \
  --annotations-root ~/TomatoWUR_trajectory/annotations_trajectory_world \
  --point-clouds-root ~/TomatoWUR_trajectory/point_clouds_trajectory_world \
  --version-name trajectory-world-plant \
  --pairing-mode strict \
  --split-unit plant \
  --sequence-delimiter _ \
  --train-ratio 0.8 \
  --val-ratio 0.1 \
  --test-ratio 0.1 \
  --seed 123 \
  --materialize-mode copy

The generated bundle contains the existing frame-wise manifests:

- json/all.json
- json/train.json
- json/val.json
- json/test.json

and these trajectory-specific files:

- json/all_trajectories.json
- json/train_trajectories.json
- json/val_trajectories.json
- json/test_trajectories.json
- json/train_units.txt
- json/val_units.txt
- json/test_units.txt
- json/train_plants.txt
- json/val_plants.txt
- json/test_plants.txt
- metadata.json

The trajectory manifests preserve frame order inside each trajectory. In the
current repo, the trajectory training path uses one trajectory per batch and
marks the first and last frame of each sequence so a recurrent module can reset
state cleanly when it is added later.

The trajectory config in this repo is:

~/2D-to-3D_segmentation/example_configs/semseg-pt-v3m1-0-base_TOMATOWUR_TRAJECTORY.py

and it expects:

- train_trajectories.json
- val_trajectories.json
- test_trajectories.json

###############################################################################
Licence
###############################################################################

Dataset is licensed under CC BY-SA 4.0.
