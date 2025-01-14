import torch
import torch.nn as nn
import math
import numpy as np
from liesvf import network_models as models

from liesvf.utils import get_jacobian


class SE3NeuralFlows(nn.Module):
    def __init__(self, depth=7, hidden_units = 128, bins=40):
        super(SE3NeuralFlows, self).__init__()

        self.depth = depth
        self.hidden_units = hidden_units
        self.num_bins = bins

        self.dim = 6
        self.m_dim = 16

        self.layer = 'LinearSpline'

        self.main_map = models.DiffeomorphicNet(self.create_flow_sequence(), dim=self.dim)
        self.b2c_map = Sphere2Cube()

    def forward(self, x, context=None):
        y = x.clone()
        x_c = self.b2c_map(y[:, 3:])
        x_p = torch.clamp(x[:, :3], -1., 1.)
        y[:, :3] = x_p
        y[:, 3:] = x_c

        z = self.main_map(y, jacobian=False)
        return z

    def pushforward(self, x, context=None):
        z = self.forward(x)
        J = get_jacobian(self, x, x.size(-1))
        return z, J

    def create_flow_sequence(self):
        chain = []
        perm_i = np.linspace(0, self.dim-1, self.dim, dtype=int)
        for i in range(self.depth):
            perm_i = np.roll(perm_i, 1)
            chain.append(self.main_layer(list(perm_i)))
            chain.append(models.RandomPermutations(self.dim))
        chain.append(self.main_layer(perm_i))
        return chain

    def main_layer(self, order):
        return models.LinearSplineLayer(num_bins=self.num_bins, features=self.dim,
                                        hidden_features=self.hidden_units, order=order)



class Sphere2Cube(nn.Module):
    def __init__(self):
        super(Sphere2Cube, self).__init__()
        iot = math.sqrt(2) / 2
        self.register_buffer('_iot', torch.Tensor([iot]))
        self.register_buffer('_norm', torch.Tensor([math.pi]))
        self.register_buffer('_pi_2', torch.Tensor([math.pi/2]))

    def jacobian(self, inputs, context=None):
        return get_jacobian(self, inputs, inputs.size(-1))

    def forward(self, inputs, context=None):
        x = inputs/self._norm

        norm_x = torch.norm(x,dim=1)
        mask = norm_x<1.

        den = 1/ torch.sqrt(1- norm_x**2)
        y0 = torch.einsum('bd, b->bd',x, den)
        y1 = torch.atan(y0)/self._pi_2

        ## Sphere to Cube
        # max_x = torch.max(torch.abs(x), 1)
        # r = x.pow(2).sum(-1).pow(0.5)
        # y1 = x * r[:, None] / max_x.values[:, None]

        ## Map to zero beyond 1
        y_out = torch.einsum('b,bx->bx',mask,y1)
        y_out[y_out != y_out] = 0

        return y_out

    def backwards(self, inputs, context=None):
        y0 = torch.tan(inputs * self._pi_2)

        norm_y = torch.norm(y0,dim=1)
        den = 1 / torch.sqrt(1 + norm_y ** 2)
        x = torch.einsum('bd, b->bd', y0, den)
        return x * self._norm

