import numpy as np
import pytest

import tensorflow as tf

from tests.helper import assert_variables
from tests.layers.flows.helper import invertible_flow_standard_check
from tfsnippet.layers import ActNorm, act_norm
from tfsnippet.shortcuts import global_reuse


def naive_act_norm_initialize(x, axis):
    """Compute the act_norm initial `scale` and `bias` for `x`."""
    x = np.asarray(x)
    axis = list(sorted(set([a + len(x.shape) if a < 0 else a for a in axis])))
    min_axis = np.min(axis)
    reduce_axis = tuple(a for a in range(len(x.shape)) if a not in axis)
    var_shape = [x.shape[a] for a in axis]
    var_shape_aligned = [x.shape[a] if a in axis else 1
                         for a in range(min_axis, len(x.shape))]
    mean = np.reshape(np.mean(x, axis=reduce_axis), var_shape)
    bias = -mean
    scale = 1. / np.reshape(
        np.sqrt(np.mean((x - np.reshape(mean, var_shape_aligned)) ** 2,
                        axis=reduce_axis)),
        var_shape
    )
    return scale, bias, var_shape_aligned


def naive_act_norm_transform(x, var_shape_aligned, value_ndims, scale, bias):
    scale = np.reshape(scale, var_shape_aligned)
    bias = np.reshape(bias, var_shape_aligned)
    y = (x + bias) * scale
    log_det = np.log(np.abs(scale)) * np.ones_like(x)
    if value_ndims > 0:
        log_det = np.sum(log_det, axis=tuple(range(-value_ndims, 0)))
    return y, log_det


def assert_allclose(a, b, epsilon=5e-4):
    assert(a.shape == b.shape)
    assert(np.max(np.abs(a - b)) <= epsilon)


