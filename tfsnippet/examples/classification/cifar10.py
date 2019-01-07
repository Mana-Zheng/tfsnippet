# -*- coding: utf-8 -*-
import click
import tensorflow as tf
from tensorflow.contrib.framework import arg_scope

import tfsnippet as ts
from tfsnippet.examples.utils import (MLConfig,
                                      MLResults,
                                      global_config as config,
                                      config_options,
                                      print_with_title)


class ExpConfig(MLConfig):
    # model parameters
    x_dim = 3 * 32 * 32
    l2_reg = 0.0001

    # training parameters
    write_summary = False
    max_epoch = 500
    max_step = None
    batch_size = 64
    test_batch_size = 64

    initial_lr = 0.001
    lr_anneal_factor = 0.5
    lr_anneal_epoch_freq = 50
    lr_anneal_step_freq = None


@ts.global_reuse
def model(x, is_training):
    with arg_scope([ts.layers.dense],
                   activation_fn=tf.nn.leaky_relu,
                   kernel_regularizer=ts.layers.l2_regularizer(config.l2_reg)):
        h_x = x
        h_x = ts.layers.dense(h_x, 1000)
        h_x = ts.layers.dense(h_x, 1000)
        h_x = ts.layers.dense(h_x, 1000)
    logits = ts.layers.dense(h_x, 10, name='logits')
    return logits


@click.command()
@click.option('--result-dir', help='The result directory.', metavar='PATH',
              required=False, type=str)
@config_options(ExpConfig)
def main(result_dir):
    # print the config
    print_with_title('Configurations', config.format_config(), after='\n')

    # open the result object and prepare for result directories
    results = MLResults(result_dir)
    results.make_dirs('train_summary', exist_ok=True)

    # input placeholders
    input_x = tf.placeholder(
        dtype=tf.float32, shape=(None, config.x_dim), name='input_x')
    input_y = tf.placeholder(
        dtype=tf.int32, shape=[None], name='input_y')
    is_training = tf.placeholder(
        dtype=tf.bool, shape=(), name='is_training')
    learning_rate = tf.placeholder(shape=(), dtype=tf.float32)
    learning_rate_var = ts.AnnealingDynamicValue(config.initial_lr,
                                                 config.lr_anneal_factor)

    # derive the loss, output and accuracy
    logits = model(input_x, is_training=is_training)
    cls_loss = tf.losses.sparse_softmax_cross_entropy(input_y, logits)
    loss = cls_loss + tf.losses.get_regularization_loss()
    y = ts.ops.softmax_classification_output(logits)
    acc = ts.ops.classification_accuracy(y, input_y)

    # derive the optimizer
    optimizer = tf.train.AdamOptimizer(learning_rate)
    params = tf.trainable_variables()
    grads = optimizer.compute_gradients(loss, var_list=params)
    with tf.control_dependencies(
            tf.get_collection(tf.GraphKeys.UPDATE_OPS)):
        train_op = optimizer.apply_gradients(grads)

    # prepare for training and testing data
    (x_train, y_train), (x_test, y_test) = \
        ts.datasets.load_cifar10(x_shape=(config.x_dim,), normalize_x=True)
    train_flow = ts.DataFlow.arrays([x_train, y_train], config.batch_size,
                                    shuffle=True, skip_incomplete=True)
    test_flow = ts.DataFlow.arrays([x_test, y_test], config.test_batch_size)

    with ts.utils.create_session().as_default():
        # train the network
        with ts.TrainLoop(params,
                          max_epoch=config.max_epoch,
                          max_step=config.max_step,
                          summary_dir=(results.system_path('train_summary')
                                       if config.write_summary else None),
                          summary_graph=tf.get_default_graph(),
                          early_stopping=False) as loop:
            trainer = ts.Trainer(
                loop, train_op, [input_x, input_y], train_flow,
                feed_dict={learning_rate: learning_rate_var, is_training: True},
                metrics={'loss': loss, 'acc': acc}
            )
            trainer.anneal_after(
                learning_rate_var,
                epochs=config.lr_anneal_epoch_freq,
                steps=config.lr_anneal_step_freq
            )
            evaluator = ts.Evaluator(
                loop,
                metrics={'test_acc': acc},
                inputs=[input_x, input_y],
                data_flow=test_flow,
                feed_dict={is_training: False},
                time_metric_name='test_time'
            )
            evaluator.after_run.add_hook(
                lambda: results.update_metrics(evaluator.last_metrics_dict))
            trainer.evaluate_after_epochs(evaluator, freq=5)
            trainer.log_after_epochs(freq=1)
            trainer.run()

    # print the final metrics and close the results object
    print_with_title('Results', results.format_metrics(), before='\n')
    results.close()


if __name__ == '__main__':
    main()
