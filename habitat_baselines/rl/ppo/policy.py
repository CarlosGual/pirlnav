#!/usr/bin/env python3

# Copyright (c) Facebook, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
import abc

import torch
from gym import spaces
from torch import nn as nn

from habitat import logger
from habitat.config import Config
from habitat.tasks.nav.nav import (
    ImageGoalSensor,
    IntegratedPointGoalGPSAndCompassSensor,
    PointGoalSensor,
)
from habitat_baselines.common.baseline_registry import baseline_registry
from habitat_baselines.rl.models.rnn_state_encoder import RNNStateEncoder
from habitat_baselines.rl.models.simple_cnn import SimpleCNN
from habitat_baselines.utils.common import CategoricalNet


class Policy(nn.Module, metaclass=abc.ABCMeta):
    def __init__(
        self,
        net,
        dim_actions,
        no_critic=False,
        mlp_critic=False,
        critic_hidden_dim=512,
        detach_critic_input=False,
    ):
        super().__init__()
        self.net = net
        self.dim_actions = dim_actions
        self.no_critic = no_critic

        self.action_distribution = CategoricalNet(
            self.net.output_size, self.dim_actions
        )
        logger.info("MLP critic: {} - {}".format(mlp_critic, detach_critic_input))
        if self.no_critic:
            pass
        else:
            if not mlp_critic:
                self.critic = CriticHead(self.net.output_size)
            else:
                self.critic = MLPCriticHead(
                    self.net.output_size,
                    critic_hidden_dim,
                    detach=detach_critic_input
                )

    def forward(self, *x):
        features, rnn_hidden_states = self.net(
            *x
        )
        distribution = self.action_distribution(features)
        distribution_entropy = distribution.entropy().mean()

        return distribution.logits, rnn_hidden_states, distribution_entropy

    def act(
        self,
        observations,
        rnn_hidden_states,
        prev_actions,
        masks,
        deterministic=False,
        return_distribution=False,
    ):
        features, rnn_hidden_states = self.net(
            observations, rnn_hidden_states, prev_actions, masks
        )
        distribution = self.action_distribution(features)

        if deterministic:
            action = distribution.mode()
        else:
            action = distribution.sample()
        action_log_probs = distribution.log_probs(action)
        distribution_entropy = distribution.entropy().mean()

        if self.no_critic:
            return action, rnn_hidden_states, distribution_entropy

        value = self.critic(features)

        if return_distribution:
            return value, action, action_log_probs, rnn_hidden_states, distribution_entropy, distribution

        return value, action, action_log_probs, rnn_hidden_states, distribution_entropy

    def get_value(self, observations, rnn_hidden_states, prev_actions, masks):
        features, _ = self.net(
            observations, rnn_hidden_states, prev_actions, masks
        )
        return self.critic(features)

    def evaluate_actions(
        self, observations, rnn_hidden_states, prev_actions, masks, action
    ):
        features, rnn_hidden_states = self.net(
            observations, rnn_hidden_states, prev_actions, masks
        )
        distribution = self.action_distribution(features)
        value = self.critic(features)

        action_log_probs = distribution.log_probs(action)
        distribution_entropy = distribution.entropy().mean()

        aux_loss_meta = {}
        aux_loss_meta["action_distribution"] = distribution

        return value, action_log_probs, distribution_entropy, rnn_hidden_states, aux_loss_meta

    @classmethod
    @abc.abstractmethod
    def from_config(cls, config, observation_space, action_space):
        pass


class CriticHead(nn.Module):
    def __init__(self, input_size):
        super().__init__()
        self.fc = nn.Linear(input_size, 1)
        # nn.init.orthogonal_(self.fc.weight)
        # nn.init.constant_(self.fc.bias, 0)

    def forward(self, x):
        return self.fc(x)