class ActNormClassTestCase(tf.test.TestCase):

    def test_error(self):
        with pytest.raises(ValueError,
                           match='Invalid value for argument `scale_type`'):
            _ = ActNorm(-1, scale_type='xyz')

        with pytest.raises(ValueError, match='`axis` must not be empty'):
            _ = ActNorm(())

        with pytest.raises(ValueError,
                           match='Initializing ActNorm requires multiple '
                                 '`x` samples, thus `x` must have at least '
                                 'one more dimension than the variable shape'):
            act_norm = ActNorm([-3, -1])
            _ = act_norm.apply(tf.zeros([2, 3, 4]))

    def test_act_norm(self):
        np.random.seed(1234)

        x = np.random.normal(size=[3, 4, 5, 6, 7])
        x_ph = tf.placeholder(dtype=tf.float64, shape=[None, None, 5, None, 7])
        x2 = np.random.normal(size=[2, 3, 4, 5, 6, 7])
        x2_ph = tf.placeholder(dtype=tf.float64,
                               shape=[None, None, None, 5, None, 7])
        x3 = np.random.normal(size=[4, 5, 6, 7])
        x3_ph = tf.placeholder(dtype=tf.float64, shape=[None, 5, None, 7])

        with self.test_session() as sess:
            # -- static input shape, scale_type = 'linear', value_ndims = 0
            axis = [-1, -3]
            value_ndims = 0
            var_shape = (5, 7)

            scale, bias, var_shape_aligned = naive_act_norm_initialize(x, axis)
            self.assertEqual(scale.shape, var_shape)
            self.assertEqual(bias.shape, var_shape)

            # test initialize
            act_norm = ActNorm(axis=axis, value_ndims=value_ndims,
                               scale_type='linear')
            y_out, log_det_out = sess.run(
                act_norm.transform(tf.constant(x, dtype=tf.float64)))
            self.assertEqual(act_norm._bias.dtype.base_dtype, tf.float64)

            scale_out, bias_out = sess.run(
                [act_norm._pre_scale, act_norm._bias])
            assert_allclose(scale_out, scale)
            assert_allclose(bias_out, bias)

            # test the transform output from the initializing procedure
            y, log_det = naive_act_norm_transform(
                x, var_shape_aligned, value_ndims, scale, bias)
            self.assertEqual(y.shape, x.shape)
            self.assertEqual(log_det.shape, x.shape)
            assert_allclose(y_out, y)
            assert_allclose(log_det_out, log_det)

            # test use an initialized act_norm
            y2, log_det2 = naive_act_norm_transform(
                x2, var_shape_aligned, value_ndims, scale, bias)
            self.assertEqual(y2.shape, x2.shape)
            self.assertEqual(log_det2.shape, x2.shape)
            y2_out, log_det2_out = sess.run(
                act_norm.transform(tf.constant(x2, dtype=tf.float64)))
            assert_allclose(y2_out, y2)
            assert_allclose(log_det2_out, log_det2)

            # -- dynamic input shape, scale_type = 'exp', value_ndims = 2
            value_ndims = 2

            # test initialize
            act_norm = ActNorm(axis=axis, value_ndims=value_ndims,
                               scale_type='exp')
            y_out, log_det_out = sess.run(
                act_norm.transform(x_ph), feed_dict={x_ph: x})
            self.assertEqual(act_norm._bias.dtype.base_dtype, tf.float64)

            scale_out, bias_out = sess.run(
                [tf.exp(act_norm._pre_scale), act_norm._bias])
            assert_allclose(scale_out, scale)
            assert_allclose(bias_out, bias)

            # test the transform output from the initializing procedure
            y, log_det = naive_act_norm_transform(
                x, var_shape_aligned, value_ndims, scale, bias)
            self.assertEqual(y.shape, x.shape)
            self.assertEqual(log_det.shape, x.shape[:-value_ndims])
            assert_allclose(y_out, y)
            assert_allclose(log_det_out, log_det)

            # test use an initialized act_norm
            y2, log_det2 = naive_act_norm_transform(
                x2, var_shape_aligned, value_ndims, scale, bias)
            self.assertEqual(y2.shape, x2.shape)
            self.assertEqual(log_det2.shape, x2.shape[:-value_ndims])
            y2_out, log_det2_out = sess.run(
                act_norm.transform(x2_ph), feed_dict={x2_ph: x2})
            assert_allclose(y2_out, y2)
            assert_allclose(log_det2_out, log_det2)

            # invertible flow standard checks
            invertible_flow_standard_check(
                self, act_norm, sess, x_ph, feed_dict={x_ph: x})

            # -- dynamic input shape, scale_type = 'linear', value_ndims = 4
            value_ndims = 4

            # test initialize
            act_norm = ActNorm(axis=axis, value_ndims=value_ndims,
                               scale_type='linear')
            y_out, log_det_out = sess.run(
                act_norm.transform(x_ph), feed_dict={x_ph: x})
            self.assertEqual(act_norm._bias.dtype.base_dtype, tf.float64)

            scale_out, bias_out = sess.run(
                [act_norm._pre_scale, act_norm._bias])
            assert_allclose(scale_out, scale)
            assert_allclose(bias_out, bias)

            # test the transform output from the initializing procedure
            y, log_det = naive_act_norm_transform(
                x, var_shape_aligned, value_ndims, scale, bias)
            self.assertEqual(y.shape, x.shape)
            self.assertEqual(log_det.shape, x.shape[:-value_ndims])
            assert_allclose(y_out, y)
            assert_allclose(log_det_out, log_det)

            # test use an initialized act_norm
            y3, log_det3 = naive_act_norm_transform(
                x3, var_shape_aligned, value_ndims, scale, bias)
            self.assertEqual(y3.shape, x3.shape)
            self.assertEqual(log_det3.shape, x3.shape[:-value_ndims])
            y3_out, log_det3_out = sess.run(
                act_norm.transform(x3_ph), feed_dict={x3_ph: x3})
            assert_allclose(y3_out, y3)
            assert_allclose(log_det3_out, log_det3)

            # invertible flow standard checks
            invertible_flow_standard_check(self, act_norm, sess, x)

    def test_channels_last(self):
        # test reuse variables in ActNorm with different channels_last
        @global_reuse
        def f(x, channels_last=True, initializing=False):
            an = ActNorm(axis=-1 if channels_last else -3, value_ndims=3,
                         initialized=not initializing)
            return an.transform(x)

        x = np.random.normal(size=[2, 3, 4, 5, 6])  # NHWC
        x2 = np.transpose(x, [0, 1, 4, 2, 3])  # NCHW
        self.assertTupleEqual(x2.shape, (2, 3, 6, 4, 5))

        with self.test_session() as sess:
            y, log_det = sess.run(f(x, channels_last=True, initializing=True))
            y2, log_det2 = sess.run(f(x2, channels_last=False))

            np.testing.assert_allclose(log_det2, log_det)
            np.testing.assert_allclose(np.transpose(y2, (0, 1, 3, 4, 2)), y)

    def test_act_norm_vars(self):
        # test trainable
        with tf.Graph().as_default():
            _ = act_norm(tf.zeros([2, 3]), trainable=True, scale_type='linear')
            assert_variables(['scale', 'bias'], trainable=True,
                             scope='act_norm')
            assert_variables(['log_scale'], exist=False,  scope='act_norm')

        # test non-trainable
        with tf.Graph().as_default():
            _ = act_norm(tf.zeros([2, 3]), trainable=False, scale_type='exp')
            assert_variables(['log_scale', 'bias'], trainable=False,
                             scope='act_norm')
            assert_variables(['scale'], exist=False,  scope='act_norm')
