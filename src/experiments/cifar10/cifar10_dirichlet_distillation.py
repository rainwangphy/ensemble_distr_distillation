"""Train and make predictions with distilled network parameterising a Dirichlet distribution over ensemble output"""

import logging
from pathlib import Path
from datetime import datetime
import numpy as np
import torch
import h5py

from src import utils
from src import metrics
from src.dataloaders import cifar10_corrupted
from src.dataloaders import cifar10_ensemble_pred
from src.ensemble import ensemble_wrapper
from src.distilled import cifar_resnet_dirichlet
from src.experiments.cifar10 import resnet_utils

LOGGER = logging.getLogger(__name__)


def train_distilled_network_dirichlet(model_dir="models/distilled_model_cifar10_dirichlet"):
    """Distill ensemble with distribution distillation (Dirichlet) """

    args = utils.parse_args()

    log_file = Path("{}.log".format(datetime.now().strftime('%Y%m%d_%H%M%S')))
    utils.setup_logger(log_path=Path.cwd() / args.log_dir / log_file,
                       log_level=args.log_level)

    data_ind = np.load("src/experiments/cifar10/training_files/training_data_indices.npy")
    num_train_points = 40000
    train_ind = data_ind[:num_train_points]
    valid_ind = data_ind[num_train_points:]

    train_data = cifar10_ensemble_pred.Cifar10Data(ind=train_ind, augmentation=True)
    valid_data = cifar10_ensemble_pred.Cifar10Data(ind=valid_ind)

    train_loader = torch.utils.data.DataLoader(train_data.set,
                                               batch_size=100,
                                               shuffle=True,
                                               num_workers=0)

    valid_loader = torch.utils.data.DataLoader(valid_data.set,
                                               batch_size=100,
                                               shuffle=True,
                                               num_workers=0)

    test_data = cifar10_ensemble_pred.Cifar10Data(train=False)

    test_loader = torch.utils.data.DataLoader(test_data.set,
                                              batch_size=64,
                                              shuffle=True,
                                              num_workers=0)

    ensemble_size = 10

    # Note that the ensemble predictions are assumed to have been saved to file (see ensemble_predictions.py),
    # ensemble_indices.npy contains the order of the ensemble members such that ind[:ensemble_size] are the indices
    # of the first ensemble, ind[ensemble_size:2*ensemble_size] are the indices of the second ensemble and so on
    ind = np.load("src/experiments/cifar10/training_files/ensemble_indices.npy")[((args.rep - 1) * ensemble_size):
                                                                                 (args.rep * ensemble_size)]
    ensemble = ensemble_wrapper.EnsembleWrapper(
        output_size=10, indices=ind)

    device = utils.torch_settings(args.seed, args.gpu)
    distilled_model = cifar_resnet_dirichlet.CifarResnetDirichlet(ensemble,
                                                                  resnet_utils.BasicBlock,
                                                                  [3, 2, 2, 2],
                                                                  device=device,
                                                                  learning_rate=args.lr)

    loss_metric = metrics.Metric(name="Mean loss", function=distilled_model.calculate_loss)
    distilled_model.add_metric(loss_metric)

    distilled_model.train(train_loader, num_epochs=args.num_epochs, validation_loader=valid_loader)
    
    distilled_model.eval_mode()
    predicted_distribution = []
    all_labels = []

    for batch in test_loader:
        inputs, labels = batch
        inputs, labels = inputs[0].to(distilled_model.device), labels.to(distilled_model.device)

        predicted_distribution.append(distilled_model.predict(inputs).to(distilled_model.device))
        all_labels.append(labels.long())

    test_acc = metrics.accuracy(torch.cat(predicted_distribution), torch.cat(all_labels))
    LOGGER.info("Test accuracy is {}".format(test_acc))

    torch.save(distilled_model.state_dict(), model_dir)


