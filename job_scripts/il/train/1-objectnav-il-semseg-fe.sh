#!/bin/bash
#SBATCH --job-name=onav_il
#SBATCH --gres gpu:8
#SBATCH --nodes 2
#SBATCH --cpus-per-task 6
#SBATCH --ntasks-per-node 8
#SBATCH --signal=USR1@1000
#SBATCH --partition=long
#SBATCH --constraint=a40
#SBATCH --exclude=robby
#SBATCH --output=slurm_logs/ddpil-%j.out
#SBATCH --error=slurm_logs/ddpil-%j.err
#SBATCH --requeue

source /srv/flash1/rramrakhya6/miniconda3/etc/profile.d/conda.sh
conda deactivate
conda activate il-rl

export GLOG_minloglevel=2
export MAGNUM_LOG=quiet

MASTER_ADDR=$(srun --ntasks=1 hostname 2>&1 | tail -n1)
export MASTER_ADDR

config=$1

DATA_PATH="data/datasets/objectnav/objectnav_hm3d/objectnav_hm3d_fe_20k_balanced/"
TENSORBOARD_DIR="tb/objectnav_il/objectnav_hm3d/objectnav_hm3d_fe_20k_balanced/sem_seg_pred/seed_3_40k/"
CHECKPOINT_DIR="data/new_checkpoints/objectnav_il/objectnav_hm3d/objectnav_hm3d_fe_20k_balanced/sem_seg_pred/seed_3_40k/"
INFLECTION_COEF=2.106159015778148
set -x

echo "In ObjectNav IL DDP"
srun python -u -m habitat_baselines.run \
--exp-config $config \
--run-type train \
TENSORBOARD_DIR $TENSORBOARD_DIR \
CHECKPOINT_FOLDER $CHECKPOINT_DIR \
CHECKPOINT_INTERVAL 500 \
NUM_UPDATES 40000 \
NUM_PROCESSES 8 \
IL.BehaviorCloning.num_steps 64 \
TASK_CONFIG.TASK.INFLECTION_WEIGHT_SENSOR.INFLECTION_COEF $INFLECTION_COEF \
TASK_CONFIG.DATASET.SPLIT "train" \
TASK_CONFIG.DATASET.DATA_PATH "$DATA_PATH/{split}/{split}.json.gz" \
MODEL.hm3d_goal True \
MODEL.USE_SEMANTICS True \
MODEL.USE_PRED_SEMANTICS True \
MODEL.SEMANTIC_ENCODER.is_hm3d False \
MODEL.SEMANTIC_ENCODER.is_thda True \
MODEL.SEMANTIC_PREDICTOR.name "rednet" \
# MODEL.SEMANTIC_PREDICTOR.SHAPECONV.only_rednet_cats True \
# MODEL.SEMANTIC_PREDICTOR.SHAPECONV.config "configs/semantic_predictor/shapeconv/hm3d_deeplabv3plus_resnet101_baseline.py" \
# MODEL.SEMANTIC_PREDICTOR.SHAPECONV.pretrained_weights "data/new_checkpoints/mmdet/semantic_predictor/shapeconv/shapeconv_23cat_best_class_acc_with_bg.pth" \