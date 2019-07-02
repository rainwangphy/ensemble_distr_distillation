"""Metrics"""
import torch


def entropy(predicted_distribution):
    """Entropy

    B = batch size, C = num classes
    Labels as one hot vectors
    Note: if a batch with B samples is given,
    then the output is a tensor with B values

    Args:
        predicted_distribution: torch.tensor((B, C))

    Returns:
        entropy(ies): torch.tensor(B,)
    """

    return -torch.sum(
        predicted_distribution * torch.log(predicted_distribution), dim=-1)


def nll(true_labels, predicted_distribution):
    """Negative log likelihood

    B = batch size, C = num classes
    Labels as one hot vectors
    Note: if a batch with B samples is given,
    then the output is a tensor with B values

    Args:
        true_labels: torch.tensor((B, C))
        predicted_distribution: torch.tensor((B, C))

    Returns:
        nll(s): torch.tensor(B,)
    """

    true_labels_float = true_labels.float()
    return -torch.sum(true_labels_float * torch.log(predicted_distribution),
                      dim=-1)


def brier_score(true_labels, predicted_distribution):
    """Negative log likelihood

    B = batch size, C = num classes
    Labels as one hot vectors
    Note: if a batch with B samples is given,
    then the output is a tensor with B values

    Args:
        true_labels: torch.tensor((B, C))
        predicted_distribution: torch.tensor((B, C))

    Returns:
        Brier score(s): torch.tensor(B,)
    """

    true_labels_float = true_labels.float()