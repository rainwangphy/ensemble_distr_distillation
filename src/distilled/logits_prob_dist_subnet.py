import torch
import torch.nn as nn
import torch.optim as torch_optim
import src.loss as custom_loss
import src.distilled.distilled_network as distilled_network
import torch.distributions.multivariate_normal as torch_mvn


class LogitsProbabilityDistributionSubNet(distilled_network.DistilledNet):
    # Will make two subnetwork, where on predicts the mean and one the variance of the distribution
    def __init__(self,
                 layer_sizes_1,
                 layer_sizes_2,
                 teacher,
                 device=torch.device('cpu'),
                 use_hard_labels=False,
                 learning_rate=0.001):

        super().__init__(
            teacher=teacher,
            loss_function=custom_loss.gaussian_neg_log_likelihood,
            device=device)

        self.use_hard_labels = use_hard_labels
        self.learning_rate = learning_rate

        self.layers_1 = nn.ModuleList()
        for i in range(len(layer_sizes_1) - 1):
            self.layers.append(nn.Linear(layer_sizes_1[i], layer_sizes_1[i + 1]))

        self.layers_2 = nn.ModuleList()
        for i in range(len(layer_sizes_2) - 1):
            self.layers.append(nn.Linear(layer_sizes_2[i], layer_sizes_2[i + 1]))

        # Ad-hoc fix zero variance.
        self.variance_lower_bound = 0.0
        if self.variance_lower_bound > 0.0:
            self._log.warning("Non-zero variance lower bound set ({})".format(
                self.variance_lower_bound))

        self.layers = [self.fc1a, self.fc2a, self.fc3a, self.fc2b, self.fc2b, self.fc3b]

        self.optimizer = torch_optim.Adam(self.parameters(),
                                          lr=self.learning_rate)

        self.to(self.device)

    def forward(self, x):
        """Estimate parameters of distribution
        """

        input = x
        for layer in self.layers_1[:-1]:
            x = nn.functional.relu(layer(x))

        mean = self.layers_1[-1](x)

        x = input
        for layer in self.layers_2[:-1]:
            x = nn.functional.relu(layer(x))

        var_z = self.layers_2[-1](x)

        var = torch.log(1 + torch.exp(var_z) + self.variance_lower_bound)

        return mean, var

    def _generate_teacher_predictions(self, inputs):
        """Generate teacher predictions"""

        logits = self.teacher.get_logits(inputs)

        # OBS JAKOB ANVÄNDER INTE SCALED LOGITS; VET INTE HUR VI SKA LÖSA DET (ÄR JU INTE LOGISKT FÖ REG.OUTPUT)
        scaled_logits = logits - torch.stack([logits[:, :, -1]], axis=-1)

        return scaled_logits[:, :, 0:-1]
        #return logits

    def predict(self, input_, num_samples=None):
        """Predict parameters
        Wrapper function for the forward function.
        """

        if num_samples is None:
            num_samples = len(self.teacher.members)

        mean, var = self.forward(input_)

        samples = torch.zeros(
            [input_.size(0), num_samples,
             int(self.output_size / 2)])
        for i in range(input_.size(0)):

            rv = torch.distributions.multivariate_normal.MultivariateNormal(
                loc=mean[i, :], covariance_matrix=torch.diag(var[i, :]))
            samples[i, :, :] = rv.rsample([num_samples])

        if self.scale_teacher_logits:
            samples = torch.cat((samples, torch.zeros(samples.size(0), num_samples, 1)))

        return nn.Softmax(dim=-1)(samples)

    def _learning_rate_condition(self, epoch=None):
        """Evaluate condition for increasing learning rate
        Defaults to never increasing. I.e. returns False
        """

        return True

    def calculate_loss(self, outputs, teacher_predictions, labels=None):
        """Calculate loss function
        Wrapper function for the loss function.
        """
        return self.loss(outputs, teacher_predictions)

    def mean_expected_value(self, outputs, teacher_predictions):
        exp_value = outputs[0]

        return torch.mean(exp_value, dim=0)

    def mean_variance(self, outputs, teacher_predictions):
        variance = outputs[1]

        return torch.mean(variance, dim=0)