class MLPCriticHead(nn.Module):
    def __init__(self, input_size, hidden_dim=512, detach=False):
        super().__init__()
        self.fc = nn.Sequential(
            nn.Linear(input_size, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim,  1),
        )
        nn.init.orthogonal_(self.fc[0].weight)
        nn.init.constant_(self.fc[0].bias, 0)

        nn.init.orthogonal_(self.fc[2].weight)
        nn.init.constant_(self.fc[2].bias, 0)

        self.detach = detach
        logger.info("Detach critic: {}".format(self.detach))
        print("Detach critic: {}".format(self.detach))

    def forward(self, x):
        if self.detach:
            logger.info("detach")
            x = x.detach()
        return self.fc(x)


@baseline_registry.register_policy
class PointNavBaselinePolicy(Policy):
    def __init__(
        self,
        observation_space: spaces.Dict,
        action_space,
        hidden_size: int = 512,
        **kwargs
    ):
        super().__init__(
            PointNavBaselineNet(  # type: ignore
                observation_space=observation_space,
                hidden_size=hidden_size,
                **kwargs,
            ),
            action_space.n,
        )

    @classmethod
    def from_config(
        cls, config: Config, observation_space: spaces.Dict, action_space
    ):
        return cls(
            observation_space=observation_space,
            action_space=action_space,
            hidden_size=config.RL.PPO.hidden_size,
        )


class Net(nn.Module, metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def forward(self, observations, rnn_hidden_states, prev_actions, masks):
        pass

    @property
    @abc.abstractmethod
    def output_size(self):
        pass

    @property
    @abc.abstractmethod
    def num_recurrent_layers(self):
        pass

    @property
    @abc.abstractmethod
    def is_blind(self):
        pass


class PointNavBaselineNet(Net):
    r"""Network which passes the input image through CNN and concatenates
    goal vector with CNN's output and passes that through RNN.
    """

    def __init__(
        self,
        observation_space: spaces.Dict,
        hidden_size: int,
    ):
        super().__init__()

        if (
            IntegratedPointGoalGPSAndCompassSensor.cls_uuid
            in observation_space.spaces
        ):
            self._n_input_goal = observation_space.spaces[
                IntegratedPointGoalGPSAndCompassSensor.cls_uuid
            ].shape[0]
        elif PointGoalSensor.cls_uuid in observation_space.spaces:
            self._n_input_goal = observation_space.spaces[
                PointGoalSensor.cls_uuid
            ].shape[0]
        elif ImageGoalSensor.cls_uuid in observation_space.spaces:
            goal_observation_space = spaces.Dict(
                {"rgb": observation_space.spaces[ImageGoalSensor.cls_uuid]}
            )
            self.goal_visual_encoder = SimpleCNN(
                goal_observation_space, hidden_size
            )
            self._n_input_goal = hidden_size

        self._hidden_size = hidden_size

        self.visual_encoder = SimpleCNN(observation_space, hidden_size)

        self.state_encoder = RNNStateEncoder(
            (0 if self.is_blind else self._hidden_size) + self._n_input_goal,
            self._hidden_size,
        )

        self.train()

    @property
    def output_size(self):
        return self._hidden_size

    @property
    def is_blind(self):
        return self.visual_encoder.is_blind

    @property
    def num_recurrent_layers(self):
        return self.state_encoder.num_recurrent_layers

    def forward(self, observations, rnn_hidden_states, prev_actions, masks):
        if IntegratedPointGoalGPSAndCompassSensor.cls_uuid in observations:
            target_encoding = observations[
                IntegratedPointGoalGPSAndCompassSensor.cls_uuid
            ]

        elif PointGoalSensor.cls_uuid in observations:
            target_encoding = observations[PointGoalSensor.cls_uuid]
        elif ImageGoalSensor.cls_uuid in observations:
            image_goal = observations[ImageGoalSensor.cls_uuid]
            target_encoding = self.goal_visual_encoder({"rgb": image_goal})

        x = [target_encoding]

        if not self.is_blind:
            perception_embed = self.visual_encoder(observations)
            x = [perception_embed] + x

        x_out = torch.cat(x, dim=1)
        x_out, rnn_hidden_states = self.state_encoder(
            x_out, rnn_hidden_states, masks
        )

        return x_out, rnn_hidden_states