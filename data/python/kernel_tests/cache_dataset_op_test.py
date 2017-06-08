# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for the experimental input pipeline ops."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from os import path
import shutil
import tempfile

import numpy as np

from tensorflow.contrib.data.python.ops import dataset_ops
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import errors
from tensorflow.python.ops import array_ops
from tensorflow.python.platform import test


class CacheDatasetTest(test.TestCase):

  def setUp(self):
    self.tmp_dir = tempfile.mkdtemp()
    self.cache_prefix = path.join(self.tmp_dir, "cache")

  def tearDown(self):
    if self.tmp_dir:
      shutil.rmtree(self.tmp_dir, ignore_errors=True)

  def testCacheDatasetPassthrough(self):
    components = (np.array([1, 2, 3, 4]), np.array([5, 6, 7, 8]),
                  np.array([9.0, 10.0, 11.0, 12.0]))
    count_placeholder = array_ops.placeholder_with_default(
        constant_op.constant(5, dtypes.int64), shape=[])
    filename_placeholder = array_ops.placeholder(dtypes.string, shape=[])

    repeat_dataset = (dataset_ops.Dataset.from_tensor_slices(components)
                      .repeat(count_placeholder))

    cache_dataset = repeat_dataset.cache(filename_placeholder)

    self.assertEqual(
        tuple([c.shape[1:] for c in components]), cache_dataset.output_shapes)

    # Create initialization ops for iterators without and with
    # caching, respectively.
    iterator = dataset_ops.Iterator.from_structure(cache_dataset.output_types,
                                                   cache_dataset.output_shapes)
    init_fifo_op = iterator.make_initializer(repeat_dataset)
    init_cache_op = iterator.make_initializer(cache_dataset)

    get_next = iterator.get_next()

    with self.test_session() as sess:
      # First run without caching to collect the "ground truth".
      sess.run(init_fifo_op)
      elements = []
      for _ in range(20):
        elements.append(sess.run(get_next))
      with self.assertRaises(errors.OutOfRangeError):
        sess.run(get_next)

      # Assert that the cached dataset has the same elements as the
      # "ground truth".
      sess.run(
          init_cache_op, feed_dict={filename_placeholder: self.cache_prefix})
      cached_elements = []
      for _ in range(20):
        cached_elements.append(sess.run(get_next))
      with self.assertRaises(errors.OutOfRangeError):
        sess.run(get_next)
      self.assertAllEqual(elements, cached_elements)

      # Re-initialize with an empty upstream (to throw errors.OutOfRangeError
      # if we didn't use the cache).
      sess.run(
          init_cache_op,
          feed_dict={
              count_placeholder: 0,
              filename_placeholder: self.cache_prefix
          })
      replayed_elements = []
      for _ in range(20):
        replayed_elements.append(sess.run(get_next))
      with self.assertRaises(errors.OutOfRangeError):
        sess.run(get_next)
      self.assertEqual(cached_elements, replayed_elements)

      # Re-initialize with an empty upstream and a missing cache file (should
      # throw errors.OutOfRangeError immediately).
      sess.run(
          init_cache_op,
          feed_dict={
              count_placeholder: 0,
              filename_placeholder: self.cache_prefix + "nonsense"
          })
      with self.assertRaises(errors.OutOfRangeError):
        sess.run(get_next)

  def testConcurrentWriters(self):
    components = (np.array([1, 2, 3, 4]), np.array([5, 6, 7, 8]),
                  np.array([9.0, 10.0, 11.0, 12.0]))
    filename_placeholder = array_ops.placeholder(dtypes.string, shape=[])

    cache_dataset1 = (dataset_ops.Dataset.from_tensor_slices(components)
                      .cache(filename_placeholder))
    cache_dataset2 = (dataset_ops.Dataset.from_tensor_slices(components)
                      .cache(filename_placeholder))

    iterator1 = cache_dataset1.make_initializable_iterator()
    iterator2 = cache_dataset2.make_initializable_iterator()
    init_cache_op1 = iterator1.initializer
    init_cache_op2 = iterator2.initializer

    get_next1 = iterator1.get_next()
    get_next2 = iterator2.get_next()

    with self.test_session() as sess:
      sess.run(
          init_cache_op1, feed_dict={filename_placeholder: self.cache_prefix})
      sess.run(get_next1)  # this should succeed

      sess.run(
          init_cache_op2, feed_dict={filename_placeholder: self.cache_prefix})
      with self.assertRaises(errors.AlreadyExistsError):
        sess.run(get_next2)

      sess.run(get_next1)  # this should continue to succeed

  def testConcurrentReaders(self):
    components = (np.array([1, 2, 3, 4]), np.array([5, 6, 7, 8]),
                  np.array([9.0, 10.0, 11.0, 12.0]))
    filename_placeholder = array_ops.placeholder(dtypes.string, shape=[])

    cache_dataset1 = (dataset_ops.Dataset.from_tensor_slices(components)
                      .cache(filename_placeholder))
    cache_dataset2 = (dataset_ops.Dataset.from_tensor_slices(components)
                      .cache(filename_placeholder))

    iterator1 = cache_dataset1.make_initializable_iterator()
    iterator2 = cache_dataset2.make_initializable_iterator()
    init_cache_op1 = iterator1.initializer
    init_cache_op2 = iterator2.initializer

    get_next1 = iterator1.get_next()
    get_next2 = iterator2.get_next()

    with self.test_session() as sess:
      sess.run(
          init_cache_op1, feed_dict={filename_placeholder: self.cache_prefix})
      elements = []
      for _ in range(4):
        elements.append(sess.run(get_next1))
      with self.assertRaises(errors.OutOfRangeError):
        sess.run(get_next1)

      # Re-initialize
      sess.run(
          init_cache_op1, feed_dict={filename_placeholder: self.cache_prefix})
      sess.run(
          init_cache_op2, feed_dict={filename_placeholder: self.cache_prefix})

      # Reading concurrently should succeed.
      elements_itr1 = []
      elements_itr2 = []
      elements_itr2.append(sess.run(get_next2))
      elements_itr1.append(sess.run(get_next1))
      elements_itr2.append(sess.run(get_next2))
      elements_itr1.append(sess.run(get_next1))
      # Intentionally reversing the order
      elements_itr1.append(sess.run(get_next1))
      elements_itr2.append(sess.run(get_next2))
      elements_itr1.append(sess.run(get_next1))
      elements_itr2.append(sess.run(get_next2))

      with self.assertRaises(errors.OutOfRangeError):
        sess.run(get_next2)

      with self.assertRaises(errors.OutOfRangeError):
        sess.run(get_next1)

      self.assertAllEqual(elements, elements_itr1)
      self.assertAllEqual(elements, elements_itr2)


if __name__ == "__main__":
  test.main()
