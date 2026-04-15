<!-- # Robot harvester: works perfect
![robot](assets/example.jpg "robot")
> **Robot harvester: works perfect**\
> Me Myself, Some Supervisor, Some Other Person
> Paper: https://todo.nl -->

## About
Official implementation of [TomatoWUR](https://data.4tu.nl/datasets/e2c59841-4653-45de-a75e-4994b2766a2f/1)
 dataset: 

**An annotated dataset of tomato plants to quantitatively evaluate segmentation, skeletonisation, and plant trait extraction algorithms for 3D plant phenotyping**


The dataset is related to the paper:
[3D plant segmentation: Comparing a 2D-to-3D segmentation method with state-of-the-art 3D segmentation algorithms](https://www.sciencedirect.com/science/article/pii/S1537511025000832)

## Installation
This software is tested on Python 3.11. To install the dependencies, run:
```
pip install -r requirements.txt
```

## Usage
Make sure to extract and download the dataset, this will be done automatically if path can not be found:
```
python3 wurTomato.py --visualise 0
```
For more examples have a look at the example_notebook.ipynb

Settings are described in config file

## Training Bundles In 2D-to-3D_segmentation
This dataset repo is also used as a submodule inside the parent
`2D-to-3D_segmentation` project for Pointcept experiments.

That project generates non-destructive training bundles under:

`data/TomatoWUR/ann_versions/<version-name>/`

For the original frame-wise partial data, the bundle contains:

- `json/train.json`
- `json/val.json`
- `json/test.json`

For the newer trajectory experiments, the same builder also writes:

- `json/train_trajectories.json`
- `json/val_trajectories.json`
- `json/test_trajectories.json`

Those trajectory manifests preserve frame order inside each trajectory so the
loader can expose sequence boundaries to a future recurrent model.

Example command from the parent repo with Docker Compose:

```bash
docker compose -f ../docker-compose.yaml run --rm \
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
```

Use `--split-unit plant` for sequential experiments so all trajectories from
the same plant stay in the same split. Detailed path conventions and usage are
documented in `data/README.txt` in this repo and in the parent project
`readme.md`.

<center>
    <p align="center">
        <img src="Resources/3D_tomato_plant.png" height="200" />
        <img src="Resources/3D_tomato_plant_semantic.png" height="200" />
        <img src="Resources/3D_tomato_plant_skeleton.png" height="200" />
    </p>
</center>

<center>
    <p align="center">
        <img src="Resources/pointcloud.gif" height="200" />
    </p>
</center>

## Citation
```
@article{VANMARREWIJK2025111852,
title = {TomatoWUR: An annotated dataset of tomato plants to quantitatively evaluate segmentation, skeletonisation, and plant-trait extraction algorithms for 3D plant phenotyping},
journal = {Data in Brief},
volume = {61},
pages = {111852},
year = {2025},
issn = {2352-3409},
doi = {https://doi.org/10.1016/j.dib.2025.111852},
url = {https://www.sciencedirect.com/science/article/pii/S2352340925005773},
author = {Bart M. {van Marrewijk} and Tim {van Daalen} and Katarína Smoleňová and Bolai Xin and Gerrit Polder and Gert Kootstra},
}
```

## Related research
[2Dto3D segmentation paper](https://github.com/WUR-ABE/2D-to-3D_segmentation)

## Funding
This research is part of AgrifoodTEF: Test and Experiment Facilities for the Agri-Food Domain (101100622)
