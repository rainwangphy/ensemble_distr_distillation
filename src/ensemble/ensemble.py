"""Ensemble class"""
import logging
from abc import ABC, abstractmethod
import torch
import torch.nn as nn
import torch.optim as torch_optim
import src.metrics as metrics


# TODO: I added the option in the ensemble-members to be able to calculate metrics on new data, maybe we should have a similar ensemble-level option
class Ensemble():
    def __init__(self, output_size):
        """The ensemble member needs to track the size
        of the output of the ensemble
        This can be automatically inferred but it would look ugly
        and this now works as a sanity check as well
        """
        self.members = list()
        self._log = logging.getLogger(self.__class__.__name__)
        self.output_size = output_size
        self.size = 0

    def add_member(self, new_member):
        if issubclass(type(new_member), EnsembleMember) or True:
            self._log.warning("Is subclass check disabled")
            self._log.info("Adding {} to ensemble".format(type(new_member)))
            self.members.append(new_member)
            self.size += 1
        else:
            err_str = "Ensemble member must be an EnsembleMember subclass"
            self._log.error(err_str)
            raise ValueError(err_str)

    def add_multiple(self, number_of, constructor):
        for _ in range(number_of):
            self.add_member(constructor())

    def train(self, train_loader, num_epochs, validation_loader=None):
        """Multithreaded?"""
        self._log.info("Training ensemble")
        for ind, member in enumerate(self.members):
            self._log.info("Training member {}/{}".format(ind + 1, self.size))
            member.train(train_loader, num_epochs, validation_loader)

    def add_metrics(self, metrics_list):
        for metric in metrics_list:
            if isinstance(metric, metrics.Metric):
                for member in self.members:
                    member.metrics[metric.name] = metric
                    self._log.info("Adding metric: {}".format(metric.name))
            else:
                self._log.error(
                    "Metric {} does not inherit from metric.Metric.".format(
                        metric.name))

    def calc_metrics(self, data_loader):
        for member in self.members:
            member.calc_metrics(data_loader)

    def get_logits(self, inputs):
        """Ensemble logits
        Returns the logits of all individual ensemble members.
        B = batch size, K = num output params, N = ensemble size

        Args:
            inputs (torch.tensor((B, data_dim))): data batch

        Returns:
            logits (torch.tensor((B, N, K)))
        """

        batch_size = inputs.size(0)
        logits = torch.zeros((batch_size, self.size, self.output_size))
        for member_ind, member in enumerate(self.members):
            logits[:, member_ind, :] = member.forward(inputs)

        return logits

    def transform_logits(self, logits, transformation=None):
        """Ensemble predictions from logits
        Returns the predictions of all individual ensemble members,
        by applying the logits 'transformation' to the logits.
        B = batch size, K = num output params, N = ensemble size

        Args:
            transformed_logits (torch.tensor((B, N, K))): data batch
            transformation (funcion): maps logits to output space

        Returns:
            predictions (torch.tensor((B, N, K)))
        """

        batch_size = logits.size(0)
        transformed_logits = torch.zeros(
            (batch_size, self.size, self.output_size))
        for member_ind, member in enumerate(self.members):
            if transformation:
                transformed_logits[:, member_ind, :] = transformation(
                    logits[:, member_ind, :])
            else:
                transformed_logits[:, member_ind, :] = member.transform_logits(
                    logits[:, member_ind, :])

        return transformed_logits

    def predict(self, inputs, t=None):
        """Ensemble prediction
        Returns the predictions of all individual ensemble members.
        The return is actually a tuple with (pred_mean, all_predictions)
        for backwards compatibility but this should be removed.
        B = batch size, K = num output params, N = ensemble size
        TODO: Remove pred_mean and let the
        distilled model chose what to do with the output

        Args:
            inputs (torch.tensor((B, data_dim))): data batch

        Returns:
            predictions (torch.tensor((B, N, K)))
        """
        batch_size = inputs.size(0)
        predictions = torch.zeros((batch_size, self.size, self.output_size))
        for member_ind, member in enumerate(self.members):
            if t is None:
                predictions[:, member_ind, :] = member.predict(inputs)
            else:
                predictions[:, member_ind, :] = member.predict(inputs, t)

        return predictions

    def save_ensemble(self, filepath):

        members_dict = {}
        for i, member in enumerate(self.members):
            members_dict["ensemble_member_{}".format(i)] = member
            # To save memory one should save model.state_dict,
            # but then we also need to save class-type etc.,
            # so I will keep it like this for now

        torch.save(members_dict, filepath)

    def load_ensemble(self, filepath, num_members=None):

        check_point = torch.load(filepath)

        for i, key in enumerate(check_point):

            if num_members is not None and i == num_members:
                break

            member = check_point[key]
            # member.eval(), should be called if we have dropout or batch-norm
            # in our layers, to make sure that self.train = False,
            # just that it doesn't work for now
            self.add_member(member)