def predictions_dirichlet(model_dir="../models/distilled_model_cifar10_dirichlet",
                file_dir="../../dataloaders/data/distilled_model_predictions_dirichlet.h5"):
    """Make and save predictions on train and test data with distilled model at model_dir"""

    args = utils.parse_args()

    train_data = cifar10_ensemble_pred.Cifar10Data()
    test_data = cifar10_ensemble_pred.Cifar10Data(train=False)

    ensemble = ensemble_wrapper.EnsembleWrapper(output_size=10)

    distilled_model = cifar_resnet_dirichlet.CifarResnetDirichlet(ensemble,
                                                                  resnet_utils.BasicBlock,
                                                                  [3, 2, 2, 2],
                                                                  learning_rate=args.lr)

    distilled_model.load_state_dict(torch.load(model_dir, map_location=torch.device('cpu')))
    distilled_model.eval_mode()

    data_list = [test_data, train_data]
    labels = ["test", "train"]

    hf = h5py.File(file_dir, 'w')

    for data_set, label in zip(data_list, labels):

        data, pred_samples, alpha, teacher_predictions, targets = \
            [], [], [], [], []

        data_loader = torch.utils.data.DataLoader(data_set.set,
                                                  batch_size=32,
                                                  shuffle=False,
                                                  num_workers=0)

        for batch in data_loader:
            inputs, labels = batch
            img = inputs[0].to(distilled_model.device)
            data.append(img.data.numpy())
            targets.append(labels.data.numpy())
            teacher_predictions.append(inputs[1].data.numpy())

            a, probs = distilled_model.predict(img, return_params=True)
            alpha.append(a.data.numpy())
            pred_samples.append(probs.data.numpy())

        data = np.concatenate(data, axis=0)
        pred_samples = np.concatenate(pred_samples, axis=0)
        teacher_predictions = np.concatenate(teacher_predictions, axis=0)
        targets = np.concatenate(targets, axis=0)
        alpha = np.concatenate(alpha, axis=0)

        preds = np.argmax(np.mean(pred_samples, axis=1), axis=-1)

        # Check accuracy
        acc = np.mean(preds == targets)
        LOGGER.info("Accuracy on {} data set is: {}".format(label, acc))

        # Check accuracy relative teacher
        teacher_preds = np.argmax(np.mean(teacher_predictions, axis=1), axis=-1)
        rel_acc = np.mean(preds == teacher_preds)
        LOGGER.info("Accuracy on {} data set relative teacher is: {}".format(label, rel_acc))

        grp = hf.create_group(label)
        grp.create_dataset("data", data=data)
        grp.create_dataset("predictions", data=pred_samples)
        grp.create_dataset("teacher-predictions", data=teacher_predictions)
        grp.create_dataset("targets", data=targets)
        grp.create_dataset("alpha", data=alpha)

    return pred_samples


def predictions_corrupted_data_dirichlet(model_dir="models/distilled_model_cifar10_dirichlet",
                               file_dir="../../dataloaders/data/distilled_model_predictions_corrupted_data_dirichlet.h5"):
    """Make and save predictions on corrupted data with distilled model at model_dir"""

    args = utils.parse_args()

    # Load model
    ensemble = ensemble_wrapper.EnsembleWrapper(output_size=10)

    distilled_model = cifar_resnet_dirichlet.CifarResnetDirichlet(ensemble,
                                                                  resnet_utils.BasicBlock,
                                                                  [3, 2, 2, 2],
                                                                  learning_rate=args.lr)

    distilled_model.load_state_dict(torch.load(model_dir, map_location=torch.device(distilled_model.device)))

    distilled_model.eval_mode()

    corruption_list = ["test", "brightness", "contrast", "defocus_blur", "elastic_transform", "fog", "frost",
                       "gaussian_blur", "gaussian_noise", "glass_blur", "impulse_noise", "motion_blur", "pixelate",
                       "saturate", "shot_noise", "snow", "spatter", "speckle_noise", "zoom_blur"]

    hf = h5py.File(file_dir, 'w')

    for i, corruption in enumerate(corruption_list):
        corr_grp = hf.create_group(corruption)

        if corruption == "test":
            intensity_list = [0]
        else:
            intensity_list = [1, 2, 3, 4, 5]

        for intensity in intensity_list:
            # Load the data
            data_set = cifar10_corrupted.Cifar10DataCorrupted(corruption=corruption, intensity=intensity,
                                                              data_dir="../../")
            dataloader = torch.utils.data.DataLoader(data_set.set,
                                                     batch_size=100,
                                                     shuffle=False,
                                                     num_workers=0)

            # data = []
            predictions, targets, alpha = [], [], []

            for j, batch in enumerate(dataloader):
                inputs, labels = batch
                targets.append(labels.data.numpy())
                # data.append(inputs.data.numpy())

                inputs, labels = inputs.to(distilled_model.device), labels.to(distilled_model.device)

                a, preds = distilled_model.predict(inputs, return_params=True)
                alpha.append(a.to(torch.device("cpu")).data.numpy())
                predictions.append(preds.to(torch.device("cpu")).data.numpy())

            sub_grp = corr_grp.create_group("intensity_" + str(intensity))

            # data = np.concatenate(data, axis=0)
            # sub_grp.create_dataset("data", data=data)

            predictions = np.concatenate(predictions, axis=0)
            sub_grp.create_dataset("predictions", data=predictions)

            targets = np.concatenate(targets, axis=0)
            sub_grp.create_dataset("targets", data=targets)

            preds = np.argmax(np.mean(predictions, axis=1), axis=-1)

            acc = np.mean(preds == targets)
            LOGGER.info("Accuracy on {} data set with intensity {} is {}".format(corruption, intensity, acc))

            alpha = np.concatenate(alpha, axis=0)
            sub_grp.create_dataset("alpha", data=alpha)

    hf.close()


def main():
    args = utils.parse_args()
    log_file = Path("{}.log".format(datetime.now().strftime('%Y%m%d_%H%M%S')))
    utils.setup_logger(log_path=Path.cwd() / args.log_dir / log_file,
                       log_level=args.log_level)
    LOGGER.info("Args: {}".format(args))

    train_distilled_network_dirichlet()
    predictions_corrupted_data_dirichlet()
    #predictions_dirichlet()


if __name__ == "__main__":
    main()
