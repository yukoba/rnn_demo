import json
from statistics import median
import numpy as np
from pybrain.structure import LinearLayer, ReluLayer, BiasUnit
from pybrain.structure import FullConnection
from pybrain.structure import RecurrentNetwork
from pybrain.datasets import SequentialDataSet
from pybrain.supervised.trainers import BackpropTrainer
import data.ball_data as ball_data
from pybrain.structure.modules.neuronlayer import NeuronLayer


class HardTanhLayer(NeuronLayer):
    def _forwardImplementation(self, inbuf, outbuf):
        outbuf[:] = np.maximum(0, np.minimum(1, inbuf))

    def _backwardImplementation(self, outerr, inerr, outbuf, inbuf):
        inerr[:] = ((np.sign(outbuf) - np.sign(outbuf - 1)) / 2) * outerr


class AbsLayer(NeuronLayer):
    def _forwardImplementation(self, inbuf, outbuf):
        outbuf[:] = np.absolute(inbuf)

    def _backwardImplementation(self, outerr, inerr, outbuf, inbuf):
        inerr[:] = np.sign(outbuf) * outerr


BOX_SIZE = 10


def predict_ball(hidden_nodes, is_elman=True, training_data=16, epoch=-1, parameters={}, predict_count=16):
    # build rnn
    n = construct_network(hidden_nodes, is_elman)

    # make training data
    ep = 1 if epoch < 0 else epoch
    initial_p = [9., 7.]
    initial_v = [1., 1.]
    # initial_v = ball_data.gen_velocity(BOX_SIZE)
    data_set = ball_data.bounce_ball((training_data + 1) * ep, BOX_SIZE, initial_p=initial_p, initial_v=initial_v)
    total_avg = np.average(data_set, axis=0)
    total_std = np.std(data_set, axis=0)
    total_std[2] = 1.
    total_std[3] = 1.
    # initial_p = data_set[np.random.choice(range(training_data))][:2]

    training_ds = []
    print("data_set = {}".format(data_set))
    normalized_d = __normalize(data_set, total_avg, total_std)
    # print("normalized_d = {}".format(normalized_d))
    for e_index in range(ep):
        t_ds = SequentialDataSet(4, 4)
        t_ds.newSequence()
        e_begin = e_index * training_data
        for j in range(e_begin, e_begin + training_data):
            # from current, predict next
            p_in = normalized_d[0].tolist()
            p_out = normalized_d[j + 1].tolist()
            t_ds.addSample(p_in, p_out)

        training_ds.append(t_ds)

    # training network
    err1 = 0
    if epoch < 0:
        trainer = BackpropTrainer(n, training_ds[0], learningrate=2e-4, verbose=True)
        err1 = trainer.trainEpochs(20000)
    else:
        trainer = BackpropTrainer(n, **parameters)
        epoch_errs = []
        for ds in training_ds:
            trainer.setData(ds)
            epoch_errs.append(trainer.train())

        err1 = max(epoch_errs)

    # predict
    predict = None
    next_pv = np.hstack((initial_p, initial_v))

    n.reset()
    for i in range(predict_count):
        predict = next_pv if predict is None else np.vstack((predict, next_pv))
        # print("predict = {}".format(predict))

        p_normalized = (data_set[0] - total_avg) / total_std
        next_pv = n.activate(p_normalized.tolist())
        restored = np.array(next_pv) * total_std + total_avg
        next_pv = restored
        print("restored, answer = {}, {}".format(restored, data_set[i + 1]))

    real = ball_data.bounce_ball(predict_count, BOX_SIZE, initial_p, initial_v)
    err_matrix = (predict - real) ** 2
    err_distance = np.sqrt(np.sum(err_matrix[:, 0:2], axis=1)).reshape((predict_count, 1))
    err_velocity = np.sum(np.sqrt(err_matrix[:, 2:4]), axis=1).reshape((predict_count, 1))
    err2 = np.hstack((err_distance, err_velocity))

    return predict, real, err1, err2


