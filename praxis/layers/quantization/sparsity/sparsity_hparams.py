# coding=utf-8
# Copyright 2022 The Pax Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Collection of hyper-parameters for sparsity."""

import dataclasses
import enum
from praxis.layers.quantization.sparsity import sparsity_modes


BaseSparsityScheduleMode = sparsity_modes.BaseSparsityScheduleMode
InferenceMode = sparsity_modes.InferenceMode
FewShotMode = sparsity_modes.FewShotMode


@enum.unique
class SparsityScore(str, enum.Enum):
  """The different score function for sparsity.

  `MAGNITUDE` implements weight magnitude scoring.
  `ACTIVATION_WEIGHTED` implements activation weighted scoring.
  """

  MAGNITUDE = 'magnitude'
  ACTIVATION_WEIGHTED = 'activation_weighted'


@enum.unique
class SparsityType(str, enum.Enum):
  """The different types for sparsity.

  `STRUCTURED_NM` implementes N:M structured sparsity.
  `UNSTRUCTURED` implementes unstructured sparsity.
  """

  STRUCTURED_NM = 'structured_nm'
  UNSTRUCTURED = 'unstructured'
  CHANNELWISE_PRUNING = 'channelwise_pruning'


@dataclasses.dataclass
class PolynomialDecayParams:
  """Params for polynomial decay schedule.

  The sparsity rate is calculated as

  current_sparsity = final_sparsity + (initial_sparsity - final_sparsity)
          * (1 - (step - begin_step)/(end_step - begin_step)) ^ exponent

  which is a polynomial decay function. See
  [paper](https://arxiv.org/abs/1710.01878).

  initial_sparsity: Starting sparsity value.
  final_sparsity: Target sparsity value.
  begin_step: First step at which to start applying sparsity
  end_step: Last sparsity update
  exponent: Exponent to be used in the sparsity function.
  """

  initial_sparsity: float = 10.0
  final_sparsity: float = 70.0
  begin_step: int = 0
  end_step: int = 50_000
  exponent: float = 3.0


# TODO(ayazdan): Define parameters for activation sparsity.
@dataclasses.dataclass
class WeightSparsityParams:
  """Parameters for sparsity.

  Attributes:
    prune_rate:  Defines the rate of pruning, either for unstructured sparsity
      or N:M structured sparsity. None means no pruning will be applied.
    structure_decay: If True, a decaying schedule is applied for the structured
      sparsity, the algorithm is described in:
      https://arxiv.org/pdf/2209.07617.pdf.
    mask_decay_weight: If 0.0, no mask decay is applied. The mask value start
      with 1.0 and each time `num_update_sparsity` * `mask_decay_weight` is
      subtracted from 1.0. Due to overhead of jit, we limited the number of
      updates to `num_update_sparsity` to 16. After 16 iterations, we forcefully
      set `mask_decay_value` to zero. Mask decaying works for both structured
      and unstructured sparsity. The algorithm is described in:
      https://arxiv.org/pdf/2209.07617.pdf.
    sparse_ste: If True, a sparse-refined straight-through estimator (SR-STE) is
      applied, following the algorithm described in:
        https://arxiv.org/abs/2102.04010
    sparse_ste_weight: Denotes the relative weight for the sparse-refined term.
      As mentioned in the paper (https://arxiv.org/abs/2102.04010), the best
      default value is 0.0002 (lambda_w in the paper).
  """

  # TODO(ayazdan): Add additional sparsity parameters (order, offset, etc.)
  prune_rate: None | float | tuple[int, int]
  structure_decay: bool = False
  mask_decay_weight: float = 0.0
  sparse_ste: bool = False
  sparse_ste_weight: float = 0.0002

  def __post_init__(self):
    assert self.mask_decay_weight >= 0.0, (
        'Invalid value for '
        f'{self.mask_decay_weight}. '
        '`mask_decay_weight` must be positive.'
    )

    assert self.sparse_ste_weight >= 0.0, (
        'Invalid value for '
        f'{self.sparse_ste_weight}. '
        '`sparse_ste_weight` must be positive (uses SR-STE) or 0 (uses STE).'
    )

    if self.sparse_ste:
      if self.mask_decay_weight != 0.0:
        raise ValueError('SR-STE only works with non-decaying mask.')
      if self.structure_decay:
        raise ValueError(
            'SR-STE only works with non-decaying sparse structure.'
        )


@dataclasses.dataclass
class SparsityHParams:
  """Collection of hyper-parameters for sparsity.

  Attributes:
    sparsity_type: Defines sparsity types.
    weight_params: WeightSparsityParams object.
    mode: Defines sparsity mode.
    score: Defines sparsity score function.
    target_step: target step to start sparsity pruning.
    sparsified_layers: List of indices of layer to sparisify. None means all the
      layers to be sparsified.
    polynomial_decay_schedule: polynomial decay schedule for unstructured
      sparsity
    order: Apply pruning using this index order. Supported values are `C`, `R`.
      `C` and `R` indicate column-wise and row-wise masking, respectively.
      Default is `R` indicating to applying N:M sparsity across rows of the
      input matrix.
    track_sad_metric: Should we track sparse architecture divergence metric?
    topk_estimator_type: Sets the type of top-k mask learning.
  """

  sparsity_type: SparsityType = SparsityType.STRUCTURED_NM
  weight_params: WeightSparsityParams | None = None
  mode: BaseSparsityScheduleMode = dataclasses.field(
      default_factory=InferenceMode
  )
  score: SparsityScore = SparsityScore.MAGNITUDE
  sparsified_layers: list[int] | None = None
  polynomial_decay_schedule: PolynomialDecayParams | None = None
  order: str = 'R'
  track_sad_metric: bool = False
  topk_estimator_type: str | None = None
  # TODO enable per layer dim i.e. linear 1 and 2
  # Enable unstacking
  channelwise_pruning_dim: int = -1

  def __post_init__(self):
    if (
        self.weight_params is not None
    ):
      # Check sparsity types.
      if self.sparsity_type == SparsityType.STRUCTURED_NM:
        if self.weight_params.prune_rate is not None:
          assert isinstance(self.weight_params.prune_rate, tuple), (
              'Prune rate must be either None '
              'for no pruning or a Tuple[int, int] for '
              'N:M structured sparsity.'
          )
      elif self.sparsity_type == SparsityType.UNSTRUCTURED:
        if self.weight_params.prune_rate is not None:
          assert isinstance(self.weight_params.prune_rate, float), (
              'Prune rate must be either None or float '
              'for unstructured sparsity.'
          )
        if self.weight_params.sparse_ste:
          raise ValueError('SR-STE only works with structured sparsity.')

      elif self.sparsity_type == SparsityType.CHANNELWISE_PRUNING:
        if self.weight_params.prune_rate is not None:
          assert isinstance(self.weight_params.prune_rate, float), (
              'Prune rate must be either None or float '
              'for unstructured sparsity.'
          )
        if self.weight_params.sparse_ste:
          raise ValueError('SR-STE only works with structured sparsity.')

      else:
        assert False, f'Unrecognized sparsity type {self.sparsity_type}.'

      if self.order not in ['C', 'R']:
        raise ValueError(f'Index order {self.order} not supported.')
