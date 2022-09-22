#!/bin/bash
#SBATCH --job-name=onav_ilrl
#SBATCH --gres gpu:1
#SBATCH --nodes 1
#SBATCH --cpus-per-task 6
#SBATCH --ntasks-per-node 1
#SBATCH --signal=USR1@300
#SBATCH --partition=long
#SBATCH --constraint=a40
#SBATCH --exclude=robby
#SBATCH --output=slurm_logs/ddp-il-rl-%j.out
#SBATCH --error=slurm_logs/ddp-il-rl-%j.err
#SBATCH --requeue

source /srv/flash1/rramrakhya6/miniconda3/etc/profile.d/conda.sh
conda deactivate
conda activate il-rl

export GLOG_minloglevel=2
export MAGNUM_LOG=quiet

MASTER_ADDR=$(srun --ntasks=1 hostname 2>&1 | tail -n1)
export MASTER_ADDR

config=$1

TENSORBOARD_DIR="tb/objectnav_il_rl_ft/ddppo_hm3d_pt_77k/rgb_ovrl_with_augs/sparse_reward/hm3d_v2.0/seed_2/"
CHECKPOINT_DIR="data/new_checkpoints/objectnav_il_rl_ft/ddppo_hm3d_pt_77k/rgb_ovrl_with_augs/sparse_reward/hm3d_v2.0/seed_2/"
DATA_PATH="data/datasets/objectnav/objectnav_hm3d/objectnav_hm3d_v0.2/"
PRETRAINED_WEIGHTS="data/new_checkpoints/objectnav_il/objectnav_hm3d/objectnav_hm3d_77k/rgb_ovrl/seed_1/ObjectNav_omnidata_DINO_02_77k_with_augs.pth"
set -x

echo "In ObjectNav IL+RL DDP"
srun python -u -m habitat_baselines.run \
--exp-config $config \
--run-type train \
SENSORS "['RGB_SENSOR', 'DEPTH_SENSOR', 'SEMANTIC_SENSOR']" \
TENSORBOARD_DIR $TENSORBOARD_DIR \
CHECKPOINT_FOLDER $CHECKPOINT_DIR \
NUM_UPDATES 40000 \
NUM_PROCESSES 16 \
RL.DDPPO.pretrained_weights $PRETRAINED_WEIGHTS \
RL.DDPPO.distrib_backend "NCCL" \
RL.Finetune.start_actor_finetuning_at 325 \
RL.Finetune.actor_lr_warmup_update 750 \
RL.Finetune.start_critic_warmup_at 250 \
RL.Finetune.critic_lr_decay_update 500 \
TASK_CONFIG.DATASET.SPLIT "train" \
TASK_CONFIG.DATASET.DATA_PATH "$DATA_PATH/{split}/{split}.json.gz" \
TASK_CONFIG.TASK.SUCCESS.SUCCESS_DISTANCE 0.1 \
MODEL.hm3d_goal False \
MODEL.embed_sge False \
MODEL.USE_SEMANTICS False \
MODEL.USE_PRED_SEMANTICS False \
MODEL.SEMANTIC_ENCODER.is_hm3d False \
MODEL.SEMANTIC_ENCODER.is_thda False \
MODEL.SEMANTIC_PREDICTOR.name "rednet" \
MODEL.RGB_ENCODER.cnn_type "VisualEncoder" \
MODEL.RGB_ENCODER.backbone "resnet50" \
MODEL.RGB_ENCODER.freeze_backbone False \
MODEL.RGB_ENCODER.randomize_augmentations_over_envs False \
MODEL.RGB_ENCODER.pretrained_encoder "data/visual_encoders/omnidata_DINO_02.pth"