#!/usr/bin/env python
# Copyright 2017 Calico LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# =========================================================================
from __future__ import print_function


import sys
import time

import numpy as np
import tensorflow as tf

from basenji import params
from basenji import seqnn
from basenji import shared_flags
from basenji import tfrecord_batcher

FLAGS = tf.app.flags.FLAGS


def main(_):
  np.random.seed(FLAGS.seed)

  run(params_file=FLAGS.params,
      train_file=FLAGS.train_data,
      test_file=FLAGS.test_data,
      train_epochs=FLAGS.train_epochs,
      train_epoch_batches=FLAGS.train_epoch_batches,
      test_epoch_batches=FLAGS.test_epoch_batches)


def run(params_file, train_file, test_file, train_epochs, train_epoch_batches,
        test_epoch_batches):
  # read parameters
  job = params.read_job_params(params_file)

  # load data
  data_ops, training_init_op, test_init_op = make_data_ops(
      job, train_file, test_file)

  # initialize model
  model = seqnn.SeqNN()
  model.build_from_data_ops(job, data_ops)

  # checkpoints
  saver = tf.train.Saver()

  with tf.Session() as sess:
    train_writer = tf.summary.FileWriter(FLAGS.logdir + '/train',
                                         sess.graph) if FLAGS.logdir else None

    coord = tf.train.Coordinator()
    tf.train.start_queue_runners(coord=coord)

    if FLAGS.restart:
      # load variables into session
      saver.restore(sess, FLAGS.restart)
    else:
      # initialize variables
      t0 = time.time()
      print('Initializing...')
      sess.run(tf.local_variables_initializer())
      sess.run(tf.global_variables_initializer())
      print('Initialization time %f' % (time.time() - t0))

    train_loss = None
    best_loss = None
    early_stop_i = 0

    for epoch in range(train_epochs):
      if early_stop_i < FLAGS.early_stop or epoch < FLAGS.min_epochs:
        t0 = time.time()

        # save previous
        train_loss_last = train_loss

        # train epoch
        sess.run(training_init_op)
        train_loss, steps = model.train_epoch_from_data_ops(sess, train_writer, train_epoch_batches)

        # test validation
        sess.run(test_init_op)
        valid_acc = model.test_from_data_ops(sess, test_epoch_batches)
        valid_loss = valid_acc.loss
        valid_r2 = valid_acc.r2().mean()
        del valid_acc

        best_str = ''
        if best_loss is None or valid_loss < best_loss:
          best_loss = valid_loss
          best_str = ', best!'
          early_stop_i = 0
          saver.save(sess, '%s/model_best.tf' % FLAGS.logdir)
        else:
          early_stop_i += 1

        # measure time
        et = time.time() - t0
        if et < 600:
          time_str = '%3ds' % et
        elif et < 6000:
          time_str = '%3dm' % (et / 60)
        else:
          time_str = '%3.1fh' % (et / 3600)

        # print update
        print('Epoch: %3d,  Steps: %7d,  Train loss: %7.5f,' % (epoch+1, steps, train_loss), end='')
        print(' Valid loss: %7.5f,  Valid R2: %7.5f,' % (valid_loss, valid_r2), end='')
        print(' Time: %s%s' % (time_str, best_str))
        sys.stdout.flush()

    if FLAGS.logdir:
      train_writer.close()


def make_data_ops(job, train_file, test_file):
  def make_dataset(filename, mode):
    return tfrecord_batcher.tfrecord_dataset(
        filename,
        job['batch_size'],
        job['seq_length'],
        job.get('seq_depth', 4),
        job['target_length'],
        job['num_targets'],
        mode=mode,
        repeat=False)

  training_dataset = make_dataset(train_file, mode=tf.estimator.ModeKeys.TRAIN)
  test_dataset = make_dataset(test_file, mode=tf.estimator.ModeKeys.EVAL)

  iterator = tf.data.Iterator.from_structure(
      training_dataset.output_types, training_dataset.output_shapes)
  data_ops = iterator.get_next()

  training_init_op = iterator.make_initializer(training_dataset)
  test_init_op = iterator.make_initializer(test_dataset)

  return data_ops, training_init_op, test_init_op


if __name__ == '__main__':
  tf.app.run(main)