def construct_network(hidden_nodes, is_elman=True):
    n = RecurrentNetwork()
    n.addInputModule(LinearLayer(4, name="i"))
    n.addModule(BiasUnit("b"))
    n.addModule(ReluLayer(hidden_nodes, name="h"))
    n.addOutputModule(LinearLayer(4, name="o"))

    n.addConnection(FullConnection(n["i"], n["h"]))
    n.addConnection(FullConnection(n["b"], n["h"]))
    n.addConnection(FullConnection(n["b"], n["o"]))
    n.addConnection(FullConnection(n["h"], n["o"]))

    if is_elman:
        # Elman (hidden->hidden)
        n.addRecurrentConnection(FullConnection(n["h"], n["h"]))
    else:
        # Jordan (out->hidden)
        n.addRecurrentConnection(FullConnection(n["o"], n["h"]))

    n.sortModules()
    n.stdParams = 0.03
    n.randomize()

    return n


def __normalize(data, total_avg, total_std):
    normalized = (data - total_avg) / total_std
    return normalized


def describe_err(error, separator=","):
    # weights = [1 / math.log(x) for x in range(2, error.shape[0] + 2)]
    weights = [x / error.shape[0] for x in range(error.shape[0], 0, -1)]
    params = np.hstack((np.average(error, axis=0, weights=weights), np.std(error, axis=0)))
    return separator.join(["{0}".format(p) for p in params])


def eval_hidden_effect(min_hidden, max_hidden, is_elman=True, step=10, training_data=5000, trial_run=10):
    for h in range(min_hidden, max_hidden + step, step):
        training_e = []
        test_e = None

        for i in range(trial_run):
            p, r, e1, e2 = predict_ball(h, is_elman, training_data)
            training_e.append(e1)
            test_e = e2 if test_e is None else np.vstack((test_e, e2))

        print("{0}\t{1}\t{2}".format(h, median(training_e), describe_err(test_e, "\t")))


def eval_training_effect(hidden_nodes, min_size, max_size, is_elman=True, step=1000, trial_run=10):
    for d in range(min_size, max_size + step, step):
        training_e = []
        test_e = None

        for i in range(trial_run):
            p, r, e1, e2 = predict_ball(hidden_nodes, is_elman, training_data=d)
            training_e.append(e1)
            test_e = e2 if test_e is None else np.vstack((test_e, e2))

        print("{0}\t{1}\t{2}".format(d, median(training_e), describe_err(test_e, "\t")))


def eval_batch_effect(hidden_nodes, min_size, max_size, epoch=2000, is_elman=True, step=64, trial_run=1):
    for d in range(min_size, max_size + step, step):
        training_e = []
        test_e = None

        for i in range(trial_run):
            p, r, e1, e2 = predict_ball(hidden_nodes, is_elman, training_data=d, epoch=epoch)
            training_e.append(e1)
            test_e = e2 if test_e is None else np.vstack((test_e, e2))

        print("{0}\t{1}\t{2}".format(d, median(training_e), describe_err(test_e, "\t")))


def eval_parameter_effect(hidden_nodes, parameter_array, is_elman=True, training_data=25000, trial_run=5):
    # parameter array: learning_rate and momentum

    for ps in parameter_array:
        training_e = []
        test_e = None

        for i in range(trial_run):
            p, r, e1, e2 = predict_ball(hidden_nodes, is_elman, training_data, parameters=ps)
            training_e.append(e1)
            test_e = e2 if test_e is None else np.vstack((test_e, e2))

        desc = ""
        print("{0}\t{1}\t{2}".format(json.dumps(ps), median(training_e), describe_err(test_e, "\t")))


def run(is_elman=True):
    nodes = 20
    p, r, e1, e2 = predict_ball(nodes, is_elman=is_elman, training_data=16, predict_count=16)
    # p, r, e1, e2 = predict_ball(nodes, is_elman=is_elman, training_data=1000, epoch=2000)
    # print("training error:{0}, test error:{1}".format(e1, describe_err(e2)))
    """
    for x in p:
        print("{0}, {1}".format(x[0], x[1]))
    """

    # ball_data.show_animation([r], BOX_SIZE)
    # ball_data.show_animation([p], BOX_SIZE)


def main(is_elman=True):
    """
    # evaluate model by changing hidden layer
    print("Elman")
    for lr in range(1, 11):
        for mt in range(5, 11):
            eval_parameter_effect(4, [{"learningrate": lr / 1000, "momentum": mt / 10 if mt < 10 else 0}])

    print("Jordan")
    for lr in range(1, 11):
        eval_parameter_effect(4, [{"learningrate": lr / 1000}], is_elman=False)
    """
    run(is_elman)


if __name__ == "__main__":
    # if len(sys.argv) > 1 and sys.argv[1] == "E":
    # main(True)
    # else:
    main(True)
