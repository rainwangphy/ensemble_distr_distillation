"""Loss module"""
import torch
import numpy as np
import torch.distributions.multivariate_normal as torch_mvn

import logging

LOGGER = logging.getLogger(__name__)


def cross_entropy_soft_targets(predicted_distribution, target_distribution):
    """Cross entropy loss with soft targets.
    B = batch size, D = dimension of target (num classes), N = ensemble size

    Args:
        inputs (torch.tensor((B, D - 1))): predicted distribution
        soft_target (torch.tensor((B, D - 1))): target distribution
    """

    return torch.mean(-target_distribution * torch.log(predicted_distribution))


def gaussian_neg_log_likelihood_1d(parameters, target):
    """Negative log likelihood loss for the Gaussian distribution
    B = batch size, D = dimension of target (always 1), N = ensemble size

    Args:
        parameters (torch.tensor((B, D)), torch.tensor((B, D))):
            mean values and variances of y|x for every x in
            batch.

        target (torch.tensor((B, N, D))): sample from the normal
            distribution, if not an ensemble prediction N=1.
    """
    mean, var = parameters
    target = target.reshape((target.size(0), 1))
    exponent = -0.5 * (target - mean)**2 / var
    log_coeff = -1 / 2 * torch.log(var) - 0.5 * 1 * np.log(2 * np.pi)

    return -(log_coeff + exponent).mean()


def gaussian_neg_log_likelihood(parameters, target):
    """Negative log likelihood loss for the Gaussian distribution
    B = batch size, D = dimension of target (num classes), N = ensemble size

    Args:
        parameters (torch.tensor((B, D)), torch.tensor((B, D))):
            mean values and variances of y|x for every x in
            batch.

        target (torch.tensor((B, N, D))): sample from the normal
            distribution, if not an ensemble prediction N=1.
    """
    mean, var = parameters

    loss = 0
    for batch_index, (mean_b, cov_b) in enumerate(zip(mean, var)):
        cov_mat_b = torch.diag(cov_b)
        distr = torch_mvn.MultivariateNormal(mean_b, cov_mat_b)

        log_prob = distr.log_prob(target[batch_index, :, :])
        loss -= torch.mean(log_prob) / target.size(0)

    return loss


def gaussian_neg_log_likelihood_diag(parameters, target):
    """Negative log likelihood loss for the Gaussian distribution
    B = batch size, D = dimension of target (num classes), N = ensemble size

    Args:
        parameters (torch.tensor((B, D)), torch.tensor((B, D))):
            mean values and variances of y|x for every x in
            batch.

        target (torch.tensor((B, N, D))): sample from the normal
            distribution, if not an ensemble prediction N=1.
    """
    B, N, _ = target.size()
    mu, sigma_sq = parameters

    prec = sigma_sq.pow(-1)

    nll = 0.0
    for mu_b, prec_b, target_b in zip(mu, prec, target):
        sample_var = (target_b - mu_b).var(dim=0)
        trace_term = (prec_b * sample_var).sum() * N / 2
        nll += trace_term - N / 2 * prec_b.prod()

    return nll / B


def kl_div_gauss_and_mixture_of_gauss(parameters, targets):
    """KL divergence between a single gaussian and a mixture of M gaussians

    for derivation details, see paper.

    Note: The loss is only correct up to a constant w.r.t. the parameters.

    TODO: Support multivarate

    TODO: Support weighted mixture

    B = batch size, N = ensemble size

    Args:
        parameters (torch.tensor((B, 1)), torch.tensor((B, 1))):
            mean values and variances of y|x for every x in
            batch.
        target ((torch.tensor((B, N)), (torch.tensor((B, N)))):
            means and variances of the mixture components
    """

    mu_gauss = parameters[0]
    sigma_sq_gauss = parameters[1]

    mus_mixture = targets[0]
    sigma_sqs_mixture = targets[1]

    mu_bar = mus_mixture.mean(dim=1, keepdim=True)
    term_1 = torch.mean(
        sigma_sqs_mixture +
        (mus_mixture - mu_bar)**2, dim=1, keepdim=True) / sigma_sq_gauss
    term_2 = (mu_bar - mu_gauss)**2
    term_3 = torch.log(sigma_sq_gauss) / 2

    loss = torch.mean(term_1 + term_2 + term_3, dim=0)
    return loss


def mse(mean, target):
    """Mean squared loss (torch built-in wrapper)
    B = batch size, D = dimension of target, N = number of samples

    Args:
        mean (torch.tensor((B, D))):
            mean values of y|x for every x in
            batch (and for every ensemble member).
        target (torch.tensor((B, N, D))): Ground truth sample
            (if not an ensemble prediction N=1.)
    """

    _, N, _ = target.size()
    loss_function = torch.nn.MSELoss(reduction="mean")
    total_loss = 0
    for sample_ind in np.arange(N):
        sample = target[:, sample_ind, :]
        total_loss += loss_function(sample, mean)

    return total_loss / N


def inverse_wishart_neg_log_likelihood(parameters, target):
    """Negative log likelihood loss for the inverse-Wishart distribution
    B = batch size, D = target dimension, N = ensemble size

    Args:
        parameters (torch.tensor((B, D)), torch.tensor((B, 1))):
            diagonal of psi and degrees-of-freedom, nu > D - 1, of the
            inverse-Wishart distribution for every x in batch.
        target (torch.tensor((B, N, D))): variance
            (diagonal of covariance matrix)
            as output by N ensemble members.
            """

    # This should only happen when we only have one target (i.e. N=1)
    if target.dim() == 2:
        target = torch.unsqueeze(target, dim=1)

    psi = parameters[0]
    nu = parameters[1]

    normalizer = 0
    ll = 0
    for i in np.arange(target.size(1)):
        cov_mat = [
            torch.diag(target[b, i, :]) for b in np.arange(target.size(0))
        ]
        cov_mat_det = torch.unsqueeze(torch.stack(
            [torch.det(cov_mat_i) for cov_mat_i in cov_mat], dim=0),
                                      dim=1)

        psi_mat = [torch.diag(psi[b, :]) for b in np.arange(target.size(0))]
        psi_mat_det = torch.unsqueeze(torch.stack(
            [torch.det(psi_mat_i) for psi_mat_i in psi_mat], dim=0),
                                      dim=1)

        normalizer += (-(nu / 2) * torch.log(psi_mat_det) +
                       (nu * target.size(-1) / 2) *
                       torch.log(torch.tensor(2, dtype=torch.float32)) +
                       torch.lgamma(nu / 2) +
                       ((nu - target.size(-1) - 1) / 2) *
                       torch.log(cov_mat_det)) / target.size(
                           1)  # Mean over ensemble
        ll += torch.stack([
            0.5 * torch.trace(torch.inverse(psi_mat_i) * cov_mat_i)
            for psi_mat_i, cov_mat_i in zip(psi_mat, cov_mat)
        ],
                          dim=0) / target.size(1)

    return torch.mean(normalizer + ll)  # Mean over batch