class EnsembleMember(nn.Module, ABC):
    """Parent class for keeping common logic in one place"""
    def __init__(self, output_size, loss_function, device=torch.device("cpu")):
        super().__init__()
        self._log = logging.getLogger(self.__class__.__name__)
        self.output_size = output_size
        self.loss = loss_function
        self.metrics = dict()
        self.optimizer = None
        self._log.info("Moving model to device: {}".format(device))
        self.device = device

        if self.loss is None:  # or not issubclass(type(self.loss),
            # nn.modules.loss._Loss): THIS DOES NOT WORK OUT

            raise ValueError("Must assign proper loss function to child.loss.")

    def train(self,
              train_loader,
              num_epochs,
              validation_loader=None,
              metrics=list()):
        """Common train method for all ensemble member classes
        Should NOT be overridden!
        """

        scheduler = torch_optim.lr_scheduler.StepLR(self.optimizer,
                                                    step_size=10,
                                                    gamma=0.1)
        for epoch_number in range(1, num_epochs + 1):
            loss = self._train_epoch(train_loader, validation_loader)
            self._print_epoch(epoch_number, loss)
            if self._learning_rate_condition(epoch_number):
                scheduler.step()

    def _train_epoch(self,
                     train_loader,
                     validation_loader=None,
                     metrics=list()):
        """Common train epoch method for all ensemble member classes
        Should NOT be overridden!
        """

        self._reset_metrics()
        running_loss = 0.0
        for batch in train_loader:
            self.optimizer.zero_grad()
            inputs, targets = batch

            inputs, targets = inputs.to(self.device), targets.to(self.device)

            logits = self.forward(inputs)
            outputs = self.transform_logits(logits)
            # num_samples is different from batch size,
            # the loss expects a target with shape
            # (B, N, D), so that it can handle a full ensemble pred.
            # Here, we use a single sample N = 1.
            num_samples = 1
            batch_size = targets.size(0)
            targets = targets.reshape(
                (batch_size, num_samples, self.output_size // 2))
            loss = self.calculate_loss(outputs, targets)
            loss.backward()
            self.optimizer.step()
            running_loss += loss.item()

            if validation_loader is None:
                self._update_metrics(outputs, targets)

        if validation_loader is not None:
            for valid_batch in validation_loader:
                valid_inputs, valid_labels = valid_batch
                valid_logits = self.forward(valid_inputs)
                valid_outputs = self.transform_logits(valid_logits)
                self._update_metrics(valid_outputs, valid_labels)

                # Will automatically call

        return running_loss

    def calc_metrics(self, data_loader):
        self._reset_metrics()

        for batch in data_loader:
            inputs, targets = batch
            logits = self.forward(inputs)
            outputs = self.transform_logits(logits)
            self._update_metrics(outputs, targets)

        metric_string = ""
        for metric in self.metrics.values():
            metric_string += " {}".format(metric)
        self._log.info(metric_string)

    def _add_metric(self, metric):
        self.metrics[metric.name] = metric

    def _output_to_metric_domain(self, outputs):
        """Transform output for metric calculation
        Output distribution parameters are not necessarily
        exact representation for metrics calculation.
        This helper function can be overloaded to massage the output
        into the correct shape

        If not overridden, it works as an identity map.
        """
        return outputs

    def _update_metrics(self, outputs, targets):
        for metric in self.metrics.values():
            metric_output = self._output_to_metric_domain(outputs)
            metric.update(targets=targets, outputs=metric_output)

    def _reset_metrics(self):
        for metric in self.metrics.values():
            metric.reset()

    def _print_epoch(self, epoch_number, loss):
        epoch_string = "Epoch {}: Loss: {}".format(epoch_number, loss)
        for metric in self.metrics.values():
            epoch_string += " {}".format(metric)
        self._log.info(epoch_string)

    def _learning_rate_condition(self, epoch):
        """Evaluate condition for increasing learning rate
        Defaults to never increasing. I.e. returns False
        """

        return False

    @abstractmethod
    def forward(self, inputs):
        """Forward method only produces logits.
        I.e. no softmax or other det. transformation.
        That is instead handled by transform_logits
        This is for flexibility when using the ensemble as teacher.
        """
    @abstractmethod
    def transform_logits(self, logits):
        """Transforms the networks logits
        (produced by the forward method)
        to a suitable output value, i.e. a softmax
        to generate a probability distr.

        Default impl. is not given to avoid this transf.
        being implicitly included in the forward method.

        Args:
            logits (torch.tensor(B, K)):
        """
    @abstractmethod
    def calculate_loss(self, targets, outputs):
        """Calculates loss"""
