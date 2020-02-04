"""UCI dataset"""
from abc import abstractmethod
import logging
from pathlib import Path
import numpy as np
import torch.utils.data as torch_data
from sklearn.model_selection import KFold


class UCIData():
    """UCI base class"""
    def __init__(self, file_path, seed=0):
        super().__init__()
        self._log = logging.getLogger(self.__class__.__name__)
        self.file_path = self._validate_file_path(file_path)
        self.data = None
        self.output_dim = 1
        self.seed = seed
        self.load_full_data()
        self.num_samples, self.input_dim = self.data.shape
        self.input_dim -= 1

    def _validate_file_path(self, file_path):
        """Validate path"""
        file_path = Path(file_path)
        file_path = file_path.expanduser()
        if not file_path.exists():
            self._log.error("Dataset does not exist")
        return file_path

    @abstractmethod
    def load_full_data(self):
        """Load UCI data into np array"""
        pass

    def datasplit_generator(self, num_splits, batch_size, transform=False):
        """Create a generator of datasplits"""
        split_generator = KFold(n_splits=num_splits).split(self.data)
        for idx in split_generator:
            train_idx, test_idx = idx
            x_train, y_train = self.data[train_idx, :self.
                                         input_dim], self.data[train_idx, self.
                                                               input_dim:]

            x_mean, x_std = get_stats(x_train)
            y_mean, y_std = get_stats(y_train)

            x_test, y_test = self.data[test_idx, :self.input_dim], self.data[
                test_idx, self.input_dim:]

            x_train = (x_train - x_mean) / x_std
            y_train = (y_train - y_mean) / y_std

            x_test = (x_test - x_mean) / x_std
            y_test = (y_test - y_mean) / y_std

            train = uci_dataloader(x_train, y_train, batch_size)
            test = uci_dataloader(x_test, y_test, y_test.shape[0])
            yield train, test


class _UCIDataset(torch_data.Dataset):
    """Internal representation of a subset of UCI data"""
    def __init__(self, x_data, y_data):
        self.x_data = x_data
        self.y_data = y_data
        self.num_samples, self.input_dim = self.x_data.shape

    def __len__(self):
        return self.num_samples

    def __getitem__(self, index):
        return self.x_data[index, :], self.y_data[index, :]


def uci_dataloader(x_data, y_data, batch_size):
    """Generate a dataloader"""
    dataset = _UCIDataset(x_data, y_data)
    return torch_data.DataLoader(dataset, batch_size=batch_size, shuffle=False)


def get_stats(data):
    return data.mean(axis=0), data.var(axis=0)**0.5
